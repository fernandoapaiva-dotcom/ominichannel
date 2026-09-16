import asyncio
import glob
import json
import logging
import mimetypes
import os
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import AsyncSessionLocal
from app.models.models import Tenant
from app.services.backup_service import create_db_snapshot
from app.services.settings_service import settings_service
from app.services.gdrive_service import gdrive_service

try:
    from zoneinfo import ZoneInfo
    BACKUP_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    BACKUP_TZ = None

logger = logging.getLogger("daily_backup_drive")

UPLOADS_DIR = os.path.join(os.getcwd(), "uploads")
MEDIA_MANIFEST_DIR = os.path.join(os.getcwd(), "backups_db")
DB_SNAPSHOT_DIR = os.path.join(os.getcwd(), "backups_db")
JSON_EXPORT_DIR = os.path.join(os.getcwd(), "backups_json")

BACKUP_HOUR_LOCAL = 20  # 20h no horário de Brasília, como pedido
KEEP_LOCAL_DB_SNAPSHOTS = 3  # margem de seguranca mesmo se o upload de um dia falhar
JSON_EXPORT_RETENTION_DAYS = 30


def _media_manifest_path(tenant_id: int) -> str:
    return os.path.join(MEDIA_MANIFEST_DIR, f"gdrive_media_manifest_tenant_{tenant_id}.json")


