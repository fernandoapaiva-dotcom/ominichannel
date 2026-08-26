import os
import shutil
import asyncio
import logging
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger("backup_service")

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "backups_db")

def create_db_snapshot() -> bool:
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        
        if not os.path.exists(db_path):
            return False

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(BACKUP_DIR, f"omini_channel_snapshot_{timestamp}.db")
        
        shutil.copy2(db_path, backup_file)
        
        wal_path = f"{db_path}-wal"
        if os.path.exists(wal_path):
            shutil.copy2(wal_path, f"{backup_file}-wal")

        all_snapshots = sorted(
            [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.startswith("omini_channel_snapshot_") and f.endswith(".db")],
            key=os.path.getmtime
        )
        if len(all_snapshots) > 10:
            for old_f in all_snapshots[:-10]:
                try:
                    os.remove(old_f)
                    if os.path.exists(f"{old_f}-wal"):
                        os.remove(f"{old_f}-wal")
                except Exception:
                    pass

        logger.info(f"Database ACID persistence snapshot created successfully: {os.path.basename(backup_file)}")
        return True
    except Exception as e:
        logger.error(f"Error creating database backup snapshot: {e}")
        return False

async def start_backup_scheduler_loop(interval_hours: int = 6):
    logger.info("Database ACID persistence and backup scheduler loop started.")
    create_db_snapshot()
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            create_db_snapshot()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Unexpected error in backup scheduler: {e}")
            await asyncio.sleep(60)
