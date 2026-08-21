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
from app.api.websockets import router as ws_router

from app.services.inactivity_service import start_inactivity_checker_loop
from app.services.evolution_service import start_profile_picture_syncer_loop
from app.services.business_hours_service import start_business_hours_scheduler_loop

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
    
    # Start inactivity background monitor task (sweeps every 15 seconds for unreplied customer chats)
    inactivity_task = asyncio.create_task(start_inactivity_checker_loop(interval_seconds=15))
    logger.info("Inactivity and unreplied customer sweeper background loop started.")

    # Start WhatsApp profile picture background syncer
    profile_pic_task = asyncio.create_task(start_profile_picture_syncer_loop(interval_seconds=60))
    logger.info("WhatsApp profile picture automatic syncer background loop started.")

    # Start Business Hours 18:00 Shift Closing Scheduler
    business_hours_task = asyncio.create_task(start_business_hours_scheduler_loop(check_interval_seconds=30))
    logger.info("Business hours 18:00 shift closing scheduler loop started.")
    
    yield
    
    # Shutdown actions
    inactivity_task.cancel()
    profile_pic_task.cancel()
    business_hours_task.cancel()
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

# Ensure uploads directory exists and mount static files
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

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
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "message": "OminiChannel WhatsApp Platform API is operational",
        "docs": "/docs",
        "status": "healthy"
    }
