import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
from app.core.config import settings

logger = logging.getLogger("database")

is_sqlite = "sqlite" in settings.DATABASE_URL.lower()

engine_kwargs = {
    "echo": False,
    "future": True,
    "pool_pre_ping": True,
}

if is_sqlite:
    engine_kwargs["connect_args"] = {
        "timeout": 60.0,
        "check_same_thread": False,
    }
else:
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 30
    engine_kwargs["pool_recycle"] = 300

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=60000;")
            cursor.execute("PRAGMA wal_autocheckpoint=1000;")
            cursor.execute("PRAGMA temp_store=MEMORY;")
            cursor.close()
        except Exception as e:
            logger.debug(f"SQLite PRAGMA error: {e}")

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

from sqlalchemy import text

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        migrations = [
            "ALTER TABLE contacts ADD COLUMN foto_perfil_url VARCHAR(500);",
            "ALTER TABLE authorized_technicians ADD COLUMN cargo VARCHAR(100);",
            "ALTER TABLE authorized_technicians ADD COLUMN departamento VARCHAR(100);",
            "ALTER TABLE calendar_events ADD COLUMN event_type VARCHAR(50) DEFAULT 'geral';",
            "ALTER TABLE calendar_events ADD COLUMN employee_id INTEGER;",
            "ALTER TABLE calendar_events ADD COLUMN employee_name VARCHAR(150);",
            "ALTER TABLE calendar_events ADD COLUMN employee_phone VARCHAR(50);",
            "ALTER TABLE calendar_events ADD COLUMN notify_whatsapp BOOLEAN DEFAULT 1;",
            "ALTER TABLE calendar_events ADD COLUMN notified_creation BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN notified_day_of BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN notified_hours_before BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN custom_reminder_hours INTEGER DEFAULT 2;",
            "ALTER TABLE calendar_events ADD COLUMN confirmed_by_employee BOOLEAN DEFAULT 0;",
            "ALTER TABLE calendar_events ADD COLUMN confirmed_at DATETIME;",
            "ALTER TABLE calendar_events ADD COLUMN confirmation_token VARCHAR(100);",
            "ALTER TABLE calendar_events ADD COLUMN whatsapp_number_id INTEGER;",
            "ALTER TABLE calendar_events ADD COLUMN whatsapp_instance VARCHAR(100);",
            "ALTER TABLE calendar_events ADD COLUMN contact_name VARCHAR(200);",
            "ALTER TABLE calendar_events ADD COLUMN contact_phone VARCHAR(50);",
        ]
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass
