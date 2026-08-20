import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, ConversationStatus, Tenant, Message, MessageSender, WhatsAppNumber
from app.services.gdrive_service import gdrive_service
from app.services.gemini_service import gemini_service
from app.services.evolution_service import evolution_service
from app.services.rag_service import rag_service
from app.services.settings_service import settings_service
from app.api.v1.webhooks import ws_manager

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
                    
                    # NEVER expire WhatsApp groups or communities
                    if conv.contact and (conv.contact.telefone.startswith("120363") or "@g.us" in conv.contact.telefone or len(conv.contact.telefone) > 15):
                        continue

                    threshold_minutes = (tenant.config_geral or {}).get("inatividade_minutos", 30) if isinstance(tenant.config_geral, dict) else 30
                    threshold_time = now - timedelta(minutes=threshold_minutes)

                    if conv.ultima_interacao_em and conv.ultima_interacao_em < threshold_time:
                        conv.status = ConversationStatus.EXPIRADA_POR_INATIVIDADE
                        expired_count += 1
                        
                        # Trigger JSON backup export
                        conv_data = {
                            "conversation_id": conv.id,
                            "tenant_id": conv.tenant_id,
                            "contact_phone": conv.contact.telefone if conv.contact else "",
                            "contact_name": conv.contact.nome if conv.contact else "",
                            "status": getattr(conv.status, 'value', conv.status),
                            "criado_em": conv.criado_em,
                            "ultima_interacao_em": conv.ultima_interacao_em,
                            "messages": [
                                {
                                    "remetente": getattr(m.remetente, 'value', m.remetente),
                                    "conteudo": m.conteudo,
                                    "tipo": getattr(m.tipo, 'value', m.tipo),
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

    async def auto_respond_unreplied_conversations(self):
        """
        Sweeps all active conversations across tenants.
        If the last message in a conversation was sent by the CLIENT and has not been replied to,
        and no human or AI responded recently (>= 10s), automatically reactivates COM_IA,
        generates the AI Concierge response, sends it via WhatsApp, and notifies WebSockets.
        """
        async with AsyncSessionLocal() as db:
            try:
                conv_stmt = (
                    select(Conversation)
                    .options(
                        selectinload(Conversation.messages),
                        selectinload(Conversation.contact),
                        selectinload(Conversation.whatsapp_number)
                    )
                    .where(Conversation.status == ConversationStatus.COM_IA)
                )
                conv_res = await db.execute(conv_stmt)
                conversations = conv_res.scalars().all()

                now = datetime.utcnow()

                for conv in conversations:
                    if not conv.messages or not conv.contact or not conv.whatsapp_number:
                        continue

                    # Sort messages by timestamp ascending
                    sorted_msgs = sorted(conv.messages, key=lambda m: m.timestamp)
                    last_msg = sorted_msgs[-1]

                    last_remetente = getattr(last_msg.remetente, 'value', last_msg.remetente)
                    if last_remetente == "cliente":
                        # Check if conversation belongs to a WhatsApp group and whether AI is allowed
                        is_group_conv = (
                            "@g.us" in str(conv.contact.telefone).lower() or
                            "@temp" in str(conv.contact.telefone).lower() or
                            "120363" in str(conv.contact.telefone)
                        )

                        if is_group_conv:
                            from app.models.models import WhatsAppGroup
                            raw_jid = conv.contact.telefone.split("@")[0]
                            g_stmt = select(WhatsAppGroup).where(
                                WhatsAppGroup.tenant_id == conv.tenant_id,
                                WhatsAppGroup.group_jid.like(f"%{raw_jid}%")
                            )
                            g_res = await db.execute(g_stmt)
                            group_obj = g_res.scalar_one_or_none()

                            if not group_obj or not group_obj.ia_ativa:
                                # Group AI interaction is disabled (ia_ativa = False)! Skip auto-response!
                                logger.info(f"[VARREDURA IA] Ignorando resposta automática no grupo '{conv.contact.telefone}' pois a IA está desativada para este grupo.")
                                continue

                        # Check if customer has been waiting for at least 10 seconds without reply
                        time_waiting_sec = (now - last_msg.timestamp).total_seconds()
                        if time_waiting_sec >= 10.0:
                            logger.info(f"[VARREDURA IA] Conversa {conv.id} ({conv.contact.nome or conv.contact.telefone}) com mensagem sem resposta: '{last_msg.conteudo}'. Gerando resposta IA...")

                            # Reactivate AI
                            conv.status = ConversationStatus.COM_IA
                            conv.ultima_interacao_em = datetime.utcnow()

                            # Fetch RAG Context
                            rag_context = await rag_service.search_context(tenant_id=conv.tenant_id, query=last_msg.conteudo)

                            history = [
                                {"remetente": getattr(m.remetente, 'value', m.remetente), "conteudo": m.conteudo}
                                for m in sorted_msgs[-6:]
                            ]

                            decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, conv.tenant_id)

                            # Generate AI response
                            ai_output = await gemini_service.generate_concierge_response(
                                customer_name=conv.contact.nome or "Cliente",
                                department_name=conv.whatsapp_number.nome_departamento,
                                user_message=last_msg.conteudo,
                                conversation_history=history,
                                rag_context=rag_context,
                                tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                                tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
                            )

                            reply_text = ai_output.get("resposta", "Olá! Como posso te ajudar hoje?")
                            escalar = ai_output.get("escalar_humano", False)

                            if escalar:
                                conv.status = ConversationStatus.COM_HUMANO

                            # Create AI Message entry in DB
                            ai_msg = Message(
                                conversation_id=conv.id,
                                remetente=MessageSender.IA,
                                conteudo=reply_text,
                                tipo="texto",
                                timestamp=datetime.utcnow()
                            )
                            db.add(ai_msg)
                            await db.commit()

                            # Send via WhatsApp (Evolution API)
                            instance_name = conv.whatsapp_number.instancia_evolution_api
                            target_phone = conv.contact.telefone

                            if instance_name and target_phone:
                                try:
                                    await evolution_service.send_text_message(
                                        instance_name=instance_name,
                                        number=target_phone,
                                        text=f"🤖 *IA Concierge:*\n\n{reply_text}"
                                    )
                                except Exception as send_err:
                                    logger.error(f"Error sending sweep AI message to WhatsApp: {send_err}")

                            # Broadcast via WebSocket to update frontend UI
                            await ws_manager.broadcast_to_department(
                                tenant_id=conv.tenant_id,
                                whatsapp_number_id=conv.whatsapp_number_id,
                                message_data={
                                    "type": "NEW_MESSAGE",
                                    "conversation_id": conv.id,
                                    "remetente": MessageSender.IA.value,
                                    "conteudo": reply_text,
                                    "timestamp": ai_msg.timestamp.isoformat() + "Z",
                                    "contact_name": conv.contact.nome,
                                    "contact_phone": conv.contact.telefone,
                                    "department": conv.whatsapp_number.nome_departamento
                                }
                            )
                            await ws_manager.broadcast_to_department(
                                tenant_id=conv.tenant_id,
                                whatsapp_number_id=conv.whatsapp_number_id,
                                message_data={
                                    "type": "STATUS_CHANGE",
                                    "conversation_id": conv.id,
                                    "status": getattr(conv.status, 'value', conv.status)
                                }
                            )

            except Exception as e:
                logger.error(f"Error in auto_respond_unreplied_conversations sweep: {e}")

async def start_inactivity_checker_loop(interval_seconds: int = 15):
    """Periodic background loop running every 15 seconds to sweep unreplied messages & handle inactivity"""
    service = InactivityService()
    while True:
        await service.check_and_expire_idle_conversations()
        await service.auto_respond_unreplied_conversations()
        await asyncio.sleep(interval_seconds)


