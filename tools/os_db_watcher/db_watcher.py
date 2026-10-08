"""
Vigia de banco - roda no computador da loja (Windows), observa DIRETO o banco Firebird
do Softsystem (leitura, na esmagadora maioria do que faz aqui) em busca de eventos novos na aba
"Eventos" da Ordem de Serviço, e envia os dados já resolvidos (telefone, natureza,
equipamento, técnico) para o sistema Ominichannel processar automaticamente.

Única exceção à regra de só leitura: poll_pending_writes, que executa pedidos de mudança de
status vindos de fora do Softsystem (hoje só o Portal do Técnico - ver SoftsystemPendingWrite
no backend) - o backend roda na nuvem e não alcança o Firebird da loja, então só enfileira o
pedido; é este vigia, rodando dentro da rede da loja, quem grava de verdade.

Também observa as pastas onde o Softsystem salva o PDF (ABERTURA/ORÇAMENTO) - quando um
arquivo novo aparece, extrai o número da O.S. do NOME do arquivo (ex: "1934.pdf" -> 1934) e
consulta o banco pelos dados corretos, em vez de tentar ler texto do PDF (abordagem antiga,
frágil - ver os_folder_watcher, hoje só mantido como referência). Isso cobre o caso em que o
PDF é salvo bem depois do evento no banco já ter sido detectado: o aviso ao cliente já saiu
sem o arquivo (ver dispatch_orcamento_messages no backend - o aviso nunca espera o PDF), e
quando o arquivo aparece, esse mesmo vigia entrega só o PDF como complemento (o backend nunca
reenvia os textos informativos duas vezes para a mesma O.S. - ver check_os_dispatch_state).

Duas empresas são observadas (cada uma com seu próprio banco .fdb): Servweld e
Centro-Oeste. Configure os caminhos em config.json antes de rodar.

Uso:
    python db_watcher.py
"""
import os
import sys
import json
import time
import socket
import shutil
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