def _load_media_manifest(tenant_id: int) -> set:
    path = _media_manifest_path(tenant_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def _save_media_manifest(tenant_id: int, uploaded: set):
    os.makedirs(MEDIA_MANIFEST_DIR, exist_ok=True)
    with open(_media_manifest_path(tenant_id), "w", encoding="utf-8") as f:
        json.dump(sorted(uploaded), f)


async def _record_backup_result(tenant_id: int, success: bool, detail: str):
    """Persists the outcome of the last daily Drive backup attempt on the tenant's
    config_geral, so the admin panel can show real status instead of just a one-time
    'connected' message that says nothing about whether backups are actually happening."""
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                return
            cfg = dict(tenant.config_geral or {})
            cfg["last_gdrive_backup_at"] = datetime.utcnow().isoformat()
            cfg["last_gdrive_backup_success"] = success
            cfg["last_gdrive_backup_detail"] = detail[:500]
            tenant.config_geral = cfg
            flag_modified(tenant, "config_geral")
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to record backup result for tenant {tenant_id}: {e}")


async def _record_media_backup_result(tenant_id: int, success: bool, detail: str, total_files: int):
    """Same pattern as _record_backup_result, but for the media (photos/videos/audio/PDF)
    backup, tracked separately from the .db snapshot status."""
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = res.scalar_one_or_none()
            if not tenant:
                return
            cfg = dict(tenant.config_geral or {})
            cfg["last_gdrive_media_backup_at"] = datetime.utcnow().isoformat()
            cfg["last_gdrive_media_backup_success"] = success
            cfg["last_gdrive_media_backup_detail"] = detail[:500]
            cfg["gdrive_media_files_backed_up"] = total_files
            tenant.config_geral = cfg
            flag_modified(tenant, "config_geral")
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to record media backup result for tenant {tenant_id}: {e}")


async def run_media_backup_for_tenant(tenant_id: int) -> dict:
    """
    Uploads every media file (photos, videos, audio, PDFs) under uploads/ that hasn't been
    sent to Drive yet, into a 'Midias_WhatsApp' subfolder of the tenant's configured Drive
    folder. Tracks already-uploaded filenames in a local manifest so daily runs only send
    what's new, instead of re-uploading everything every time.
    """
    async with AsyncSessionLocal() as db:
        cfg = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

    folder_id = cfg.get("gdrive_folder_id")
    refresh_token = cfg.get("gdrive_refresh_token")
    client_id = cfg.get("google_client_id")
    client_secret = cfg.get("google_client_secret")

    if not (folder_id and refresh_token and client_id and client_secret):
        message = "Google Drive não está totalmente configurado para o backup de mídias."
        await _record_media_backup_result(tenant_id, False, message, len(_load_media_manifest(tenant_id)))
        return {"success": False, "message": message}

    if not os.path.isdir(UPLOADS_DIR):
        message = "Pasta uploads/ não encontrada no servidor."
        await _record_media_backup_result(tenant_id, False, message, 0)
        return {"success": False, "message": message}

    already_uploaded = _load_media_manifest(tenant_id)
    all_files = [f for f in os.listdir(UPLOADS_DIR) if os.path.isfile(os.path.join(UPLOADS_DIR, f))]
    pending = [f for f in all_files if f not in already_uploaded]

    if not pending:
        message = f"Nenhum arquivo de mídia novo. {len(already_uploaded)} já salvos anteriormente no Drive."
        logger.info(f"[MEDIA BACKUP] Tenant {tenant_id}: {message}")
        await _record_media_backup_result(tenant_id, True, message, len(already_uploaded))
        return {"success": True, "message": message}

    try:
        media_folder_id = await asyncio.to_thread(
            gdrive_service.get_or_create_media_folder,
            parent_folder_id=folder_id,
            client_id=client_id,
            refresh_token=refresh_token,
            client_secret=client_secret,
        )
    except Exception as e:
        message = f"Erro ao preparar a pasta de mídias no Drive: {e}"
        logger.error(f"[MEDIA BACKUP] Tenant {tenant_id}: {message}")
        await _record_media_backup_result(tenant_id, False, message, len(already_uploaded))
        return {"success": False, "message": message}

    uploaded_now = 0
    failed_now = 0
    logger.info(f"[MEDIA BACKUP] Tenant {tenant_id}: enviando {len(pending)} arquivo(s) novo(s) ao Drive...")

    for fname in pending:
        fpath = os.path.join(UPLOADS_DIR, fname)
        try:
            await asyncio.to_thread(
                gdrive_service.upload_file_to_drive,
                folder_id=media_folder_id,
                filepath=fpath,
                filename=fname,
                client_id=client_id,
                refresh_token=refresh_token,
                client_secret=client_secret,
                mimetype=mimetypes.guess_type(fname)[0] or "application/octet-stream",
            )
            already_uploaded.add(fname)
            uploaded_now += 1
            if uploaded_now % 25 == 0:
                _save_media_manifest(tenant_id, already_uploaded)
                logger.info(f"[MEDIA BACKUP] Tenant {tenant_id}: {uploaded_now}/{len(pending)} enviados...")
        except Exception as e:
            failed_now += 1
            logger.warning(f"[MEDIA BACKUP] Tenant {tenant_id}: falha ao enviar '{fname}': {e}")

    _save_media_manifest(tenant_id, already_uploaded)

    message = f"{uploaded_now} arquivo(s) de mídia enviados ao Drive"
    if failed_now:
        message += f", {failed_now} falharam"
    message += f". Total acumulado no Drive: {len(already_uploaded)}."

    success = failed_now == 0
    logger.info(f"[MEDIA BACKUP] Tenant {tenant_id}: {message}")
    await _record_media_backup_result(tenant_id, success, message, len(already_uploaded))
    return {"success": success, "message": message}


async def run_backup_for_tenant(tenant_id: int, snapshot_path: str) -> dict:
    """
    Uploads the given local snapshot file to a single tenant's Google Drive folder and
    records the outcome. Returns {"success": bool, "message": str}. If the tenant never
    finished the OAuth connection, this is reported back as a (non-exceptional) failure
    so a manual 'run backup now' call can tell the admin exactly what's missing.
    """
    async with AsyncSessionLocal() as db:
        cfg = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

    folder_id = cfg.get("gdrive_folder_id")
    refresh_token = cfg.get("gdrive_refresh_token")
    client_id = cfg.get("google_client_id")
    client_secret = cfg.get("google_client_secret")

    if not (folder_id and refresh_token and client_id and client_secret):
        missing = [
            label for label, val in [
                ("pasta do Drive", folder_id),
                ("conexão OAuth (conecte a conta Google)", refresh_token),
                ("Client ID", client_id),
                ("Client Secret", client_secret),
            ] if not val
        ]
        message = "Google Drive não está totalmente configurado. Faltando: " + ", ".join(missing) + "."
        await _record_backup_result(tenant_id, False, message)
        return {"success": False, "message": message}

    try:
        await asyncio.to_thread(
            gdrive_service.upload_file_to_drive,
            folder_id=folder_id,
            filepath=snapshot_path,
            filename=os.path.basename(snapshot_path),
            client_id=client_id,
            refresh_token=refresh_token,
            client_secret=client_secret,
            mimetype="application/x-sqlite3",
        )
        message = "Backup enviado com sucesso para o Google Drive."
        logger.info(f"[DAILY DRIVE BACKUP] Tenant {tenant_id}: {message}")
        await _record_backup_result(tenant_id, True, message)
        return {"success": True, "message": message}
    except Exception as e:
        message = str(e)
        logger.error(f"[DAILY DRIVE BACKUP] Tenant {tenant_id} falhou: {message}")
        await _record_backup_result(tenant_id, False, message)
        return {"success": False, "message": message}


def _cleanup_after_backup() -> dict:
    """
    Roda logo depois do backup diário, liberando espaço local de arquivos que agora tem
    copia segura no Drive - NUNCA mexe em uploads/ (é de lá que o proprio chat carrega
    fotos/videos na tela; o Drive e so uma copia de seguranca, nao substitui o
    armazenamento ao vivo) nem no banco de dados em uso. So remove:
      - snapshots locais antigos do banco em backups_db/, alem dos KEEP_LOCAL_DB_SNAPSHOTS
        mais recentes (fica sempre uma margem de seguranca local mesmo que o envio de um
        dia especifico falhe silenciosamente)
      - exports JSON por conversa em backups_json/ com mais de JSON_EXPORT_RETENTION_DAYS
    """
    freed_bytes = 0
    removed_count = 0

    try:
        snaps = sorted(
            glob.glob(os.path.join(DB_SNAPSHOT_DIR, "omini_channel_snapshot_*.db")),
            key=os.path.getmtime,
            reverse=True,
        )
        for old_snap in snaps[KEEP_LOCAL_DB_SNAPSHOTS:]:
            for path in (old_snap, old_snap + "-wal", old_snap + "-shm"):
                if os.path.exists(path):
                    freed_bytes += os.path.getsize(path)
                    os.remove(path)
                    removed_count += 1
    except Exception as e:
        logger.warning(f"[LIMPEZA PÓS-BACKUP] Erro limpando snapshots antigos: {e}")

    try:
        if os.path.isdir(JSON_EXPORT_DIR):
            cutoff_ts = (datetime.utcnow() - timedelta(days=JSON_EXPORT_RETENTION_DAYS)).timestamp()
            for path in glob.glob(os.path.join(JSON_EXPORT_DIR, "*.json")):
                if os.path.getmtime(path) < cutoff_ts:
                    freed_bytes += os.path.getsize(path)
                    os.remove(path)
                    removed_count += 1
    except Exception as e:
        logger.warning(f"[LIMPEZA PÓS-BACKUP] Erro limpando exports antigos: {e}")

    result = {"removed": removed_count, "freed_mb": round(freed_bytes / 1024 / 1024, 1)}
    if removed_count:
        logger.info(f"[LIMPEZA PÓS-BACKUP] {removed_count} arquivo(s) removidos, {result['freed_mb']} MB liberados.")
    return result


def _seconds_until_next_run() -> float:
    now = datetime.now(BACKUP_TZ) if BACKUP_TZ else datetime.utcnow()
    target = now.replace(hour=BACKUP_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily_drive_backup():
    """
    Creates one fresh full-database snapshot and uploads it to Google Drive for every
    tenant that has completed the OAuth connection (folder + refresh token + client
    credentials). Skips tenants that never finished configuring Drive, without treating
    that as an error for the ones that did.
    """
    snapshot_path = create_db_snapshot()
    if not snapshot_path:
        logger.error("[DAILY DRIVE BACKUP] Could not create a local database snapshot; skipping Drive upload for all tenants.")
        return

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()

    for tenant in tenants:
        await run_backup_for_tenant(tenant.id, snapshot_path)
        await run_media_backup_for_tenant(tenant.id)


async def start_daily_drive_backup_loop(interval_hours: int = 24):
    """
    Roda o backup (banco + midias) todo dia as BACKUP_HOUR_LOCAL (horario de Brasilia),
    em vez de 24h a partir do boot do processo - do jeito anterior, cada `pm2 restart`
    (que acontece a cada deploy) reiniciava a contagem, entao o horario real do backup
    ficava andando sem controle. Logo depois de cada backup, roda a limpeza dos arquivos
    locais redundantes (ver _cleanup_after_backup).
    `interval_hours` fica aceito por compatibilidade com a chamada em main.py, mas nao e
    mais usado - o horario agora e sempre o fixo.
    """
    logger.info(f"Google Drive daily system backup loop started - agendado para {BACKUP_HOUR_LOCAL:02d}:00 (America/Sao_Paulo).")
    while True:
        wait_s = _seconds_until_next_run()
        logger.info(f"[DAILY DRIVE BACKUP] Próxima execução em {wait_s / 3600:.1f}h.")
        try:
            await asyncio.sleep(wait_s)
        except asyncio.CancelledError:
            break
        try:
            await run_daily_drive_backup()
            _cleanup_after_backup()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Unexpected error in daily Drive backup loop: {e}")
            # Evita loop apertado se algo falhar logo no inicio do dia
            try:
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
