import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, ConversationStatus, Tenant, Message, MessageSender, MessageType, WhatsAppNumber
from app.services.gdrive_service import gdrive_service
from app.services.gemini_service import gemini_service
from app.services.evolution_service import evolution_service
from app.services.rag_service import rag_service
from app.services.settings_service import settings_service
from app.services.distribution_service import distribution_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("inactivity_service")

class InactivityService:
    async def check_and_expire_idle_conversations(self):
        """
        Tiered Escalated Inactivity Monitor (Fase 6):
        - Uses configurable tenant 'inatividade_minutos' (T) (e.g. 45 min).
        - Tier 1 Warning: When (T - 10) min elapsed -> Friendly check-in warning (10 min remaining).
        - Tier 2 Warning: When (T - 5) min elapsed -> Urgent notice (5 min remaining).
        - Tier 3 Expiration: When T min elapsed -> Marks EXPIRADA_POR_INATIVIDADE, exports backup, frees attendant.
        - If customer sends a message anytime, warnings are reset and timer restarts.
        """
        async with AsyncSessionLocal() as db:
            try:
                # 1. Fetch tenants
                tenants_stmt = select(Tenant)
                tenants_res = await db.execute(tenants_stmt)
                tenants = tenants_res.scalars().all()
                tenant_config_map = {t.id: t for t in tenants}

                # 2. Fetch active conversations
                conv_stmt = (
                    select(Conversation)
                    .options(
                        selectinload(Conversation.messages),
                        selectinload(Conversation.contact),
                        selectinload(Conversation.whatsapp_number)
                    )
                    .where(
                        Conversation.status.in_([
                            ConversationStatus.COM_IA,
                            ConversationStatus.COM_HUMANO,
                            ConversationStatus.AGUARDANDO_ATENDENTE
                        ])
                    )
                )
                conv_res = await db.execute(conv_stmt)
                conversations = conv_res.scalars().all()

                now = datetime.utcnow()
                changes_made = False

                for conv in conversations:
                    tenant = tenant_config_map.get(conv.tenant_id)
                    if not tenant:
                        continue

                    # NEVER expire WhatsApp groups or communities
                    if conv.contact and (conv.contact.telefone.startswith("120363") or "@g.us" in conv.contact.telefone or len(conv.contact.telefone) > 15):
                        continue

                    if not conv.ultima_interacao_em:
                        continue

                    # Total timeout T configured on tenant
                    t_total = float((tenant.config_geral or {}).get("inatividade_minutos", 45)) if isinstance(tenant.config_geral, dict) else 45.0
                    
                    # Calculate warning thresholds relative to T
                    if t_total > 10.0:
                        w1_threshold = t_total - 10.0  # 10 min remaining
                        w2_threshold = t_total - 5.0   # 5 min remaining
                    else:
                        w1_threshold = t_total * 0.5
                        w2_threshold = t_total * 0.8

                    elapsed_minutes = (now - conv.ultima_interacao_em).total_seconds() / 60.0

                    extra = dict(conv.dados_adicionais or {})
                    proto = conv.protocol_number or "S/N"
                    cust_name = conv.contact.nome if (conv.contact and conv.contact.nome) else "Cliente"
                    inst_name = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else None

                    # ----------------------------------------------------
                    # TIER 3: FINAL EXPIRATION (elapsed >= T)
                    # ----------------------------------------------------
                    if elapsed_minutes >= t_total:
                        logger.info(f"[INATIVIDADE] Conversa #{conv.id} atingiu limite total de {t_total} min sem interação. Expirando chamado...")
                        conv.status = ConversationStatus.EXPIRADA_POR_INATIVIDADE
                        extra["expired_by_inactivity_at"] = now.isoformat()
                        conv.dados_adicionais = extra

                        # Closing WhatsApp message
                        closing_msg = (
                            f"🔒 *Atendimento Finalizado por Inatividade*\n\n"
                            f"Olá, {cust_name}! Seu atendimento (Protocolo: {proto}) foi encerrado automaticamente após {int(t_total)} minutos de inatividade.\n\n"
                            f"Caso ainda precise de suporte, basta nos enviar uma nova mensagem a qualquer momento!"
                        )
                        if inst_name and conv.contact:
                            try:
                                await evolution_service.send_text_message(
                                    instance_name=inst_name,
                                    number=conv.contact.telefone,
                                    text=closing_msg
                                )
                            except Exception as err:
                                logger.warning(f"Failed to send inactivity closing message to #{conv.id}: {err}")

                        # System audit message
                        sys_msg = Message(
                            conversation_id=conv.id,
                            remetente="sistema",
                            conteudo=f"🔒 Atendimento finalizado automaticamente por inatividade ({int(t_total)} minutos).",
                            tipo=MessageType.TEXTO,
                            timestamp=now
                        )
                        db.add(sys_msg)

                        # Auto JSON backup
                        conv_data = {
                            "conversation_id": conv.id,
                            "tenant_id": conv.tenant_id,
                            "contact_phone": conv.contact.telefone if conv.contact else "",
                            "contact_name": conv.contact.nome if conv.contact else "",
                            "protocol_number": conv.protocol_number,
                            "status": "expirada_por_inatividade",
                            "criado_em": conv.criado_em,
                            "ultima_interacao_em": conv.ultima_interacao_em,
                            "messages": [
                                {
                                    "remetente": getattr(m.remetente, 'value', str(m.remetente)),
                                    "conteudo": m.conteudo,
                                    "tipo": getattr(m.tipo, 'value', str(m.tipo)),
                                    "timestamp": m.timestamp.isoformat() if m.timestamp else None
                                } for m in (conv.messages or [])
                            ]
                        }
                        await gdrive_service.sync_conversation_to_drive(
                            tenant_drive_folder_id=None,
                            conversation_id=conv.id,
                            contact_phone=conv.contact.telefone if conv.contact else "desconhecido",
                            conversation_data=conv_data
                        )

                        changes_made = True

                        # Broadcast WS update
                        try:
                            await ws_manager.broadcast_to_department(
                                tenant_id=conv.tenant_id,
                                whatsapp_number_id=conv.whatsapp_number_id,
                                message_data={
                                    "type": "NEW_MESSAGE",
                                    "conversation_id": conv.id,
                                    "status_updated": conv.status.value
                                }
                            )
                        except Exception:
                            pass

                        # Re-balance pending queue
                        if conv.whatsapp_number_id:
                            try:
                                await distribution_service.process_pending_queue(db, conv.tenant_id, conv.whatsapp_number_id)
                            except Exception:
                                pass

                        continue

                    # ----------------------------------------------------
                    # TIER 2: WARNING 2 (5 min remaining / elapsed >= w2_threshold)
                    # ----------------------------------------------------
                    if elapsed_minutes >= w2_threshold and not extra.get("inactivity_warning_5m_sent"):
                        rem_mins = max(1, int(round(t_total - elapsed_minutes)))
                        logger.info(f"[INATIVIDADE] Enviando 2º aviso prévio ({rem_mins} min restantes) para conversa #{conv.id}...")
                        
                        warning_text = (
                            f"⚠️ *Aviso de Inatividade*\n\n"
                            f"Olá, {cust_name}! Seu atendimento (Protocolo: {proto}) será finalizado em aproximadamente {rem_mins} minutos por ausência de interação.\n\n"
                            f"Estamos à disposição caso queira dar continuidade!"
                        )
                        if inst_name and conv.contact:
                            try:
                                await evolution_service.send_text_message(
                                    instance_name=inst_name,
                                    number=conv.contact.telefone,
                                    text=warning_text
                                )
                            except Exception as err:
                                logger.warning(f"Failed to send 5m warning message to #{conv.id}: {err}")

                        sys_msg = Message(
                            conversation_id=conv.id,
                            remetente="sistema",
                            conteudo=f"⏳ Segundo aviso prévio de inatividade ({rem_mins} minutos restantes) enviado ao cliente.",
                            tipo=MessageType.TEXTO,
                            timestamp=now
                        )
                        db.add(sys_msg)

                        extra["inactivity_warning_5m_sent"] = True
                        extra["inactivity_warning_5m_at"] = now.isoformat()
                        conv.dados_adicionais = extra
                        changes_made = True
                        continue

                    # ----------------------------------------------------
                    # TIER 1: WARNING 1 (10 min remaining / elapsed >= w1_threshold)
                    # ----------------------------------------------------
                    if elapsed_minutes >= w1_threshold and not extra.get("inactivity_warning_10m_sent"):
                        rem_mins = max(1, int(round(t_total - elapsed_minutes)))
                        logger.info(f"[INATIVIDADE] Enviando 1º aviso prévio ({rem_mins} min restantes) para conversa #{conv.id}...")
                        
                        warning_text = (
                            f"⏳ *Aviso de Atendimento*\n\n"
                            f"Olá, {cust_name}! Notamos que você está sem interagir há algum tempo. Ainda está por aí?\n\n"
                            f"Seu atendimento (Protocolo: {proto}) será encerrado em aproximadamente {rem_mins} minutos caso não haja nova resposta."
                        )
                        if inst_name and conv.contact:
                            try:
                                await evolution_service.send_text_message(
                                    instance_name=inst_name,
                                    number=conv.contact.telefone,
                                    text=warning_text
                                )
                            except Exception as err:
                                logger.warning(f"Failed to send 10m warning message to #{conv.id}: {err}")

                        sys_msg = Message(
                            conversation_id=conv.id,
                            remetente="sistema",
                            conteudo=f"⏳ Primeiro aviso prévio de inatividade ({rem_mins} minutos restantes) enviado ao cliente.",
                            tipo=MessageType.TEXTO,
                            timestamp=now
                        )
                        db.add(sys_msg)

                        extra["inactivity_warning_10m_sent"] = True
                        extra["inactivity_warning_10m_at"] = now.isoformat()
                        conv.dados_adicionais = extra
                        changes_made = True

                if changes_made:
                    await db.commit()

            except Exception as e:
                logger.error(f"Error during tiered inactivity check: {e}")

    async def auto_respond_unreplied_conversations(self):
        """
        Sweeps conversations in COM_IA where the last message was sent by the client
        and has not been replied to for >= 10s.
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

                    sorted_msgs = sorted(conv.messages, key=lambda m: m.timestamp)
                    last_msg = sorted_msgs[-1]

                    last_remetente = getattr(last_msg.remetente, 'value', last_msg.remetente)
                    if last_remetente == "cliente":
                        # Check group permissions
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
                                continue

                        time_waiting_sec = (now - last_msg.timestamp).total_seconds()
                        if time_waiting_sec >= 10.0:
                            logger.info(f"[VARREDURA IA] Conversa {conv.id} ({conv.contact.nome or conv.contact.telefone}) com mensagem sem resposta: '{last_msg.conteudo}'. Gerando resposta IA...")

                            conv.status = ConversationStatus.COM_IA
                            conv.ultima_interacao_em = datetime.utcnow()

                            rag_context = await rag_service.search_context(tenant_id=conv.tenant_id, query=last_msg.conteudo)

                            history = [
                                {"remetente": getattr(m.remetente, 'value', m.remetente), "conteudo": m.conteudo}
                                for m in sorted_msgs[-6:]
                            ]

                            decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, conv.tenant_id)

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

                            ai_msg = Message(
                                conversation_id=conv.id,
                                remetente=MessageSender.IA,
                                conteudo=reply_text,
                                tipo=MessageType.TEXTO,
                                timestamp=datetime.utcnow()
                            )
                            db.add(ai_msg)

                            if conv.whatsapp_number.instancia_evolution_api:
                                formatted_ai_text = f"*🤖 IA Concierge:*\n\n{reply_text}"
                                await evolution_service.send_text_message(
                                    instance_name=conv.whatsapp_number.instancia_evolution_api,
                                    number=conv.contact.telefone,
                                    text=formatted_ai_text
                                )

                            if escalar:
                                conv.status = ConversationStatus.AGUARDANDO_ATENDENTE
                                conv.assigned_user_id = None
                                try:
                                    await distribution_service.process_pending_queue(db, conv.tenant_id, conv.whatsapp_number_id)
                                except Exception:
                                    pass

                            await db.commit()

            except Exception as e:
                logger.error(f"Error during auto_respond_unreplied_conversations: {e}")

inactivity_service = InactivityService()

async def start_inactivity_checker_loop(interval_seconds: int = 15):
    """Continuous background loop for inactivity check and unreplied message auto-response."""
    logger.info("Inactivity background monitor task started.")
    while True:
        try:
            await inactivity_service.check_and_expire_idle_conversations()
            await inactivity_service.auto_respond_unreplied_conversations()
        except Exception as e:
            logger.error(f"Error in inactivity checker background loop: {e}")
        await asyncio.sleep(interval_seconds)
