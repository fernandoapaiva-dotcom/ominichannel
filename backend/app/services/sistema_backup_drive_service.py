"""
Backup do RAG e do sistema no Google Drive (14/10/2026). Pedido do usuário: "preciso de backup de tudo
isso que estamos fazendo... toda atualização da rag suba para o drive para não ter risco de perder nada".

O backup diário que já existia (daily_backup_drive_service) manda o BANCO (.db - inclui o catálogo de
peças, o consumo de IA, as conversas) e as MÍDIAS. Faltavam:
  - o RAG (chroma_data, ~1,3 GB: todo o treino dos manuais, inclusive o OCR que custou IA);
  - o sistema (código do backend/frontend + .env, que tem a chave que descriptografa as configurações
    do banco - sem ela o backup do banco não serve para nada).

Como funciona (loop dentro do backend, ver start_sistema_backup_loop):
  - a cada 30 min confere se o RAG mudou desde o último backup; se mudou, espera ele ficar QUIETO
    (30 min sem gravação - o treino da madrugada termina 7h50) e sobe uma cópia consistente:
    chroma.sqlite3 via API de backup do SQLite + pastas do índice, compactado (.tar.gz);
  - o sistema (código + .env) sobe quando algum arquivo mudar (ou seja, a cada publicação);
  - no Drive ficam as últimas MANTER_RAG cópias do RAG e MANTER_SISTEMA do sistema, nas subpastas
    Backup_RAG e Backup_Sistema da pasta de backup configurada em Admin > Integrações.

Restaurar o RAG: parar o backend (pm2 stop omini-backend rag-folder-watcher), renomear chroma_data,
criar uma chroma_data nova e extrair o .tar.gz dentro dela (tar -xzf rag_chroma_....tar.gz -C chroma_data),
iniciar de novo.  Restaurar o sistema: extrair o sistema_....tar.gz na pasta do projeto, recriar o venv
(pip install -r backend/requirements.txt) e o frontend (npm install && npm run build).

Rodar na mão:  venv/bin/python -m app.services.sistema_backup_drive_service --agora
"""
import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from datetime import datetime

logger = logging.getLogger("sistema_backup_drive")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJETO_DIR = os.path.dirname(BACKEND_DIR)
CHROMA_DIR = os.path.join(BACKEND_DIR, "chroma_data")
TRABALHO_DIR = os.path.join(BACKEND_DIR, "backups_db")
ESTADO_ARQ = os.path.join(TRABALHO_DIR, "backup_sistema_estado.json")
TRAVA_ARQ = os.path.join(TRABALHO_DIR, "backup_sistema.lock")

PASTA_RAG, PASTA_SISTEMA = "Backup_RAG", "Backup_Sistema"
MANTER_RAG, MANTER_SISTEMA = 3, 10
QUIETO_SEG = 30 * 60          # RAG sem gravação há 30 min = treino parado, cópia consistente
INTERVALO_SEG = 30 * 60
MIN_ENTRE_RAG_SEG = 12 * 3600  # no máximo 2 cópias do RAG por dia (cada uma tem ~1 GB)

# Fora do backup do sistema: pesado, regenerável ou já coberto por outro backup
EXCLUIR_DIRS = {"venv", ".venv", "node_modules", "chroma_data", "uploads", "backups_db", "backups_json", "dist",
                "__pycache__", ".git", "logs", ".pytest_cache", ".mypy_cache"}
EXCLUIR_SUFIXOS = (".db", ".db-journal", ".db-wal", ".db-shm", ".log", ".pyc", ".tar.gz", ".zip", ".pkl")


# ----------------------------------------------------------------------------------------- estado

def ler_estado() -> dict:
    try:
        with open(ESTADO_ARQ, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _salvar_estado(tipo: str, **campos) -> None:
    estado = ler_estado()
    estado.setdefault(tipo, {}).update(campos)
    os.makedirs(TRABALHO_DIR, exist_ok=True)
    tmp = ESTADO_ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO_ARQ)


