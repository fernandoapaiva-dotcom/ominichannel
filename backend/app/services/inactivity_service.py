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

from zoneinfo import ZoneInfo
from app.services.business_hours_service import BRASILIA_TZ

TIMEOUT_INATIVIDADE = timedelta(hours=4)
AVISO_1 = timedelta(minutes=30)   # 30 minutos antes do fechamento (210 min úteis)
AVISO_2 = timedelta(minutes=10)   # 10 minutos antes do fechamento (230 min úteis)


def esta_aberta(momento: datetime) -> bool:
    """Verifica se o momento está dentro do horário de funcionamento comercial (08:00 às 18:00 seg-sex em Brasília)."""
    if momento.tzinfo is None:
        from datetime import timezone
        local_dt = momento.replace(tzinfo=timezone.utc).astimezone(BRASILIA_TZ)
    else:
        local_dt = momento.astimezone(BRASILIA_TZ)

    # Sábado (5) e Domingo (6) fechado
    if local_dt.weekday() >= 5:
        return False

    hora = local_dt.time()
    from datetime import time
    return time(8, 0, 0) <= hora < time(18, 0, 0)


def calcula_inatividade_util(ultima_mensagem_em: datetime, agora: datetime) -> timedelta:
    """
    Soma somente os minutos que caem dentro do horário de funcionamento comercial da loja.
    """
    if not ultima_mensagem_em or ultima_mensagem_em >= agora:
        return timedelta(0)

    total = timedelta()
    cursor = ultima_mensagem_em
    passo = timedelta(minutes=1)

    while cursor < agora:
        proximo = min(cursor + passo, agora)
        if esta_aberta(cursor):
            total += (proximo - cursor)
        cursor = proximo

    return total


