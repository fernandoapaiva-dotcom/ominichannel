import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, ConversationStatus, Tenant, Message
from app.services.gdrive_service import gdrive_service

logger = logging.getLogger("inactivity_service")

class InactivityService:
    async def check_and_expire_idle_conversations(self):
        """
        Queries all active conversations across tenants, checks tenant's inatividade_minutos,
        and marks conversations exceeding threshold as EXPIRADA_POR_INATIVIDADE.
        Generates automatic JSON backup export.
        """
        async with AsyncSessionLocal() as db:
            try:
                # 1. Fetch tenants and their configs
                tenants_stmt = select(Tenant)
                tenants_res = await db.execute(tenants_stmt)
                tenants = tenants_res.scalars().all()
                tenant_config_map = {t.id: t for t in tenants}

                # 2. Fetch active conversations (COM_IA or COM_HUMANO)
                conv_stmt = (
                    select(Conversation)
                    .options(selectinload(Conversation.messages), selectinload(Conversation.contact))
                    .where(Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO]))
                )
                conv_res = await db.execute(conv_stmt)
                conversations = conv_res.scalars().all()

                now = datetime.utcnow()
                expired_count = 0

                for conv in conversations:
                    tenant = tenant_config_map.get(conv.tenant_id)
                    if not tenant:
                        continue
                    
                    config = tenant.config_geral or {}
                    inactivity_minutes = config.get("inatividade_minutos", 30)
                    threshold_time = now - timedelta(minutes=inactivity_minutes)

                    if conv.ultima_interacao_em < threshold_time:
                        conv.status = ConversationStatus.EXPIRADA_POR_INATIVIDADE
                        expired_count += 1
                        
                        # Trigger JSON backup export
                        conv_data = {
                            "conversation_id": conv.id,
                            "tenant_id": conv.tenant_id,
                            "contact_phone": conv.contact.telefone if conv.contact else "",
                            "contact_name": conv.contact.nome if conv.contact else "",
                            "status": conv.status.value,
                            "criado_em": conv.criado_em,
                            "ultima_interacao_em": conv.ultima_interacao_em,
                            "messages": [
                                {
                                    "remetente": m.remetente.value,
                                    "conteudo": m.conteudo,
                                    "tipo": m.tipo.value,
                                    "timestamp": m.timestamp
                                } for m in conv.messages
                            ]
                        }
                        
                        await gdrive_service.sync_conversation_to_drive(
                            tenant_drive_folder_id=tenant.pasta_google_drive_id or "",
                            conversation_id=conv.id,
                            contact_phone=conv.contact.telefone if conv.contact else "desconhecido",
                            conversation_data=conv_data
                        )

                if expired_count > 0:
                    await db.commit()
                    logger.info(f"Auto-expired {expired_count} idle conversations.")

            except Exception as e:
                logger.error(f"Error during inactivity check: {e}")

async def start_inactivity_checker_loop(interval_seconds: int = 120):
    """Periodic background loop running every 2 minutes"""
    service = InactivityService()
    while True:
        await service.check_and_expire_idle_conversations()
        await asyncio.sleep(interval_seconds)