def _pegar_trava() -> bool:
    """Evita dois backups ao mesmo tempo (loop do backend x execução manual)."""
    os.makedirs(TRABALHO_DIR, exist_ok=True)
    try:
        if os.path.exists(TRAVA_ARQ) and time.time() - os.path.getmtime(TRAVA_ARQ) < 4 * 3600:
            return False
        with open(TRAVA_ARQ, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return False


def _soltar_trava() -> None:
    try:
        os.remove(TRAVA_ARQ)
    except Exception:
        pass


# ----------------------------------------------------------------------------------------- assinaturas

def _arquivos_rag() -> list:
    out = []
    for raiz, _, nomes in os.walk(CHROMA_DIR):
        for n in nomes:
            out.append(os.path.join(raiz, n))
    return out


def assinatura_rag() -> tuple:
    """(assinatura, segundos desde a última gravação)."""
    h, ultima = hashlib.sha1(), 0.0
    for p in sorted(_arquivos_rag()):
        try:
            st = os.stat(p)
        except OSError:
            continue
        h.update(f"{os.path.relpath(p, CHROMA_DIR)}|{st.st_size}|{int(st.st_mtime)}".encode())
        ultima = max(ultima, st.st_mtime)
    return h.hexdigest()[:16], (time.time() - ultima) if ultima else 0


def _arquivos_sistema() -> list:
    out = []
    for raiz, dirs, nomes in os.walk(PROJETO_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUIR_DIRS and not d.startswith("dist.bak") and ".bak-" not in d]
        for n in nomes:
            if n.endswith(EXCLUIR_SUFIXOS) or ".bak-" in n:
                continue
            p = os.path.join(raiz, n)
            try:
                if os.path.getsize(p) > 50 * 1024 * 1024:  # arquivo solto gigante não é código
                    continue
            except OSError:
                continue
            out.append(p)
    return out


def assinatura_sistema() -> str:
    h = hashlib.sha1()
    for p in sorted(_arquivos_sistema()):
        try:
            st = os.stat(p)
        except OSError:
            continue
        h.update(f"{os.path.relpath(p, PROJETO_DIR)}|{st.st_size}|{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


# ----------------------------------------------------------------------------------------- Drive

def _credenciais_drive():
    """Pega pasta + OAuth do primeiro tenant com o Google Drive conectado (Admin > Integrações)."""
    async def _ler():
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.models import Tenant
        from app.services.settings_service import settings_service
        async with AsyncSessionLocal() as db:
            for t in (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().all():
                cfg = await settings_service.get_tenant_decrypted_settings(db, t.id)
                cred = (cfg.get("gdrive_folder_id"), cfg.get("google_client_id"), cfg.get("google_client_secret"), cfg.get("gdrive_refresh_token"))
                if all(cred):
                    return cred
        return None
    return _ler


def _servico_drive(client_id, client_secret, refresh_token):
    from app.services.gdrive_service import gdrive_service
    svc = gdrive_service._get_drive_service_from_refresh_token(client_id, client_secret, refresh_token)
    if not svc:
        raise RuntimeError("Falha ao autenticar no Google Drive (token expirado ou revogado - reconecte em Admin > Integrações)")
    return svc


def _subpasta(svc, pai: str, nome: str) -> str:
    q = f"'{pai}' in parents and name = '{nome}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    achou = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    if achou:
        return achou[0]["id"]
    return svc.files().create(body={"name": nome, "mimeType": "application/vnd.google-apps.folder", "parents": [pai]},
                              fields="id").execute()["id"]


def _enviar(svc, pasta: str, caminho: str, nome: str) -> str:
    """Upload em partes (retomável) - o RAG tem ~1 GB, não dá pra mandar numa requisição só."""
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(caminho, mimetype="application/gzip", resumable=True, chunksize=16 * 1024 * 1024)
    req = svc.files().create(body={"name": nome, "parents": [pasta]}, media_body=media, fields="id")
    resp = None
    while resp is None:
        _, resp = req.next_chunk(num_retries=6)
    return resp["id"]


def _limpar_antigos(svc, pasta: str, prefixo: str, manter: int) -> int:
    q = f"'{pasta}' in parents and name contains '{prefixo}' and trashed = false"
    arqs = svc.files().list(q=q, fields="files(id, name)", pageSize=200).execute().get("files", [])
    arqs = sorted((a for a in arqs if a["name"].startswith(prefixo)), key=lambda a: a["name"], reverse=True)
    for a in arqs[manter:]:
        try:
            svc.files().delete(fileId=a["id"]).execute()
        except Exception as e:
            logger.warning(f"[BACKUP SISTEMA] não apaguei a cópia antiga {a['name']}: {e}")
    return max(0, len(arqs) - manter)


# ----------------------------------------------------------------------------------------- cópias

def _compactar(origem_dir: str, destino: str, arquivos: list | None = None) -> None:
    if arquivos is None and shutil.which("tar") and shutil.which("nice"):
        subprocess.run(["nice", "-n", "15", "tar", "-C", origem_dir, "--use-compress-program=gzip -1", "-cf", destino, "."],
                       check=True, timeout=3 * 3600)
        return
    with tarfile.open(destino, "w:gz", compresslevel=1) as tar:
        if arquivos is None:
            tar.add(origem_dir, arcname=".")
        else:
            for p in arquivos:
                tar.add(p, arcname=os.path.relpath(p, origem_dir))


def _copia_rag(destino_tar: str) -> str:
    """Cópia consistente do RAG. Devolve a assinatura copiada (ou levanta erro se mudou durante a cópia)."""
    assin_antes, _ = assinatura_rag()
    tmp = os.path.join(TRABALHO_DIR, f"_rag_tmp_{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        for nome in os.listdir(CHROMA_DIR):
            orig = os.path.join(CHROMA_DIR, nome)
            if nome == "chroma.sqlite3":
                src = sqlite3.connect(f"file:{orig}?mode=ro", uri=True, timeout=60)
                dst = sqlite3.connect(os.path.join(tmp, nome))
                src.backup(dst, pages=8192, sleep=0.05)  # em partes: não trava o backend lendo o RAG
                dst.close()
                src.close()
            elif os.path.isdir(orig):
                shutil.copytree(orig, os.path.join(tmp, nome))
            elif not nome.endswith(("-journal", "-wal", "-shm")):
                shutil.copy2(orig, os.path.join(tmp, nome))
        if assinatura_rag()[0] != assin_antes:
            raise RuntimeError("o RAG foi alterado durante a cópia (treino rodando) - tento de novo mais tarde")
        _compactar(tmp, destino_tar)
        return assin_antes
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _fazer_backup(tipo: str, cred) -> str:
    """Executa um backup ('rag' ou 'sistema') e devolve a mensagem de sucesso."""
    pasta_raiz, client_id, client_secret, refresh_token = cred
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs(TRABALHO_DIR, exist_ok=True)
    if tipo == "rag":
        nome, prefixo, subpasta, manter = f"rag_chroma_{stamp}.tar.gz", "rag_chroma_", PASTA_RAG, MANTER_RAG
    else:
        nome, prefixo, subpasta, manter = f"sistema_{stamp}.tar.gz", "sistema_", PASTA_SISTEMA, MANTER_SISTEMA
    local = os.path.join(TRABALHO_DIR, nome)
    t0 = time.time()
    try:
        if tipo == "rag":
            assin = _copia_rag(local)
        else:
            assin = assinatura_sistema()
            _compactar(PROJETO_DIR, local, _arquivos_sistema())
        tamanho_mb = os.path.getsize(local) / (1024 * 1024)
        svc = _servico_drive(client_id, client_secret, refresh_token)
        pasta = _subpasta(svc, pasta_raiz, subpasta)
        _enviar(svc, pasta, local, nome)
        apagados = _limpar_antigos(svc, pasta, prefixo, manter)
    finally:
        try:
            os.remove(local)
        except OSError:
            pass
    msg = (f"{nome} ({tamanho_mb:,.0f} MB) enviado para {subpasta} em {(time.time() - t0) / 60:.0f} min"
           f"{f'; {apagados} cópia(s) antiga(s) removida(s)' if apagados else ''} - mantidas as últimas {manter}")
    _salvar_estado(tipo, assinatura=assin, em=datetime.utcnow().isoformat(timespec="seconds"), ok=True, detalhe=msg,
                   ultimo_sucesso=datetime.utcnow().isoformat(timespec="seconds"), tamanho_mb=round(tamanho_mb, 1))
    logger.info(f"[BACKUP SISTEMA] {msg}")
    return msg


def _precisa(tipo: str, forcar: bool) -> tuple:
    """(precisa, motivo de não fazer)."""
    est = ler_estado().get(tipo, {})
    if tipo == "rag":
        if not os.path.isdir(CHROMA_DIR):
            return False, "pasta chroma_data não encontrada"
        assin, parado_ha = assinatura_rag()
        if not forcar:
            if assin == est.get("assinatura"):
                return False, "RAG sem alterações desde o último backup"
            ultimo = est.get("ultimo_sucesso")
            if ultimo and (datetime.utcnow() - datetime.fromisoformat(ultimo)).total_seconds() < MIN_ENTRE_RAG_SEG:
                return False, "último backup do RAG tem menos de 12 h"
        if parado_ha < (60 if forcar else QUIETO_SEG):
            return False, "RAG sendo atualizado agora (treino) - espero ficar parado"
        return True, ""
    if not forcar and assinatura_sistema() == est.get("assinatura"):
        return False, "sistema sem alterações desde o último backup"
    return True, ""


async def rodar(forcar: bool = False, tipos=("sistema", "rag")) -> dict:
    """Faz os backups pendentes. Devolve {tipo: mensagem}."""
    resultado = {}
    cred = await _credenciais_drive()()
    if not cred:
        for tipo in tipos:
            resultado[tipo] = "Google Drive não configurado (Admin > Integrações)"
            _salvar_estado(tipo, em=datetime.utcnow().isoformat(timespec="seconds"), ok=False, detalhe=resultado[tipo])
        return resultado
    if not _pegar_trava():
        return {t: "outro backup já está em andamento" for t in tipos}
    try:
        for tipo in tipos:
            precisa, motivo = await asyncio.to_thread(_precisa, tipo, forcar)
            if not precisa:
                resultado[tipo] = motivo
                continue
            try:
                resultado[tipo] = await asyncio.to_thread(_fazer_backup, tipo, cred)
            except Exception as e:
                resultado[tipo] = f"falhou: {type(e).__name__}: {str(e)[:300]}"
                _salvar_estado(tipo, em=datetime.utcnow().isoformat(timespec="seconds"), ok=False, detalhe=resultado[tipo])
                logger.error(f"[BACKUP SISTEMA] {tipo}: {resultado[tipo]}")
    finally:
        _soltar_trava()
    return resultado


async def start_sistema_backup_loop():
    """Iniciado junto com o backup diário (daily_backup_drive_service.start_daily_drive_backup_loop)."""
    logger.info("[BACKUP SISTEMA] loop do backup do RAG e do sistema no Drive iniciado (confere a cada 30 min)")
    await asyncio.sleep(300)  # deixa o backend terminar de subir
    while True:
        try:
            await rodar()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[BACKUP SISTEMA] erro inesperado: {e}")
        try:
            await asyncio.sleep(INTERVALO_SEG)
        except asyncio.CancelledError:
            break


if __name__ == "__main__":
    sys.path.insert(0, BACKEND_DIR)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for ruidoso in ("httpx", "googleapiclient", "google", "urllib3"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    print(json.dumps(asyncio.run(rodar(forcar="--agora" in sys.argv)), ensure_ascii=False, indent=1))