class InactivityService:
    async def check_and_expire_idle_conversations(self):
        """
        Inactivity Monitor Ciente do Horário de Funcionamento (Tarefa 3):
        - Timeout total: 4 horas úteis (240 min) dentro do expediente (08:00 - 18:00 seg-sex).
        - Aviso 1: 30 minutos restantes (210 min úteis decorridos).
        - Aviso 2: 10 minutos restantes (230 min úteis decorridos).
        - Encerramento: 4 horas úteis (240 min úteis decorridos).
        - Mensagens fora do expediente não contam inatividade até a reabertura da loja.
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

                    # CRITICAL: Inactivity warnings and closing messages MUST ONLY EVER be sent to live active protocols!
                    if not conv.protocol_number or conv.protocol_number in ["S/N", "None", "", None]:
                        continue

                    extra = dict(conv.dados_adicionais or {})
                    if extra.get("is_migrated") or extra.get("migrated_from_whatsapp"):
                        continue

                    if not conv.ultima_interacao_em:
                        continue

                    # Calcula inatividade útil (somente minutos dentro do expediente)
                    inatividade_util = calcula_inatividade_util(conv.ultima_interacao_em, now)
                    minutos_uteis = inatividade_util.total_seconds() / 60.0

                    proto = conv.protocol_number or "S/N"
                    cust_name = conv.contact.nome if (conv.contact and conv.contact.nome) else "Cliente"
                    inst_name = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else None

                    # ----------------------------------------------------
                    # TIER 3: FINAL EXPIRATION (inatividade_util >= 4 horas = 240 min)
                    # ----------------------------------------------------
                    if inatividade_util >= TIMEOUT_INATIVIDADE:
                        logger.info(f"[INATIVIDADE ÚTIL] Conversa #{conv.id} atingiu limite de 4 horas úteis de expediente ({minutos_uteis:.1f} min). Expirando chamado...")
                        conv.status = ConversationStatus.EXPIRADA_POR_INATIVIDADE
                        extra["expired_by_inactivity_at"] = now.isoformat()
                        conv.dados_adicionais = extra
                        conv.protocol_number = None

                        # Closing WhatsApp message
                        closing_msg = (
                            f"🔒 *Atendimento Finalizado por Inatividade*\n\n"
                            f"Olá, {cust_name}! Seu atendimento (Protocolo: {proto}) foi encerrado automaticamente após 4 horas de inatividade durante o horário de expediente.\n\n"
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
                            conteudo="🔒 Atendimento finalizado automaticamente por inatividade (4 horas úteis de expediente).",
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
                        # Auto JSON backup to Google Drive
                        try:
                            async with AsyncSessionLocal() as gdrive_db:
                                gdrive_settings = await settings_service.get_tenant_decrypted_settings(gdrive_db, conv.tenant_id)
                        except Exception:
                            gdrive_settings = {}
                        await gdrive_service.sync_conversation_to_drive(
                            tenant_drive_folder_id=gdrive_settings.get("gdrive_folder_id") or "1Xv8qI4NLU9pjbbUvCZami3TfkgsjRfd0",
                            conversation_id=conv.id,
                            contact_phone=conv.contact.telefone if conv.contact else "desconhecido",
                            conversation_data=conv_data,
                            refresh_token=gdrive_settings.get("gdrive_refresh_token", ""),
                            client_id=gdrive_settings.get("google_client_id", ""),
                            client_secret=gdrive_settings.get("google_client_secret", ""),
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
                    # TIER 2: WARNING 2 (10 min restantes / inatividade >= 3h50 = 230 min)
                    # ----------------------------------------------------
                    if inatividade_util >= (TIMEOUT_INATIVIDADE - AVISO_2) and not extra.get("aviso_2_enviado") and not extra.get("inactivity_warning_10m_sent"):
                        logger.info(f"[INATIVIDADE ÚTIL] Enviando 2º aviso prévio (10 min restantes) para conversa #{conv.id}...")
                        
                        warning_text = (
                            f"⚠️ *Aviso de Inatividade*\n\n"
                            f"Olá, {cust_name}! Seu atendimento (Protocolo: {proto}) será finalizado em aproximadamente 10 minutos por ausência de interação.\n\n"
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
                                logger.warning(f"Failed to send 10m warning message to #{conv.id}: {err}")

                        sys_msg = Message(
                            conversation_id=conv.id,
                            remetente="sistema",
                            conteudo="⏳ Segundo aviso prévio de inatividade (10 minutos restantes) enviado ao cliente.",
                            tipo=MessageType.TEXTO,
                            timestamp=now
                        )
                        db.add(sys_msg)

                        extra["aviso_2_enviado"] = True
                        extra["inactivity_warning_10m_sent"] = True
                        extra["inactivity_warning_10m_at"] = now.isoformat()
                        conv.dados_adicionais = extra
                        changes_made = True
                        continue

                    # ----------------------------------------------------
                    # TIER 1: WARNING 1 (30 min restantes / inatividade >= 3h30 = 210 min)
                    # ----------------------------------------------------
                    if inatividade_util >= (TIMEOUT_INATIVIDADE - AVISO_1) and not extra.get("aviso_1_enviado") and not extra.get("inactivity_warning_30m_sent"):
                        logger.info(f"[INATIVIDADE ÚTIL] Enviando 1º aviso prévio (30 min restantes) para conversa #{conv.id}...")
                        
                        warning_text = (
                            f"⏳ *Aviso de Atendimento*\n\n"
                            f"Olá, {cust_name}! Notamos que você está sem interagir há algum tempo. Ainda está por aí?\n\n"
                            f"Seu atendimento (Protocolo: {proto}) será encerrado em aproximadamente 30 minutos caso não haja nova resposta."
                        )
                        if inst_name and conv.contact:
                            try:
                                await evolution_service.send_text_message(
                                    instance_name=inst_name,
                                    number=conv.contact.telefone,
                                    text=warning_text
                                )
                            except Exception as err:
                                logger.warning(f"Failed to send 30m warning message to #{conv.id}: {err}")

                        sys_msg = Message(
                            conversation_id=conv.id,
                            remetente="sistema",
                            conteudo="⏳ Primeiro aviso prévio de inatividade (30 minutos restantes) enviado ao cliente.",
                            tipo=MessageType.TEXTO,
                            timestamp=now
                        )
                        db.add(sys_msg)

                        extra["aviso_1_enviado"] = True
                        extra["inactivity_warning_30m_sent"] = True
                        extra["inactivity_warning_30m_at"] = now.isoformat()
                        conv.dados_adicionais = extra
                        changes_made = True

                if changes_made:
                    await db.commit()

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

                    # Only auto-respond if a real protocol was opened in the live system
                    if not conv.protocol_number or conv.protocol_number in ["S/N", "None", "", None]:
                        continue

                    extra = dict(conv.dados_adicionais or {})
                    if extra.get("is_migrated") or extra.get("migrated_from_whatsapp"):
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
                                protocol_number=conv.protocol_number,
                                customer_phone=conv.contact.telefone if conv.contact else None,
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
    """Continuous background loop for inactivity check."""
    logger.info("Inactivity background monitor task started.")
    while True:
        try:
            await inactivity_service.check_and_expire_idle_conversations()
        except Exception as e:
            logger.error(f"Error in inactivity checker background loop: {e}")
        await asyncio.sleep(interval_seconds)
