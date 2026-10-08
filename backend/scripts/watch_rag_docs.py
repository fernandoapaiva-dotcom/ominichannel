"""
Observador contínuo das pastas de manuais técnicos (DOC. TÉCNICOS / ONDA DE CIRCUITO) —
quando um arquivo novo é criado/movido/alterado nessas pastas, indexa ele sozinho na base
RAG, sem precisar rodar scripts/ingest_rag_docs.py manualmente de novo.

Roda como processo de fundo no PM2, dentro da própria VM (mesmo lugar onde o mount CIFS e
o RAG já estão disponíveis):

    pm2 start venv/bin/python3 --name rag-folder-watcher -- scripts/watch_rag_docs.py
    pm2 save
"""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, time as dtime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# PollingObserver (não o Observer "nativo"/inotify) - achado em produção em 08/10/2026: o
# Observer padrão depende de notificação do KERNEL (inotify no Linux), que só dispara pra
# mudanças feitas localmente no filesystem. A pasta observada é um mount CIFS (rede) - quando um
# arquivo é criado remotamente por OUTRO computador via SMB (ex: o scraper rodando no Windows
# copiando pra Z:\...), o kernel Linux deste servidor nunca recebe esse evento de criação, então
# o vigia nunca "via" os arquivos novos, mesmo o mount CIFS já enxergando eles no disco (872+
# arquivos da ESAB chegaram sem gerar um único log de "[NOVO ARQUIVO]"). PollingObserver varre o
# diretório periodicamente em vez de depender de notificação do kernel - funciona com qualquer
# filesystem, local ou de rede.
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

from scripts.ingest_rag_docs import (
    is_allowed_file,
    marca_modelo_from_path,
    ingest_one_file,
    resolve_tenant_id,
    iter_target_files,
    doc_id_for_path,
    load_done_ids,
)
# Mesma lista de feriados nacionais já usada pra pausar a cobrança automática de O.S. em dia que a
# loja não abre - reaproveitada aqui pra pausar o TREINAMENTO pesado (ingestão/OCR) no mesmo
# critério de "dia útil", em vez de duplicar a lista (achado em produção em 08/10/2026: ingestão em
# massa rodando de tarde competia por CPU com as buscas reais dos técnicos).
from app.services.os_board_followup_service import _FERIADOS_NACIONAIS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("watch_rag_docs")
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

WATCHED_ROOTS = [
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/DOC. TÉCNICOS",
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/ONDA DE CIRCUITO",
]

STABILITY_CHECKS = 4
STABILITY_INTERVAL = 2.0

# Janela de processamento (treinamento) - pedido do usuário em 08/10/2026: arquivo novo detectado
# a qualquer hora (ex: dump de outro fabricante copiado de tarde) fica na FILA, sem processar na
# hora - a ingestão/OCR real (CPU pesada, minutos por arquivo) só roda fora do horário protegido,
# pra não disputar CPU com o uso real do sistema pelos técnicos (achado em produção no mesmo dia: a
# ingestão em massa da ESAB rodando de tarde chegou a deixar buscas reais lentas/com erro). Regra
# exata pedida pelo usuário: roda das 18h às 07h50 todo dia útil, corta nesse horário e só retoma
# às 18h seguintes - EXCETO sexta-feira ou véspera de feriado, onde roda sem cortar até voltar o
# próximo dia útil (ou seja: sábado/domingo/feriado inteiros também são janela livre, não só a
# noite). Isso cai numa regra só: só fica PROTEGIDO (bloqueado) quando hoje é dia útil normal E o
# horário está dentro do expediente (07h50-18h) - qualquer fim de semana/feriado já é dia não-útil
# inteiro, então nunca entra no bloqueio, não precisa de uma exceção separada pra "véspera".
PROTECTED_START = dtime(7, 50)
PROTECTED_END = dtime(18, 0)


def _now_brt() -> datetime:
    # Servidor roda em UTC - mesma conversão usada em os_board_followup_service._now_brt().
    return datetime.utcnow() - timedelta(hours=3)


def _is_business_day(d) -> bool:
    if d.weekday() >= 5:
        return False
    if d.strftime("%Y-%m-%d") in _FERIADOS_NACIONAIS:
        return False
    return True


def _in_night_window(now: datetime = None) -> bool:
    now = now or _now_brt()
    if not _is_business_day(now.date()):
        return True
    t = now.time()
    return not (PROTECTED_START <= t < PROTECTED_END)


