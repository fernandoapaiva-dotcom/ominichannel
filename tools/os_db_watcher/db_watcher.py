"""
Vigia de banco - roda no computador da loja (Windows), observa DIRETO o banco Firebird
do Softsystem (só leitura, nunca escreve nada nele) em busca de eventos novos na aba
"Eventos" da Ordem de Serviço, e envia os dados já resolvidos (telefone, natureza,
equipamento, técnico) para o sistema Ominichannel processar automaticamente.

Substitui o vigia de pasta (os_folder_watcher) como fonte principal de dados - lê direto
das tabelas do Softsystem em vez de tentar extrair texto de PDF, o que elimina os problemas
de ordem de extração e de sincronização do Google Drive enfrentados com a abordagem antiga.
O PDF ainda é enviado ao cliente quando encontrado na pasta compartilhada (procurado pelo
nome esperado "<codigo da os>.pdf"), mas só como anexo - os dados vêm todos do banco.

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
import logging
import re
from datetime import datetime

import requests
from firebird.driver import connect, TPB, Isolation, TraAccessMode

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
    return connect(
        f"{empresa_cfg['host']}:{empresa_cfg['database']}",
        user=empresa_cfg.get("user", "SYSDBA"),
        password=empresa_cfg["password"],
        no_db_triggers=True
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
                   cli.RAZAOSOCIAL, cli.NOMEFANTASIA, cli.DDD, cli.CELULAR, cli.FONE
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
                   cli.RAZAOSOCIAL, cli.NOMEFANTASIA, cli.DDD, cli.CELULAR, cli.FONE
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


def send_event_to_backend(config: dict, empresa_key: str, event: dict, tipo: str, pdf_path: str) -> bool:
    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/db-event"
    headers = {"X-OS-Handler-Key": config["api_key"]}
    phone = build_phone(event.get("DDD"), event.get("CELULAR") or event.get("FONE"))
    if not phone:
        logger.warning(f"[{empresa_key}] O.S. #{event['CODOS']}: sem telefone do cliente, não enviado.")
        return True  # não é um erro de rede - não faz sentido re-tentar, só pula

    payload = {
        "empresa": empresa_key,
        "loja": event["LOJA"],
        "codos": event["CODOS"],
        "cod_tipo_evento": event["CODTIPOEVENTOOS"],
        "cliente_nome": event.get("RAZAOSOCIAL") or event.get("NOMEFANTASIA"),
        "cliente_telefone": phone,
        "natureza_codigo": event.get("CODTIPOORDEMSERVICO"),
        "equip_marca": event.get("_equip_marca"),
        "equip_modelo": event.get("_equip_modelo"),
        "equip_descricao": event.get("_equip_descricao"),
        "equip_defeito": event.get("_equip_defeito"),
        "tecnico_nome": event.get("TECNICOATENDIMENTO"),
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
            logger.info(f"OK [{empresa_key}] O.S. #{event['CODOS']} evento {event['CODTIPOEVENTOOS']} -> {resp.json()}")
            return True
        else:
            logger.error(f"FALHA [{empresa_key}] O.S. #{event['CODOS']} evento {event['CODTIPOEVENTOOS']} -> HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"ERRO ao enviar O.S. #{event['CODOS']} ({empresa_key}): {e}")
        return False


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
                event["_equip_marca"] = equip.get("marca")
                event["_equip_modelo"] = equip.get("modelo")
                event["_equip_descricao"] = equip.get("descricao")
                event["_equip_defeito"] = equip.get("defeito")

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


def main():
    _lock_socket = acquire_single_instance_lock()  # noqa: F841
    config = load_config()
    state = load_state()

    poll_interval = config.get("poll_interval_seconds", 20)
    logger.info(f"Vigia de banco iniciado. Consultando a cada {poll_interval}s. Pressione Ctrl+C para parar.")

    while True:
        for empresa_key, empresa_cfg in config.get("empresas", {}).items():
            try:
                poll_empresa(config, empresa_key, empresa_cfg, state)
            except Exception as e:
                logger.error(f"[{empresa_key}] Erro inesperado no ciclo de consulta: {e}", exc_info=True)
        time.sleep(poll_interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Vigia de banco encerrado.")
