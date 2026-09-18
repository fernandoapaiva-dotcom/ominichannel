"""
Vigia de pasta - roda no computador da loja (Windows), observa as pastas onde o
Softsystem salva o PDF da Ordem de Serviço, e envia cada arquivo novo para o
sistema Ominichannel processar automaticamente (avisos + PDF pro cliente).

Duas pastas são observadas, cada uma com um sentido diferente:
  - ABERTURA:  quando a O.S. é aberta (orçamento/garantia/locação) -> origem="abertura"
  - ORCAMENTO: quando o técnico alimenta a O.S. com o laudo/valor  -> origem="orcamento"

Configuração: edite config.json (mesma pasta deste script) antes de rodar.

Uso:
    python watcher.py

Para rodar sempre em segundo plano, crie uma Tarefa Agendada do Windows que execute
este comando no logon (ver README.md nesta pasta para o passo a passo).
"""
import os
import sys
import json
import time
import shutil
import socket
import logging
from datetime import datetime

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
# Arbitrary fixed local port used purely as a system-wide single-instance lock (not a real
# server). Binding fails if another watcher is already running - system-wide, not per-user,
# which matters here: on a shared station, more than one operator can log in over the course
# of the day and each logon starts the watcher again (see README) - this stops duplicates
# without needing a Windows service or any special permissions.
SINGLE_INSTANCE_PORT = 47812

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watcher.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("os_folder_watcher")


def acquire_single_instance_lock() -> socket.socket:
    """Returns a bound socket (kept open for the process lifetime) or exits if one is already running."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        logger.info("Já existe um vigia de pasta rodando nesta estação - encerrando esta segunda instância.")
        sys.exit(0)
    return s


def wait_for_folders(folders: list, max_wait_seconds: int = 60) -> None:
    """
    On logon, a mapped network drive (Z:) can take a few seconds to become available - the
    Startup entry can fire before that finishes. Retry instead of failing immediately.
    """
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        if all(os.path.isdir(f) for f in folders if f):
            return
        time.sleep(3)


def load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        logger.error(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def wait_until_file_is_stable(path: str, checks: int = 4, interval: float = 1.0) -> bool:
    """
    Espera o arquivo parar de crescer antes de ler - o Softsystem pode ainda estar
    terminando de escrever o PDF quando o evento de 'arquivo criado' disparar.
    """
    last_size = -1
    stable_count = 0
    for _ in range(30):  # até 30s de espera no total
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


def send_to_backend(config: dict, file_path: str, origem: str) -> bool:
    url = config["backend_url"].rstrip("/") + "/api/v1/os-handler/ingest"
    headers = {"X-OS-Handler-Key": config["api_key"]}
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/pdf")}
            data = {"origem": origem}
            resp = requests.post(url, headers=headers, files=files, data=data, timeout=config.get("timeout_seconds", 60))
        if resp.status_code == 200:
            logger.info(f"OK [{origem}] {file_path} -> {resp.json()}")
            return True
        else:
            logger.error(f"FALHA [{origem}] {file_path} -> HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"ERRO ao enviar {file_path}: {e}")
        return False


def move_processed_file(config: dict, file_path: str, success: bool):
    subdir = "processados" if success else "erros"
    dest_dir = os.path.join(os.path.dirname(file_path), subdir)
    os.makedirs(dest_dir, exist_ok=True)
    filename = os.path.basename(file_path)
    dest_path = os.path.join(dest_dir, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}")
    try:
        shutil.move(file_path, dest_path)
    except Exception as e:
        logger.error(f"Não foi possível mover {file_path} para {dest_dir}: {e}")


class PdfHandler(FileSystemEventHandler):
    def __init__(self, config: dict, origem: str):
        self.config = config
        self.origem = origem
        self._seen = set()

    def _process(self, path: str):
        if not path.lower().endswith(".pdf"):
            return
        if path in self._seen:
            return
        self._seen.add(path)

        logger.info(f"Novo arquivo detectado [{self.origem}]: {path}")
        if not wait_until_file_is_stable(path):
            logger.warning(f"Arquivo não estabilizou a tempo, tentando mesmo assim: {path}")

        success = send_to_backend(self.config, path, self.origem)
        if self.config.get("move_processed_files", True):
            move_processed_file(self.config, path, success)

        self._seen.discard(path)

    def on_created(self, event):
        if not event.is_directory:
            self._process(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._process(event.dest_path)


def main():
    _lock_socket = acquire_single_instance_lock()  # noqa: F841 - kept alive for process lifetime

    config = load_config()

    all_folders = [config.get("pasta_abertura"), config.get("pasta_orcamento")]
    wait_for_folders(all_folders)

    observer = Observer()
    watched_any = False

    for origem, folder_key in [("abertura", "pasta_abertura"), ("orcamento", "pasta_orcamento")]:
        folder = config.get(folder_key)
        if not folder:
            logger.warning(f"'{folder_key}' não configurado em config.json - pulando.")
            continue
        if not os.path.isdir(folder):
            logger.error(f"Pasta não encontrada, verifique config.json: {folder}")
            continue
        handler = PdfHandler(config, origem)
        observer.schedule(handler, folder, recursive=False)
        logger.info(f"Observando [{origem}]: {folder}")
        watched_any = True

    if not watched_any:
        logger.error("Nenhuma pasta válida configurada. Verifique config.json e tente novamente.")
        sys.exit(1)

    observer.start()
    logger.info("Vigia de pasta iniciado. Pressione Ctrl+C para parar.")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