# Fila de arquivos detectados durante o horário comercial, aguardando a janela livre (18h, ou
# antes se virar fim de semana/feriado). Compartilhada entre os handlers das duas pastas
# observadas - um único loop de dreno (_night_drain_loop) cuida de todas.
PENDING_QUEUE: list = []
PENDING_SET: set = set()

# Reaproveita o MESMO arquivo de retomada já usado pelo backfill manual da ESAB (49 arquivos já
# marcados como feitos não são reprocessados à toa) - a partir de agora serve como log geral de
# "já treinado", não mais exclusivo da ESAB: qualquer fabricante novo dropado em WATCHED_ROOTS
# soma nele. Caminho relativo a backend/ (cwd de quando o PM2 inicia este script).
RESUME_LOG_PATH = "scripts/ingest_esab_resume.log"
DONE_IDS: set = set()


def _mark_done(full_path: str):
    doc_id = doc_id_for_path(full_path)
    if doc_id in DONE_IDS:
        return
    DONE_IDS.add(doc_id)
    try:
        with open(RESUME_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(doc_id + "\n")
    except OSError as e:
        logger.error(f"[ERRO] Não consegui gravar {RESUME_LOG_PATH}: {e}")


def wait_until_file_is_stable(path: str, checks: int = STABILITY_CHECKS, interval: float = STABILITY_INTERVAL) -> bool:
    """Waits for file size to stop changing (file is still being copied over the network otherwise)."""
    last_size = -1
    stable_count = 0
    for _ in range(checks * 15):
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if size == last_size and size > 0:
            stable_count += 1
            if stable_count >= checks:
                return True
        else:
            stable_count = 0
        last_size = size
        time.sleep(interval)
    return False


class ManualsHandler(FileSystemEventHandler):
    def __init__(self, root: str, loop: asyncio.AbstractEventLoop, tenant_id: int):
        self.root = root
        self.loop = loop
        self.tenant_id = tenant_id
        self._processing = set()

    def _maybe_handle(self, path: str):
        fname = os.path.basename(path)
        if not is_allowed_file(fname):
            return
        if path in self._processing:
            return
        self._processing.add(path)
        asyncio.run_coroutine_threadsafe(self._process(path, fname), self.loop)

    def _process_sync_cleanup(self, path: str):
        self._processing.discard(path)

    async def _process(self, path: str, fname: str):
        try:
            stable = await asyncio.to_thread(wait_until_file_is_stable, path)
            if not stable or not os.path.exists(path):
                logger.warning(f"[INSTAVEL] Arquivo não estabilizou a tempo, ignorando: {path}")
                return
            marca, modelo = marca_modelo_from_path(self.root, path)

            if not _in_night_window():
                if path not in PENDING_SET:
                    PENDING_SET.add(path)
                    PENDING_QUEUE.append((path, marca, modelo, fname, self.tenant_id))
                    logger.info(
                        f"[NOVO ARQUIVO - NA FILA] {marca} / {modelo} / {fname} - "
                        f"processamento (treinamento) adiado pra fora do horário comercial"
                    )
                return

            logger.info(f"[NOVO ARQUIVO] Detectado: {marca} / {modelo} / {fname}")
            # use_ocr=True (pedido do usuário em 08/10/2026 - "ela está configurada pra aprender
            # com cada manual novo?"): sem isso, um arquivo novo que fosse página escaneada (sem
            # texto extraível) ficava de fora da base pra sempre, só o reprocessamento manual em
            # lote (ver scripts/ingest_rag_docs.py --ocr) pegava - agora o vigia cobre isso sozinho.
            await ingest_one_file(path, marca, modelo, fname, self.tenant_id, use_ocr=True)
            _mark_done(path)
        except Exception as e:
            logger.error(f"[ERRO] Falha processando {path}: {e}")
        finally:
            self._process_sync_cleanup(path)


    def on_created(self, event):
        if not event.is_directory:
            self._maybe_handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._maybe_handle(event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._maybe_handle(event.src_path)


async def _night_drain_loop():
    """
    Processa a fila (PENDING_QUEUE) de arquivos detectados fora da janela de treinamento, um de
    cada vez, só enquanto _in_night_window() continuar True - se bater 07h50 de um dia útil no
    meio do lote, para na hora e deixa o resto pra próxima janela (18h, ou antes se virar
    sexta/véspera de feriado).
    """
    while True:
        if _in_night_window() and PENDING_QUEUE:
            logger.info(f"[JANELA LIVRE] Iniciando treinamento de {len(PENDING_QUEUE)} arquivo(s) na fila")
            while PENDING_QUEUE and _in_night_window():
                path, marca, modelo, fname, tenant_id = PENDING_QUEUE.pop(0)
                PENDING_SET.discard(path)
                if not os.path.exists(path):
                    continue
                try:
                    logger.info(f"[TREINANDO] {marca} / {modelo} / {fname}")
                    await ingest_one_file(path, marca, modelo, fname, tenant_id, use_ocr=True)
                    _mark_done(path)
                except Exception as e:
                    logger.error(f"[ERRO] Falha processando (janela livre) {path}: {e}")
                await asyncio.sleep(0.3)
            if not PENDING_QUEUE:
                logger.info("[JANELA LIVRE] Fila esvaziada")
            elif not _in_night_window():
                logger.info(f"[JANELA LIVRE] Horário comercial começou - {len(PENDING_QUEUE)} arquivo(s) ainda na fila, retomando depois")
        await asyncio.sleep(120)


async def _reconcile_backlog_loop(tenant_id: int, interval_seconds: int = 300):
    """
    O PollingObserver só enxerga mudanças a partir do momento em que o watcher está rodando - um
    arquivo que já estava na pasta ANTES do processo (atual ou de uma ingestão em lote anterior,
    interrompida) nunca dispara on_created/on_modified sozinho (achado em produção em 08/10/2026:
    é por isso que o backfill da ESAB precisava de scripts/ingest_rag_docs.py rodado manualmente).
    Esta varredura periódica cobre esse buraco sem precisar de intervenção manual nunca mais - acha
    TODO arquivo elegível em WATCHED_ROOTS ainda não marcado em DONE_IDS e põe na fila (respeitando
    a mesma janela de horário protegido). Cobre tanto o restante da ESAB quanto qualquer fabricante
    novo que for só copiado pra rede (sem precisar reiniciar nada).
    """
    while True:
        try:
            # os.walk numa pasta de rede (CIFS) com centenas de arquivos pode demorar alguns
            # segundos - roda numa thread separada pra não travar o loop de eventos (handlers
            # ao vivo, drain loop) enquanto varre.
            all_files = await asyncio.to_thread(lambda: list(iter_target_files(WATCHED_ROOTS)))
            found_new = 0
            for full_path, marca, modelo, fname in all_files:
                if doc_id_for_path(full_path) in DONE_IDS or full_path in PENDING_SET:
                    continue
                PENDING_SET.add(full_path)
                PENDING_QUEUE.append((full_path, marca, modelo, fname, tenant_id))
                found_new += 1
            if found_new:
                logger.info(f"[RECONCILIACAO] {found_new} arquivo(s) de backlog adicionado(s) à fila")
        except Exception as e:
            logger.error(f"[ERRO] Falha na reconciliação de backlog: {e}")
        await asyncio.sleep(interval_seconds)


async def main():
    env_tenant_id = os.environ.get("RAG_TENANT_ID")
    tenant_id = int(env_tenant_id) if env_tenant_id else await resolve_tenant_id()
    logger.info(f"Usando tenant_id={tenant_id}")

    DONE_IDS.update(load_done_ids(RESUME_LOG_PATH))
    logger.info(f"{len(DONE_IDS)} documento(s) já treinados antes (não serão reprocessados)")

    loop = asyncio.get_running_loop()
    # timeout=30s: intervalo de varredura do PollingObserver - não precisa ser instantâneo (o
    # vigia só serve pra não esquecer de indexar manualmente, não pra tempo real), e varrer uma
    # pasta de rede a cada 1s (padrão) geraria tráfego CIFS desnecessário o tempo todo.
    observer = Observer(timeout=30)

    any_root = False
    for root in WATCHED_ROOTS:
        if not os.path.isdir(root):
            logger.warning(f"Pasta não encontrada, não será observada: {root}")
            continue
        handler = ManualsHandler(root, loop, tenant_id)
        observer.schedule(handler, root, recursive=True)
        logger.info(f"Observando: {root}")
        any_root = True

    if not any_root:
        logger.error("Nenhuma pasta válida para observar. Encerrando.")
        return

    observer.start()
    drain_task = asyncio.create_task(_night_drain_loop())
    reconcile_task = asyncio.create_task(_reconcile_backlog_loop(tenant_id))
    logger.info(
        f"Observador rodando. Aguardando arquivos novos... "
        f"(treinamento roda fora do horário comercial - 18h às 07h50 em dia útil, sem corte em "
        f"fim de semana/feriado; durante o expediente, fica na fila)"
    )
    try:
        while True:
            await asyncio.sleep(2)
    finally:
        drain_task.cancel()
        reconcile_task.cancel()
        observer.stop()
        observer.join()


if __name__ == "__main__":
    asyncio.run(main())
