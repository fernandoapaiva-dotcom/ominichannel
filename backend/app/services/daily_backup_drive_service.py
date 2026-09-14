import asyncio
import logging
import os
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import AsyncSessionLocal
from app.models.models import Tenant
from app.services.backup_service import create_db_snapshot
from app.services.settings_service import settings_service
from app.services.gdrive_service import gdrive_service

logger = logging.getLogger("daily_backup_drive")


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


async def start_daily_drive_backup_loop(interval_hours: int = 24):
    logger.info("Google Drive daily system backup loop started.")
    # Give the app a minute to finish booting before the first attempt.
    await asyncio.sleep(60)
    while True:
        try:
            await run_daily_drive_backup()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Unexpected error in daily Drive backup loop: {e}")
        try:
            await asyncio.sleep(interval_hours * 3600)
        except asyncio.CancelledError:
            break
