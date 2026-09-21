"""
Vigia de banco - roda no computador da loja (Windows), observa DIRETO o banco Firebird
do Softsystem (só leitura, nunca escreve nada nele) em busca de eventos novos na aba
"Eventos" da Ordem de Serviço, e envia os dados já resolvidos (telefone, natureza,
equipamento, técnico) para o sistema Ominichannel processar automaticamente.

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
from datetime import datetime, timedelta

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
            basename = os.path.splitext(os.path.basename(path))[0]
            if not basename.isdigit():
                logger.warning(f"[vigia de pasta] Nome de arquivo não é um código de O.S. numérico, ignorando: {path}")
                return
            codos = int(basename)

            logger.info(f"[vigia de pasta] Novo PDF detectado [{self.tipo}]: {path}")
            if not wait_until_file_is_stable(path):
                logger.warning(f"[vigia de pasta] Arquivo não estabilizou a tempo, tentando mesmo assim: {path}")

            empresa_key, event = find_os_by_codos(self.config, codos)
            if not event:
                logger.error(f"[vigia de pasta] O.S. #{codos} não encontrada em nenhuma empresa - PDF não enviado: {path}")
                move_processed_pdf(path, success=False)
                return

            event["CODTIPOEVENTOOS"] = self.cod_tipo_evento
            success = send_event_to_backend(self.config, empresa_key, event, self.tipo, path)
            move_processed_pdf(path, success)
        finally:
            self._seen.discard(path)

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
               os.CODTIPOORDEMSERVICO, os.DATAALTERACAO, cli.RAZAOSOCIAL, cli.NOMEFANTASIA, os.CODCONDPAG
        FROM ORDEMSERVICO os
        LEFT JOIN CLIENTES cli ON cli.CGC = os.CNPJ
        {where_sql}
    """


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


def _board_events(cur, keys: set) -> dict:
    out = {}
    if not keys:
        return out
    codos = sorted({c for _, c in keys})
    for i in range(0, len(codos), 500):
        chunk = codos[i:i + 500]
        marks = ",".join("?" for _ in chunk)
        cur.execute(f"SELECT LOJA, CODOS, DATA, CODTIPOEVENTOOS FROM EVENTOSORDEMSERVICO WHERE CODOS IN ({marks}) ORDER BY DATA", tuple(chunk))
        for loja, codos_, data, cod in cur.fetchall():
            out.setdefault((loja, codos_), []).append((data, cod))
    return out


def _board_payload(cur, empresa_key: str, order_rows: list) -> dict:
    keys = {(r[0], r[1]) for r in order_rows}
    equips = _board_equipamentos(cur, keys)
    events = _board_events(cur, keys)
    orders, evs = [], []
    for loja, codos, cnpj, data, tec1, tec2, cod_tipo, _alt, razao, fantasia, cond_pag in order_rows:
        orders.append({
            "loja": loja, "codos": codos, "cnpj": cnpj, "cliente": razao or fantasia,
            "tecnico": tec1, "tecnico2": tec2, "data_entrada": data.isoformat() if data else None,
            "cod_tipo_os": cod_tipo, "equipamento": equips.get((loja, codos)),
            # Condição de pagamento preenchida = O.S. já efetivada (venda gerada): sai do quadro
            "paga": cond_pag is not None,
        })
        for ev_data, cod in events.get((loja, codos), []):
            evs.append({"loja": loja, "codos": codos, "cod_evento": cod, "data": ev_data.isoformat()})
    return {"empresa": empresa_key, "orders": orders, "events": evs}


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

            if not board.get("backfilled"):
                backfill_from = datetime.now() - timedelta(days=BOARD_BACKFILL_DAYS)
                # O.S. já efetivadas (condição de pagamento preenchida) não entram na carga inicial
                cur.execute(_board_orders_query("WHERE os.DATA >= ? AND os.CODCONDPAG IS NULL ORDER BY os.CODOS"), (backfill_from,))
                rows = cur.fetchall()
                logger.info(f"[{empresa_key}] Quadro de técnicos: carga inicial de {len(rows)} O.S. em aberto de pagamento (desde {backfill_from.date()}).")
                for i in range(0, len(rows), BOARD_BATCH_SIZE):
                    batch = rows[i:i + BOARD_BATCH_SIZE]
                    if not _board_post(config, _board_payload(cur, empresa_key, batch)):
                        logger.warning(f"[{empresa_key}] Quadro: carga inicial interrompida no lote {i // BOARD_BATCH_SIZE + 1}; tenta de novo no próximo ciclo.")
                        return
                board["backfilled"] = True
                board["cursor_alt"] = str(max_alt) if max_alt else None
                board["cursor_evt"] = str(max_evt) if max_evt else None
                save_state(state)
                logger.info(f"[{empresa_key}] Quadro de técnicos: carga inicial concluída.")
                return

            default_cursor = datetime.now() - timedelta(days=1)
            cursor_alt = datetime.fromisoformat(board["cursor_alt"]) if board.get("cursor_alt") else default_cursor
            cursor_evt = datetime.fromisoformat(board["cursor_evt"]) if board.get("cursor_evt") else default_cursor
            changed = set()
            cur.execute("SELECT LOJA, CODOS FROM ORDEMSERVICO WHERE DATAALTERACAO > ?", (cursor_alt,))
            changed.update((r[0], r[1]) for r in cur.fetchall())
            cur.execute("SELECT LOJA, CODOS FROM EVENTOSORDEMSERVICO WHERE DATA > ?", (cursor_evt,))
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
            save_state(state)
        finally:
            tra.commit()
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
                    sync_board_empresa(config, empresa_key, empresa_cfg, state)
                except Exception as e:
                    logger.error(f"[{empresa_key}] Quadro de técnicos: erro no ciclo (não afeta os avisos): {e}", exc_info=True)
            time.sleep(poll_interval)
    finally:
        folder_observer.stop()
        folder_observer.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Vigia de banco encerrado.")
