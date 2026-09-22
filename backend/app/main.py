import asyncio
import logging
from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.v1.auth import router as auth_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.whatsapp_numbers import router as whatsapp_numbers_router
from app.api.v1.users import router as users_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.contacts import router as contacts_router
from app.api.v1.segments import router as segments_router
from app.api.v1.rag import router as rag_router
from app.api.v1.settings import router as settings_router
from app.api.v1.whatsapp_groups import router as whatsapp_groups_router
from app.api.v1.pix_keys import router as pix_keys_router
from app.api.v1.technicians import router as technicians_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.os_handler_ingest import router as os_handler_ingest_router
from app.api.v1.os_board import router as os_board_router
from app.api.websockets import router as ws_router

from app.services.inactivity_service import start_inactivity_checker_loop
from app.services.evolution_service import start_profile_picture_syncer_loop
from app.services.business_hours_service import start_business_hours_scheduler_loop
from app.services.calendar_reminder_service import start_calendar_reminder_loop
from app.services.whatsapp_watchdog_service import start_whatsapp_watchdog_loop
from app.services.whatsapp_reconciliation_service import start_whatsapp_reconciliation_loop
from app.services.backup_service import start_backup_scheduler_loop
from app.services.daily_backup_drive_service import start_daily_drive_backup_loop
from app.services.os_board_followup_service import start_os_board_followup_loop

import mimetypes

mimetypes.add_type('audio/ogg', '.ogg')
mimetypes.add_type('audio/opus', '.opus')
mimetypes.add_type('audio/mpeg', '.mp3')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Initializing Database...")
    await init_db()
    
    # Start database ACID persistence & snapshot scheduler loop (every 6h + startup)
    backup_task = asyncio.create_task(start_backup_scheduler_loop(interval_hours=6))
    logger.info("💾 Database ACID persistence snapshot background loop started.")

    # Start daily full-system backup upload to Google Drive (once per tenant that has
    # completed the OAuth connection in Settings > Integrações)
    drive_backup_task = asyncio.create_task(start_daily_drive_backup_loop(interval_hours=24))
    logger.info("☁️ Google Drive daily system backup background loop started (24h interval).")

    # Start inactivity background monitor task (sweeps every 60 seconds — reduced from 15s to prevent WhatsApp rate-limit/ban)
    inactivity_task = asyncio.create_task(start_inactivity_checker_loop(interval_seconds=60))
    logger.info("Inactivity and unreplied customer sweeper background loop started (60s interval).")


    # Start WhatsApp profile picture background syncer (gentle 30m interval)
    profile_pic_task = asyncio.create_task(start_profile_picture_syncer_loop(interval_seconds=1800))
    logger.info("WhatsApp profile picture automatic syncer background loop started.")

    # Business Hours 18:00 Shift Closing Scheduler - PAUSADO a pedido do usuário em 22/09/2026: a
    # mensagem de "encerramento de expediente" às 18h não faz sentido enquanto a abertura de
    # protocolo no início do chat não estiver funcionando (ela finaliza/anuncia um protocolo que
    # muitas vezes nem foi aberto certo). Retomar quando a abertura de protocolo for corrigida.
    BUSINESS_HOURS_CLOSING_ENABLED = False
    if BUSINESS_HOURS_CLOSING_ENABLED:
        business_hours_task = asyncio.create_task(start_business_hours_scheduler_loop(check_interval_seconds=30))
        logger.info("Business hours 18:00 shift closing scheduler loop started.")
    else:
        business_hours_task = None
        logger.info("Business hours 18:00 shift closing scheduler PAUSADO (aguardando correção da abertura de protocolo).")

    # Start Calendar WhatsApp reminders loop
    calendar_reminder_task = asyncio.create_task(start_calendar_reminder_loop(interval_seconds=60))
    logger.info("Calendar WhatsApp reminder background scheduler loop started.")

    # Start WhatsApp Instance Connection Auto-Heal Watchdog
    watchdog_task = asyncio.create_task(start_whatsapp_watchdog_loop(interval_seconds=30))
    logger.info("🛡️ WhatsApp Instance Auto-Heal Watchdog background loop started (30s interval).")

    # Quadro de Técnicos: cobrança automática de aprovação de orçamento (2 em 2 dias) e retirada do
    # equipamento (2 em 2 dias, com contagem regressiva de 90 dias até o descarte). Roda só entre 8h e
    # 18h de Brasília e distribui a fila pendente ao longo do horário que resta até as 18h (no máximo
    # 8 mensagens a cada 10 min) - ver app/services/os_board_followup_service.py.
    # Ligado em 22/09/2026 com confirmação explícita do usuário, já com o ritmo de 8h-18h acima.
    OS_BOARD_FOLLOWUP_ENABLED = True
    if OS_BOARD_FOLLOWUP_ENABLED:
        os_board_followup_task = asyncio.create_task(start_os_board_followup_loop())
        logger.info("📋 Quadro de Técnicos: cobrança automática de aprovação/retirada iniciada (ritmo de 8h-18h).")
    else:
        os_board_followup_task = None
        logger.info("📋 Quadro de Técnicos: cobrança automática PAUSADA (aguardando confirmação do usuário).")

    # Continuous WhatsApp polling disabled to prevent WhatsApp Meta anti-spam bans.
    # Reconciliation is triggered passively via connection webhooks or manual admin action.
    reconcile_task = None
    logger.info("🛡️ WhatsApp Continuous Polling disabled for safety (anti-ban protection).")
    
    yield
    
    # Shutdown actions
    backup_task.cancel()
    drive_backup_task.cancel()
    inactivity_task.cancel()
    profile_pic_task.cancel()
    if business_hours_task:
        business_hours_task.cancel()
    calendar_reminder_task.cancel()
    watchdog_task.cancel()
    if os_board_followup_task:
        os_board_followup_task.cancel()
    if reconcile_task:
        reconcile_task.cancel()
    logger.info("Application shutdown completed.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# CORS middleware for Web, Mobile, PWA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
from fastapi import Request

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    response.headers["X-Process-Time-Ms"] = str(round(process_time, 2))
    if process_time > 100:
        logger.info(f"⚡ [TIMING] {request.method} {request.url.path} processed in {process_time:.2f}ms")
    return response

# Ensure uploads directory exists and mount static files using absolute path
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Include Routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(tenants_router, prefix=settings.API_V1_STR)
app.include_router(whatsapp_numbers_router, prefix=settings.API_V1_STR)
app.include_router(users_router, prefix=settings.API_V1_STR)
app.include_router(conversations_router, prefix=settings.API_V1_STR)
app.include_router(contacts_router, prefix=settings.API_V1_STR)
app.include_router(segments_router, prefix=settings.API_V1_STR)
app.include_router(webhooks_router, prefix=settings.API_V1_STR)
app.include_router(rag_router, prefix=settings.API_V1_STR)
app.include_router(settings_router, prefix=settings.API_V1_STR)
app.include_router(whatsapp_groups_router, prefix=settings.API_V1_STR)
app.include_router(pix_keys_router, prefix=settings.API_V1_STR)
app.include_router(technicians_router, prefix=settings.API_V1_STR)
app.include_router(calendar_router, prefix=settings.API_V1_STR)
app.include_router(os_handler_ingest_router, prefix=settings.API_V1_STR)
app.include_router(os_board_router, prefix=settings.API_V1_STR)
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "message": "OminiChannel WhatsApp Platform API is operational",
        "docs": "/docs",
        "status": "healthy"
    }