import requests
from firebird.driver import connect, TPB, Isolation, TraAccessMode
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
STATE_PATH = os.path.join(SCRIPT_DIR, "state.json")
SINGLE_INSTANCE_PORT = 47813  # different from os_folder_watcher's 47812 - both can run together

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(SCRIPT_DIR, "db_watcher.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("os_db_watcher")

# Eventos que precisam do PDF da O.S. anexado (ver os_handler_ingest.py no backend)
EVENTOS_COM_PDF = {1: "abertura", 3: "orcamento"}


def acquire_single_instance_lock():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        logger.info("Já existe um vigia de banco rodando nesta estação - encerrando esta segunda instância.")
        sys.exit(0)
    return s


def load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        logger.error(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state() -> dict:
    if os.path.isfile(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    tmp_path = STATE_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp_path, STATE_PATH)


def db_connect(empresa_cfg: dict):
    # WIN1252 explícito: o Softsystem grava texto em ANSI. Com a conexão em UTF8 (padrão do
    # driver), qualquer linha com acento na observação ("...NÃO VAI FAZER O SERVIÇO") estoura
    # UnicodeDecodeError - e como o cursor só avança após enviar com sucesso, o vigia ficaria
    # tentando o mesmo evento pra sempre, travando todos os avisos daquela empresa.
    return connect(
        f"{empresa_cfg['host']}:{empresa_cfg['database']}",
        user=empresa_cfg.get("user", "SYSDBA"),
        password=empresa_cfg["password"],
        no_db_triggers=True,
        charset="WIN1252"
    )


def read_only_cursor(con):
    """Returns (transaction, cursor) using an explicit READ-ONLY transaction - never writes."""
    tpb = TPB(access_mode=TraAccessMode.READ, isolation=Isolation.READ_COMMITTED_RECORD_VERSION)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    return tra, tra.cursor()


def write_cursor(con):
    """Transação normal (leitura E escrita) - só usada por poll_pending_writes, o único ponto
    deste vigia que grava no Softsystem."""
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    return tra, tra.cursor()


def build_phone(ddd: str, numero: str) -> str:
    digits = re.sub(r"\D", "", f"{ddd or ''}{numero or ''}")
    if not digits:
        return ""
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


# Número dentro do texto livre do campo "Contato" da O.S.: DDD opcional + 8 ou 9 dígitos,
# com espaço, ponto ou hífen no meio ("61 9606-0567", "996463103", "33191133").
_CONTATO_NUM = re.compile(r"(?<!\d)(?:\(?(\d{2})\)?[\s.-]*)?(9?\d{4})[\s.-]?(\d{4})(?!\d)")
_CONTATO_RUIDO = re.compile(r"\b(E|OU|TEL|CEL|CELULAR|FONE|WHATSAPP|ZAP)\b", re.I)


def parse_contato(texto: str, ddd_padrao: str = "61"):
    """
    O campo "Contato" da O.S. é texto livre digitado pelo atendente: 'ANDRE 33191133 / 996463103',
    '61 984276819 - ROSANGELA', 'JAIME', '9'. Devolve (nome, [celulares], [fixos]) - números já
    com 55+DDD. Celular = 9 dígitos começando em 9 (ou 8 dígitos começando em 6-9, sem o nono
    dígito antigo, ao qual o 9 é acrescentado). Fixo (33191133) não recebe WhatsApp.
    """
    texto = (texto or "").strip()
    celulares, fixos = [], []

    def _achou(m):
        ddd, a, b = m.group(1), m.group(2), m.group(3)
        numero = a + b
        if len(numero) == 9 and numero[0] != "9":
            return m.group(0)  # 9 dígitos que não começam com 9 não são telefone
        if len(numero) == 8 and numero[0] in "6789":
            numero = "9" + numero
        completo = "55" + (ddd or ddd_padrao) + numero
        (celulares if len(numero) == 9 else fixos).append(completo)
        return " "

    resto = _CONTATO_NUM.sub(_achou, texto)
    nome = re.sub(r"[^A-Za-zÀ-ÿ ]", " ", resto)
    nome = _CONTATO_RUIDO.sub(" ", nome)
    nome = re.sub(r"\s+", " ", nome).strip().title()
    return nome, celulares, fixos


def resolve_recipient(event: dict):
    """
    Quem recebe o aviso: se o campo "Contato" da O.S. tem um celular (o responsável que responde
    pelo cliente, ex. o André de uma empresa/CNPJ), o aviso vai para ele, chamando-o pelo nome.
    Sem celular no Contato, continua como sempre: celular/fone do cadastro do cliente.
    Retorna (telefone, nome, origem).
    """
    nome_cliente = event.get("RAZAOSOCIAL") or event.get("NOMEFANTASIA")
    ddd_cliente = re.sub(r"\D", "", str(event.get("DDD") or "")) or "61"
    nome_contato, celulares, _fixos = parse_contato(event.get("CONTATO"), ddd_cliente)
    if celulares:
        return celulares[0], (nome_contato or nome_cliente), "contato"
    return build_phone(event.get("DDD"), event.get("CELULAR") or event.get("FONE")), nome_cliente, "cadastro"


def find_expected_pdf(config: dict, tipo: str, codos: int, wait_seconds: int = 5) -> str:
    """
    Softsystem salva o PDF nomeado pelo código da O.S. (confirmado: "1933.pdf" para
    CODOS=1933), numa pasta compartilhada entre as duas empresas. Espera um pouco caso o
    evento tenha disparado um instante antes do Softsystem terminar de salvar o arquivo -
    mas o PDF é só um extra (ver dispatch_orcamento_messages no backend: o aviso ao cliente
    sai de qualquer forma), então a espera aqui é curta, não vale travar o ciclo por muito
    tempo à toa quando o arquivo simplesmente ainda não existe.
    """
    folder_key = "pasta_abertura" if tipo == "abertura" else "pasta_orcamento"
    folder = config.get(folder_key)
    if not folder:
        return ""
    expected_path = os.path.join(folder, f"{codos}.pdf")
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if os.path.isfile(expected_path):
            return expected_path
        time.sleep(2)
    return ""


def fetch_new_events(cur, since_data) -> list:
    if since_data:
        cur.execute("""
            SELECT eo.LOJA, eo.CODOS, eo.DATA, eo.CODTIPOEVENTOOS, eo.OBS,
                   os.CODTIPOORDEMSERVICO, os.CNPJ, os.TECNICOATENDIMENTO,
                   cli.RAZAOSOCIAL, cli.NOMEFANTASIA, cli.DDD, cli.CELULAR, cli.FONE, os.CONTATO
            FROM EVENTOSORDEMSERVICO eo
            JOIN ORDEMSERVICO os ON os.LOJA = eo.LOJA AND os.CODOS = eo.CODOS
            LEFT JOIN CLIENTES cli ON cli.CGC = os.CNPJ
            WHERE eo.DATA > ?
            ORDER BY eo.DATA ASC
        """, (since_data,))
    else:
        # Primeira execução: não reenviar histórico - só a partir de agora.
        cur.execute("""
            SELECT eo.LOJA, eo.CODOS, eo.DATA, eo.CODTIPOEVENTOOS, eo.OBS,
                   os.CODTIPOORDEMSERVICO, os.CNPJ, os.TECNICOATENDIMENTO,
                   cli.RAZAOSOCIAL, cli.NOMEFANTASIA, cli.DDD, cli.CELULAR, cli.FONE, os.CONTATO
            FROM EVENTOSORDEMSERVICO eo
            JOIN ORDEMSERVICO os ON os.LOJA = eo.LOJA AND os.CODOS = eo.CODOS
            LEFT JOIN CLIENTES cli ON cli.CGC = os.CNPJ
            WHERE 1=0
        """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_equipamento(cur, loja: int, codos: int, cnpj: str) -> dict:
    cur.execute("SELECT FIRST 1 CODEQUIP, DEFEITO FROM EQUIPORDEMSERVICO WHERE LOJA=? AND CODOS=?", (loja, codos))
    row = cur.fetchone()
    if not row:
        return {}
    codequip, defeito = row
    result = {"defeito": defeito}
    if codequip and cnpj:
        cur.execute(
            "SELECT MARCA, MODELO, DESCRICAO FROM EQUIPAMENTOS WHERE CNPJ=? AND CODEQUIP=?",
            (cnpj, codequip)
        )
        eq_row = cur.fetchone()
        if eq_row:
            result["marca"], result["modelo"], result["descricao"] = eq_row
    return result


def find_os_by_codos(config: dict, codos: int):
    """
    Usado pelo vigia de pasta: dado só o número da O.S. (extraído do nome do arquivo PDF),
    tenta achar essa O.S. em cada empresa configurada (tenta todas - os códigos de cada
    empresa vêm de sequências separadas no Softsystem, então não há ambiguidade real).
    Retorna (empresa_key, event_dict) na mesma forma de fetch_new_events, ou (None, None).
    """
    for empresa_key, empresa_cfg in config.get("empresas", {}).items():
        try:
            con = db_connect(empresa_cfg)
        except Exception as e:
            logger.error(f"[{empresa_key}] Não foi possível conectar ao banco: {e}")
            continue
        try:
            tra, cur = read_only_cursor(con)
            try:
                cur.execute("""
                    SELECT os.LOJA, os.CODOS, os.CODTIPOORDEMSERVICO, os.CNPJ, os.TECNICOATENDIMENTO,
                           cli.RAZAOSOCIAL, cli.NOMEFANTASIA, cli.DDD, cli.CELULAR, cli.FONE, os.CONTATO
                    FROM ORDEMSERVICO os
                    LEFT JOIN CLIENTES cli ON cli.CGC = os.CNPJ
                    WHERE os.CODOS = ?
                """, (codos,))
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    continue
                event = dict(zip(cols, row))
                equip = fetch_equipamento(cur, event["LOJA"], event["CODOS"], event.get("CNPJ"))
                event["_equip_marca"] = equip.get("marca")
                event["_equip_modelo"] = equip.get("modelo")
                event["_equip_descricao"] = equip.get("descricao")
                event["_equip_defeito"] = equip.get("defeito")
                return empresa_key, event
            finally:
                tra.commit()
        finally:
            con.close()
    return None, None


def send_event_to_backend(config: dict, empresa_key: str, event: dict, tipo: str, pdf_path: str) -> bool:
    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/db-event"
    headers = {"X-OS-Handler-Key": config["api_key"]}
    phone, recipient_name, recipient_source = resolve_recipient(event)
    if recipient_source == "contato":
        logger.info(f"[{empresa_key}] O.S. #{event['CODOS']}: aviso vai para o Contato da O.S. ({recipient_name}, {phone}).")
    if not phone:
        logger.warning(f"[{empresa_key}] O.S. #{event['CODOS']}: sem telefone do cliente, não enviado.")
        return True  # não é um erro de rede - não faz sentido re-tentar, só pula

    payload = {
        "empresa": empresa_key,
        "loja": event["LOJA"],
        "codos": event["CODOS"],
        "cod_tipo_evento": event["CODTIPOEVENTOOS"],
        "cliente_nome": recipient_name,
        # Razão Social da O.S. - é o nome que vai no arquivo do PDF (o cliente_nome acima pode ser o do
        # campo Contato, a pessoa que responde pela empresa)
        "cliente_razao_social": event.get("RAZAOSOCIAL") or event.get("NOMEFANTASIA"),
        "cliente_telefone": phone,
        "natureza_codigo": event.get("CODTIPOORDEMSERVICO"),
        "equip_marca": event.get("_equip_marca"),
        "equip_modelo": event.get("_equip_modelo"),
        "equip_descricao": event.get("_equip_descricao"),
        "equip_defeito": event.get("_equip_defeito"),
        "tecnico_nome": event.get("TECNICOATENDIMENTO"),
        # Observação do técnico neste evento (ex.: por que não tem conserto) e os eventos
        # anteriores da O.S., do mais recente pro mais antigo - o backend adapta o aviso
        # ("Aguardando Retirada" muda conforme o que aconteceu antes; "Sem Conserto" lê a observação).
        "obs": event.get("OBS"),
        "eventos_anteriores": event.get("_eventos_anteriores", []),
    }

    try:
        files = {}
        opened_file = None
        if pdf_path:
            opened_file = open(pdf_path, "rb")
            files["file"] = (os.path.basename(pdf_path), opened_file, "application/pdf")
        try:
            resp = requests.post(
                url, headers=headers,
                data={"payload": json.dumps(payload, ensure_ascii=False)},
                files=files if files else None,
                timeout=config.get("timeout_seconds", 60)
            )
        finally:
            if opened_file:
                opened_file.close()

        if resp.status_code == 200:
            resp_json = resp.json()
            # HTTP 200 só significa que o backend processou a chamada - "status" no corpo é
            # que diz se a entrega do PDF de verdade funcionou (ver deliver_late_pdf).
            if resp_json.get("status") == "pdf_delivery_failed":
                logger.error(f"FALHA [{empresa_key}] O.S. #{event['CODOS']} evento {event['CODTIPOEVENTOOS']} -> PDF não entregue: {resp_json}")
                return False
            logger.info(f"OK [{empresa_key}] O.S. #{event['CODOS']} evento {event['CODTIPOEVENTOOS']} -> {resp_json}")
            return True
        else:
            logger.error(f"FALHA [{empresa_key}] O.S. #{event['CODOS']} evento {event['CODTIPOEVENTOOS']} -> HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"ERRO ao enviar O.S. #{event['CODOS']} ({empresa_key}): {e}")
        return False


# ---------------------------------------------------------------------------------------------
# Aviso automático de Nota Fiscal do Pedido: quando o usuário cria uma tarefa na agenda vinculada
# a um "Código" (CODORCAMENTO) de Pedido do Softsystem, avisa o funcionário responsável assim que
# uma Nota Fiscal aparecer na tabela NOTAFISCAL pra esse mesmo pedido - sem precisar avisar
# manualmente. Backend decide se existe alguma tarefa vinculada (ver
# os_handler_ingest.ingest_pedido_nf_event); esse vigia só detecta e encaminha, igual o
# fetch_new_events/send_event_to_backend acima fazem pros eventos de O.S.
# ---------------------------------------------------------------------------------------------

def fetch_new_notas_fiscais(cur, since_data) -> list:
    if since_data:
        cur.execute("""
            SELECT LOJA, CODORCAMENTO, NUMERONOTA, SERIENOTA, DATA, CANCELADA
            FROM NOTAFISCAL
            WHERE DATA > ?
            ORDER BY DATA ASC
        """, (since_data,))
    else:
        cur.execute("SELECT LOJA, CODORCAMENTO, NUMERONOTA, SERIENOTA, DATA, CANCELADA FROM NOTAFISCAL WHERE 1=0")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def send_nf_event_to_backend(config: dict, empresa_key: str, nf: dict) -> bool:
    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/pedido-nf-event"
    headers = {"X-OS-Handler-Key": config["api_key"]}
    payload = {
        "codorcamento": nf["CODORCAMENTO"],
        "numero_nota": str(nf["NUMERONOTA"]) if nf.get("NUMERONOTA") else None,
        "cancelada": str(nf.get("CANCELADA") or "").strip().upper() in ("S", "1", "TRUE"),
    }
    try:
        resp = requests.post(
            url, headers=headers,
            data={"payload": json.dumps(payload, ensure_ascii=False)},
            timeout=config.get("timeout_seconds", 60)
        )
        if resp.status_code == 200:
            resp_json = resp.json()
            if resp_json.get("notified"):
                logger.info(f"OK [{empresa_key}] Pedido #{nf['CODORCAMENTO']} - nota #{nf.get('NUMERONOTA')} -> {resp_json}")
            return True
        logger.error(f"FALHA [{empresa_key}] Pedido #{nf['CODORCAMENTO']} (nota fiscal) -> HTTP {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"ERRO ao enviar evento de nota fiscal do pedido #{nf['CODORCAMENTO']} ({empresa_key}): {e}")
        return False


def poll_notas_fiscais(config: dict, empresa_key: str, empresa_cfg: dict, state: dict):
    try:
        con = db_connect(empresa_cfg)
    except Exception as e:
        logger.error(f"[{empresa_key}] Nota fiscal: não foi possível conectar ao banco: {e}")
        return

    try:
        tra, cur = read_only_cursor(con)
        try:
            since_data_raw = state.get(empresa_key, {}).get("last_nf_data")
            since_data = datetime.fromisoformat(since_data_raw) if since_data_raw else None
            notas = fetch_new_notas_fiscais(cur, since_data)

            if since_data is None and notas == []:
                # Primeira vez rodando: marca o "agora" do banco como ponto de partida, sem
                # avisar retroativamente de notas fiscais antigas.
                cur.execute("SELECT FIRST 1 DATA FROM NOTAFISCAL ORDER BY DATA DESC")
                row = cur.fetchone()
                baseline = row[0] if row else None
                state.setdefault(empresa_key, {})["last_nf_data"] = str(baseline) if baseline else "1900-01-01"
                save_state(state)
                logger.info(f"[{empresa_key}] Nota fiscal: primeira execução - marcando ponto de partida em {baseline}.")
                return

            for nf in notas:
                success = send_nf_event_to_backend(config, empresa_key, nf)
                if success:
                    state.setdefault(empresa_key, {})["last_nf_data"] = str(nf["DATA"])
                    save_state(state)
                else:
                    logger.warning(f"[{empresa_key}] Vai tentar a nota fiscal do pedido #{nf['CODORCAMENTO']} de novo no próximo ciclo.")
                    break
        finally:
            tra.commit()
    finally:
        con.close()


def wait_until_file_is_stable(path: str, checks: int = 4, interval: float = 1.0) -> bool:
    """Espera o arquivo parar de crescer - o Softsystem pode ainda estar terminando de escrever."""
    last_size = -1
    stable_count = 0
    for _ in range(30):
        try:
            size = os.path.getsize(path)
        except OSError:
            time.sleep(interval)
            continue
        if size == last_size and size > 0:
            stable_count += 1
            if stable_count >= checks:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(interval)
    return False


def move_processed_pdf(file_path: str, success: bool):
    subdir = "processados" if success else "erros"
    dest_dir = os.path.join(os.path.dirname(file_path), subdir)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.path.basename(file_path)}")
    try:
        shutil.move(file_path, dest_path)
    except Exception as e:
        logger.error(f"Não foi possível mover {file_path} para {dest_dir}: {e}")


def process_pdf_file(config: dict, path: str, cod_tipo_evento: int, tipo: str) -> None:
    """
    Processa um PDF de O.S. (ABERTURA/ORÇAMENTO): acha o evento correspondente no banco pelo
    número no nome do arquivo e manda pro backend. Reaproveitado tanto pelo gatilho em tempo real
    (PdfFolderHandler.on_created) quanto pela varredura periódica de pendências
    (retry_pending_folder_pdfs) - por isso NÃO decide sozinho se deve mover o arquivo: só
    "erros" (falha permanente, ex. O.S. não encontrada) é decidido aqui; falha de envio ao
    backend (rede/backend fora do ar - quase sempre transitória) deixa o arquivo *no lugar*,
    pra próxima varredura tentar de novo, em vez de arquivar em "erros" e nunca mais tentar -
    era exatamente esse o buraco relatado pelo usuário em 28/09/2026: "sexta o sistema estava
    caindo e salvamos algumas O.S's, eu não vi ele disparar".
    """
    basename = os.path.splitext(os.path.basename(path))[0]
    if not basename.isdigit():
        logger.warning(f"[vigia de pasta] Nome de arquivo não é um código de O.S. numérico, ignorando: {path}")
        return
    codos = int(basename)

    logger.info(f"[vigia de pasta] Processando PDF [{tipo}]: {path}")
    if not wait_until_file_is_stable(path):
        logger.warning(f"[vigia de pasta] Arquivo não estabilizou a tempo, tentando mesmo assim: {path}")

    empresa_key, event = find_os_by_codos(config, codos)
    if not event:
        # Falha permanente: o número no nome do arquivo não bate com nenhuma O.S. em nenhuma
        # empresa - tentar de novo depois não vai mudar isso. Só aqui é seguro mover pra "erros".
        logger.error(f"[vigia de pasta] O.S. #{codos} não encontrada em nenhuma empresa - PDF não enviado: {path}")
        move_processed_pdf(path, success=False)
        return

    event["CODTIPOEVENTOOS"] = cod_tipo_evento
    success = send_event_to_backend(config, empresa_key, event, tipo, path)
    if success:
        move_processed_pdf(path, success=True)
    else:
        logger.warning(f"[vigia de pasta] Falha ao enviar O.S. #{codos} pro backend - arquivo fica na pasta pra tentar de novo: {path}")


class PdfFolderHandler(FileSystemEventHandler):
    """
    Gatilho pelo ARQUIVO em vez do evento no banco - cobre o caso em que o PDF só é salvo
    bem depois do evento já ter sido detectado pelo poll_empresa (ver check_os_dispatch_state
    no backend: ele nunca reenvia os textos informativos duas vezes, só complementa com o
    PDF quando ele chega atrasado).
    """
    def __init__(self, config: dict, cod_tipo_evento: int, tipo: str):
        self.config = config
        self.cod_tipo_evento = cod_tipo_evento
        self.tipo = tipo
        self._seen = set()

    def _process(self, path: str):
        if not path.lower().endswith(".pdf") or path in self._seen:
            return
        self._seen.add(path)
        try:
            process_pdf_file(self.config, path, self.cod_tipo_evento, self.tipo)
        finally:
            self._seen.discard(path)

    def on_created(self, event):
        if not event.is_directory:
            self._process(event.src_path)


_PDF_RETRY_FOLDERS = [(1, "abertura", "pasta_abertura"), (3, "orcamento", "pasta_orcamento")]
_PDF_RETRY_INTERVAL_SECONDS = 300  # não retenta a cada 20s (ciclo normal) - só a cada 5 min, pra
                                    # não bater no backend repetidamente enquanto ele estiver fora
_last_pdf_retry_ts = 0.0


def retry_pending_folder_pdfs(config: dict):
    """
    Varredura periódica (chamada do loop principal): qualquer .pdf que ainda esteja direto na
    raiz de pasta_abertura/pasta_orcamento (não em "processados" nem "erros") é um arquivo cujo
    envio falhou da última vez - process_pdf_file só move pra "erros" em falha permanente,
    deixando o resto pra essa varredura tentar de novo. Sem isso, um PDF que chegou com o backend
    fora do ar ficava esquecido pra sempre (só reenviado se alguém reiniciasse o vigia).
    """
    global _last_pdf_retry_ts
    now = time.time()
    if now - _last_pdf_retry_ts < _PDF_RETRY_INTERVAL_SECONDS:
        return
    _last_pdf_retry_ts = now

    for cod_tipo_evento, tipo, folder_key in _PDF_RETRY_FOLDERS:
        folder = config.get(folder_key)
        if not folder or not os.path.isdir(folder):
            continue
        try:
            pendentes = [
                os.path.join(folder, name) for name in os.listdir(folder)
                if name.lower().endswith(".pdf") and os.path.isfile(os.path.join(folder, name))
            ]
        except Exception as e:
            logger.error(f"[vigia de pasta] Não foi possível listar '{folder}' pra retentativa: {e}")
            continue
        if not pendentes:
            continue
        logger.info(f"[vigia de pasta] Retentativa [{tipo}]: {len(pendentes)} PDF(s) pendente(s) em {folder}")
        for path in pendentes:
            try:
                process_pdf_file(config, path, cod_tipo_evento, tipo)
            except Exception as e:
                logger.error(f"[vigia de pasta] Erro inesperado ao retentar {path}: {e}", exc_info=True)

    def on_moved(self, event):
        if not event.is_directory:
            self._process(event.dest_path)


# ---------------------------------------------------------------------------------------------
# Documentos do cliente (Nota Fiscal): Z:\SOFTSYSTEM\NFe\pdf guarda o par PDF+XML de cada nota
# emitida pela loja (nome = chave de acesso de 44 dígitos + "-procNFe"; "-procEventoNFe" são
# eventos de cancelamento, ignorados). Sem evento equivalente no banco pra monitorar - o gatilho
# é o ARQUIVO aparecendo, igual o vigia de pasta de O.S. já faz, mas aqui o dado todo vem de
# dentro do XML (padrão SEFAZ), não do nome do arquivo. Pedido do usuário em 24/09/2026: guardar
# a nota (e o boleto, por e-mail - fora deste script) pra poder mandar pro cliente quando ele
# pedir pelo WhatsApp.
# ---------------------------------------------------------------------------------------------
NFE_NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


def parse_nfe_xml(xml_path: str) -> dict:
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        inf_nfe = root.find(".//nfe:infNFe", NFE_NS)
        if inf_nfe is None:
            return {}

        def txt(parent_tag: str, tag: str):
            parent = inf_nfe.find(f"nfe:{parent_tag}", NFE_NS)
            if parent is None:
                return None
            node = parent.find(f"nfe:{tag}", NFE_NS)
            return node.text if node is not None else None

        chave = (inf_nfe.get("Id") or "").replace("NFe", "").strip()
        v_nf = None
        total = inf_nfe.find("nfe:total/nfe:ICMSTot/nfe:vNF", NFE_NS)
        if total is not None and total.text:
            try:
                v_nf = float(total.text)
            except ValueError:
                v_nf = None

        return {
            "chave_acesso": chave,
            "nNF": txt("ide", "nNF"),
            "serie": txt("ide", "serie"),
            "dhEmi": txt("ide", "dhEmi"),
            "dest_cnpj": txt("dest", "CNPJ"),
            "dest_nome": txt("dest", "xNome"),
            "vNF": v_nf,
        }
    except Exception as e:
        logger.error(f"[NFe] Erro ao ler XML {xml_path}: {e}")
        return {}


def find_client_phone_by_cnpj(config: dict, cnpj: str):
    """Procura o CNPJ em CLIENTES em cada empresa configurada - retorna (telefone, nome) do
    primeiro cadastro encontrado, ou ("", None) se não achar em nenhuma."""
    for empresa_key, empresa_cfg in config.get("empresas", {}).items():
        try:
            con = db_connect(empresa_cfg)
        except Exception:
            continue
        try:
            tra, cur = read_only_cursor(con)
            try:
                cur.execute(
                    "SELECT FIRST 1 DDD, CELULAR, FONE, RAZAOSOCIAL, NOMEFANTASIA FROM CLIENTES WHERE CGC=?",
                    (cnpj,)
                )
                row = cur.fetchone()
                if row:
                    ddd, celular, fone, razao, fantasia = row
                    phone = build_phone(ddd, celular or fone)
                    if phone:
                        return phone, (fantasia or razao)
            finally:
                tra.commit()
        finally:
            con.close()
    return "", None


def send_nfe_document_to_backend(config: dict, payload: dict, pdf_path: str, xml_path: str) -> bool:
    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/nfe-document"
    headers = {"X-OS-Handler-Key": config["api_key"]}
    opened = []
    try:
        files = {}
        if pdf_path and os.path.isfile(pdf_path):
            f1 = open(pdf_path, "rb")
            opened.append(f1)
            files["pdf_file"] = (os.path.basename(pdf_path), f1, "application/pdf")
        if xml_path and os.path.isfile(xml_path):
            f2 = open(xml_path, "rb")
            opened.append(f2)
            files["xml_file"] = (os.path.basename(xml_path), f2, "application/xml")

        resp = requests.post(
            url, headers=headers,
            data={"payload": json.dumps(payload, ensure_ascii=False)},
            files=files if files else None,
            timeout=config.get("timeout_seconds", 60)
        )
        if resp.status_code == 200:
            logger.info(f"OK [NFe] Nota #{payload.get('numero_nota')} (CNPJ {payload.get('cnpj')}) -> {resp.json()}")
            return True
        logger.error(f"FALHA [NFe] Nota #{payload.get('numero_nota')} -> HTTP {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"ERRO ao enviar documento NFe (nota {payload.get('numero_nota')}): {e}")
        return False
    finally:
        for f in opened:
            f.close()


def move_processed_nfe(xml_path: str, pdf_path: str, success: bool):
    for p in (xml_path, pdf_path):
        if p and os.path.isfile(p):
            move_processed_pdf(p, success)


class NFeFolderHandler(FileSystemEventHandler):
    """Observa Z:\\SOFTSYSTEM\\NFe\\pdf pelo XML da Nota Fiscal de venda (gatilho pelo arquivo,
    mesma ideia do PdfFolderHandler acima, mas o dado todo vem de dentro do XML, não do nome)."""

    def __init__(self, config: dict):
        self.config = config
        self._seen = set()

    def _process(self, xml_path: str):
        if not xml_path.lower().endswith("-procnfe.xml") or xml_path in self._seen:
            return
        self._seen.add(xml_path)
        try:
            logger.info(f"[NFe] Novo XML detectado: {xml_path}")
            if not wait_until_file_is_stable(xml_path):
                logger.warning(f"[NFe] XML não estabilizou a tempo, tentando mesmo assim: {xml_path}")

            pdf_path = xml_path[:-4] + ".pdf"
            for _ in range(10):
                if os.path.isfile(pdf_path):
                    break
                time.sleep(2)
            if os.path.isfile(pdf_path):
                wait_until_file_is_stable(pdf_path)
            else:
                logger.warning(f"[NFe] PDF correspondente não apareceu, seguindo só com o XML: {pdf_path}")

            parsed = parse_nfe_xml(xml_path)
            if not parsed or not parsed.get("dest_cnpj") or not parsed.get("chave_acesso"):
                logger.warning(f"[NFe] Não consegui ler dados do XML, pulando: {xml_path}")
                move_processed_nfe(xml_path, pdf_path, success=False)
                return

            phone, nome_cadastro = find_client_phone_by_cnpj(self.config, parsed["dest_cnpj"])
            if not phone:
                logger.warning(f"[NFe] Cliente CNPJ {parsed['dest_cnpj']} sem telefone cadastrado - nota #{parsed.get('nNF')} guardada sem vínculo de contato.")

            payload = {
                "cnpj": parsed["dest_cnpj"],
                "cliente_nome": nome_cadastro or parsed.get("dest_nome"),
                "cliente_telefone": phone or None,
                "numero_nota": parsed.get("nNF"),
                "serie_nota": parsed.get("serie"),
                "chave_acesso": parsed.get("chave_acesso"),
                "valor": parsed.get("vNF"),
                "data_emissao": parsed.get("dhEmi"),
            }
            success = send_nfe_document_to_backend(self.config, payload, pdf_path, xml_path)
            move_processed_nfe(xml_path, pdf_path, success)
        finally:
            self._seen.discard(xml_path)

    def on_created(self, event):
        if not event.is_directory:
            self._process(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._process(event.dest_path)


def start_folder_watcher(config: dict) -> Observer:
    observer = Observer()
    watched_any = False
    for cod_tipo_evento, tipo, folder_key in [(1, "abertura", "pasta_abertura"), (3, "orcamento", "pasta_orcamento")]:
        folder = config.get(folder_key)
        if not folder or not os.path.isdir(folder):
            logger.warning(f"[vigia de pasta] '{folder_key}' não configurado ou pasta não encontrada - pulando: {folder}")
            continue
        observer.schedule(PdfFolderHandler(config, cod_tipo_evento, tipo), folder, recursive=False)
        logger.info(f"[vigia de pasta] Observando [{tipo}]: {folder}")
        watched_any = True

    nfe_folder = config.get("pasta_nfe")
    if nfe_folder and os.path.isdir(nfe_folder):
        observer.schedule(NFeFolderHandler(config), nfe_folder, recursive=False)
        logger.info(f"[vigia de pasta] Observando [nota fiscal]: {nfe_folder}")
        watched_any = True
    elif nfe_folder:
        logger.warning(f"[vigia de pasta] 'pasta_nfe' configurada mas não encontrada - pulando: {nfe_folder}")

    if watched_any:
        observer.start()
    return observer


def poll_empresa(config: dict, empresa_key: str, empresa_cfg: dict, state: dict):
    try:
        con = db_connect(empresa_cfg)
    except Exception as e:
        logger.error(f"[{empresa_key}] Não foi possível conectar ao banco: {e}")
        return

    try:
        tra, cur = read_only_cursor(con)
        try:
            since_data_raw = state.get(empresa_key, {}).get("last_data")
            # Firebird rejeita a comparação com uma string Python crua (erro de conversão em
            # torno das casas de microssegundos) - precisa de um datetime real.
            since_data = datetime.fromisoformat(since_data_raw) if since_data_raw else None
            events = fetch_new_events(cur, since_data)

            if since_data is None and events == []:
                # Primeira vez rodando para esta empresa: descobre o "agora" do banco e
                # salva como ponto de partida, sem processar nada retroativo.
                cur.execute("SELECT FIRST 1 DATA FROM EVENTOSORDEMSERVICO ORDER BY DATA DESC")
                row = cur.fetchone()
                baseline = row[0] if row else None
                state.setdefault(empresa_key, {})["last_data"] = str(baseline) if baseline else "1900-01-01"
                save_state(state)
                logger.info(f"[{empresa_key}] Primeira execução - marcando ponto de partida em {baseline}, sem processar histórico.")
                return

            for event in events:
                loja, codos, cnpj = event["LOJA"], event["CODOS"], event.get("CNPJ")
                equip = fetch_equipamento(cur, loja, codos, cnpj)
                if not equip and event["CODTIPOEVENTOOS"] == 1:
                    # O evento ENTRADA é gravado antes de o atendente lançar o equipamento na O.S. Espera um
                    # pouco (só leitura) para o aviso já sair com marca/modelo, em vez de "seu equipamento
                    # referente à O.S." sem dizer qual. Passado o prazo, avisa assim mesmo.
                    for _ in range(12):
                        time.sleep(5)
                        equip = fetch_equipamento(cur, loja, codos, cnpj)
                        if equip:
                            break
                event["_equip_marca"] = equip.get("marca")
                event["_equip_modelo"] = equip.get("modelo")
                event["_equip_descricao"] = equip.get("descricao")
                event["_equip_defeito"] = equip.get("defeito")
                cur.execute(
                    "SELECT CODTIPOEVENTOOS FROM EVENTOSORDEMSERVICO "
                    "WHERE LOJA=? AND CODOS=? AND DATA < ? ORDER BY DATA DESC",
                    (loja, codos, event["DATA"])
                )
                event["_eventos_anteriores"] = [r[0] for r in cur.fetchall()][:10]

                cod_evento = event["CODTIPOEVENTOOS"]
                pdf_path = ""
                if cod_evento in EVENTOS_COM_PDF:
                    pdf_path = find_expected_pdf(config, EVENTOS_COM_PDF[cod_evento], codos)

                success = send_event_to_backend(config, empresa_key, event, EVENTOS_COM_PDF.get(cod_evento, ""), pdf_path)
                if success:
                    state.setdefault(empresa_key, {})["last_data"] = str(event["DATA"])
                    save_state(state)
                else:
                    # Não avança o cursor - tenta esse mesmo evento de novo no próximo ciclo.
                    logger.warning(f"[{empresa_key}] Vai tentar o evento da O.S. #{codos} de novo no próximo ciclo.")
                    break
        finally:
            tra.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------------------------
# Quadro de técnicos: espelho das O.S. (técnico, cliente, equipamento, datas, eventos) no Ominichannel.
# SOMENTE LEITURA no Softsystem. Roda em conexão própria e com try/except: uma falha aqui nunca atrapalha
# os avisos aos clientes (poll_empresa acima).
# ---------------------------------------------------------------------------------------------
BOARD_BACKFILL_DAYS = 92   # a carga inicial traz os últimos ~3 meses (combinado com a loja)
BOARD_BATCH_SIZE = 200


def _board_orders_query(where_sql: str) -> str:
    return f"""
        SELECT os.LOJA, os.CODOS, os.CNPJ, os.DATA, os.TECNICOATENDIMENTO, os.TECNICOATENDIMENTO2,
               os.CODTIPOORDEMSERVICO, os.DATAALTERACAO, cli.RAZAOSOCIAL, cli.NOMEFANTASIA, os.CODCONDPAG,
               os.CODORCAMENTO, os.CONTATO, cli.DDD, cli.CELULAR, cli.FONE, cp.DESCRICAO
        FROM ORDEMSERVICO os
        LEFT JOIN CLIENTES cli ON cli.CGC = os.CNPJ
        LEFT JOIN CONDPAG cp ON cp.CODCONDPAG = os.CODCONDPAG
        {where_sql}
    """


def _board_valores(cur, keys: set) -> dict:
    """Valor de cada O.S. = soma dos itens (ITENSORDEMSERVICO.QUANTIDADE * PRECO) - é uma referência pra
    acompanhamento no quadro, não substitui o fechamento contábil oficial (não considera descontos/impostos)."""
    out = {}
    if not keys:
        return out
    codos = sorted({c for _, c in keys})
    for i in range(0, len(codos), 500):
        chunk = codos[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        cur.execute(f"""
            SELECT LOJA, CODOS, SUM(QUANTIDADE * PRECO)
            FROM ITENSORDEMSERVICO
            WHERE CODOS IN ({marks})
            GROUP BY LOJA, CODOS
        """, tuple(chunk))
        for loja, codos_, total in cur.fetchall():
            out[(loja, codos_)] = float(total) if total is not None else None
    return out


def _board_itens(cur, keys: set) -> dict:
    """Peças/produtos lançados em cada O.S. (ITENSORDEMSERVICO) - descrição, quantidade e preço
    linha a linha, pra tela de detalhe da O.S. no quadro. _board_valores (acima) já lê essa mesma
    tabela mas só soma o total; aqui é a listagem de verdade, item por item."""
    out = {}
    if not keys:
        return out
    codos = sorted({c for _, c in keys})
    for i in range(0, len(codos), 500):
        chunk = codos[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        cur.execute(f"""
            SELECT LOJA, CODOS, DESCRICAO, QUANTIDADE, PRECO
            FROM ITENSORDEMSERVICO
            WHERE CODOS IN ({marks})
            ORDER BY LOJA, CODOS
        """, tuple(chunk))
        for loja, codos_, descricao, quantidade, preco in cur.fetchall():
            if not descricao:
                continue
            out.setdefault((loja, codos_), []).append({
                "descricao": descricao.strip(),
                "quantidade": float(quantidade) if quantidade is not None else None,
                "preco": float(preco) if preco is not None else None,
            })
    return out


def _board_equipamentos(cur, keys: set) -> dict:
    """Primeiro equipamento de cada O.S. -> 'MARCA MODELO (DESCRIÇÃO)'. Uma consulta por faixa de CODOS."""
    out = {}
    if not keys:
        return out
    codos = sorted({c for _, c in keys})
    for i in range(0, len(codos), 500):
        chunk = codos[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        cur.execute(f"""
            SELECT eq.LOJA, eq.CODOS, eq.CODEQUIP, e.MARCA, e.MODELO, e.DESCRICAO
            FROM EQUIPORDEMSERVICO eq
            JOIN ORDEMSERVICO os ON os.LOJA = eq.LOJA AND os.CODOS = eq.CODOS
            LEFT JOIN EQUIPAMENTOS e ON e.CNPJ = os.CNPJ AND e.CODEQUIP = eq.CODEQUIP
            WHERE eq.CODOS IN ({marks})
            ORDER BY eq.LOJA, eq.CODOS, eq.CODEQUIP
        """, tuple(chunk))
        for loja, codos_, _cod, marca, modelo, desc in cur.fetchall():
            if (loja, codos_) in out:
                continue
            mm = " ".join(p for p in [marca, modelo] if p)
            out[(loja, codos_)] = f"{mm} ({desc})" if mm and desc else (mm or desc or None)
    return out


def _board_equip_obs(cur, keys: set) -> dict:
    """Observação que o próprio técnico escreve na tela da O.S. (EQUIPORDEMSERVICO.OBS, aba
    Equipamentos do Softsystem) descrevendo o problema/correção - usada como entrada pro laudo
    da IA (os_report_service.py). Pedido do usuário em 07/10/2026: quando a O.S. é só mão de
    obra/serviço (sem peça física pra 'dar a dica' sozinha pra IA), ele escreve a direção do
    problema ali, a IA lê, reelabora um laudo melhor e GRAVA POR CIMA (substitui, não acrescenta -
    diferente do mecanismo write_type='nota_defeito' já existente, que só acrescenta)."""
    out = {}
    if not keys:
        return out
    codos = sorted({c for _, c in keys})
    for i in range(0, len(codos), 500):
        chunk = codos[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        cur.execute(f"""
            SELECT LOJA, CODOS, OBS
            FROM EQUIPORDEMSERVICO
            WHERE CODOS IN ({marks})
            ORDER BY LOJA, CODOS
        """, tuple(chunk))
        for loja, codos_, obs in cur.fetchall():
            if (loja, codos_) in out or not obs:
                continue
            out[(loja, codos_)] = obs.strip()
    return out


def _board_events(cur, keys: set) -> dict:
    """O quadro espelha o Softsystem fielmente, sem exceção - o que muda por lá tem que aparecer
    aqui igual (e vice-versa: mudanças feitas pelo nosso sistema, como aprovação por WhatsApp, se
    refletem lá - ver poll_pending_writes). "N/A" na Observação só afeta se sai mensagem direta pro
    cliente sobre aquele evento (ver ingest_db_event_common no backend) - nunca se o evento conta
    pro estado do quadro. Pedido explícito do usuário em 28/09/2026 (O.S. #1676: Softsystem mostra
    "Orçamento enviado" mesmo com N/A, e o quadro tem que mostrar a mesma coisa)."""
    out = {}
    if not keys:
        return out
    codos = sorted({c for _, c in keys})
    for i in range(0, len(codos), 500):
        chunk = codos[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        cur.execute(f"SELECT LOJA, CODOS, DATA, CODTIPOEVENTOOS, OBS FROM EVENTOSORDEMSERVICO WHERE CODOS IN ({marks}) ORDER BY DATA", tuple(chunk))
        for loja, codos_, data, cod, obs in cur.fetchall():
            out.setdefault((loja, codos_), []).append((data, cod, obs))
    return out


def _board_payload(cur, empresa_key: str, order_rows: list) -> dict:
    keys = {(r[0], r[1]) for r in order_rows}
    equips = _board_equipamentos(cur, keys)
    equip_obs = _board_equip_obs(cur, keys)
    events = _board_events(cur, keys)
    valores = _board_valores(cur, keys)
    itens_por_os = _board_itens(cur, keys)
    orders, evs, itens = [], [], []
    for loja, codos, cnpj, data, tec1, tec2, cod_tipo, _alt, razao, fantasia, cond_pag, venda_codigo, contato, ddd, celular, fone, forma_pag in order_rows:
        # Mesma regra do aviso de abertura: celular do campo Contato da O.S., senão o do cadastro do
        # cliente - é quem recebe a cobrança automática de aprovação/retirada (ver os_board_followup_service).
        telefone, contato_nome, _origem = resolve_recipient({
            "RAZAOSOCIAL": razao, "NOMEFANTASIA": fantasia, "DDD": ddd, "CELULAR": celular, "FONE": fone, "CONTATO": contato,
        })
        orders.append({
            "loja": loja, "codos": codos, "cnpj": cnpj, "cliente": razao or fantasia,
            "tecnico": tec1, "tecnico2": tec2, "data_entrada": data.isoformat() if data else None,
            "cod_tipo_os": cod_tipo, "equipamento": equips.get((loja, codos)),
            "telefone": telefone or None, "contato_nome": contato_nome,
            # Já efetivada (sai do quadro, fica só na auditoria): condição de pagamento preenchida OU venda
            # gerada ("Ver Venda N" na tela da O.S., devolvida ao cliente)
            "paga": cond_pag is not None,
            "venda_codigo": venda_codigo,
            "valor_total": valores.get((loja, codos)),
            "forma_pagamento": forma_pag,
            "equip_obs": equip_obs.get((loja, codos)),
        })
        for ev_data, cod, obs in events.get((loja, codos), []):
            evs.append({"loja": loja, "codos": codos, "cod_evento": cod, "obs": obs, "data": ev_data.isoformat()})
        for item in itens_por_os.get((loja, codos), []):
            itens.append({"loja": loja, "codos": codos, **item})
    return {"empresa": empresa_key, "orders": orders, "events": evs, "itens": itens}


def _board_post(config: dict, payload: dict) -> bool:
    url = config["backend_url"].rstrip("/") + "/api/v1/os-board/sync"
    try:
        resp = requests.post(url, headers={"X-OS-Handler-Key": config["api_key"]}, json=payload,
                             timeout=config.get("timeout_seconds", 60))
        if resp.status_code == 200:
            return True
        logger.error(f"[quadro] Servidor recusou o lote ({len(payload['orders'])} O.S.): HTTP {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[quadro] Erro ao enviar lote ao servidor: {e}")
    return False


def sync_board_empresa(config: dict, empresa_key: str, empresa_cfg: dict, state: dict):
    """Carga inicial do histórico (uma vez) e depois só o que mudou (O.S. alteradas ou com evento novo)."""
    board = state.setdefault(empresa_key, {}).setdefault("board", {})
    con = db_connect(empresa_cfg)
    try:
        tra, cur = read_only_cursor(con)
        try:
            # marcos de "agora" lidos ANTES da carga: o que mudar durante ela é pego no ciclo seguinte
            cur.execute("SELECT MAX(DATAALTERACAO) FROM ORDEMSERVICO")
            max_alt = cur.fetchone()[0]
            cur.execute("SELECT MAX(DATA) FROM EVENTOSORDEMSERVICO")
            max_evt = cur.fetchone()[0]
            # Lançar peça/mão de obra sozinho (sem mudar status, sem gerar evento) NÃO bate
            # ORDEMSERVICO.DATAALTERACAO nem EVENTOSORDEMSERVICO - achado em produção em
            # 07/10/2026 testando a O.S. #1942 (peças lançadas pelo Softsystem de verdade, mas
            # a O.S. nunca apareceu como "mudada" pros dois cursores acima, ficou invisível pro
            # quadro). ITENSORDEMSERVICO.DATACADASTRO (data de criação de cada item) é o único
            # jeito de detectar isso incrementalmente.
            cur.execute("SELECT MAX(DATACADASTRO) FROM ITENSORDEMSERVICO")
            max_itens = cur.fetchone()[0]

            if not board.get("backfilled"):
                backfill_from = datetime.now() - timedelta(days=BOARD_BACKFILL_DAYS)
                # Traz TODAS as O.S. do período, inclusive já efetivadas: o backend decide o que entra no
                # quadro (paga/venda_codigo) e mantém as efetivadas disponíveis para a auditoria.
                cur.execute(_board_orders_query("WHERE os.DATA >= ? ORDER BY os.CODOS"), (backfill_from,))
                rows = cur.fetchall()
                logger.info(f"[{empresa_key}] Quadro de técnicos: carga inicial de {len(rows)} O.S. (desde {backfill_from.date()}).")
                for i in range(0, len(rows), BOARD_BATCH_SIZE):
                    batch = rows[i:i + BOARD_BATCH_SIZE]
                    if not _board_post(config, _board_payload(cur, empresa_key, batch)):
                        logger.warning(f"[{empresa_key}] Quadro: carga inicial interrompida no lote {i // BOARD_BATCH_SIZE + 1}; tenta de novo no próximo ciclo.")
                        return
                board["backfilled"] = True
                board["cursor_alt"] = str(max_alt) if max_alt else None
                board["cursor_evt"] = str(max_evt) if max_evt else None
                board["cursor_itens"] = str(max_itens) if max_itens else None
                save_state(state)
                logger.info(f"[{empresa_key}] Quadro de técnicos: carga inicial concluída.")
                return

            default_cursor = datetime.now() - timedelta(days=1)
            cursor_alt = datetime.fromisoformat(board["cursor_alt"]) if board.get("cursor_alt") else default_cursor
            cursor_evt = datetime.fromisoformat(board["cursor_evt"]) if board.get("cursor_evt") else default_cursor
            cursor_itens = datetime.fromisoformat(board["cursor_itens"]) if board.get("cursor_itens") else default_cursor
            changed = set()
            cur.execute("SELECT LOJA, CODOS FROM ORDEMSERVICO WHERE DATAALTERACAO > ?", (cursor_alt,))
            changed.update((r[0], r[1]) for r in cur.fetchall())
            cur.execute("SELECT LOJA, CODOS FROM EVENTOSORDEMSERVICO WHERE DATA > ?", (cursor_evt,))
            changed.update((r[0], r[1]) for r in cur.fetchall())
            cur.execute("SELECT LOJA, CODOS FROM ITENSORDEMSERVICO WHERE DATACADASTRO > ?", (cursor_itens,))
            changed.update((r[0], r[1]) for r in cur.fetchall())
            if changed:
                codos = sorted({c for _, c in changed})
                rows = []
                for i in range(0, len(codos), 500):
                    chunk = codos[i:i + 500]
                    marks = ",".join("?" for _ in chunk)
                    cur.execute(_board_orders_query(f"WHERE os.CODOS IN ({marks})"), tuple(chunk))
                    rows.extend(r for r in cur.fetchall() if (r[0], r[1]) in changed)
                for i in range(0, len(rows), BOARD_BATCH_SIZE):
                    if not _board_post(config, _board_payload(cur, empresa_key, rows[i:i + BOARD_BATCH_SIZE])):
                        return  # cursor não avança: reenvia no próximo ciclo
                logger.info(f"[{empresa_key}] Quadro de técnicos: {len(rows)} O.S. atualizada(s).")
            board["cursor_alt"] = str(max_alt) if max_alt else board.get("cursor_alt")
            board["cursor_evt"] = str(max_evt) if max_evt else board.get("cursor_evt")
            board["cursor_itens"] = str(max_itens) if max_itens else board.get("cursor_itens")
            save_state(state)
        finally:
            tra.commit()
    finally:
        con.close()


def _ack_pending_write(config: dict, write_id: int, success: bool, error: Optional[str]):
    url = config["backend_url"].rstrip("/") + f"/api/v1/os-handler/pending-writes/{write_id}/ack"
    try:
        requests.post(
            url, headers={"X-OS-Handler-Key": config["api_key"]},
            json={"success": success, "error": error}, timeout=config.get("timeout_seconds", 60)
        )
    except Exception as e:
        logger.error(f"Falha ao confirmar pro backend a escrita pendente #{write_id}: {e}")


def _sanitize_for_firebird(text: Optional[str]) -> str:
    """
    A conexão com esse Firebird usa charset=WIN1252 (ver db_connect) - texto com emoji ou outros
    caracteres fora do Windows-1252 (ex: relatório escrito pela IA, que usa emoji de propósito pro
    WhatsApp) quebra a escrita com UnicodeEncodeError ('charmap' codec can't encode...), e a
    escrita falhava calada (só ficava "failed" na fila, sem avisar ninguém). Troca cada caractere
    não suportado por "?" em vez de travar - mantém o resto do texto legível. Achado em produção em
    07/10/2026 (O.S. #1987/#1310/#1868, rascunho de relatório automático).
    """
    if not text:
        return ""
    return text.encode("cp1252", errors="replace").decode("cp1252")


def poll_pending_writes(config: dict, empresa_key: str, empresa_cfg: dict):
    """
    Único ponto deste vigia que ESCREVE no Softsystem: pega os pedidos de mudança de status que se
    acumularam no backend (hoje só o Portal do Técnico - ver SoftsystemPendingWrite e
    technician_update_os_status no backend) e grava de verdade no Firebird - insere o evento novo em
    EVENTOSORDEMSERVICO e "toca" a O.S. em ORDEMSERVICO (UPDATE de DATAALTERACAO) pra disparar o
    gatilho TG_SITUACAO_OS, que é quem recalcula a situação que a TELA do Softsystem mostra (sem
    esse toque, o evento fica gravado mas a tela da O.S. não reflete). Mecanismo confirmado
    manualmente em produção na O.S. #1933 antes de automatizar (28/09/2026).
    """
    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/pending-writes"
    try:
        resp = requests.get(
            url, headers={"X-OS-Handler-Key": config["api_key"]},
            params={"empresa": empresa_key}, timeout=config.get("timeout_seconds", 60)
        )
        resp.raise_for_status()
        writes = resp.json().get("writes", [])
    except Exception as e:
        logger.error(f"[{empresa_key}] Escrita pendente: erro ao consultar a fila no backend: {e}")
        return
    if not writes:
        return

    con = db_connect(empresa_cfg)
    try:
        for w in writes:
            write_id = w["id"]
            loja, codos, obs = w["loja"], w["codos"], _sanitize_for_firebird(w.get("obs"))
            write_type = w.get("write_type") or "evento"
            cod_evento = w.get("cod_evento")
            # Nome de quem pediu a mudança (técnico do Portal, ou "SISTEMA" pros avisos
            # automáticos) - grava no OPERADOR de verdade em vez do literal fixo de antes, pra dar
            # auditoria nativa no Softsystem (quem mudou, e quando - DATA já é CURRENT_TIMESTAMP).
            # Pedido do usuário em 07/10/2026, junto com liberar qualquer técnico mudar O.S. de outro.
            operador = (w.get("requested_by") or "PORTAL_TECNICO").strip()[:30] or "PORTAL_TECNICO"
            try:
                tra, cur = write_cursor(con)
                try:
                    if write_type == "nota_defeito":
                        # Acrescenta no campo "Observação" da O.S. (coluna OBS, VARCHAR(2000)), SEM
                        # mudar a etapa - usado pra avisos automáticos (ex.: WhatsApp do cliente
                        # inválido) e pro rascunho de relatório da IA. Campo CORRIGIDO em 07/10/2026:
                        # a escrita ia pra DEFEITO (VARCHAR(255), campo pequeno de defeito do
                        # equipamento) por engano - o campo real "Observação" que aparece na tela do
                        # Softsystem é OBS, bem maior (2000 chars). Usuário confirmou testando digitar
                        # direto em OBS. 14 O.S. tiveram DEFEITO corrompido por essa escrita errada
                        # antes da correção (ver backfill/limpeza feita junto com esse deploy).
                        cur.execute("SELECT FIRST 1 OBS FROM EQUIPORDEMSERVICO WHERE LOJA=? AND CODOS=?", (loja, codos))
                        existing_row = cur.fetchone()
                        existing_len = len(existing_row[0]) if existing_row and existing_row[0] else 0
                        prefix = f"\r\n[{operador} {datetime.now().strftime('%d/%m/%Y %H:%M')}] "
                        max_total = 2000
                        room = max_total - existing_len - len(prefix)
                        if room < 20:
                            logger.warning(f"[{empresa_key}] Escrita pendente #{write_id}: O.S. #{codos} sem espaço no campo de observação (já tem {existing_len}/2000 caracteres) - pulando.")
                            tra.rollback()
                            _ack_pending_write(config, write_id, False, f"Campo de observação cheio ({existing_len}/2000 caracteres)")
                            continue
                        obs_fit = obs if len(obs) <= room else (obs[:max(0, room - 3)] + "...")
                        nota = prefix + obs_fit
                        cur.execute(
                            "UPDATE EQUIPORDEMSERVICO SET OBS = COALESCE(OBS, '') || ? WHERE LOJA=? AND CODOS=?",
                            (nota, loja, codos)
                        )
                    elif write_type == "nota_defeito_replace":
                        # Substitui o campo Observação inteiro (não acrescenta) - usado só pelo
                        # laudo final da IA (os_report_service.approve_report): o técnico escreve
                        # uma nota crua ali (ex.: "igbt em curto, troquei os 4"), o sistema LÊ essa
                        # nota (ver db_watcher._board_equip_obs / sync_board_empresa) como entrada
                        # pro laudo, a IA reelabora um texto melhor e grava por cima - pedido
                        # explícito do usuário em 07/10/2026 ("a IA capta a informação do que
                        # escrevi, refaz o texto e escreve por cima do que escrevi melhorado").
                        nota = obs[:2000]
                        cur.execute(
                            "UPDATE EQUIPORDEMSERVICO SET OBS = ? WHERE LOJA=? AND CODOS=?",
                            (nota, loja, codos)
                        )
                    else:
                        cur.execute(
                            "INSERT INTO EVENTOSORDEMSERVICO (LOJA, CODOS, DATA, CODTIPOEVENTOOS, OBS, OPERADOR) "
                            "VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
                            (loja, codos, cod_evento, obs or "", operador)
                        )
                        cur.execute(
                            "UPDATE ORDEMSERVICO SET DATAALTERACAO = CURRENT_TIMESTAMP WHERE LOJA=? AND CODOS=?",
                            (loja, codos)
                        )
                    tra.commit()
                except Exception:
                    tra.rollback()
                    raise
                if write_type == "nota_defeito":
                    logger.info(f"[{empresa_key}] Escrita pendente #{write_id}: O.S. #{codos} -> nota gravada no campo de observação.")
                elif write_type == "nota_defeito_replace":
                    logger.info(f"[{empresa_key}] Escrita pendente #{write_id}: O.S. #{codos} -> campo de observação substituído pelo laudo da IA.")
                else:
                    logger.info(f"[{empresa_key}] Escrita pendente #{write_id}: O.S. #{codos} -> evento {cod_evento} gravado no Softsystem.")
                _ack_pending_write(config, write_id, True, None)
            except Exception as e:
                logger.error(f"[{empresa_key}] Escrita pendente #{write_id}: falha ao gravar O.S. #{codos} no Softsystem: {e}")
                _ack_pending_write(config, write_id, False, str(e))
    finally:
        con.close()


def _ack_pending_file_attach(config: dict, attach_id: int, success: bool, error: Optional[str]):
    url = config["backend_url"].rstrip("/") + f"/api/v1/os-handler/pending-file-attaches/{attach_id}/ack"
    try:
        requests.post(
            url, headers={"X-OS-Handler-Key": config["api_key"]},
            json={"success": success, "error": error}, timeout=config.get("timeout_seconds", 60)
        )
    except Exception as e:
        logger.error(f"Falha ao confirmar pro backend o anexo pendente #{attach_id}: {e}")


def poll_pending_file_attachs(config: dict, empresa_key: str, empresa_cfg: dict):
    """
    Fotos/arquivos de O.S. tirados direto no sistema (câmera do atendente/técnico - ver
    app/services/os_board_photo_service.py no backend) ainda não anexados na aba "Arquivos" da
    O.S. no Softsystem. A tela "Arquivos" só mostra Descrição/Data/Operador - ela NÃO guarda o
    arquivo em si, só esse metadado em ARQUIVOSORDEMSERVICO; quem acha o arquivo físico é o
    próprio Softsystem, pelo NOME, dentro da pasta configurada em CONFIGURACAO.DIRETORIOIMAGENS
    (confirmado em produção em 05/10/2026, testando um anexo manual pela tela em O.S.
    #1964/Centro-Oeste e #33160/Servweld: ambos salvos achatados nessa pasta, sem subpasta, como
    "Ordem Serviço {loja} {codos} {AAAAMMDD} {HHMMSS}.{extensão}" - o nome digitado pelo usuário
    vira só o rótulo em DESCRICAO). Então este vigia: copia o arquivo (já salvo pelo backend,
    mesma máquina deste vigia) pra essa pasta com esse nome, e grava a linha correspondente.
    """
    pasta = (config.get("pasta_arquivos") or {}).get(empresa_key)
    if not pasta or not os.path.isdir(pasta):
        return  # não configurado ou pasta não montada/acessível nesta máquina - pula sem erro

    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/pending-file-attaches"
    try:
        resp = requests.get(
            url, headers={"X-OS-Handler-Key": config["api_key"]},
            params={"empresa": empresa_key}, timeout=config.get("timeout_seconds", 60)
        )
        resp.raise_for_status()
        attaches = resp.json().get("attaches", [])
    except Exception as e:
        logger.error(f"[{empresa_key}] Anexo de O.S. pendente: erro ao consultar a fila no backend: {e}")
        return
    if not attaches:
        return

    con = db_connect(empresa_cfg)
    try:
        for a in attaches:
            attach_id = a["id"]
            loja, codos, source_path = a["loja"], a["codos"], a["source_path"]
            descricao, extensao, operador = a["descricao"], a["extensao"], a.get("operador") or "SISTEMA"
            try:
                if not os.path.isfile(source_path):
                    raise FileNotFoundError(f"Arquivo de origem não encontrado: {source_path}")
                now = datetime.now()
                dest_name = f"Ordem Serviço {loja} {codos} {now.strftime('%Y%m%d')} {now.strftime('%H%M%S')}{extensao}"
                dest_path = os.path.join(pasta, dest_name)
                shutil.copyfile(source_path, dest_path)

                tra, cur = write_cursor(con)
                try:
                    cur.execute(
                        "INSERT INTO ARQUIVOSORDEMSERVICO (LOJA, CODOS, DATA, OPERADOR, DESCRICAO, EXTENSAO) "
                        "VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
                        (loja, codos, operador, descricao, extensao)
                    )
                    tra.commit()
                except Exception:
                    tra.rollback()
                    raise
                logger.info(f"[{empresa_key}] Anexo pendente #{attach_id}: O.S. #{codos} -> '{dest_name}' copiado e gravado no Softsystem.")
                _ack_pending_file_attach(config, attach_id, True, None)
            except Exception as e:
                logger.error(f"[{empresa_key}] Anexo pendente #{attach_id}: falha ao anexar arquivo da O.S. #{codos} no Softsystem: {e}")
                _ack_pending_file_attach(config, attach_id, False, str(e))
    finally:
        con.close()


def main():
    _lock_socket = acquire_single_instance_lock()  # noqa: F841
    config = load_config()
    state = load_state()

    poll_interval = config.get("poll_interval_seconds", 20)
    logger.info(f"Vigia de banco iniciado. Consultando a cada {poll_interval}s. Pressione Ctrl+C para parar.")

    folder_observer = start_folder_watcher(config)

    try:
        while True:
            for empresa_key, empresa_cfg in config.get("empresas", {}).items():
                try:
                    poll_empresa(config, empresa_key, empresa_cfg, state)
                except Exception as e:
                    logger.error(f"[{empresa_key}] Erro inesperado no ciclo de consulta: {e}", exc_info=True)
                try:
                    poll_notas_fiscais(config, empresa_key, empresa_cfg, state)
                except Exception as e:
                    logger.error(f"[{empresa_key}] Nota fiscal: erro inesperado no ciclo (não afeta os avisos de O.S.): {e}", exc_info=True)
                try:
                    sync_board_empresa(config, empresa_key, empresa_cfg, state)
                except Exception as e:
                    logger.error(f"[{empresa_key}] Quadro de técnicos: erro no ciclo (não afeta os avisos): {e}", exc_info=True)
                try:
                    poll_pending_writes(config, empresa_key, empresa_cfg)
                except Exception as e:
                    logger.error(f"[{empresa_key}] Escrita pendente: erro inesperado no ciclo: {e}", exc_info=True)
                try:
                    poll_pending_file_attachs(config, empresa_key, empresa_cfg)
                except Exception as e:
                    logger.error(f"[{empresa_key}] Anexo de O.S. pendente: erro inesperado no ciclo: {e}", exc_info=True)
            try:
                retry_pending_folder_pdfs(config)
            except Exception as e:
                logger.error(f"Retentativa de PDFs pendentes: erro inesperado no ciclo: {e}", exc_info=True)
            time.sleep(poll_interval)
    finally:
        folder_observer.stop()
        folder_observer.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Vigia de banco encerrado.")
