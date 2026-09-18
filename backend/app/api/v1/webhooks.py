import asyncio
import logging
import base64
import uuid
import os
import re
import time
import httpx
from typing import Optional, Dict, Any, Set
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import get_db
from app.core.config import settings
from app.models.models import (
    WhatsAppNumber, Contact, Conversation, Message, ConversationMemory,
    ConversationStatus, MessageSender, MessageType, WhatsAppGroup, User, UserRole, TransferLog,
    AuthorizedTechnician, CalendarEvent
)

from app.services.evolution_service import evolution_service
from app.services.whatsapp_sync_service import whatsapp_sync_service
from app.services.gemini_service import gemini_service, sanitize_customer_name, is_bot_or_menu_message
from app.services.rag_service import rag_service
from app.services.settings_service import settings_service
from app.services.protocol_service import generate_daily_protocol
from app.services.distribution_service import distribution_service
from app.services.business_hours_service import business_hours_service
from app.api.v1.conversations import generate_bacen_pix_string, extract_evolution_msg_id
from app.api.websockets import manager as ws_manager
from app.services.lid_resolver_service import resolve_lid_info, download_and_cache_avatar_locally, resolve_and_bind_contact
from app.services.whatsapp_sync_service import parse_quoted_context

logger = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks Integration"])

SEEN_WEBHOOK_KEYS = {}
_conversation_ai_timestamps: Dict[int, float] = {}
_conversation_location_timestamps: Dict[int, float] = {}
_in_flight_webhook_messages: Dict[str, float] = {}
_in_flight_ai_conversations: Dict[int, float] = {}
_last_customer_msg_timestamps: Dict[int, float] = {}

def extract_message_datetime(data: Any) -> datetime:
    if not isinstance(data, dict):
        return datetime.utcnow()
    ts_raw = data.get("messageTimestamp")
    if not ts_raw and isinstance(data.get("message"), dict):
        ts_raw = data.get("message", {}).get("messageTimestamp")
    if not ts_raw and isinstance(data.get("key"), dict):
        ts_raw = data.get("key", {}).get("messageTimestamp")
    if not ts_raw:
        ts_raw = data.get("timestamp") or data.get("date")
    
    if ts_raw:
        try:
            ts_int = int(ts_raw)
            if ts_int > 10_000_000_000:
                ts_int = ts_int // 1000
            if ts_int > 0:
                return datetime.utcfromtimestamp(ts_int)
        except Exception:
            pass
    return datetime.utcnow()

def extract_amount_from_text(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    patterns = [
        r'r\$\s*(\d+(?:[.,]\d{2})?)',
        r'(\d+(?:[.,]\d{2})?)\s*(?:reais|rs)',
        r'(?:valor|pagar|nota|orcamento|orçamento|pedido)\s*(?:de\s*)?(?:r\$\s*)?(\d+(?:[.,]\d{2})?)',
        r'\b(\d{2,6}(?:[.,]\d{2})?)\b'
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(',', '.')
            try:
                v = float(raw)
                if 1.0 <= v <= 500000.0:
                    return v
            except ValueError:
                pass
    return None

async def check_is_authorized_technician_or_admin(db: AsyncSession, tenant_id: int, phone_number: str) -> tuple[bool, Optional[str]]:
    if not phone_number:
        return False, None
    clean_digits = re.sub(r'\D', '', phone_number)
    
    # 1. Check in AuthorizedTechnician table
    tech_stmt = select(AuthorizedTechnician).where(
        AuthorizedTechnician.tenant_id == tenant_id,
        AuthorizedTechnician.ativo == True
    )
    tech_res = await db.execute(tech_stmt)
    technicians = tech_res.scalars().all()
    for tech in technicians:
        t_digits = re.sub(r'\D', '', str(tech.telefone))
        if t_digits and (clean_digits == t_digits or (len(clean_digits) >= 8 and len(t_digits) >= 8 and clean_digits[-8:] == t_digits[-8:])):
            return True, tech.nome

    # 2. Check in Users table (if user has role 'admin')
    user_stmt = select(User).where(
        User.tenant_id == tenant_id,
        User.status == True
    )
    user_res = await db.execute(user_stmt)
    users = user_res.scalars().all()
    for u in users:
        is_admin = u.role == "admin" or str(getattr(u.role, 'value', u.role)).lower() == "admin"
        if is_admin:
            u_login_digits = re.sub(r'\D', '', str(u.login))
            if u_login_digits and len(u_login_digits) >= 8 and (clean_digits == u_login_digits or clean_digits[-8:] == u_login_digits[-8:]):
                return True, u.nome

    return False, None

async def assign_least_busy_attendant(db: AsyncSession, tenant_id: int, whatsapp_number_id: int) -> Optional[User]:
    return await distribution_service.assign_least_loaded_attendant(db, tenant_id, whatsapp_number_id)


async def send_os_pdf_after_confirmation(
    tenant_id: int,
    conversation_id: int,
    whatsapp_number_id: int,
    instance_name: Optional[str],
    recipient_phone: str,
    pdf_relative_path: str
):
    """
    Fired as a background task once the customer confirms they read the O.S. conditions
    (see the CONFIRM_OS_PDF handling in receive_evolution_webhook). Runs in its own DB
    session since it's decoupled from the triggering request, same pattern as
    automation_service.process_and_dispatch_automation.
    """
    from app.core.database import AsyncSessionLocal
    try:
        abs_path = os.path.join("uploads", pdf_relative_path)
        if not os.path.isfile(abs_path):
            logger.error(f"[OS HANDLER PDF] Arquivo não encontrado para envio: {abs_path}")
            return
        with open(abs_path, "rb") as f:
            file_bytes = f.read()
        base64_data = base64.b64encode(file_bytes).decode("utf-8")

        send_res = await evolution_service.send_media_message(
            instance_name=instance_name,
            number=recipient_phone,
            media_type="document",
            mimetype="application/pdf",
            media=base64_data,
            file_name="Ordem_de_Servico.pdf",
            skip_anti_ban_pacing=True
        )
        wa_msg_id = extract_evolution_msg_id(send_res) if isinstance(send_res, dict) else None

        async with AsyncSessionLocal() as db:
            db_content = f"/uploads/{pdf_relative_path}|Ordem_de_Servico.pdf"
            saved_msg = Message(
                conversation_id=conversation_id,
                remetente=MessageSender.SISTEMA,
                conteudo=db_content,
                tipo=MessageType.ARQUIVO,
                status="sent",
                whatsapp_msg_id=wa_msg_id,
                timestamp=datetime.utcnow()
            )
            db.add(saved_msg)
            conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
            conv = (await db.execute(conv_stmt)).scalar_one_or_none()
            if conv:
                conv.ultima_interacao_em = datetime.utcnow()
            await db.commit()
            await db.refresh(saved_msg)

            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number_id,
                message_data={
                    "type": "NEW_MESSAGE",
                    "conversation_id": conversation_id,
                    "id": saved_msg.id,
                    "remetente": MessageSender.SISTEMA.value,
                    "conteudo": db_content,
                    "tipo": MessageType.ARQUIVO.value,
                    "status": "sent",
                    "timestamp": saved_msg.timestamp.isoformat() + "Z",
                    "agent_name": "Automação OS"
                }
            )

            # Explain what happens next - otherwise the PDF just lands with no context and
            # the customer is left wondering what to expect (reported directly: getting only
            # the file read as confusing).
            next_steps_text = (
                "🔧 Em breve, nossos técnicos farão a verificação do equipamento e entraremos "
                "em contato novamente para enviar o laudo técnico com o orçamento do reparo."
            )
            next_steps_res = await evolution_service.send_text_message(
                instance_name=instance_name, number=recipient_phone, text=next_steps_text
            )
            next_msg = Message(
                conversation_id=conversation_id,
                remetente=MessageSender.SISTEMA,
                conteudo=next_steps_text,
                tipo=MessageType.TEXTO,
                status="sent",
                whatsapp_msg_id=extract_evolution_msg_id(next_steps_res) if isinstance(next_steps_res, dict) else None,
                timestamp=datetime.utcnow()
            )
            db.add(next_msg)
            await db.commit()
            await db.refresh(next_msg)
            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number_id,
                message_data={
                    "type": "NEW_MESSAGE",
                    "conversation_id": conversation_id,
                    "id": next_msg.id,
                    "remetente": MessageSender.SISTEMA.value,
                    "conteudo": next_steps_text,
                    "tipo": MessageType.TEXTO.value,
                    "status": "sent",
                    "timestamp": next_msg.timestamp.isoformat() + "Z",
                    "agent_name": "Automação OS"
                }
            )
        logger.info(f"[OS HANDLER PDF] PDF enviado com sucesso para conversa #{conversation_id}")
    except Exception as err:
        logger.error(f"[OS HANDLER PDF] Erro ao enviar PDF após confirmação: {err}", exc_info=True)


async def notify_os_approval_result(
    tenant_id: int,
    conversation_id: int,
    whatsapp_number_id: int,
    instance_name: Optional[str],
    os_numero: str,
    client_name: str,
    aprovado: bool,
    pdf_relative_path: str,
    tecnico_phone: Optional[str]
):
    """
    Fired as a background task once the customer approves/rejects the technician's quote
    (fase 2 do OS Handler). Announces the result in the "SERV - SOLICITAÇÃO DE O.S." WhatsApp
    group, and forwards the quote PDF straight to the responsible technician (if one was
    identified on the document) so they know exactly what was approved.
    """
    from app.core.database import AsyncSessionLocal
    try:
        status_label = "✅ *APROVADO*" if aprovado else "❌ *RECUSADO*"
        group_text = (
            f"📋 *Ordem de Serviço #{os_numero}*\n"
            f"Cliente: {client_name}\n"
            f"Status: {status_label} pelo cliente via WhatsApp."
        )
        await evolution_service.send_text_message(
            instance_name=instance_name,
            number=settings.SERV_OS_GROUP_JID,
            text=group_text
        )
        logger.info(f"[OS HANDLER APROVAÇÃO] Grupo SERV notificado sobre O.S. #{os_numero} ({'aprovado' if aprovado else 'recusado'})")

        if tecnico_phone:
            abs_path = os.path.join("uploads", pdf_relative_path)
            if os.path.isfile(abs_path):
                with open(abs_path, "rb") as f:
                    file_bytes = f.read()
                base64_data = base64.b64encode(file_bytes).decode("utf-8")
                caption = f"{status_label.replace('*', '')} - O.S. #{os_numero} ({client_name})"
                await evolution_service.send_media_message(
                    instance_name=instance_name,
                    number=tecnico_phone,
                    media_type="document",
                    mimetype="application/pdf",
                    media=base64_data,
                    file_name="Orcamento_OS.pdf",
                    caption=caption,
                    skip_anti_ban_pacing=True
                )
                logger.info(f"[OS HANDLER APROVAÇÃO] PDF do orçamento enviado ao técnico ({tecnico_phone})")
            else:
                logger.warning(f"[OS HANDLER APROVAÇÃO] Arquivo do orçamento não encontrado para reenvio ao técnico: {abs_path}")

        async with AsyncSessionLocal() as db:
            note_msg = Message(
                conversation_id=conversation_id,
                remetente=MessageSender.SISTEMA,
                conteudo=f"{status_label.replace('*', '')} - Notificação enviada ao grupo SERV - SOLICITAÇÃO DE O.S." + (
                    " e ao técnico responsável." if tecnico_phone else " (técnico não identificado no documento, avise manualmente)."
                ),
                tipo=MessageType.TEXTO,
                timestamp=datetime.utcnow()
            )
            db.add(note_msg)
            await db.commit()
            await db.refresh(note_msg)
            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number_id,
                message_data={
                    "type": "NEW_MESSAGE",
                    "conversation_id": conversation_id,
                    "id": note_msg.id,
                    "remetente": MessageSender.SISTEMA.value,
                    "conteudo": note_msg.conteudo,
                    "tipo": MessageType.TEXTO.value,
                    "status": "sent",
                    "timestamp": note_msg.timestamp.isoformat() + "Z",
                    "agent_name": "Automação OS"
                }
            )
    except Exception as err:
        logger.error(f"[OS HANDLER APROVAÇÃO] Erro ao notificar resultado da aprovação: {err}", exc_info=True)


@router.post("/evolution")
async def receive_evolution_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook handler for Evolution API incoming WhatsApp messages.
    """
    try:
        payload = await request.json()
    except Exception as err:
        logger.error(f"Failed to parse JSON body from webhook: {err}")
        return {"status": "error", "message": "Invalid JSON body"}

    event_type = payload.get("event")
    data = payload.get("data", {})
    if isinstance(data, list):
        data = data[0] if len(data) > 0 and isinstance(data[0], dict) else {}
    elif not isinstance(data, dict):
        data = {}

    instance_name = payload.get("instance") or data.get("instance")

    print(f"[WEBHOOK RECEBIDO] Evento: '{event_type}' | Instancia: '{instance_name}'", flush=True)
    logger.info(f"[WEBHOOK RECEBIDO] Evento: '{event_type}' | Instancia: '{instance_name}'")

    key = data.get("key", {}) if isinstance(data, dict) else {}
    msg_id = key.get("id") if isinstance(key, dict) else None
    
    # Deduplicate incoming webhooks (Evolution API sends duplicate events for same msg_id)
    if msg_id:
        now_ts = time.time()
        # Clean cache older than 60s
        to_del = [k for k, ts in SEEN_WEBHOOK_KEYS.items() if (now_ts - (ts if isinstance(ts, (int, float)) else ts.timestamp())) > 60]
        for k in to_del:
            del SEEN_WEBHOOK_KEYS[k]

        # Prevent concurrent in-flight race conditions for the exact same message id
        inflight_ts = _in_flight_webhook_messages.get(msg_id, 0.0)
        if (now_ts - inflight_ts) < 10.0:
            logger.info(f"[ANTI-RACE] Mensagem '{msg_id}' já está em processamento concorrente há {(now_ts - inflight_ts):.2f}s. Ignorando payload repetido.")
            return {"status": "ignored", "reason": "Message currently in-flight"}

        norm_ev_check = str(event_type or "").lower().replace("_", ".").strip()
        is_status_update = norm_ev_check in ["messages.update", "message.update"]

        dedup_keys = [
            f"{instance_name}_{msg_id}",
            f"msg_{msg_id}",
            f"{instance_name}_{event_type}_{msg_id}"
        ]
        if not is_status_update:
            dedup_keys.insert(0, msg_id)

        if any(k in SEEN_WEBHOOK_KEYS for k in dedup_keys):
            logger.info(f"[DEDUP INICIAL] Ignorando webhook duplicado para msg_id '{msg_id}' (instância '{instance_name}', evento '{event_type}')")
            return {"status": "ignored", "reason": "Duplicate webhook payload"}

        for k in dedup_keys:
            SEEN_WEBHOOK_KEYS[k] = now_ts
        _in_flight_webhook_messages[msg_id] = now_ts

    # Handle QRCODE_UPDATED event to cache QR code in real-time
    if event_type in ["qrcode.updated", "qrcode_updated", "qrcode"]:
        qr_obj = data.get("qrcode") or data
        qr_base64 = None
        if isinstance(qr_obj, dict):
            qr_base64 = qr_obj.get("base64")
        elif isinstance(qr_obj, str):
            qr_base64 = qr_obj
        if not qr_base64:
            qr_base64 = payload.get("qrcode", {}).get("base64") if isinstance(payload.get("qrcode"), dict) else None

        if qr_base64 and instance_name:
            evolution_service.qr_code_cache[instance_name] = qr_base64
            logger.info(f"Updated cached QR Code for instance '{instance_name}' via webhook event '{event_type}'")
            return {"status": "success", "event": event_type, "message": "QR Code cached successfully"}

    # Handle CONNECTION_UPDATE event (trigger auto-reconciliation when connection is restored)
    if event_type in ["connection.update", "connection_update", "CONNECTION_UPDATE"]:
        conn_state = data.get("state") or data.get("status") or payload.get("state")
        logger.info(f"[CONNECTION_UPDATE] Instância '{instance_name}' estado: '{conn_state}'")
        if str(conn_state).lower() in ["open", "connected"] and instance_name:
            logger.info(f"🔄 [AUTO-RECONCILE] Instância '{instance_name}' restabelecida! Executando varredura em segundo plano...")
            from app.services.whatsapp_reconciliation_service import whatsapp_reconciliation_service
            asyncio.create_task(whatsapp_reconciliation_service.reconcile_by_instance_name(instance_name))
        return {"status": "success", "event": event_type, "state": conn_state}

    # Handle PRESENCE_UPDATE event (Customer typing or recording audio on WhatsApp)
    if event_type in ["presence.update", "presence_update", "PRESENCE_UPDATE"]:
        p_data = data
        if isinstance(p_data, list) and len(p_data) > 0:
            p_data = p_data[0]
        
        if not isinstance(p_data, dict):
            p_data = payload.get("data") or {}
            if isinstance(p_data, list) and len(p_data) > 0:
                p_data = p_data[0]
                
        presences = p_data.get("presences") if isinstance(p_data, dict) else {}
        p_id = (p_data.get("id") or p_data.get("jid") or payload.get("id") or "") if isinstance(p_data, dict) else ""
        
        last_presence = None
        target_jid = p_id
        
        if isinstance(presences, dict):
            for k, v in presences.items():
                if isinstance(v, dict):
                    last_presence = v.get("lastKnownPresence") or v.get("presence")
                    target_jid = k
                    break
        elif isinstance(p_data, dict):
            last_presence = p_data.get("lastKnownPresence") or p_data.get("presence")

        if target_jid and last_presence:
            clean_phone = target_jid.split("@")[0].split(":")[0]
            clean_digits = "".join(filter(str.isdigit, clean_phone))
            
            if clean_digits:
                c_stmt = (
                    select(Conversation.id, Conversation.tenant_id)
                    .join(Contact, Conversation.contact_id == Contact.id)
                    .where(
                        (Contact.telefone == clean_digits) | (Contact.telefone == clean_phone) | (Contact.telefone.like(f"%{clean_digits[-8:]}%"))
                    )
                    .order_by(Conversation.id.desc())
                    .limit(1)
                )
                c_res = await db.execute(c_stmt)
                conv_row = c_res.first()
                
                if conv_row:
                    conv_id, tenant_id = conv_row[0], conv_row[1]
                    logger.info(f"📱 [PRESENCE_UPDATE] Cliente ({clean_phone}) na conversa #{conv_id}: status='{last_presence}'")
                    await ws_manager.broadcast_to_tenant(tenant_id, {
                        "type": "USER_PRESENCE",
                        "conversation_id": conv_id,
                        "phone": clean_phone,
                        "presence": last_presence
                    })
        return {"status": "success", "event": event_type, "presence": last_presence}

    # Handle CONTACTS_UPDATE / CONTACTS_UPSERT (Phone address book synced or updated on mobile)
    if event_type in ["contacts.update", "contacts.upsert", "contacts_update", "contacts_upsert"]:
        contacts_raw = payload.get("data") or data
        if not isinstance(contacts_raw, list):
            contacts_raw = [contacts_raw] if isinstance(contacts_raw, dict) else []

        wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.instancia_evolution_api == instance_name)
        wn_res = await db.execute(wn_stmt)
        wn = wn_res.scalar_one_or_none()
        tenant_id = wn.tenant_id if wn else 1

        updated_count = 0
        for c_entry in contacts_raw:
            if not isinstance(c_entry, dict):
                continue
            jid = c_entry.get("remoteJid") or c_entry.get("id") or ""
            if not jid or "status@broadcast" in jid:
                continue
            
            # NEVER match or sync individual names onto WhatsApp Groups
            is_entry_group = "@g.us" in str(jid).lower() or str(jid).startswith("120363") or ("-" in str(jid).split("@")[0] and len(str(jid).split("@")[0]) > 15)
            if is_entry_group:
                continue

            clean_phone = jid.split("@")[0].split(":")[0]
            clean_digits = "".join(filter(str.isdigit, clean_phone))
            if not clean_digits or len(clean_digits) < 8:
                continue
            
            contact_name = c_entry.get("pushName") or c_entry.get("name") or c_entry.get("verifiedName")
            profile_pic = c_entry.get("profilePicUrl")

            if contact_name or profile_pic:
                # Exclude groups from matching individual contact phones!
                c_stmt = select(Contact).where(
                    Contact.tenant_id == tenant_id,
                    Contact.telefone.notlike("%@g.us%"),
                    Contact.telefone.notlike("%-%"),
                    Contact.telefone.notlike("120363%"),
                    (Contact.telefone == clean_digits) | (Contact.telefone.like(f"%{clean_digits[-8:]}%"))
                )
                c_matches = await db.execute(c_stmt)
                for existing_c in c_matches.scalars().all():
                    # Double check that contact is not a group
                    c_extra = existing_c.dados_adicionais or {}
                    if c_extra.get("is_group") or "@g.us" in str(existing_c.telefone) or "-" in str(existing_c.telefone) or str(existing_c.telefone).startswith("120363"):
                        continue
                    # Only auto-apply the incoming pushName if the CURRENT name is a weak
                    # placeholder (missing, equal to the phone number, or has no letters at
                    # all, e.g. "556183603945" or "+55 61 8360-3945"). Without this guard, a
                    # real business-relevant name we already had (e.g. "Adalberto Gas
                    # Particular", set from a fuller source or manually) was getting silently
                    # downgraded to whatever short pushName the customer happens to have set
                    # for themselves on WhatsApp (e.g. just "Adalberto") every time this
                    # webhook fired again.
                    current_name = (existing_c.nome or "").strip()
                    current_is_weak = (
                        not current_name or
                        current_name == clean_digits or
                        not re.search(r'[A-Za-zÀ-ÿ]', current_name)
                    )
                    if not c_extra.get("custom_name_locked") and current_is_weak and contact_name and contact_name != clean_digits and contact_name not in ["Cliente", "WhatsApp", "WhatsApp Business"]:
                        existing_c.nome = contact_name
                    if profile_pic and not existing_c.foto_perfil_url:
                        existing_c.foto_perfil_url = profile_pic
                    updated_count += 1

        if updated_count > 0:
            await db.commit()
            logger.info(f"[CONTACTS_UPDATE] Sincronizados {updated_count} contatos da agenda do celular via webhook.")
        return {"status": "success", "event": event_type, "updated_contacts": updated_count}

    # Handle Incoming WhatsApp Call event (CALL / call / call.updated)
    is_call_event = (
        event_type in ["call", "CALL", "call.updated", "call_received"] or
        "call" in str(event_type).lower() or
        data.get("status") in ["offer", "ringing"] or
        "caller" in data
    )

    if is_call_event:
        try:
            status_call = str(data.get("status") or "offer").lower()
            # Only log a "missed call" card on an actual negative outcome. "offer"/"ringing" are
            # just the call starting - not yet an outcome - and "accept" means it was answered.
            # This used to fire on "offer" alone, so every call got marked as missed the instant
            # it started ringing, and since "accept" was never handled, answering it never fixed
            # the card - the customer's call showed as missed even when the agent picked up.
            if status_call not in ["missed", "timeout", "reject"]:
                return {"status": "ignored", "reason": f"Call status '{status_call}' is not a missed-call outcome"}

            call_id = data.get("id") or data.get("callId") or (data.get("key") or {}).get("id") or ""
            raw_caller_jid = (
                data.get("caller") or
                data.get("from") or
                data.get("chatId") or
                data.get("creator") or
                data.get("creatorJid") or
                data.get("peerJid") or
                (data.get("key") or {}).get("remoteJid", "")
            )
            raw_phone = str(raw_caller_jid).split("@")[0] if "@" in str(raw_caller_jid) else str(raw_caller_jid)
            phone_number = "".join(filter(str.isdigit, raw_phone))

            is_video = bool(data.get("isVideo", False))
            push_name = data.get("pushName") or "Cliente"

            # Find WhatsApp Number by instance
            wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.instancia_evolution_api == instance_name)
            wn_res = await db.execute(wn_stmt)
            wn = wn_res.scalar_one_or_none()
            if not wn:
                wn_stmt = select(WhatsAppNumber)
                wn_res = await db.execute(wn_stmt)
                wn = wn_res.scalars().first()

            if not wn:
                return {"status": "error", "message": "Nenhum número cadastrado"}

            # Resolve contact strictly to the caller (no erroneous fallback to recent active conversation)
            contact = None
            if raw_caller_jid:
                contact = await resolve_and_bind_contact(
                    session=db,
                    tenant_id=wn.tenant_id,
                    raw_jid=str(raw_caller_jid),
                    push_name=push_name
                )
            elif phone_number and len(phone_number) >= 8:
                c_stmt = select(Contact).where(Contact.tenant_id == wn.tenant_id, Contact.telefone.like(f"%{phone_number[-8:]}%"))
                c_res = await db.execute(c_stmt)
                contact = c_res.scalars().first()

            now = datetime.utcnow()
            call_dt = extract_message_datetime(data)

            if not contact:
                contact = Contact(
                    tenant_id=wn.tenant_id,
                    nome=push_name,
                    telefone=phone_number or "Cliente",
                    criado_em=now
                )
                db.add(contact)
                await db.commit()
                await db.refresh(contact)

            # Find or create conversation
            conv_stmt = select(Conversation).where(
                Conversation.contact_id == contact.id,
                Conversation.whatsapp_number_id == wn.id
            )
            conv_res = await db.execute(conv_stmt)
            conv = conv_res.scalar_one_or_none()

            if not conv:
                conv = Conversation(
                    tenant_id=wn.tenant_id,
                    whatsapp_number_id=wn.id,
                    contact_id=contact.id,
                    status=ConversationStatus.COM_HUMANO,
                    criado_em=now,
                    ultima_interacao_em=now
                )
                db.add(conv)
                await db.commit()
                await db.refresh(conv)
            else:
                conv.ultima_interacao_em = now
                await db.commit()

            # Deduplication: Check if this call was already recorded
            if call_id:
                existing_call_stmt = select(Message.id).where(
                    (Message.whatsapp_msg_id == f"call_{call_id}") |
                    (Message.whatsapp_msg_id == str(call_id))
                )
                existing_call_res = await db.execute(existing_call_stmt)
                if existing_call_res.scalars().first():
                    return {"status": "ignored", "reason": f"Call ID '{call_id}' already recorded"}

            # Deduplication cooldown (60 seconds within same conversation)
            recent_call_stmt = select(Message).where(
                Message.conversation_id == conv.id,
                (Message.conteudo.like("%[CHAMADA_%") | Message.conteudo.like("%O CLIENTE ESTÁ LIGANDO%") | Message.conteudo.like("%Ligação de%"))
            ).order_by(Message.timestamp.desc())
            recent_call_res = await db.execute(recent_call_stmt)
            last_call_msg = recent_call_res.scalars().first()

            if last_call_msg and (now - last_call_msg.timestamp).total_seconds() < 60.0:
                return {"status": "ignored", "reason": "Call already logged within cooldown"}

            # Format authentic WhatsApp Call card text
            call_token = "[CHAMADA_VIDEO_PERDIDA]" if is_video else "[CHAMADA_VOZ_PERDIDA]"
            call_title = "Ligação de vídeo perdida" if is_video else "Ligação de voz perdida"
            call_sub = "Clique para retornar"
            call_msg_text = f"{call_token}|{call_title}|{call_sub}"

            call_msg = Message(
                conversation_id=conv.id,
                remetente="cliente",
                tipo=MessageType.TEXTO,
                conteudo=call_msg_text,
                whatsapp_msg_id=f"call_{call_id}" if call_id else None,
                dados_adicionais={
                    "call_id": call_id,
                    "call_type": "video" if is_video else "voice",
                    "is_video": is_video,
                    "call_status": status_call
                },
                timestamp=call_dt
            )
            db.add(call_msg)
            await db.commit()
            await db.refresh(call_msg)

            # Broadcast to department so UI updates immediately
            try:
                await ws_manager.broadcast_to_department(
                    tenant_id=wn.tenant_id,
                    whatsapp_number_id=wn.id,
                    message_data={
                        "type": "NEW_MESSAGE",
                        "conversation_id": conv.id,
                        "remetente": "cliente",
                        "conteudo": call_msg_text,
                        "tipo": "texto",
                        "dados_adicionais": call_msg.dados_adicionais,
                        "timestamp": call_msg.timestamp.isoformat() + "Z" if hasattr(call_msg.timestamp, "isoformat") else str(call_msg.timestamp),
                        "contact_name": contact.nome,
                        "contact_phone": contact.telefone,
                        "department": wn.nome_departamento
                    }
                )
                await ws_manager.broadcast({
                    "type": "incoming_call",
                    "conversation_id": conv.id,
                    "contact_name": contact.nome,
                    "phone": contact.telefone,
                    "is_video": is_video,
                    "message_id": call_msg.id
                })
            except Exception as err:
                logger.error(f"Error broadcasting call websocket event: {err}")

            return {"status": "success", "event": "incoming_call", "conversation_id": conv.id}
        except Exception as e:
            logger.error(f"Error processing call webhook: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


    # Handle WhatsApp Message Status Updates (Delivered, Read / Played, Sent & Group Receipts)
    norm_event = str(event_type or "").lower().replace("_", ".")

    # 1. Handle Chat Read Receipt Event (chats.upsert / chats.update with unreadMessages: 0)
    if norm_event in ["chats.upsert", "chats.update", "chat.update", "chats_upsert", "chats_update"]:
        chat_list = data if isinstance(data, list) else [data]
        updated_any = False
        for c_item in chat_list:
            if not isinstance(c_item, dict):
                continue
            unread = c_item.get("unreadMessages")
            r_jid = c_item.get("remoteJid") or c_item.get("id") or ""
            if unread == 0 or "unread" in str(c_item).lower():
                r_phone = "".join(filter(str.isdigit, str(r_jid)))
                conv_to_read = None
                if r_phone and len(r_phone) >= 8:
                    c_stmt = select(Contact).where(Contact.telefone.like(f"%{r_phone[-8:]}%"))
                    c_res = await db.execute(c_stmt)
                    c_obj = c_res.scalars().first()
                    if c_obj:
                        latest_conv = select(Conversation).where(Conversation.contact_id == c_obj.id).order_by(Conversation.ultima_interacao_em.desc())
                        lc_res = await db.execute(latest_conv)
                        conv_to_read = lc_res.scalars().first()

                if not conv_to_read and instance_name:
                    # Fallback to latest active conversation on this WhatsApp number
                    wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.instancia_evolution_api == instance_name)
                    wn_res = await db.execute(wn_stmt)
                    wn_obj = wn_res.scalar_one_or_none()
                    if wn_obj:
                        latest_conv = select(Conversation).where(Conversation.whatsapp_number_id == wn_obj.id).order_by(Conversation.ultima_interacao_em.desc())
                        lc_res = await db.execute(latest_conv)
                        conv_to_read = lc_res.scalars().first()

                if conv_to_read:
                    await db.execute(
                        update(Message)
                        .where(
                            Message.conversation_id == conv_to_read.id,
                            Message.remetente.in_(["atendente", "ia"]),
                            Message.status != "read"
                        )
                        .values(status="read")
                    )
                    await db.commit()
                    updated_any = True
                    try:
                        await ws_manager.broadcast({
                            "type": "MESSAGE_STATUS_UPDATE",
                            "conversation_id": conv_to_read.id,
                            "status": "read"
                        })
                    except Exception as err:
                        logger.error(f"Error broadcasting chat read update: {err}")

        return {"status": "success", "event": "chats.update", "updated": updated_any}

    # 2. Handle Message Update Event (messages.update)
    if norm_event in ["messages.update", "messages_update", "message.update"]:
        updates_list = data if isinstance(data, list) else [data]
        updated_any = False
        
        for item in updates_list:
            if not isinstance(item, dict):
                continue
            key_id = item.get("keyId") or item.get("id") or (item.get("key") or {}).get("id")
            raw_val = item.get("status") if item.get("status") is not None else (item.get("update") or {}).get("status")
            raw_status = str(raw_val or "").upper()
            
            mapped_status = "sent"
            if raw_status in ["READ", "PLAYED", "VIEWED", "4", "5", "READ_ACK"]:
                mapped_status = "read"
            elif raw_status in ["DELIVERY_ACK", "DELIVERED", "3"]:
                mapped_status = "delivered"
            elif raw_status in ["SERVER_ACK", "SENT", "2"]:
                mapped_status = "sent"
            elif raw_status in ["PENDING", "1"]:
                mapped_status = "pending"
            else:
                continue

            participant_jid = item.get("participant") or (item.get("key") or {}).get("participant")
            participant_phone = "".join(filter(str.isdigit, str(participant_jid))) if participant_jid else None

            msg_to_update = None
            if key_id:
                m_stmt = select(Message).where(Message.whatsapp_msg_id == key_id)
                m_res = await db.execute(m_stmt)
                msg_to_update = m_res.scalars().first()

            # Fallback by remoteJid
            if not msg_to_update and (item.get("remoteJid") or (item.get("key") or {}).get("remoteJid")):
                r_jid = item.get("remoteJid") or (item.get("key") or {}).get("remoteJid")
                r_phone = "".join(filter(str.isdigit, str(r_jid)))
                if r_phone and len(r_phone) >= 8:
                    c_stmt = select(Contact).where(Contact.telefone.like(f"%{r_phone[-8:]}%"))
                    c_res = await db.execute(c_stmt)
                    c_obj = c_res.scalars().first()
                    if c_obj:
                        latest_conv = select(Conversation).where(Conversation.contact_id == c_obj.id).order_by(Conversation.ultima_interacao_em.desc())
                        lc_res = await db.execute(latest_conv)
                        cv_obj = lc_res.scalars().first()
                        if cv_obj:
                            m_last_stmt = select(Message).where(
                                Message.conversation_id == cv_obj.id,
                                Message.remetente.in_(["atendente", "ia"])
                            ).order_by(Message.id.desc())
                            ml_res = await db.execute(m_last_stmt)
                            msg_to_update = ml_res.scalars().first()

            if msg_to_update:
                now_str = datetime.utcnow().strftime("%d/%m/%Y às %H:%M")
                msg_extra = dict(msg_to_update.dados_adicionais or {})
                read_by_list = list(msg_extra.get("read_by", []))
                delivered_to_list = list(msg_extra.get("delivered_to", []))

                # Track group participant details if available
                if participant_phone:
                    part_contact_res = await db.execute(select(Contact).where(Contact.telefone.like(f"%{participant_phone[-8:]}%")))
                    part_contact = part_contact_res.scalars().first()
                    part_name = part_contact.nome if part_contact else f"Participante ({participant_phone})"
                    part_avatar = part_contact.foto_perfil_url if part_contact else None

                    entry = {
                        "phone": participant_phone,
                        "name": part_name,
                        "avatar": part_avatar,
                        "time": now_str
                    }

                    if mapped_status == "read":
                        if not any(r.get("phone") == participant_phone for r in read_by_list):
                            read_by_list.append(entry)
                    elif mapped_status == "delivered":
                        if not any(d.get("phone") == participant_phone for d in delivered_to_list):
                            delivered_to_list.append(entry)

                msg_extra["read_by"] = read_by_list
                msg_extra["delivered_to"] = delivered_to_list
                msg_to_update.dados_adicionais = msg_extra

                conv_id = msg_to_update.conversation_id
                m_id = msg_to_update.id
                m_status = msg_to_update.status

                if mapped_status == "read" or len(read_by_list) > 0:
                    msg_to_update.status = "read"
                    m_status = "read"
                    # Also mark all previous messages in this conversation as read
                    await db.execute(
                        update(Message)
                        .where(
                            Message.conversation_id == conv_id,
                            Message.id <= m_id,
                            Message.remetente.in_(["atendente", "ia"])
                        )
                        .values(status="read")
                    )
                elif mapped_status == "delivered" and msg_to_update.status != "read":
                    msg_to_update.status = "delivered"
                    m_status = "delivered"

                if key_id and not msg_to_update.whatsapp_msg_id:
                    msg_to_update.whatsapp_msg_id = key_id

                await db.commit()
                updated_any = True

                try:
                    await ws_manager.broadcast({
                        "type": "MESSAGE_STATUS_UPDATE",
                        "conversation_id": conv_id,
                        "message_id": m_id,
                        "status": m_status,
                        "dados_adicionais": msg_extra,
                        "whatsapp_msg_id": key_id
                    })
                except Exception as err:
                    logger.error(f"Error broadcasting message status update: {err}")

        return {"status": "success", "event": "messages.update", "updated": updated_any}

    # Filter non-message events (chats.upsert, connection.update, etc.)
    if norm_event not in ["messages.upsert", "messages_upsert", "send.message", "send_message"]:
        return {"status": "ignored", "reason": f"Event '{event_type}' is not a new message event"}

    key = data.get("key", {}) if isinstance(data, dict) else {}
    from_me = key.get("fromMe", False) if isinstance(key, dict) else False
    if norm_event in ["send.message", "send_message"]:
        from_me = True

    remote_jid = key.get("remoteJid", "") if isinstance(key, dict) else ""
    remote_jid_alt = key.get("remoteJidAlt") or data.get("remoteJidAlt") or ""
    sender_jid = data.get("sender", "") or data.get("senderPhone", "") or ""
    participant_jid = key.get("participant", "") or data.get("participant", "") or ""

    raw_phone_candidate = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    # Fix LID numbers: resolve to real WhatsApp phone number.
    # original_lid keeps the internal id even after remote_jid is rewritten to the real
    # number, so the contact lookup below can find (and upgrade) a contact that was created
    # earlier under that LID - WhatsApp often only reveals the real number on a later
    # message, and without this the same person would get a second, duplicate contact.
    original_lid = ""
    if "@lid" in str(remote_jid).lower() or (len(raw_phone_candidate) >= 14 and not raw_phone_candidate.startswith("55") and not raw_phone_candidate.startswith("120363") and "@g.us" not in str(remote_jid)):
        original_lid = "".join(filter(str.isdigit, raw_phone_candidate))
        if "@s.whatsapp.net" in str(remote_jid_alt):
            remote_jid = remote_jid_alt
        elif "@s.whatsapp.net" in str(participant_jid):
            remote_jid = participant_jid
        elif "@s.whatsapp.net" in str(sender_jid):
            remote_jid = sender_jid
        else:
            lid_info = await resolve_lid_info(raw_phone_candidate)
            if lid_info.get("real_phone"):
                remote_jid = f"{lid_info['real_phone']}@s.whatsapp.net"
            if lid_info.get("name") and push_name in ["Cliente", "Cliente WhatsApp", raw_phone_candidate]:
                push_name = lid_info["name"]
            if lid_info.get("profile_pic"):
                data["profilePicUrl"] = lid_info["profile_pic"]

    is_group = (
        "@g.us" in str(remote_jid).lower() or
        str(remote_jid).startswith("120363") or
        "-" in str(remote_jid).split("@")[0] or
        data.get("isGroup") is True
    )
    raw_phone = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    if is_group:
        phone_number = f"{raw_phone}@g.us"
    else:
        phone_number = "".join(filter(str.isdigit, raw_phone))

    if from_me:
        participant_name = "Você"
        push_name = None
    else:
        raw_pn = data.get("pushName") or data.get("senderName") or ""
        BUSINESS_NAMES = {"servweld", "servsolda", "assistência técnica", "assistencia tecnica", "vendas", "locação", "locacao", "financeiro", "atendente", "você", "voce", "admin"}
        if raw_pn and not any(b in raw_pn.lower() for b in BUSINESS_NAMES):
            participant_name = raw_pn
            push_name = raw_pn
        else:
            participant_name = "Cliente"
            push_name = None


    # NEVER `data.get("message", {})` here: Evolution/Baileys sends "message": null (not a
    # missing key) for several common event types - protocol/system messages, polls, group
    # admin notices - and `.get(key, default)` only falls back to `default` when the key is
    # absent, not when its stored value is explicitly None. That crashed every `.get()` call
    # below with AttributeError, aborting this whole webhook request before any DB write -
    # for a group with frequent non-text events, that meant the conversation never got created
    # at all, which is why some whole conversations were missing from the system.
    message_obj = data.get("message") or {}

    # "View Once" photos/videos (the circled "1" toggle shown when sending a photo
    # straight from the in-chat camera) wrap the real imageMessage/videoMessage one
    # level deeper under viewOnceMessage/viewOnceMessageV2/viewOnceMessageV2Extension.
    # Without unwrapping it here, img_msg/vid_msg below are never found, so the photo
    # is silently discarded — this is why sending a photo via the phone camera can
    # appear to "not send" even though WhatsApp itself delivered it fine.
    for _vo_key in ("viewOnceMessageV2Extension", "viewOnceMessageV2", "viewOnceMessage"):
        _vo_wrap = message_obj.get(_vo_key)
        if isinstance(_vo_wrap, dict) and isinstance(_vo_wrap.get("message"), dict):
            message_obj = _vo_wrap["message"]
            break

    # Handle incoming WhatsApp Emoji Reaction (reactionMessage) from customer
    reaction_msg = message_obj.get("reactionMessage")
    if reaction_msg or data.get("messageType") == "reactionMessage":
        reaction_payload = reaction_msg if isinstance(reaction_msg, dict) else (data.get("reaction") or {})
        target_key_id = (reaction_payload.get("key") or {}).get("id") or reaction_payload.get("keyId")
        emoji_reaction = reaction_payload.get("text") or ""

        if target_key_id:
            m_res = await db.execute(select(Message).where(Message.whatsapp_msg_id == target_key_id))
            target_msg = m_res.scalar_one_or_none()
            if target_msg:
                msg_extra = dict(target_msg.dados_adicionais or {})
                msg_extra["reaction"] = emoji_reaction
                target_msg.dados_adicionais = msg_extra
                await db.commit()

                await ws_manager.broadcast({
                    "type": "MESSAGE_REACTION_UPDATE",
                    "conversation_id": target_msg.conversation_id,
                    "message_id": target_msg.id,
                    "reaction": emoji_reaction
                })
                return {"status": "success", "event": "reactionMessage", "reaction": emoji_reaction}

    # Extract text, media, or button responses. `.get(x) or {}` (never `.get(x, {})`) because
    # Evolution/Baileys often stores these sub-keys as explicit null rather than omitting them,
    # and `.get(x, {})` only falls back to `{}` for a MISSING key, not a present-but-None one.
    btn_response = (
        message_obj.get("buttonsResponseMessage") or
        message_obj.get("templateButtonReplyMessage") or
        (message_obj.get("interactiveResponseMessage") or {}).get("nativeFlowResponseMessage") or
        message_obj.get("listResponseMessage")
    )
    btn_id = ""
    btn_text = ""
    if btn_response:
        btn_id = (
            btn_response.get("selectedButtonId") or
            btn_response.get("selectedId") or
            btn_response.get("selectedRowId") or
            ""
        )
        btn_text = (
            btn_response.get("selectedDisplayText") or
            btn_response.get("title") or
            ""
        )

    text_content = (
        message_obj.get("conversation") or
        (message_obj.get("extendedTextMessage") or {}).get("text") or
        btn_text or
        btn_id or
        ""
    )

    # 1. Handle Task View Confirmation Button from Employee
    cleaned_txt = text_content.lower().strip()
    is_view_confirmation = (
        btn_id.startswith("confirm_view_task") or
        btn_id.startswith("confirm_task") or
        "sim, confirmo" in cleaned_txt or
        "sim, confirmo a atividade" in cleaned_txt or
        "confirmar visualização" in cleaned_txt or
        "confirmar visualizacao" in cleaned_txt or
        "vi a atividade" in cleaned_txt or
        cleaned_txt in ["confirmar", "confirmado", "ok", "1", "visualizado", "visto", "recebido", "sim", "aceito", "aceitar"]
    )
    if is_view_confirmation and phone_number:
        # A bare "sim"/"ok"/"1" is a very broad, generic match - it fires for ANY phone with
        # ANY pending calendar task, regardless of what THIS specific conversation is actually
        # waiting on. If this conversation has an explicit, more specific pending marker (OS
        # Handler PDF/approval confirmation, sector-transfer confirmation), that's a much
        # stronger signal of intent than "some calendar task happens to be pending for this
        # phone" - honor it instead of hijacking the reply into the task-confirmation flow.
        # (Found via a real test: a "Sim" meant to confirm reading the O.S. terms got
        # swallowed here because the same test phone also had a leftover pending task.)
        guard_stmt = (
            select(Conversation.assunto_atual)
            .join(Contact, Conversation.contact_id == Contact.id)
            .where(Contact.telefone == phone_number)
            .order_by(Conversation.ultima_interacao_em.desc())
            .limit(1)
        )
        guard_marker = (await db.execute(guard_stmt)).scalar_one_or_none() or ""
        if guard_marker.startswith(("CONFIRM_OS_PDF:", "CONFIRM_OS_APPROVAL:", "CONFIRM_TRANSFER:")):
            is_view_confirmation = False

    if is_view_confirmation and phone_number:
        event_id = None
        for prefix in ["confirm_view_task_", "confirm_task_"]:
            if prefix in btn_id:
                try:
                    event_id = int(btn_id.replace(prefix, ""))
                    break
                except Exception:
                    pass

        if event_id:
            ev_stmt = select(CalendarEvent).options(selectinload(CalendarEvent.contact)).where(CalendarEvent.id == event_id)
        else:
            ev_stmt = (
                select(CalendarEvent)
                .options(selectinload(CalendarEvent.contact))
                .where(
                    CalendarEvent.employee_phone.like(f"%{phone_number[-8:]}%"),
                    CalendarEvent.status.in_(["pendente", "em_progresso"])
                )
                .order_by(CalendarEvent.start_time.desc())
            )
        ev_res = await db.execute(ev_stmt)
        ev_obj = ev_res.scalars().first()

        if ev_obj:
            ev_obj.confirmed_by_employee = True
            ev_obj.confirmed_at = datetime.utcnow()
            ev_obj.status = "em_progresso"
            ev_obj.atualizado_em = datetime.utcnow()
            await db.commit()
            await db.refresh(ev_obj)
            logger.info(f"Atividade #{ev_obj.id} visualizada e colocada em progresso pelo funcionário {phone_number}")

            await ws_manager.broadcast({
                "type": "CALENDAR_EVENT_UPDATED",
                "event_id": ev_obj.id,
                "confirmed_by_employee": True,
                "status": "em_progresso"
            })

            emp_name = ev_obj.employee_name or "Colaborador"
            client_info = "Não informado"
            if ev_obj.contact:
                client_info = f"{ev_obj.contact.nome or 'Cliente'} ({ev_obj.contact.telefone or ''})".strip()
            elif getattr(ev_obj, 'contact_name', None) or getattr(ev_obj, 'contact_phone', None):
                client_info = f"{getattr(ev_obj, 'contact_name', None) or 'Cliente'}"
                if getattr(ev_obj, 'contact_phone', None):
                    client_info += f" ({ev_obj.contact_phone})"

            now_utc = datetime.utcnow()
            now_brt = now_utc - timedelta(hours=3)
            event_time_brt = ev_obj.start_time if ev_obj.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")

            title_step2 = "📋 DETALHES DA ATIVIDADE EM EXECUÇÃO"
            desc_step2 = (
                f"Ótimo, *{emp_name}*! Confirmamos seu aceite. A atividade está registrada como *Em Andamento* no sistema.\n\n"
                f"🏷️ *Atividade:* {ev_obj.title}\n"
                f"⏰ *Horário:* {time_str}\n"
                f"👤 *Cliente:* {client_info}\n"
                f"📝 *Detalhes:* {ev_obj.description or 'Sem observações adicionais.'}\n\n"
                f"🏁 *Assim que concluir o atendimento, clique abaixo para finalizar:*"
            )
            buttons_step2 = [
                {
                    "type": "reply",
                    "displayText": "Sim, atividade concluída",
                    "id": f"complete_task_{ev_obj.id}"
                }
            ]

            try:
                await evolution_service.send_text_message(
                    instance_name=instance_name,
                    number=phone_number,
                    text=f"*{title_step2}*\n\n{desc_step2}\n\n_Servsolda • Sistema de Tarefas_"
                )
                try:
                    await evolution_service.send_poll_message(
                        instance_name=instance_name,
                        number=phone_number,
                        question="🏁 Concluiu a atividade? Clique abaixo:",
                        options=["Sim, atividade concluída", "⏳ Em Andamento"]
                    )
                except Exception as poll_err:
                    logger.debug(f"Poll step 2 error: {poll_err}")
            except Exception as e:
                logger.error(f"Erro ao enviar etapa 2 de cumprimento de tarefa: {e}")

            return {"status": "success", "action": "task_view_confirmed", "event_id": ev_obj.id}

    # 2. Handle Task Refusal Button from Employee
    is_task_refusal = (
        btn_id.startswith("refuse_task") or
        btn_id.startswith("refuse_view_task") or
        "não, quero recusar" in cleaned_txt or
        "nao, quero recusar" in cleaned_txt or
        "não, recusar" in cleaned_txt or
        "nao, recusar" in cleaned_txt or
        "❌ recusar" in cleaned_txt or
        "recusar" in cleaned_txt or
        "recusado" in cleaned_txt or
        "não posso" in cleaned_txt or
        "nao posso" in cleaned_txt or
        cleaned_txt in ["não", "nao", "cancelar"]
    )
    if is_task_refusal and phone_number:
        ev_stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.employee_phone.like(f"%{phone_number[-8:]}%"),
                CalendarEvent.status.in_(["pendente", "em_progresso"])
            )
            .order_by(CalendarEvent.start_time.desc())
        )
        ev_res = await db.execute(ev_stmt)
        ev_obj = ev_res.scalars().first()
        if ev_obj:
            ev_obj.status = "cancelado"
            ev_obj.confirmed_by_employee = False
            ev_obj.atualizado_em = datetime.utcnow()
            await db.commit()
            await db.refresh(ev_obj)

            await ws_manager.broadcast({
                "type": "CALENDAR_EVENT_UPDATED",
                "event_id": ev_obj.id,
                "confirmed_by_employee": False,
                "status": "cancelado"
            })

            emp_name = ev_obj.employee_name or "Colaborador"
            refuse_reply = (
                f"⚠️ *ATIVIDADE RECUSADA*\n\n"
                f"Entendido, *{emp_name}*. A recusa foi registrada no calendário do sistema para que a coordenação faça o remanejamento da atividade *\"{ev_obj.title}\"*."
            )
            try:
                await evolution_service.send_text_message(
                    instance_name=instance_name,
                    number=phone_number,
                    text=refuse_reply
                )
            except Exception as e:
                logger.error(f"Erro ao enviar resposta de recusa: {e}")

            return {"status": "success", "action": "task_refused", "event_id": ev_obj.id}

    # 3. Handle Task Completion Button from Employee
    is_task_completion = (
        btn_id.startswith("complete_task") or
        "sim, atividade concluída" in cleaned_txt or
        "sim, atividade concluida" in cleaned_txt or
        "concluído" in cleaned_txt or
        "concluido" in cleaned_txt or
        "✅ concluído" in cleaned_txt or
        "✅ concluido" in cleaned_txt or
        "concluir atividade" in cleaned_txt or
        "concluir tarefa" in cleaned_txt or
        "finalizar atividade" in cleaned_txt or
        "finalizar tarefa" in cleaned_txt or
        "tarefa concluida" in cleaned_txt or
        "tarefa concluída" in cleaned_txt or
        cleaned_txt in ["concluir", "concluido", "concluído", "pronto", "feito", "finalizar", "finalizado", "2"]
    )
    if is_task_completion and phone_number:
        event_id = None
        if "complete_task_" in btn_id:
            try:
                event_id = int(btn_id.replace("complete_task_", ""))
            except Exception:
                pass

        if event_id:
            ev_stmt = select(CalendarEvent).where(CalendarEvent.id == event_id)
        else:
            ev_stmt = (
                select(CalendarEvent)
                .where(
                    CalendarEvent.employee_phone.like(f"%{phone_number[-8:]}%"),
                    CalendarEvent.status.in_(["pendente", "em_progresso"])
                )
                .order_by(CalendarEvent.start_time.desc())
            )
        ev_res = await db.execute(ev_stmt)
        ev_obj = ev_res.scalars().first()

        if ev_obj:
            ev_obj.status = "concluido"
            ev_obj.atualizado_em = datetime.utcnow()
            await db.commit()
            await db.refresh(ev_obj)
            logger.info(f"Atividade #{ev_obj.id} finalizada como concluída pelo funcionário {phone_number}")

            await ws_manager.broadcast({
                "type": "CALENDAR_EVENT_UPDATED",
                "event_id": ev_obj.id,
                "status": "concluido"
            })

            emp_name = ev_obj.employee_name or "Colaborador"
            conf_reply = (
                f"🎉 *PARABÉNS! ATIVIDADE CONCLUÍDA COM SUCESSO!*\n\n"
                f"A atividade *\"{ev_obj.title}\"* foi finalizada e registrada como *Concluída* na agenda da empresa.\n\n"
                f"Obrigado pelo seu trabalho! 👏"
            )
            try:
                await evolution_service.send_text_message(
                    instance_name=instance_name,
                    number=phone_number,
                    text=conf_reply
                )
            except Exception as e:
                logger.error(f"Erro ao responder conclusão de tarefa: {e}")

            return {"status": "success", "action": "task_completed", "event_id": ev_obj.id}

    msg_type = MessageType.TEXTO
    # Check media payloads
    img_msg = message_obj.get("imageMessage")
    vid_msg = message_obj.get("videoMessage")
    aud_msg = message_obj.get("audioMessage")
    doc_msg = message_obj.get("documentMessage")
    stk_msg = message_obj.get("stickerMessage") or (message_obj.get("sticker") if isinstance(message_obj.get("sticker"), dict) else None)
    if not stk_msg and data.get("messageType") == "stickerMessage":
        stk_msg = message_obj

    msg_id = key.get("id", "") if isinstance(key, dict) else ""
    if msg_id:
        now_ts = datetime.utcnow().timestamp()
        if instance_name:
            existing_msg_stmt = (
                select(Message.id)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .join(WhatsAppNumber, Conversation.whatsapp_number_id == WhatsAppNumber.id)
                .where(
                    WhatsAppNumber.instancia_evolution_api == instance_name,
                    Message.whatsapp_msg_id == msg_id
                )
            )
        else:
            existing_msg_stmt = select(Message.id).where(Message.whatsapp_msg_id == msg_id)

        existing_msg_res = await db.execute(existing_msg_stmt)
        if existing_msg_res.scalars().first():
            logger.info(f"[DEDUPLICACAO DB] Mensagem '{msg_id}' para instância '{instance_name}' já gravada no banco. Descartando duplicata.")
            return {"status": "success", "action": "ignored_duplicate"}

    media_base64 = data.get("base64") or (data.get("media", {}).get("base64") if isinstance(data.get("media"), dict) else None)

    # Check location payload
    loc_msg = message_obj.get("locationMessage") or message_obj.get("liveLocationMessage")
    if loc_msg:
        msg_type = MessageType.LOCALIZACAO
        c_lat = loc_msg.get("degreesLatitude")
        c_lng = loc_msg.get("degreesLongitude")
        c_name = loc_msg.get("name") or loc_msg.get("address") or "Localização Compartilhada pelo Cliente"
        c_addr = loc_msg.get("address") or ""
        text_content = f"📍 *LOCALIZAÇÃO RECEBIDA DO CLIENTE*\n{c_name}\n{c_addr}\nhttps://maps.google.com/?q={c_lat},{c_lng}"

    # Check contact / vcard payload
    contact_msg = message_obj.get("contactMessage")
    contacts_arr_msg = message_obj.get("contactsArrayMessage")
    if contact_msg:
        c_vcard = contact_msg.get("vcard") or ""
        c_disp_name = contact_msg.get("displayName") or ""
        if not c_disp_name:
            fn_m = re.search(r"FN:(.+)", c_vcard)
            c_disp_name = fn_m.group(1).strip() if fn_m else "Contato"
        c_phone = ""
        if "waid=" in c_vcard:
            try:
                c_phone = c_vcard.split("waid=")[1].split(":")[0].split("\n")[0].strip()
            except Exception:
                pass
        if not c_phone and "TEL" in c_vcard:
            tel_m = re.findall(r"TEL[^:]*:(.+)", c_vcard)
            if tel_m:
                c_phone = tel_m[0].strip()
        text_content = f"[CONTATO]|{c_disp_name}|{c_phone}|{c_vcard}"

    elif contacts_arr_msg:
        c_list = contacts_arr_msg.get("contacts", [])
        items = []
        for c in c_list:
            c_vcard = c.get("vcard") or ""
            c_disp_name = c.get("displayName") or "Contato"
            c_phone = ""
            if "waid=" in c_vcard:
                try:
                    c_phone = c_vcard.split("waid=")[1].split(":")[0].split("\n")[0].strip()
                except Exception:
                    pass
            if not c_phone and "TEL" in c_vcard:
                tel_m = re.findall(r"TEL[^:]*:(.+)", c_vcard)
                if tel_m:
                    c_phone = tel_m[0].strip()
            items.append(f"{c_disp_name}:{c_phone}")
        text_content = f"[CONTATOS_MULTIPLOS]|" + ";".join(items)

    if (img_msg or vid_msg or aud_msg or doc_msg or stk_msg) and not media_base64 and msg_id:
        try:
            media_base64 = await evolution_service.get_media_base64(
                instance_name, msg_id, from_me=from_me, remote_jid=remote_jid, full_message=message_obj
            )
        except Exception as err:
            logger.error(f"Failed to fetch media base64 from Evolution API: {err}")

    msg_extra: Dict[str, Any] = {}
    if img_msg or vid_msg or aud_msg or doc_msg or stk_msg:
        caption = ""
        ext = ""
        media_bytes = None
        if media_base64:
            try:
                if "," in media_base64:
                    media_bytes = base64.b64decode(media_base64.split(",")[1])
                else:
                    media_bytes = base64.b64decode(media_base64)
            except Exception as e:
                logger.error(f"Error decoding incoming media base64: {e}")

        if stk_msg:
            msg_type = MessageType.IMAGEM
            caption = ""
            ext = ".webp"
        elif img_msg:
            msg_type = MessageType.IMAGEM
            caption = img_msg.get("caption") or ""
            ext = ".png"
        elif vid_msg:
            msg_type = MessageType.VIDEO
            caption = vid_msg.get("caption") or ""
            ext = ".mp4"
        elif aud_msg:
            msg_type = MessageType.AUDIO
            ext = ".ogg"
            aud_seconds = aud_msg.get("seconds") or aud_msg.get("duration") or 0
            if aud_seconds:
                msg_extra["seconds"] = int(aud_seconds)
                msg_extra["duration"] = int(aud_seconds)
            if media_bytes:
                # Transcrição adiada: só vamos transcrever se a conversa for com a IA (COM_IA)
                # para economizar tokens do Gemini, conforme estratégia do usuário.
                pass
        elif doc_msg:
            msg_type = MessageType.ARQUIVO
            caption = doc_msg.get("caption") or ""
            if caption and re.match(r'^\*👤 [^*]+:\*\s*$', caption.strip()):
                caption = ""
            doc_filename = doc_msg.get("fileName") or doc_msg.get("title") or "documento.pdf"
            ext = os.path.splitext(doc_filename)[1] or ".bin"
            msg_extra["original_filename"] = doc_filename
            msg_extra["file_name"] = doc_filename

        target_obj = stk_msg or img_msg or vid_msg or aud_msg or doc_msg or {}
        if target_obj.get("fileName"):
            msg_extra["original_filename"] = target_obj.get("fileName")
            msg_extra["file_name"] = target_obj.get("fileName")

        # If base64 is present, ALWAYS save file to disk using absolute path
        saved_media_url = None
        if media_bytes:
            try:
                upload_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads"))
                os.makedirs(upload_dir, exist_ok=True)
                unique_name = f"{uuid.uuid4().hex}{ext}"
                media_path = os.path.join(upload_dir, unique_name)
                with open(media_path, "wb") as f:
                    f.write(media_bytes)

                saved_media_url = f"/uploads/{unique_name}"
            except Exception as e:
                logger.error(f"Error saving incoming media file: {e}")

        if saved_media_url:
            if doc_msg:
                if caption and caption != doc_filename:
                    text_content = f"{saved_media_url}|{doc_filename}|{caption}"
                else:
                    text_content = f"{saved_media_url}|{doc_filename}"
            else:
                text_content = f"{saved_media_url}|{caption}" if caption else saved_media_url
        else:
            # Fallback to direct media URL if base64 decoding was not available
            fallback_url = target_obj.get("url") or target_obj.get("directPath") or ""
            if fallback_url:
                if doc_msg:
                    if caption and caption != doc_filename:
                        text_content = f"{fallback_url}|{doc_filename}|{caption}"
                    else:
                        text_content = f"{fallback_url}|{doc_filename}"
                else:
                    text_content = f"{fallback_url}|{caption}" if caption else fallback_url
            elif caption:
                text_content = caption
            elif stk_msg:
                text_content = "[Figurinha do WhatsApp]"
            elif img_msg or vid_msg or aud_msg or doc_msg:
                text_content = "[Mídia não carregada ou formato não suportado]"

    if not text_content:
        return {"status": "ignored", "reason": "Non-text or empty message payload"}

    # 1. Identify WhatsAppNumber & Tenant
    wn_stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.instancia_evolution_api == instance_name,
        WhatsAppNumber.status == True
    )
    wn_res = await db.execute(wn_stmt)
    whatsapp_number = wn_res.scalar_one_or_none()

    if not whatsapp_number:
        logger.warning(f"No active WhatsAppNumber found for instance '{instance_name}'")
        return {"status": "error", "message": "Instance not mapped to any tenant"}

    tenant_id = whatsapp_number.tenant_id

    # 2. Get or Create Contact (matching exact phone, 8/9 digit variants or group JID)
    if is_group:
        group_raw = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
        contact_stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            (Contact.telefone == phone_number) |
            (Contact.telefone == remote_jid) |
            (Contact.telefone == group_raw) |
            (Contact.telefone == f"{group_raw}@g.us")
        )
    else:
        phone_variants = [phone_number]
        if len(phone_number) == 13 and phone_number.startswith("55"):
            phone_variants.append(phone_number[:4] + phone_number[5:])
        elif len(phone_number) == 12 and phone_number.startswith("55"):
            phone_variants.append(phone_number[:4] + "9" + phone_number[4:])

        # Exclude groups from individual phone matching!
        phone_match = Contact.telefone.in_(phone_variants) | (Contact.telefone.like(f"%{phone_number[-8:]}%") if len(phone_number) >= 8 else False)
        if original_lid and original_lid != phone_number:
            phone_match = phone_match | (Contact.telefone == original_lid)

        contact_stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.telefone.notlike("%@g.us%"),
            Contact.telefone.notlike("%-%"),
            Contact.telefone.notlike("120363%"),
            phone_match
        )

    contact_res = await db.execute(contact_stmt)
    contact = contact_res.scalars().first()

    sender_obj = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    contact_obj = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    profile_pic_url = (
        data.get("profilePicUrl") or
        data.get("pictureUrl") or
        data.get("profilePictureUrl") or
        data.get("picture") or
        sender_obj.get("profilePicUrl") or
        sender_obj.get("profilePictureUrl") or
        sender_obj.get("pictureUrl") or
        contact_obj.get("profilePicUrl") or
        contact_obj.get("profilePictureUrl") or
        contact_obj.get("pictureUrl")
    )

    # If message is from a WhatsApp Group, fetch official group subject / title
    group_subject = None
    if is_group:
        # 1. First check WhatsAppGroup table for official name
        raw_jid_clean = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
        g_tbl_stmt = select(WhatsAppGroup).where(
            WhatsAppGroup.tenant_id == tenant_id,
            (WhatsAppGroup.group_jid == remote_jid) |
            (WhatsAppGroup.group_jid == f"{raw_jid_clean}@g.us") |
            (WhatsAppGroup.group_jid.like(f"%{raw_jid_clean}%"))
        )
        g_tbl_res = await db.execute(g_tbl_stmt)
        g_tbl_obj = g_tbl_res.scalars().first()
        if g_tbl_obj and g_tbl_obj.nome:
            group_subject = g_tbl_obj.nome

        if not group_subject:
            group_subject = (
                data.get("groupName") or
                data.get("groupSubject") or
                data.get("subject")
            )
        try:
            if not group_subject or group_subject.lower() in ["none", "null", "undefined", "grupo whatsapp"]:
                g_info = await asyncio.wait_for(
                    evolution_service.fetch_group_info(whatsapp_number.instancia_evolution_api, remote_jid),
                    timeout=2.0
                )
                if g_info and isinstance(g_info, dict):
                    fetched_subj = g_info.get("subject") or g_info.get("name")
                    if fetched_subj and fetched_subj.lower() not in ["none", "null", "undefined"]:
                        group_subject = fetched_subj
                    if g_info.get("pictureUrl"):
                        profile_pic_url = g_info.get("pictureUrl")
        except Exception:
            pass

    if not profile_pic_url and (not contact or not contact.foto_perfil_url) and whatsapp_number.instancia_evolution_api:
        try:
            profile_pic_url = await asyncio.wait_for(
                evolution_service.fetch_profile_picture_url(whatsapp_number.instancia_evolution_api, phone_number),
                timeout=5.0
            )
        except Exception:
            profile_pic_url = None

    clean_push_name = sanitize_customer_name(push_name) if push_name else "Cliente"
    if not contact:
        # Check if an existing contact can be matched by pushName before creating a duplicate
        if clean_push_name and clean_push_name not in ["Cliente", "WhatsApp", "WhatsApp Business"] and not is_group:
            nm_stmt = select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.telefone.notlike("%@g.us%"),
                Contact.telefone.notlike("%-%"),
                Contact.telefone.notlike("120363%"),
                Contact.nome.ilike(clean_push_name)
            )
            nm_res = await db.execute(nm_stmt)
            matched_by_name = nm_res.scalars().first()
            if matched_by_name:
                contact = matched_by_name
                # If incoming phone is real and contact had a LID, update phone
                if len(phone_number) in [10, 11, 12, 13] and (len(contact.telefone or "") >= 14 or "lid" in str(contact.telefone)):
                    contact.telefone = phone_number

    def _format_contact_display(p: str) -> str:
        clean = "".join(filter(str.isdigit, p))
        if len(clean) == 13 and clean.startswith("55"):
            return f"+{clean[:2]} {clean[2:4]} {clean[4:9]}-{clean[9:]}"
        elif len(clean) == 12 and clean.startswith("55"):
            return f"+{clean[:2]} {clean[2:4]} {clean[4:8]}-{clean[8:]}"
        elif len(clean) in [10, 11]:
            return f"+55 {clean[:2]} {clean[2:7]}-{clean[7:]}" if len(clean) == 11 else f"+55 {clean[:2]} {clean[2:6]}-{clean[6:]}"
        return f"+{clean}" if clean.startswith("55") else clean

    BUSINESS_NAMES = {"servweld", "servsolda", "assistência técnica", "assistencia tecnica", "vendas", "locação", "locacao", "financeiro", "atendente", "você", "voce", "admin"}
    formatted_phone_display = _format_contact_display(phone_number)

    if not contact:
        initial_name = group_subject if is_group else (
            clean_push_name if clean_push_name and clean_push_name not in ["Cliente", "WhatsApp", "WhatsApp Business"] and not any(b in clean_push_name.lower() for b in BUSINESS_NAMES)
            else formatted_phone_display
        )
        if is_group and not initial_name:
            initial_name = "Grupo WhatsApp"
        extra_c = {"is_group": True} if is_group else {}
        contact = Contact(tenant_id=tenant_id, telefone=phone_number, nome=initial_name, foto_perfil_url=profile_pic_url, dados_adicionais=extra_c)
        db.add(contact)
        await db.flush()
    else:
        if is_group:
            extra_c = dict(contact.dados_adicionais or {})
            extra_c["is_group"] = True
            contact.dados_adicionais = extra_c
            contact.telefone = phone_number
            # CRITICAL RULE: NEVER overwrite group name with participant name or message!
            if group_subject and group_subject.lower() not in ["grupo whatsapp", "none", "null", "undefined", "cliente", (clean_push_name or "").lower()]:
                contact.nome = group_subject
        else:
            # Upgrade phone if contact had a LID and we now have a real number
            if len(phone_number) in [10, 11, 12, 13] and (len(contact.telefone or "") >= 14 or "lid" in str(contact.telefone)):
                old_lid = "".join(filter(str.isdigit, str(contact.telefone or "")))
                contact.telefone = phone_number
                if old_lid:
                    extra_c = dict(contact.dados_adicionais or {})
                    extra_c["lid"] = old_lid
                    contact.dados_adicionais = extra_c
                logger.info(f"[LID RESOLVIDO] Contato #{contact.id} atualizado de '{old_lid}' para o número real '{phone_number}'")
        # For individual contacts: update pushName if name is generic, empty, or phone number, OR contains business name
        if not (contact.dados_adicionais or {}).get("custom_name_locked"):
            GENERIC_NAMES = {"cliente", "cliente whatsapp", "cliente whatsapp business", "whatsapp", "whatsapp business"}
            cur_n = str(contact.nome or "").strip().lower()
            is_business_name = any(b in cur_n for b in BUSINESS_NAMES)
            is_generic = (
                not cur_n or
                cur_n in GENERIC_NAMES or
                is_business_name or
                cur_n.startswith("contato ") or
                cur_n.startswith("+55") or
                cur_n.startswith("55") or
                cur_n.replace("+", "").replace("-", "").replace(" ", "").isdigit()
            )
            if clean_push_name and clean_push_name.lower() not in GENERIC_NAMES and not any(b in clean_push_name.lower() for b in BUSINESS_NAMES) and is_generic:
                contact.nome = clean_push_name
            elif is_business_name:
                contact.nome = formatted_phone_display

    # Avatar handling for both new and existing contacts
    if profile_pic_url and not (contact.foto_perfil_url or "").startswith("/uploads/avatars/"):
        cached_avatar = await download_and_cache_avatar_locally(contact.id, profile_pic_url)
        if cached_avatar:
            contact.foto_perfil_url = cached_avatar
        elif contact.foto_perfil_url != profile_pic_url:
            contact.foto_perfil_url = profile_pic_url
    elif not contact.foto_perfil_url and phone_number and not is_group and whatsapp_number.instancia_evolution_api:
        asyncio.create_task(
            evolution_service.fetch_and_update_contact_avatar(
                contact.id, whatsapp_number.instancia_evolution_api, phone_number
            )
        )

    # 3. Get or Create Conversation (strictly isolated per instance/department to prevent mixing)
    conv_stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
            Conversation.whatsapp_number_id == whatsapp_number.id,
            Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO])
        )
        .order_by(Conversation.ultima_interacao_em.desc())
    )
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalars().first()

    if not conversation:
        # Also check if there is an existing conversation for this contact on THIS specific instance to reopen
        any_conv_stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.contact_id == contact.id,
                Conversation.whatsapp_number_id == whatsapp_number.id
            )
            .order_by(Conversation.ultima_interacao_em.desc())
        )
        any_conv_res = await db.execute(any_conv_stmt)
        conversation = any_conv_res.scalars().first()

        if conversation:
            if conversation.status in [
                ConversationStatus.ENCERRADA,
                ConversationStatus.EXPIRADA_POR_INATIVIDADE,
                ConversationStatus.ENCERRADA_FORA_EXPEDIENTE
            ]:
                # CSAT Recognition: Check if customer is answering the satisfaction survey (1 to 5)
                clean_txt = (text_content or "").strip()
                csat_match = re.match(r"^(?:nota\s*)?([1-5])(?:\s*(?:estrelas?|⭐))?$", clean_txt, re.IGNORECASE)
                
                sorted_msgs = sorted(conversation.messages or [], key=lambda m: m.timestamp or datetime.min)
                had_csat_survey = any("Como você avalia" in (m.conteudo or "") or "Pesquisa" in (m.conteudo or "") or "Atendimento Finalizado" in (m.conteudo or "") for m in sorted_msgs[-4:]) if sorted_msgs else False

                if csat_match or (had_csat_survey and clean_txt in ["1", "2", "3", "4", "5"]):
                    score = int(csat_match.group(1)) if csat_match else int(clean_txt)
                    extra = dict(conversation.dados_adicionais or {})
                    extra["csat_score"] = score
                    extra["csat_received_at"] = datetime.utcnow().isoformat()
                    conversation.dados_adicionais = extra
                    
                    # Record the customer's CSAT score message in chat
                    user_msg = Message(
                        conversation_id=conversation.id,
                        remetente=MessageSender.CLIENTE,
                        conteudo=text_content,
                        tipo=msg_type,
                        status="read",
                        whatsapp_msg_id=msg_id if msg_id else None,
                        timestamp=datetime.utcnow()
                    )
                    db.add(user_msg)

                    # Add system confirmation message in chat
                    sys_msg = Message(
                        conversation_id=conversation.id,
                        remetente="sistema",
                        conteudo=f"⭐ Nota de Satisfação CSAT registrada: {score}/5 estrelas.",
                        tipo=MessageType.TEXTO,
                        timestamp=datetime.utcnow()
                    )
                    db.add(sys_msg)
                    await db.commit()

                    # Send thank-you message back on WhatsApp without reopening conversation
                    if whatsapp_number and whatsapp_number.instancia_evolution_api:
                        try:
                            await evolution_service.send_text_message(
                                instance_name=whatsapp_number.instancia_evolution_api,
                                number=phone_number,
                                text=f"🙏 Agradecemos pela sua avaliação ({score}/5 estrelas)! Sua opinião nos ajuda a melhorar nossos serviços continuamente."
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send CSAT thank you: {e}")

                    # Broadcast WS update
                    await ws_manager.broadcast_to_department(
                        tenant_id=tenant_id,
                        whatsapp_number_id=whatsapp_number.id,
                        message_data={
                            "type": "CSAT_RECEIVED",
                            "conversation_id": conversation.id,
                            "score": score
                        }
                    )

                    return {
                        "status": "success",
                        "message": f"CSAT score {score} recorded successfully without reopening conversation."
                    }

                # Otherwise, customer sent a new message -> ALWAYS generate a NEW daily protocol!
                prev_proto = conversation.protocol_number
                last_time = conversation.ultima_interacao_em or datetime.utcnow()
                hours_diff = (datetime.utcnow() - last_time).total_seconds() / 3600.0

                new_proto = await generate_daily_protocol(db, tenant_id)
                conversation.status = ConversationStatus.COM_IA
                conversation.protocol_number = new_proto
                conversation.assigned_user_id = None

                extra = dict(conversation.dados_adicionais or {})
                extra["reopened_at"] = datetime.utcnow().isoformat()
                extra["previous_protocol_number"] = prev_proto
                extra["reopened_within_5_days"] = (hours_diff <= 120.0)
                conversation.dados_adicionais = extra
            conversation.whatsapp_number_id = whatsapp_number.id
        else:
            proto = await generate_daily_protocol(db, tenant_id)
            conversation = Conversation(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                contact_id=contact.id,
                protocol_number=proto,
                status=ConversationStatus.COM_IA,
                assunto_atual="Atendimento Concierge"
            )
            db.add(conversation)
            await db.flush()

    # Check if contact is an authorized technician or system admin
    is_tech, tech_name = await check_is_authorized_technician_or_admin(db, tenant_id, phone_number)
    if is_tech:
        conversation.protocol_number = None
    elif not conversation.protocol_number:
        conversation.protocol_number = await generate_daily_protocol(db, tenant_id)

    # Reset inactivity warning flags and restart timer
    extra = dict(conversation.dados_adicionais or {})
    extra["inactivity_warning_10m_sent"] = False
    extra["inactivity_warning_5m_sent"] = False
    conversation.dados_adicionais = extra
    conversation.ultima_interacao_em = datetime.utcnow()

    # Check if incoming message is from another internal WhatsApp number of the company
    all_tenant_numbers_stmt = select(WhatsAppNumber.numero).where(WhatsAppNumber.tenant_id == tenant_id)
    all_tenant_numbers_res = await db.execute(all_tenant_numbers_stmt)
    tenant_phones = [
        "".join(filter(str.isdigit, str(p))) for p in all_tenant_numbers_res.scalars().all() if p
    ]

    is_internal_company_number = False
    for tp in tenant_phones:
        if tp and (phone_number == tp or (len(phone_number) >= 8 and len(tp) >= 8 and phone_number[-8:] == tp[-8:])):
            is_internal_company_number = True
            break

    is_bot_echo = (
        "*🤖 IA Concierge:*" in text_content or
        "🤖" in text_content or
        "Protocolo de Atendimento:" in text_content or
        "Protocolo:" in text_content or
        "DADOS OFICIAIS PARA PAGAMENTO VIA PIX" in text_content or
        "RESUMO DE ONBOARDING" in text_content or
        "Resumo de Onboarding" in text_content or
        "equipe especialista dar continuidade" in text_content or
        "Seja bem-vindo(a) à" in text_content or
        ("Servweld" in text_content and "GPS" in text_content) or
        ("SOF Q 5" in text_content and "71215-226" in text_content) or
        is_bot_or_menu_message(text_content)
    )

    # 4. If message was sent from mobile cellphone by attendant/staff (fromMe: True)
    if from_me:
        # Echo Shield: Never record bot/system replies as human attendant messages!
        if is_bot_echo:
            logger.info(f"[ECHO ESCUDO] Mensagem com fromMe:True é eco do próprio robô/IA ('{text_content[:60]}...'). Descartando para não atribuir a atendente.")
            if msg_id:
                try:
                    bot_msg_stmt = (
                        select(Message)
                        .where(
                            Message.conversation_id == conversation.id,
                            Message.remetente.in_([MessageSender.IA, "ia", "sistema"]),
                            Message.whatsapp_msg_id == None
                        )
                        .order_by(Message.id.desc())
                    )
                    b_res = await db.execute(bot_msg_stmt)
                    b_msg = b_res.scalars().first()
                    if b_msg:
                        b_msg.whatsapp_msg_id = msg_id
                        await db.commit()
                except Exception as link_err:
                    logger.debug(f"Não foi possível vincular whatsapp_msg_id ao bot: {link_err}")
            return {"status": "success", "action": "bot_echo_ignored"}

        # Check if this outgoing message is already recorded in the database
        if msg_id:
            existing_outgoing_stmt = select(Message.id).where(Message.whatsapp_msg_id == msg_id)
            existing_outgoing_res = await db.execute(existing_outgoing_stmt)
            if existing_outgoing_res.scalars().first():
                logger.info(f"[OUTGOING DEDUP] Mensagem '{msg_id}' já gravada no sistema. Descartando duplicata.")
                return {"status": "success", "action": "ignored_duplicate"}

        # Check if an attendant message was sent recently (last 60s) with matching text
        clean_text_compare = re.sub(r'^\*👤 [^*]+:\*\n\n?', '', text_content).strip().rstrip('\u200b')
        recent_cutoff = datetime.utcnow() - timedelta(seconds=60)
        # IA/SISTEMA senders are included here too: the dedicated bot-echo shield above only
        # catches known phrase markers (see is_bot_echo), so a freeform AI reply without those
        # markers would otherwise fall through to here, find no match among ATENDENTE-only rows,
        # and get re-inserted as a second, duplicate message on screen.
        recent_att_stmt = select(Message).where(
            Message.conversation_id == conversation.id,
            Message.remetente.in_([MessageSender.ATENDENTE, "atendente", MessageSender.IA, "ia", MessageSender.SISTEMA, "sistema"]),
            Message.timestamp >= recent_cutoff
        ).order_by(Message.id.desc())
        recent_att_res = await db.execute(recent_att_stmt)
        matched_existing = None
        is_media_type = msg_type not in [MessageType.TEXTO, "texto"]

        for r_msg in recent_att_res.scalars().all():
            r_c = (r_msg.conteudo or "").strip().rstrip('\u200b')
            r_c_clean = re.sub(r'^\*👤 [^*]+:\*\n\n?', '', r_c).strip().rstrip('\u200b')

            # Extract captions if media format: "/uploads/xyz.ext|Caption"
            cap_existing = r_c_clean.split("|", 1)[1].strip() if "|" in r_c_clean else ""
            cap_webhook = clean_text_compare.split("|", 1)[1].strip() if "|" in clean_text_compare else ""

            # IMPORTANT: text-content matching must only link this webhook echo to an
            # existing message that is still unlinked (whatsapp_msg_id is None, i.e. it was
            # optimistically saved when dispatched from the panel and is awaiting its real
            # WhatsApp id). Without this guard, sending the same/similar text twice in a row
            # (e.g. from the attendant's own phone) makes the second, genuinely distinct
            # message get discarded as a "duplicate" of the first one, which already has its
            # own whatsapp_msg_id \u2014 causing real messages to silently vanish from the panel.
            text_match = (
                (msg_id and r_msg.whatsapp_msg_id == msg_id) or
                (r_msg.whatsapp_msg_id is None and (
                    r_c == clean_text_compare or
                    r_c_clean == clean_text_compare or
                    r_c == text_content.strip().rstrip('\u200b') or
                    clean_text_compare in r_c or r_c in clean_text_compare
                ))
            )

            # Media match: same media type or media file sent recently by attendant from web panel
            media_match = False
            if is_media_type or "/uploads/" in text_content or text_content.startswith("/uploads/"):
                if r_msg.tipo != MessageType.TEXTO or "/uploads/" in (r_msg.conteudo or ""):
                    if not r_msg.whatsapp_msg_id or r_msg.whatsapp_msg_id == msg_id:
                        media_match = True

            if text_match or media_match:
                matched_existing = r_msg
                break

        if matched_existing:
            logger.info(f"[OUTGOING DEDUP] Mensagem #{matched_existing.id} enviada via painel já existe na conversa #{conversation.id}. Vinculando whatsapp_msg_id '{msg_id}' e ignorando duplicata.")
            if msg_id and not matched_existing.whatsapp_msg_id:
                matched_existing.whatsapp_msg_id = msg_id
                await db.commit()
            return {"status": "success", "action": "ignored_duplicate"}

        # If it genuinely came from the mobile device directly, strip any prefix if present
        clean_outgoing_text = re.sub(r'^\*👤 [^*]+:\*\n\n?', '', text_content).strip().rstrip('\u200b') if text_content.startswith('*👤 ') else text_content
        clean_outgoing_text = re.sub(r'\|\*👤 [^*]+:\*$', '', clean_outgoing_text).strip()

        # Prevent media from being marked as plain text if it contains an uploads URL
        if "/uploads/" in clean_outgoing_text or "http" in clean_outgoing_text:
            c_low = clean_outgoing_text.lower()
            if ".pdf" in c_low:
                msg_type = MessageType.ARQUIVO
            elif any(e in c_low for e in [".png", ".jpg", ".jpeg", ".webp"]):
                msg_type = MessageType.IMAGEM
            elif any(e in c_low for e in [".mp4", ".mov", ".avi"]):
                msg_type = MessageType.VIDEO
            elif any(e in c_low for e in [".ogg", ".mp3", ".wav", ".m4a"]):
                msg_type = MessageType.AUDIO
        agent_extracted_name = None
        m_agent = re.match(r'^\*👤\s*([^:*]+):?\*', text_content)
        if m_agent:
            agent_extracted_name = m_agent.group(1).strip()

        quote_data = parse_quoted_context(data, from_me=True, contact_name=contact.nome)
        attendant_msg_extra = {}
        if agent_extracted_name:
            attendant_msg_extra["agent_name"] = agent_extracted_name
        if quote_data:
            if quote_data.get("stanza_id"):
                p_stmt = select(Message).where(Message.whatsapp_msg_id == quote_data["stanza_id"])
                p_msg = (await db.execute(p_stmt)).scalars().first()
                if p_msg:
                    quote_data["message_id"] = p_msg.id
                    if p_msg.remetente in [MessageSender.ATENDENTE, "atendente"]:
                        quote_data["sender_name"] = "Você"
                    else:
                        quote_data["sender_name"] = contact.nome or "Cliente"
                    if not quote_data.get("text") and p_msg.conteudo:
                        quote_data["text"] = p_msg.conteudo[:120]
            attendant_msg_extra["quoted_message"] = quote_data

        msg_dt = extract_message_datetime(data)
        attendant_msg = Message(
            conversation_id=conversation.id,
            remetente=MessageSender.ATENDENTE,
            conteudo=clean_outgoing_text,
            tipo=msg_type,
            status="read",
            whatsapp_msg_id=msg_id if msg_id else None,
            dados_adicionais=attendant_msg_extra if attendant_msg_extra else None,
            timestamp=msg_dt
        )
        db.add(attendant_msg)
        conversation.ultima_interacao_em = max(conversation.ultima_interacao_em or msg_dt, msg_dt)
        conversation.status = ConversationStatus.COM_HUMANO
        extra = dict(conversation.dados_adicionais or {})
        extra["marked_as_read"] = True
        extra["pending_dismissed"] = True
        conversation.dados_adicionais = extra
        flag_modified(conversation, "dados_adicionais")
        await db.commit()

        # Broadcast attendant mobile message via WebSockets to agents
        await ws_manager.broadcast_to_department(
            tenant_id=tenant_id,
            whatsapp_number_id=whatsapp_number.id,
            message_data={
                "type": "NEW_MESSAGE",
                "conversation_id": conversation.id,
                "remetente": MessageSender.ATENDENTE.value,
                "conteudo": text_content,
                "dados_adicionais": attendant_msg.dados_adicionais,
                "timestamp": attendant_msg.timestamp.isoformat() + "Z" if hasattr(attendant_msg.timestamp, "isoformat") else str(attendant_msg.timestamp),
                "contact_name": contact.nome,
                "contact_phone": contact.telefone,
                "department": whatsapp_number.nome_departamento
            }
        )
        logger.info(f"[OUTGOING MOBILE SYNC] Mensagem/Foto enviada pelo celular sincronizada na conversa #{conversation.id} ({contact.nome})")

        # Honor a pending OS Handler confirmation (PDF terms / orçamento approval) even when
        # the reply arrives via this "attendant's own linked phone" sync path instead of a
        # genuine inbound customer message. This matters in practice: testing a conversation
        # by typing directly from the business's own logged-in WhatsApp session (instead of
        # from the customer's own number) makes Baileys report it as fromMe:true - reported
        # directly: a "Sim" typed this way was silently dropped because the confirmation
        # check below only ran on the inbound-customer code path. An attendant relaying a
        # verbal "sim"/"não" from a customer on a phone call is the same real scenario.
        pending_marker = conversation.assunto_atual or ""
        if pending_marker.startswith("CONFIRM_OS_PDF:"):
            from app.services.automation_service import automation_service
            pending_file_rel_path = pending_marker.split(":", 1)[1]
            classification = automation_service.classify_yes_no_reply(text_content)
            logger.info(f"[OS HANDLER PDF] (via mobile sync) Classificação de '{text_content}': {classification}")
            if classification == "CONFIRMA":
                conversation.assunto_atual = "Atendimento Concierge"
                await db.commit()
                asyncio.create_task(
                    send_os_pdf_after_confirmation(
                        tenant_id=tenant_id, conversation_id=conversation.id,
                        whatsapp_number_id=whatsapp_number.id, instance_name=instance_name,
                        recipient_phone=contact.telefone, pdf_relative_path=pending_file_rel_path
                    )
                )
            elif classification == "NEGA":
                conversation.assunto_atual = "Atendimento Concierge"
                await db.commit()
            # AMBIGUA: leave the marker pending, don't send anything new here - the customer's
            # own next reply (not this synced attendant one) is what should be re-prompted.
            return {"status": "success", "action": "synced_attendant_mobile_message", "os_handler": "pdf_confirmation_handled"}

        if pending_marker.startswith("CONFIRM_OS_APPROVAL:"):
            from app.services.automation_service import automation_service
            parts = pending_marker.split(":", 1)[1].split("|")
            os_numero = parts[0] if len(parts) > 0 else "?"
            pdf_rel_path = parts[1] if len(parts) > 1 else ""
            tecnico_phone = parts[2] if len(parts) > 2 and parts[2] else None
            classification = automation_service.classify_yes_no_reply(text_content)
            logger.info(f"[OS HANDLER APROVAÇÃO] (via mobile sync) Classificação de '{text_content}' para O.S. #{os_numero}: {classification}")
            if classification in ("CONFIRMA", "NEGA"):
                aprovado = classification == "CONFIRMA"
                conversation.assunto_atual = "Atendimento Concierge"
                await db.commit()
                asyncio.create_task(
                    notify_os_approval_result(
                        tenant_id=tenant_id, conversation_id=conversation.id,
                        whatsapp_number_id=whatsapp_number.id, instance_name=instance_name,
                        os_numero=os_numero, client_name=contact.nome or "Cliente",
                        aprovado=aprovado, pdf_relative_path=pdf_rel_path, tecnico_phone=tecnico_phone
                    )
                )
            return {"status": "success", "action": "synced_attendant_mobile_message", "os_handler": "approval_handled"}

        # Trigger Smart Automation Engine (OS Handler & Custom Rules) for attendant message.
        # Never in groups: this path is independent of the group shield further down, so an
        # attendant message from their own phone into a group could otherwise still trigger
        # an automated reply (e.g. Pix) posted back into the group.
        if not is_group:
            from app.services.automation_service import automation_service
            asyncio.create_task(
                automation_service.process_and_dispatch_automation(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    message_text=text_content,
                    from_me=True,
                    contact_name=contact.nome if contact else "Cliente",
                    instance_name=instance_name,
                    recipient_phone=contact.telefone if contact else ""
                )
            )
        return {"status": "success", "action": "synced_attendant_mobile_message"}

    # 4. Save Customer Message with WhatsApp Message ID (status received/unread)
    extra_conv = dict(conversation.dados_adicionais or {})
    extra_conv["marked_as_read"] = False
    extra_conv["pending_dismissed"] = False
    extra_conv["aviso_1_enviado"] = False
    extra_conv["aviso_2_enviado"] = False
    extra_conv["inactivity_warning_30m_sent"] = False
    extra_conv["inactivity_warning_10m_sent"] = False
    extra_conv["inactivity_warning_5m_sent"] = False
    conversation.dados_adicionais = extra_conv
    flag_modified(conversation, "dados_adicionais")

    msg_extra = dict(msg_extra or {})
    quote_data = parse_quoted_context(data, from_me=False, contact_name=contact.nome)
    if quote_data:
        if quote_data.get("stanza_id"):
            p_stmt = select(Message).where(Message.whatsapp_msg_id == quote_data["stanza_id"])
            p_msg = (await db.execute(p_stmt)).scalars().first()
            if p_msg:
                quote_data["message_id"] = p_msg.id
                if p_msg.remetente in [MessageSender.ATENDENTE, "atendente"]:
                    quote_data["sender_name"] = "Você"
                else:
                    quote_data["sender_name"] = contact.nome or "Cliente"
                if not quote_data.get("text") and p_msg.conteudo:
                    quote_data["text"] = p_msg.conteudo[:120]
        msg_extra["quoted_message"] = quote_data

    if is_group:
        msg_extra["participant_name"] = participant_name
        msg_extra["participant_phone"] = "".join(filter(str.isdigit, str(participant_jid or sender_jid)))
        msg_extra["participant"] = str(participant_jid or sender_jid)
        msg_extra["is_group"] = True

    # Extract WhatsApp OpenGraph Link Preview metadata if present
    ext_msg = message_obj.get("extendedTextMessage")
    if ext_msg and isinstance(ext_msg, dict):
        preview_title = ext_msg.get("title")
        preview_desc = ext_msg.get("description")
        preview_thumb = ext_msg.get("jpegThumbnail")
        preview_url = ext_msg.get("matchedText") or ext_msg.get("canonicalUrl")
        if preview_title or preview_thumb or preview_desc:
            thumb_url = None
            if preview_thumb:
                thumb_url = f"data:image/jpeg;base64,{preview_thumb}" if not str(preview_thumb).startswith("data:") else preview_thumb
            msg_extra["link_preview"] = {
                "url": preview_url,
                "title": preview_title,
                "description": preview_desc,
                "image": thumb_url
            }

    # Lazy audio transcription: only transcribe if AI is going to answer (COM_IA) and not in a group
    if msg_type == MessageType.AUDIO and media_bytes and conversation.status == ConversationStatus.COM_IA and not is_group and not is_internal_company_number and not is_bot_echo:
        try:
            dec_sets = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
            audio_transcription = await gemini_service.process_audio_message(
                audio_bytes=media_bytes,
                mime_type="audio/ogg",
                tenant_gemini_api_key=dec_sets.get("gemini_api_key"),
                tenant_gemini_model_name=dec_sets.get("gemini_model_name")
            )
            if audio_transcription:
                new_caption = f"🎙️ *Transcrição do Áudio:*\n_{audio_transcription}_"
                if saved_media_url:
                    text_content = f"{saved_media_url}|{new_caption}"
                else:
                    target_obj = message_obj.get("audioMessage") or {}
                    fallback_url = target_obj.get("url") or target_obj.get("directPath") or ""
                    if fallback_url:
                        text_content = f"{fallback_url}|{new_caption}"
                    else:
                        text_content = new_caption
        except Exception as audio_err:
            logger.error(f"Error transcribing customer audio note lazily: {audio_err}")

    msg_dt = extract_message_datetime(data)

    # Ensure customer message is not already saved in database for this msg_id
    if msg_id:
        chk_stmt = select(Message.id).where(Message.whatsapp_msg_id == msg_id)
        chk_res = await db.execute(chk_stmt)
        if chk_res.scalars().first():
            logger.info(f"[DB DEDUP] Mensagem cliente '{msg_id}' já gravada no banco. Ignorando inserção duplicada.")
            return {"status": "success", "action": "ignored_duplicate"}

    user_msg = Message(
        conversation_id=conversation.id,
        remetente=MessageSender.CLIENTE,
        conteudo=text_content,
        tipo=msg_type,
        status="received",
        whatsapp_msg_id=msg_id if msg_id else None,
        dados_adicionais=msg_extra if msg_extra else None,
        timestamp=msg_dt
    )
    db.add(user_msg)
    conversation.ultima_interacao_em = max(conversation.ultima_interacao_em or msg_dt, msg_dt)
    await db.commit()

    # Send Read Receipt to WhatsApp (blue ticks simulation)
    if msg_id and instance_name:
        try:
            target_jid = str(remote_jid) if "@" in str(remote_jid) else f"{phone_number}@s.whatsapp.net"
            await evolution_service.mark_message_as_read(
                instance_name=instance_name,
                message_id=msg_id,
                remote_jid=target_jid
            )
        except Exception as read_err:
            logger.debug(f"[ANTI-BAN] Failed to send read receipt: {read_err}")

    # Broadcast customer message via WebSockets to agents
    await ws_manager.broadcast_to_department(
        tenant_id=tenant_id,
        whatsapp_number_id=whatsapp_number.id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conversation.id,
            "id": user_msg.id,
            "remetente": MessageSender.CLIENTE.value,
            "conteudo": text_content,
            "dados_adicionais": user_msg.dados_adicionais,
            "tipo": user_msg.tipo.value if hasattr(user_msg.tipo, "value") else str(user_msg.tipo),
            "timestamp": user_msg.timestamp.isoformat() + "Z",
            "contact_name": contact.nome,
            "contact_phone": contact.telefone,
            "department": whatsapp_number.nome_departamento
        }
    )

    # Trigger Smart Automation Engine for customer incoming message (never in groups —
    # this fires independently of the AI/Gemini flow below, so the group shield further
    # down does NOT cover it; skip it here too or automated replies like Pix leak into groups)
    if not is_group and not is_internal_company_number and not is_bot_echo:
        from app.services.automation_service import automation_service
        asyncio.create_task(
            automation_service.process_and_dispatch_automation(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_text=text_content,
                from_me=False,
                contact_name=contact.nome if contact else "Cliente",
                instance_name=instance_name,
                recipient_phone=contact.telefone if contact else ""
            )
        )

    # Internal Number / Bot Echo / Group Shield: Never run AI if sender is another internal phone, bot, or a Group
    if is_group or is_internal_company_number or is_bot_echo:
        if is_group:
            logger.info(f"[GROUP SHIELD] Mensagem de grupo detectada ({phone_number}). Silenciando IA para evitar spam e economizar tokens.")
        else:
            logger.info(f"[ANTI-LOOP ESCUDO] Mensagem de número interno ({phone_number}) ou eco de bot detectado. Silenciando IA.")
        
        if conversation.status == ConversationStatus.COM_IA:
            conversation.status = ConversationStatus.COM_HUMANO
            
        await db.commit()
        return {"status": "success", "action": "group_or_bot_silenced"}

    # Check if conversation is handled by human attendant (or has had attendant interaction)
    att_stmt = select(Message.id).where(
        Message.conversation_id == conversation.id,
        Message.remetente.in_([MessageSender.ATENDENTE, "atendente"])
    ).limit(1)
    att_res = await db.execute(att_stmt)
    has_attendant_messages = att_res.scalars().first() is not None
    is_human_handled = (
        conversation.status == ConversationStatus.COM_HUMANO or
        conversation.assigned_user_id is not None or
        has_attendant_messages
    )

    if is_human_handled:
        text_lower = (text_content or "").lower()
        explicit_ai_keywords = ["falar com ia", "reativar ia", "chamar ia", "iniciar ia", "menu ia"]
        is_explicit_ai = any(k in text_lower for k in explicit_ai_keywords)

        if is_explicit_ai:
            conversation.status = ConversationStatus.COM_IA
            conversation.assigned_user_id = None
            logger.info(f"[IA REATIVADA EXPLICITAMENTE] Conversa {conversation.id} com {contact.nome or contact.telefone} reativada para COM_IA a pedido do cliente.")
            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                message_data={
                    "type": "STATUS_CHANGE",
                    "conversation_id": conversation.id,
                    "status": "com_ia"
                }
            )
        else:
            # Enforce COM_HUMANO
            if conversation.status != ConversationStatus.COM_HUMANO:
                conversation.status = ConversationStatus.COM_HUMANO

            dec_sets = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
            store_intent = await gemini_service.classify_store_info_intent(
                user_message=text_content,
                tenant_gemini_api_key=dec_sets.get("gemini_api_key"),
                tenant_gemini_model_name=dec_sets.get("gemini_model_name")
            )

            if store_intent == "STORE_LOCATION":
                now_ts = time.time()
                last_loc_ts = _conversation_location_timestamps.get(conversation.id, 0.0)
                if (now_ts - last_loc_ts) < 15.0:
                    logger.info(f"[DEBOUNCE LOCATION] Conversa {conversation.id} já recebeu localização há {(now_ts - last_loc_ts):.1f}s. Silenciando disparo duplicado.")
                    return {"status": "success", "action": "ignored_duplicate_location"}
                _conversation_location_timestamps[conversation.id] = now_ts

                client_first_name = contact.nome.strip().split()[0] if (contact and contact.nome and contact.nome.strip().lower() not in ["cliente", "unknown", ""]) else ""
                greeting_name = f", {client_first_name}" if client_first_name else ""
                auto_loc_text = f"Com certeza{greeting_name}! Segue a nossa localização no mapa abaixo. Ficamos à sua disposição e aguardamos sua visita! 📍"

                target_inst = (whatsapp_number.instancia_evolution_api if whatsapp_number else "") or instance_name
                if target_inst:
                    try:
                        await evolution_service.send_text_message(
                            instance_name=target_inst,
                            number=phone_number,
                            text=f"*🤖 IA Concierge:*\n\n{auto_loc_text}"
                        )
                        await evolution_service.send_location_message(
                            instance_name=target_inst,
                            number=phone_number,
                            latitude=-15.820418,
                            longitude=-47.956467,
                            name="Servweld / Servsolda",
                            address="SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226"
                        )
                    except Exception as e:
                        logger.warning(f"Error sending auto location reply: {e}")

                loc_msg = Message(
                    conversation_id=conversation.id,
                    remetente=MessageSender.IA,
                    conteudo=auto_loc_text,
                    tipo=MessageType.TEXTO,
                    status="delivered",
                    dados_adicionais={"auto_reply": True, "info_type": "location"},
                    timestamp=datetime.utcnow()
                )
                db.add(loc_msg)
                await db.commit()

                await ws_manager.broadcast_to_department(
                    tenant_id=tenant_id,
                    whatsapp_number_id=whatsapp_number.id,
                    message_data={
                        "type": "NEW_MESSAGE",
                        "conversation_id": conversation.id,
                        "id": loc_msg.id,
                        "remetente": "ia",
                        "tipo": "texto",
                        "conteudo": auto_loc_text,
                        "timestamp": loc_msg.timestamp.isoformat() + "Z"
                    }
                )
                return {"status": "success", "action": "store_location_sent"}

            elif store_intent == "STORE_HOURS":
                auto_hours_text = (
                    "⏰ *Horário de Atendimento Servweld:*\n\n"
                    "• *Segunda a Sexta-feira:* das 08h00 às 18h00 (Horário de Brasília)\n"
                    "• *Sábados, Domingos e Feriados:* Fechado\n\n"
                    "Nosso laboratório e loja estão à sua disposição durante todo o horário comercial!"
                )
                if whatsapp_number and whatsapp_number.instancia_evolution_api:
                    try:
                        await evolution_service.send_text_message(
                            instance_name=whatsapp_number.instancia_evolution_api,
                            number=phone_number,
                            text=f"*🤖 IA Concierge:*\n\n{auto_hours_text}"
                        )
                    except Exception as e:
                        logger.warning(f"Error sending auto hours reply: {e}")

                hours_msg = Message(
                    conversation_id=conversation.id,
                    remetente=MessageSender.IA,
                    conteudo=auto_hours_text,
                    tipo=MessageType.TEXTO,
                    status="delivered",
                    dados_adicionais={"auto_reply": True, "info_type": "hours"},
                    timestamp=datetime.utcnow()
                )
                db.add(hours_msg)
                await db.commit()

                await ws_manager.broadcast_to_department(
                    tenant_id=tenant_id,
                    whatsapp_number_id=whatsapp_number.id,
                    message_data={
                        "type": "NEW_MESSAGE",
                        "conversation_id": conversation.id,
                        "id": hours_msg.id,
                        "remetente": "ia",
                        "tipo": "texto",
                        "conteudo": auto_hours_text,
                        "timestamp": hours_msg.timestamp.isoformat() + "Z"
                    }
                )
                return {"status": "success", "action": "store_hours_sent"}

            # For all other messages during human attendance, SILENCE the AI completely!
            logger.info(f"[HUMAN SHIELD] Conversa #{conversation.id} possui atendimento humano ativo ({contact.nome or contact.telefone}). IA Concierge 100% silenciada.")
            await db.commit()
            return {"status": "success", "action": "human_handled_ai_silenced"}

    # 5. Process AI Concierge response if conversation is with AI
    current_status_str = getattr(conversation.status, 'value', str(conversation.status))
    if current_status_str == ConversationStatus.COM_IA.value or conversation.status == ConversationStatus.COM_IA:
        now_ts = time.time()

        # Anti-Spam / Burst Debounce: se a IA respondeu nesta conversa há menos de 8.0 segundos,
        # grava a mensagem no banco e transmite via WebSocket, mas silencia o disparo duplicado da IA para não enviar rajadas
        last_ai_ts = _conversation_ai_timestamps.get(conversation.id, 0.0)
        if (now_ts - last_ai_ts) < 8.0:
            logger.info(f"[DEBOUNCE AI] Conversa #{conversation.id} recebeu mensagem em rajada ({(now_ts - last_ai_ts):.1f}s desde última resposta da IA). Silenciando disparo duplicado.")
            return {"status": "success", "action": "message_saved_ai_debounced"}

        # Acumulador inteligente de digitação do cliente:
        # Quando um cliente envia frases separadas rapidamente, aguarda breve intervalo (4.5s) para consolidar
        _last_customer_msg_timestamps[conversation.id] = now_ts
        await asyncio.sleep(4.5)

        # Se uma mensagem mais recente do cliente chegou durante esta janela, o webhook mais novo responderá
        latest_cust_ts = _last_customer_msg_timestamps.get(conversation.id, now_ts)
        if latest_cust_ts > now_ts:
            logger.info(f"[BURST ACCUMULATOR] Conversa #{conversation.id}: cliente continuou digitando. Absorvendo mensagem para resposta única consolidada.")
            return {"status": "success", "action": "absorbed_by_newer_message"}

        conv_id = conversation.id

        # In-Flight Concurrency Shield: se esta conversa já possui IA em execução, descarta duplicata
        inflight_ai_ts = _in_flight_ai_conversations.get(conv_id, 0.0)
        if (time.time() - inflight_ai_ts) < 20.0:
            logger.info(f"[AI LOCK] Conversa #{conv_id} já possui resposta de IA em processamento ({(time.time() - inflight_ai_ts):.1f}s atrás). Silenciando webhook concorrente.")
            return {"status": "success", "action": "ai_already_in_flight"}
        _in_flight_ai_conversations[conv_id] = time.time()

        # Recarrega a conversa com relacionamentos para ler mensagens que foram salvas durante os 4.5s
        conv_fresh_stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages), selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
            .where(Conversation.id == conv_id)
        )
        fresh_res = await db.execute(conv_fresh_stmt)
        fresh_conv = fresh_res.scalar_one_or_none()
        if fresh_conv:
            conversation = fresh_conv
            contact = fresh_conv.contact
            whatsapp_number = fresh_conv.whatsapp_number


        # Check if message comes from a WhatsApp group and whether AI is explicitly allowed
        if is_group:
            clean_jid = remote_jid.split("@")[0] if "@" in str(remote_jid) else str(remote_jid)
            g_stmt = select(WhatsAppGroup).where(
                WhatsAppGroup.tenant_id == tenant_id,
                WhatsAppGroup.group_jid.like(f"%{clean_jid}%")
            )
            g_res = await db.execute(g_stmt)
            group_obj = g_res.scalar_one_or_none()

            if not group_obj or not group_obj.ia_ativa:
                logger.info(f"Skipping AI response for group '{remote_jid}' (ia_ativa = False or group not registered)")
                _in_flight_ai_conversations.pop(conversation.id, None)
                await db.commit()
                return {"status": "success", "message": "Group message logged; AI interaction disabled for this group."}

        # Fetch Memory Summary

        mem_stmt = select(ConversationMemory).where(
            ConversationMemory.tenant_id == tenant_id,
            ConversationMemory.contact_id == contact.id
        )
        mem_res = await db.execute(mem_stmt)
        memory = mem_res.scalar_one_or_none()
        memory_summary = memory.resumo_estruturado if memory else ""

        # Fallback: if memory_summary is empty, load last 10 messages from previous conversations of this contact
        if not memory_summary:
            past_msgs_stmt = (
                select(Message)
                .join(Conversation)
                .where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.contact_id == contact.id,
                    Conversation.id != conversation.id
                )
                .order_by(Message.timestamp.desc())
                .limit(10)
            )
            past_msgs_res = await db.execute(past_msgs_stmt)
            past_msgs = list(reversed(past_msgs_res.scalars().all()))
            if past_msgs:
                memory_summary = "Histórico do atendimento anterior:\n" + "\n".join([
                    f"[{getattr(m.remetente, 'value', str(m.remetente))}]: {m.conteudo}" for m in past_msgs if m.conteudo
                ])

        ai_input_text = text_content
        if text_content and text_content.startswith("/uploads/"):
            if "|" in text_content:
                ai_input_text = text_content.split("|", 1)[1].strip()
            else:
                ai_input_text = "[Foto/Mídia enviada pelo cliente para análise]"

        # Fetch RAG Context (Geral + Department Specific)
        rag_context = await rag_service.search_context(
            tenant_id=tenant_id,
            query=ai_input_text,
            department_id=whatsapp_number.id
        )

        # Fetch recent messages for AI context
        msg_stmt = select(Message).where(Message.conversation_id == conversation.id).order_by(Message.timestamp.desc()).limit(6)
        msg_res = await db.execute(msg_stmt)
        recent_msgs = list(reversed(msg_res.scalars().all()))

        history = [
            {"remetente": getattr(m.remetente, 'value', str(m.remetente)), "conteudo": m.conteudo}
            for m in recent_msgs
        ]


        # Fetch all available departments/numbers for this tenant
        dept_stmt = select(WhatsAppNumber).where(
            WhatsAppNumber.tenant_id == tenant_id,
            WhatsAppNumber.status == True
        )
        dept_res = await db.execute(dept_stmt)
        all_wns = dept_res.scalars().all()
        available_dept_names = [wn_item.nome_departamento for wn_item in all_wns if wn_item.nome_departamento]

        # Fetch all active users/attendants for tenant to support preferred attendant routing
        u_stmt = select(User).where(User.tenant_id == tenant_id)
        u_res = await db.execute(u_stmt)
        tenant_users = u_res.scalars().all()
        available_attendants = [u.nome for u in tenant_users if u.nome]

        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

        # Check if conversation was waiting for customer confirmation on sector transfer
        is_pending_transfer = (conversation.assunto_atual or "").startswith("CONFIRM_TRANSFER:")
        # Check if conversation is waiting for the customer to confirm they read the O.S.
        # conditions before we send them the full PDF (set by the OS Handler PDF ingestion
        # endpoint - see os_handler_ingest.py). Format: "CONFIRM_OS_PDF:<uploads-relative-path>"
        is_pending_os_pdf = (conversation.assunto_atual or "").startswith("CONFIRM_OS_PDF:")
        # Check if conversation is waiting for the customer to approve/reject the
        # technician's quote (fase 2 do OS Handler). Format:
        # "CONFIRM_OS_APPROVAL:<numero da os>|<uploads-relative-path>|<telefone do tecnico ou vazio>"
        is_pending_os_approval = (conversation.assunto_atual or "").startswith("CONFIRM_OS_APPROVAL:")
        transfer_executed = False
        ai_output = None

        # Trigger AI typing presence ("digitando...") for customer on WhatsApp & attendants in system UI
        if instance_name and phone_number:
            clean_phone_for_presence = phone_number.split("@")[0]
            asyncio.create_task(
                evolution_service.send_presence(
                    instance_name=instance_name,
                    number=clean_phone_for_presence,
                    presence="composing"
                )
            )
            asyncio.create_task(
                ws_manager.broadcast_to_tenant(tenant_id, {
                    "type": "USER_PRESENCE",
                    "conversation_id": conversation.id,
                    "phone": phone_number,
                    "presence": "ai_composing"
                })
            )

        if is_tech:
            logger.info(f"[COPILOTO TECNICO] Atendimento direto ao técnico autorizado/admin {tech_name} ({phone_number}) no modo Master.")
            ai_output = await gemini_service.generate_concierge_response(
                customer_name=tech_name or "Técnico",
                department_name=whatsapp_number.nome_departamento,
                user_message=text_content,
                conversation_history=history,
                memory_summary=memory_summary,
                rag_context=rag_context,
                available_departments=available_dept_names,
                available_attendants=available_attendants,
                protocol_number=None,
                should_announce_protocol=False,
                is_technician_or_admin=True,
                customer_phone=phone_number,
                tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
            )
        elif is_pending_transfer:
            parts = conversation.assunto_atual.split(":", 2)
            target_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            intent_sum = parts[2] if len(parts) > 2 else "Assunto em confirmação"

            target_wn = next((w for w in all_wns if w.id == target_id), None)
            target_dept_name = target_wn.nome_departamento if target_wn else "o setor responsável"
            question_asked = f"Entendi que o seu assunto é sobre {intent_sum}, correto? Posso te encaminhar para a nossa equipe de {target_dept_name}?"

            # Semantic natural language classification with Gemini
            classification = await gemini_service.classify_confirmation_response(
                question_asked=question_asked,
                customer_response=text_content,
                tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
            )
            logger.info(f"Gemini confirmation classification for '{text_content}': {classification}")

            if classification == "CONFIRMA":
                if target_wn and target_wn.id != whatsapp_number.id:
                    old_dept_name = whatsapp_number.nome_departamento
                    old_dept_id = whatsapp_number.id
                    conversation.whatsapp_number_id = target_wn.id
                    whatsapp_number = target_wn
                    conversation.assunto_atual = intent_sum

                    tlog = TransferLog(
                        conversation_id=conversation.id,
                        de_whatsapp_number_id=old_dept_id,
                        para_whatsapp_number_id=target_wn.id,
                        motivo=f"Roteamento IA confirmado pelo cliente: {intent_sum}",
                        timestamp=datetime.utcnow()
                    )
                    db.add(tlog)

                    sys_transfer_msg = Message(
                        conversation_id=conversation.id,
                        remetente="sistema",
                        conteudo=f"🔀 *TRANSFERÊNCIA DE SETOR PELA IA*\nAtendimento redirecionado do setor '{old_dept_name}' para '{target_wn.nome_departamento}'.\nMotivo: {intent_sum} (Confirmado pelo cliente)",
                        tipo=MessageType.TEXTO,
                        timestamp=datetime.utcnow()
                    )
                    db.add(sys_transfer_msg)

                    ai_output = {
                        "resposta": f"Perfeito! Já encaminhei o seu chamado para a nossa equipe de *{target_wn.nome_departamento}*. Um de nossos especialistas dará continuidade em instantes!",
                        "transferir_setor": "NENHUM",
                        "enviar_localizacao": False,
                        "enviar_pix": False,
                        "escalar_humano": True,
                        "nova_memoria": f"Cliente confirmou transferência para {target_wn.nome_departamento} | Assunto: {intent_sum}"
                    }
                    transfer_executed = True
            elif classification == "NEGA":
                logger.info(f"Customer declined sector transfer confirmation for conversation {conversation.id}")
                conversation.assunto_atual = "Atendimento Concierge"
                ai_output = {
                    "resposta": "Sem problemas! Para que eu possa te direcionar corretamente, por favor me informe com mais detalhes: o que exatamente você precisa ou qual é a sua dúvida?",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": "Cliente recusou sugestão de setor; solicitando mais detalhes."
                }
                transfer_executed = True
            else:
                # AMBIGUA -> Fallback: asks for clarification without transferring
                logger.info(f"Customer response was ambiguous during confirmation for conversation {conversation.id}")
                conversation.assunto_atual = "Atendimento Concierge"
                ai_output = {
                    "resposta": "Para eu ter certeza e não te encaminhar para o setor errado, por favor me confirme: qual é o serviço ou produto exato que você gostaria de tratar hoje?",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": "Resposta ambígua na confirmação; solicitando esclarecimento."
                }
                transfer_executed = True
        elif is_pending_os_pdf:
            from app.services.automation_service import automation_service
            pending_file_rel_path = conversation.assunto_atual.split(":", 1)[1]
            classification = automation_service.classify_yes_no_reply(text_content)
            logger.info(f"[OS HANDLER PDF] Classificação da resposta de confirmação '{text_content}': {classification}")

            if classification == "CONFIRMA":
                conversation.assunto_atual = "Atendimento Concierge"
                ai_output = {
                    "resposta": "Perfeito! Só um instante, já vou te enviar o PDF completo da sua Ordem de Serviço. 📎",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": "Cliente confirmou leitura das condições; PDF da O.S. enviado."
                }
                # Sent as its own background task (base64+upload of a PDF doesn't fit the
                # plain-text ai_reply pipeline below) - self-contained, doesn't touch any of
                # the enviar_pix/enviar_localizacao downstream branches.
                asyncio.create_task(
                    send_os_pdf_after_confirmation(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        whatsapp_number_id=whatsapp_number.id,
                        instance_name=instance_name,
                        recipient_phone=phone_number,
                        pdf_relative_path=pending_file_rel_path
                    )
                )
            elif classification == "NEGA":
                conversation.assunto_atual = "Atendimento Concierge"
                ai_output = {
                    "resposta": "Sem problemas! Fico à disposição para te enviar o PDF completo da sua Ordem de Serviço quando você quiser - só me chamar aqui novamente. 😊",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": "Cliente optou por não confirmar leitura das condições agora; PDF não enviado."
                }
            else:
                # AMBIGUA -> keep the pending marker, ask again more directly instead of giving up
                ai_output = {
                    "resposta": "Só para eu confirmar certinho: você leu a condição informada e posso te enviar o PDF completo da sua Ordem de Serviço agora? Responda *SIM* ou *NÃO*.",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": "Resposta ambígua na confirmação do PDF da O.S.; perguntando de novo."
                }
            transfer_executed = True
        elif is_pending_os_approval:
            from app.services.automation_service import automation_service
            marker_body = conversation.assunto_atual.split(":", 1)[1]
            parts = marker_body.split("|")
            os_numero = parts[0] if len(parts) > 0 else "?"
            pdf_rel_path = parts[1] if len(parts) > 1 else ""
            tecnico_phone = parts[2] if len(parts) > 2 and parts[2] else None

            classification = automation_service.classify_yes_no_reply(text_content)
            logger.info(f"[OS HANDLER APROVAÇÃO] Classificação da resposta '{text_content}' para O.S. #{os_numero}: {classification}")

            if classification in ("CONFIRMA", "NEGA"):
                aprovado = classification == "CONFIRMA"
                conversation.assunto_atual = "Atendimento Concierge"
                ai_output = {
                    "resposta": "Ótimo, muito obrigado pela confirmação! Já estamos providenciando o serviço. 🔧" if aprovado
                                else "Entendido, agradecemos o retorno! Fico à disposição caso mude de ideia ou tenha dúvidas.",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": f"Cliente {'aprovou' if aprovado else 'recusou'} o orçamento da O.S. #{os_numero}."
                }
                asyncio.create_task(
                    notify_os_approval_result(
                        tenant_id=tenant_id,
                        conversation_id=conversation.id,
                        whatsapp_number_id=whatsapp_number.id,
                        instance_name=instance_name,
                        os_numero=os_numero,
                        client_name=contact.nome or "Cliente",
                        aprovado=aprovado,
                        pdf_relative_path=pdf_rel_path,
                        tecnico_phone=tecnico_phone
                    )
                )
            else:
                ai_output = {
                    "resposta": f"Só para eu confirmar: você *aprova* a execução do serviço da O.S. #{os_numero} pelo valor informado no orçamento? Responda *SIM* ou *NÃO*.",
                    "transferir_setor": "NENHUM",
                    "enviar_localizacao": False,
                    "enviar_pix": False,
                    "escalar_humano": False,
                    "nova_memoria": f"Resposta ambígua na aprovação do orçamento da O.S. #{os_numero}; perguntando de novo."
                }
            transfer_executed = True

        if not transfer_executed and not is_tech:
            dept_dicts = [
                {
                    "id": wn_item.id,
                    "nome": wn_item.nome_departamento,
                    "descricao": wn_item.descricao_roteamento or ""
                }
                for wn_item in all_wns
            ]

            routing_decision = await gemini_service.evaluate_department_routing(
                customer_name=contact.nome or "Cliente",
                current_department_name=whatsapp_number.nome_departamento,
                user_message=text_content,
                conversation_history=history,
                departments=dept_dicts,
                tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
            )

            needs_tr = routing_decision.get("needs_transfer", False)
            target_dept_id = routing_decision.get("target_department_id")
            conf_score = float(routing_decision.get("confidence", 0.0))
            intent_summary = routing_decision.get("customer_intent_summary", "")

            target_wn = next((w for w in all_wns if w.id == target_dept_id), None) if target_dept_id else None

            if needs_tr and target_wn and target_wn.id != whatsapp_number.id:
                if conf_score >= 0.85:
                    logger.info(f"High confidence routing ({conf_score:.2f}) -> Direct transfer to {target_wn.nome_departamento}")
                    old_dept_name = whatsapp_number.nome_departamento
                    old_dept_id = whatsapp_number.id
                    conversation.whatsapp_number_id = target_wn.id
                    whatsapp_number = target_wn
                    conversation.assunto_atual = intent_summary

                    tlog = TransferLog(
                        conversation_id=conversation.id,
                        de_whatsapp_number_id=old_dept_id,
                        para_whatsapp_number_id=target_wn.id,
                        motivo=f"Roteamento automático IA (Confiança {conf_score:.2f}): {intent_summary}",
                        timestamp=datetime.utcnow()
                    )
                    db.add(tlog)

                    sys_transfer_msg = Message(
                        conversation_id=conversation.id,
                        remetente="sistema",
                        conteudo=f"🔀 *TRANSFERÊNCIA DE SETOR PELA IA*\nAtendimento redirecionado do setor '{old_dept_name}' para '{target_wn.nome_departamento}'.\nMotivo: {intent_summary}",
                        tipo=MessageType.TEXTO,
                        timestamp=datetime.utcnow()
                    )
                    db.add(sys_transfer_msg)

                    ai_output = {
                        "resposta": f"Com certeza! Identifiquei que a sua solicitação é sobre *{intent_summary}*. Estou transferindo seu atendimento para a nossa equipe de *{target_wn.nome_departamento}*, que já vai te atender.",
                        "transferir_setor": "NENHUM",
                        "enviar_localizacao": False,
                        "enviar_pix": False,
                        "escalar_humano": True,
                        "nova_memoria": f"Transferência automática para {target_wn.nome_departamento} | Assunto: {intent_summary}"
                    }
                elif conf_score >= 0.40:
                    logger.info(f"Medium confidence routing ({conf_score:.2f}) -> Asking customer confirmation before transfer to {target_wn.nome_departamento}")
                    ai_output = {
                        "resposta": f"Entendi que o seu assunto é sobre *{intent_summary}*, correto? Posso te encaminhar para a nossa equipe de *{target_wn.nome_departamento}*?",
                        "transferir_setor": "NENHUM",
                        "enviar_localizacao": False,
                        "enviar_pix": False,
                        "escalar_humano": False,
                        "nova_memoria": f"Aguardando confirmação do cliente para transferir para {target_wn.nome_departamento}"
                    }
                # Verificação de segurança no histórico do banco para protocolo já anunciado
                extra = dict(conversation.dados_adicionais or {})
                protocol_already_announced = bool(extra.get("protocol_announced"))
                if not protocol_already_announced:
                    check_proto_stmt = select(Message.id).where(
                        Message.conversation_id == conversation.id,
                        Message.remetente.in_([MessageSender.IA, MessageSender.ATENDENTE, "ia", "atendente"]),
                        or_(
                            Message.conteudo.like("%Protocolo%"),
                            Message.conteudo.like("%Seja bem-vindo%"),
                            Message.conteudo.like("%bem-vindo(a)%")
                        )
                    ).limit(1)
                    check_proto_res = await db.execute(check_proto_stmt)
                    if check_proto_res.scalars().first() is not None:
                        protocol_already_announced = True
                        extra["protocol_announced"] = True
                        conversation.dados_adicionais = extra
                        flag_modified(conversation, "dados_adicionais")

                should_announce_proto = not protocol_already_announced
                ai_output = await gemini_service.generate_concierge_response(
                    customer_name=contact.nome or "Cliente",
                    department_name=whatsapp_number.nome_departamento,
                    user_message=text_content,
                    conversation_history=history,
                    memory_summary=memory_summary,
                    rag_context=rag_context,
                    available_departments=available_dept_names,
                    available_attendants=available_attendants,
                    protocol_number=conversation.protocol_number,
                    should_announce_protocol=should_announce_proto,
                    is_technician_or_admin=False,
                    customer_phone=phone_number,
                    tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                    tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
                )
                extra["protocol_announced"] = True
                conversation.dados_adicionais = extra
                flag_modified(conversation, "dados_adicionais")
            else:
                extra = dict(conversation.dados_adicionais or {})
                protocol_already_announced = bool(extra.get("protocol_announced"))
                if not protocol_already_announced:
                    check_proto_stmt = select(Message.id).where(
                        Message.conversation_id == conversation.id,
                        Message.remetente.in_([MessageSender.IA, MessageSender.ATENDENTE, "ia", "atendente"]),
                        or_(
                            Message.conteudo.like("%Protocolo%"),
                            Message.conteudo.like("%Seja bem-vindo%"),
                            Message.conteudo.like("%bem-vindo(a)%")
                        )
                    ).limit(1)
                    check_proto_res = await db.execute(check_proto_stmt)
                    if check_proto_res.scalars().first() is not None:
                        protocol_already_announced = True
                        extra["protocol_announced"] = True
                        conversation.dados_adicionais = extra
                        flag_modified(conversation, "dados_adicionais")

                should_announce_proto = not protocol_already_announced
                ai_output = await gemini_service.generate_concierge_response(
                    customer_name=contact.nome or "Cliente",
                    department_name=whatsapp_number.nome_departamento,
                    user_message=text_content,
                    conversation_history=history,
                    memory_summary=memory_summary,
                    rag_context=rag_context,
                    available_departments=available_dept_names,
                    available_attendants=available_attendants,
                    protocol_number=conversation.protocol_number,
                    should_announce_protocol=should_announce_proto,
                    is_technician_or_admin=False,
                    customer_phone=phone_number,
                    tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                    tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
                )
                extra["protocol_announced"] = True
                conversation.dados_adicionais = extra
                flag_modified(conversation, "dados_adicionais")

        ai_reply = ai_output["resposta"]
        transferir_setor = ai_output.get("transferir_setor", "NENHUM")
        enviar_localizacao = ai_output.get("enviar_localizacao", False)
        enviar_pix = ai_output.get("enviar_pix", False)
        escalar_humano = ai_output.get("escalar_humano", False) if not is_tech else False
        nova_memoria = ai_output.get("nova_memoria", "")

        # Guarantee Protocol Number is sent ONLY AND EXCLUSIVELY ONCE per conversation/protocol!
        extra = dict(conversation.dados_adicionais or {})
        proto_str = str(conversation.protocol_number).strip() if conversation.protocol_number else ""

        if not protocol_already_announced and proto_str:
            for h in (history or []):
                h_content = str(h.get("conteudo", ""))
                if proto_str in h_content or "📋 *Protocolo:*" in h_content or "Protocolo de Atendimento" in h_content or "*Protocolo:*" in h_content:
                    protocol_already_announced = True
                    extra["protocol_announced"] = True
                    conversation.dados_adicionais = extra
                    flag_modified(conversation, "dados_adicionais")
                    break

        if not is_tech and conversation.protocol_number:
            if not protocol_already_announced:
                # FIRST TIME ONLY: Attach protocol header
                if proto_str not in ai_reply:
                    ai_reply = f"📋 *Protocolo:* #{proto_str}\n\n{ai_reply}"
                extra["protocol_announced"] = True
                conversation.dados_adicionais = extra
                flag_modified(conversation, "dados_adicionais")
            else:
                # PROTOCOL ALREADY ANNOUNCED: NEVER send protocol banner again!
                # If AI text repeated the protocol number/header, strip it clean!
                ai_reply = re.sub(r'📋\s*\*?Protocolo:.*?\n+', '', ai_reply, flags=re.IGNORECASE).strip()
                ai_reply = re.sub(r'^\s*\*?Protocolo:.*?\n+', '', ai_reply, flags=re.IGNORECASE).strip()
                if proto_str:
                    ai_reply = re.sub(r'#?' + re.escape(proto_str), '', ai_reply).strip()
                # Strip repetitive welcome greeting if already welcomed
                ai_reply = re.sub(r'^(?:Olá!?\s*)?Seja bem-vindo\(a\)[^.!?]*[.!?]\s*', '', ai_reply, flags=re.IGNORECASE).strip()

        # Enforce Pix Payload Appending if AI or customer requested Pix data and details are present
        msg_lower = text_content.lower()
        wants_pix = enviar_pix or any(k in msg_lower for k in ["pix", "chave pix", "pode enviar", "manda o pix", "envia o pix"])

        if wants_pix and "54804458000122" not in ai_reply and "00020126" not in ai_reply:
            has_details = any(k in (memory_summary or "").lower() or k in msg_lower for k in ["nota", "serviço", "servico", "orcamento", "orçamento", "pedido", "150", "valor", "pode enviar", "enviar pix", "dados"])
            if has_details:
                ai_reply += (
                    "\n\n💸 *DADOS OFICIAIS PARA PAGAMENTO VIA PIX SERVWELD*\n\n"
                    "🏢 *Favorecido:* Servweld / Servsolda Equipamentos e Serviços Ltda\n"
                    "🆔 *Chave Pix CNPJ:* 54.804.458/0001-22 (Chave Limpa: 54804458000122)\n\n"
                    "📋 *PIX COPIA E COLA (Copie e cole no App do Banco):*\n"
                    "00020126360014br.gov.bcb.pix0114548044580001225204000053039865802BR5914SERVWELD SOLDA6008BRASILIA62070503***6304E6FC\n\n"
                    "⚠️ *Importante:* Após realizar a transferência, por favor envie o comprovante neste chat para validação do setor Financeiro."
                )

        # Check Sector Transfer by AI Concierge
        if transferir_setor and transferir_setor.strip().upper() != "NENHUM":
            target_wn = None
            for wn_item in all_wns:
                if wn_item.nome_departamento and wn_item.nome_departamento.strip().lower() == transferir_setor.strip().lower():
                    target_wn = wn_item
                    break
            
            if target_wn and target_wn.id != whatsapp_number.id:
                logger.info(f"AI requested sector transfer for conversation {conversation.id} from {whatsapp_number.nome_departamento} to {target_wn.nome_departamento}")
                old_dept_name = whatsapp_number.nome_departamento
                conversation.whatsapp_number_id = target_wn.id
                whatsapp_number = target_wn

                # Guarantee the customer is explicitly informed about the sector transfer
                if target_wn.nome_departamento.lower() not in ai_reply.lower():
                    ai_reply = f"Com certeza! Estou transferindo seu atendimento para a nossa equipe de *{target_wn.nome_departamento}*, que é o setor responsável e dará continuidade.\n\n" + ai_reply

                # Insert system message logging the sector transfer
                sys_transfer_msg = Message(
                    conversation_id=conversation.id,
                    remetente="sistema",
                    conteudo=f"🔀 *TRANSFERÊNCIA DE SETOR PELA IA*\nAtendimento redirecionado do setor '{old_dept_name}' para '{target_wn.nome_departamento}'.",
                    tipo=MessageType.TEXTO,
                    timestamp=datetime.utcnow()
                )
                db.add(sys_transfer_msg)

                # Broadcast update event to frontend
                await ws_manager.broadcast_to_department(
                    tenant_id=tenant_id,
                    whatsapp_number_id=target_wn.id,
                    message_data={
                        "type": "CONVERSATION_UPDATED",
                        "conversation_id": conversation.id,
                        "whatsapp_number_id": target_wn.id,
                        "department": target_wn.nome_departamento,
                        "status": getattr(conversation.status, 'value', str(conversation.status))
                    }
                )

        # Anti-Loop Guard: If incoming message is a bot, menu, or URA from another company, silence AI
        is_bot_detected = bool(ai_output.get("is_bot_or_menu")) or ai_reply.strip() in ["[SILENCIAR_IA]", ""]
        if is_bot_detected:
            logger.info(f"[ANTI-LOOP BOT] Mensagem identificada como menu/bot de outra empresa. Silenciando IA e passando para COM_HUMANO.")
            conversation.status = ConversationStatus.COM_HUMANO
            sys_bot_note = Message(
                conversation_id=conversation.id,
                remetente="sistema",
                conteudo="🤖 *Menu/Bot Automático Detectado:* A mensagem recebida pertence a uma URA/Menu de outra empresa. A IA foi silenciada para evitar redundância e loops infinitos.",
                tipo=MessageType.TEXTO,
                timestamp=datetime.utcnow()
            )
            db.add(sys_bot_note)
            await db.commit()
            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                message_data={
                    "type": "STATUS_CHANGE",
                    "conversation_id": conversation.id,
                    "status": "com_humano"
                }
            )
            return {"status": "success", "action": "bot_silenced"}

        # Save AI Response Text Message
        ai_msg = Message(
            conversation_id=conversation.id,
            remetente=MessageSender.IA,
            conteudo=ai_reply,
            tipo=MessageType.TEXTO,
            timestamp=datetime.utcnow()
        )
        db.add(ai_msg)

        # Prepare Native WhatsApp Location Card if requested by customer/IA
        should_send_location = False
        if enviar_localizacao:
            now_ts = time.time()
            last_loc_ts = _conversation_location_timestamps.get(conversation.id, 0.0)
            if (now_ts - last_loc_ts) < 15.0:
                logger.info(f"[DEBOUNCE LOCATION] Conversa {conversation.id} já enviou localização há {(now_ts - last_loc_ts):.1f}s. Evitando reenvio em rajada.")
            else:
                _conversation_location_timestamps[conversation.id] = now_ts
                should_send_location = True

        # Dispatch Native WhatsApp Pix QR Code Image (with preset amount) if requested by customer/IA
        if wants_pix:
            pix_amount = (
                extract_amount_from_text(text_content) or
                extract_amount_from_text(memory_summary) or
                extract_amount_from_text(ai_reply)
            )

            bacen_payload = generate_bacen_pix_string(
                key="54804458000122",
                merchant_name="SERVWELD SOLDA",
                merchant_city="BRASILIA",
                amount=pix_amount
            )

            qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={bacen_payload}"
            file_bytes = None
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(qr_image_url, timeout=10.0)
                    if r.status_code == 200:
                        file_bytes = r.content
            except Exception as e:
                logger.error(f"Error fetching Pix QR Code image in webhook: {e}")

            if file_bytes:
                os.makedirs("uploads", exist_ok=True)
                unique_fn = f"pix_{uuid.uuid4().hex}.png"
                up_path = os.path.join("uploads", unique_fn)
                with open(up_path, "wb") as f:
                    f.write(file_bytes)

                amount_caption = f"\n💵 *Valor a Pagar:* R$ {pix_amount:.2f}".replace('.', ',') if pix_amount else ""
                pix_caption = (
                    f"💸 *DADOS OFICIAIS PARA PAGAMENTO VIA PIX SERVWELD*\n\n"
                    f"🏢 *Favorecido:* Servweld / Servsolda Equipamentos e Serviços Ltda\n"
                    f"🆔 *Chave Pix CNPJ:* 54.804.458/0001-22 (Chave Limpa: 54804458000122)"
                    f"{amount_caption}\n\n"
                    f"📋 *PIX COPIA E COLA (Copie e cole no App do Banco):*\n"
                    f"{bacen_payload}\n\n"
                    f"📲 *Escaneie o QR Code acima pelo app do seu Banco.*\n"
                    f"⚠️ *Importante:* Após realizar a transferência, envie o comprovante neste chat para validação do setor Financeiro."
                )

                base64_img = base64.b64encode(file_bytes).decode('utf-8')
                formatted_caption = f"*🤖 IA Concierge:*\n\n{pix_caption}"

                instances_to_try = [instance_name] + [wn.instancia_evolution_api for wn in all_wns if wn.instancia_evolution_api != instance_name]
                pix_sent = False
                for inst in instances_to_try:
                    if not inst:
                        continue
                    res_pix = await evolution_service.send_media_message(
                        instance_name=inst,
                        number=contact.telefone,
                        media_type="image",
                        mimetype="image/png",
                        media=base64_img,
                        file_name="qrcode_pix.png",
                        caption=formatted_caption
                    )
                    if res_pix.get("success"):
                        logger.info(f"Successfully sent native Pix QR Code image to {contact.telefone} with amount {pix_amount}")
                        pix_sent = True
                        break

                if pix_sent:
                    pix_msg = Message(
                        conversation_id=conversation.id,
                        remetente=MessageSender.IA,
                        conteudo=f"/uploads/{unique_fn}|{pix_caption}",
                        tipo=MessageType.IMAGEM,
                        timestamp=datetime.utcnow()
                    )
                    db.add(pix_msg)

        # Update Conversation Memory
        if memory:
            memory.resumo_estruturado = nova_memoria
            memory.atualizado_em = datetime.utcnow()
        else:
            new_mem = ConversationMemory(
                tenant_id=tenant_id,
                contact_id=contact.id,
                resumo_estruturado=nova_memoria
            )
            db.add(new_mem)

        # Check Human Escalation
        if escalar_humano:
            is_open = business_hours_service.is_within_business_hours()
            atendente_pref = ai_output.get("atendente_preferencial")
            preferred_user = None

            if atendente_pref:
                clean_pref = atendente_pref.strip().lower()
                for u in tenant_users:
                    if u.nome and (clean_pref in u.nome.lower() or u.nome.lower() in clean_pref):
                        preferred_user = u
                        break

            if is_open:
                if preferred_user:
                    conversation.status = ConversationStatus.COM_HUMANO
                    conversation.assigned_user_id = preferred_user.id
                    assigned_user_name = f"{preferred_user.nome} (Solicitado pelo cliente)"
                    logger.info(f"[ROTEAMENTO PREFERENCIAL] Conversa #{conversation.id} direcionada especificamente para o atendente {preferred_user.nome} (ID {preferred_user.id})")
                else:
                    # Find and assign the least loaded eligible operator in this department
                    assigned_user = await assign_least_busy_attendant(db, tenant_id, whatsapp_number.id)
                    if assigned_user:
                        conversation.status = ConversationStatus.COM_HUMANO
                        conversation.assigned_user_id = assigned_user.id
                        assigned_user_name = assigned_user.nome
                    else:
                        conversation.status = ConversationStatus.AGUARDANDO_ATENDENTE
                        conversation.assigned_user_id = None
                        assigned_user_name = "Fila Geral (Aguardando Atendente)"
            else:
                # Outside business hours (after 18:00 or weekends)
                conversation.status = ConversationStatus.AGUARDANDO_ATENDENTE
                conversation.assigned_user_id = preferred_user.id if preferred_user else None
                assigned_user_name = f"Fila Matutina ({preferred_user.nome if preferred_user else 'Geral'})"
                ai_reply += (
                    f"\n\n⏰ *Aviso de Expediente:* Informamos que nosso expediente comercial é de Segunda a Sexta das 08:00 às 18:00. "
                    f"Seu chamado foi registrado com prioridade sob o protocolo *{conversation.protocol_number}* e será atendido pela nossa equipe no próximo dia útil a partir das 08:00!"
                )

            logger.info(f"Conversation {conversation.id} escalated and assigned to {assigned_user_name} (business_hours={is_open}).")

            # Dedup check: Avoid duplicate onboarding summaries if already generated for this protocol
            conv_extra = dict(conversation.dados_adicionais or {})
            has_onboarding_for_proto = conv_extra.get("onboarding_summary_protocol") == conversation.protocol_number
            if not has_onboarding_for_proto:
                onb_stmt = select(Message.id).where(
                    Message.conversation_id == conversation.id,
                    Message.conteudo.like("%RESUMO DE ONBOARDING%")
                ).limit(1)
                onb_res = await db.execute(onb_stmt)
                if onb_res.scalars().first():
                    has_onboarding_for_proto = True

            if not has_onboarding_for_proto:
                # Generate structured Onboarding Summary with Provenance Tracking (Tarefa 2)
                onboarding_summary = await gemini_service.generate_onboarding_summary(
                    customer_name=contact.nome or "Cliente",
                    protocol_number=conversation.protocol_number or "S/N",
                    department_name=whatsapp_number.nome_departamento,
                    messages_history=history + [{"remetente": "cliente", "conteudo": text_content}],
                    tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                    tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
                )

                # Create pinned system transfer card with Onboarding Summary
                sys_escalate_msg = Message(
                    conversation_id=conversation.id,
                    remetente="sistema",
                    conteudo=onboarding_summary,
                    tipo=MessageType.TEXTO,
                    timestamp=datetime.utcnow()
                )
                db.add(sys_escalate_msg)
                conv_extra["onboarding_summary_protocol"] = conversation.protocol_number
                conversation.dados_adicionais = conv_extra

            # Broadcast high-priority escalation alert with summary & assigned operator!
            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                message_data={
                    "type": "CONVERSATION_ESCALATED",
                    "conversation_id": conversation.id,
                    "contact_name": contact.nome or contact.telefone,
                    "contact_phone": contact.telefone,
                    "department": whatsapp_number.nome_departamento,
                    "whatsapp_number_id": whatsapp_number.id,
                    "assigned_user_id": conversation.assigned_user_id,
                    "assigned_user_name": assigned_user_name,
                    "summary": nova_memoria or memory_summary or "Cliente solicita atendimento especializado.",
                    "message": f"🚨 TRANSFERÊNCIA DA IA: Cliente {contact.nome or contact.telefone} atribuído a {assigned_user_name} (Operador mais disponível)!"
                }
            )


        await db.commit()

        # Send AI reply back to WhatsApp via Evolution API
        # Se for mensagem continuada, não repete *🤖 IA Concierge:* para manter diálogo natural e humanizado
        if protocol_already_announced:
            formatted_ai_text = ai_reply
        else:
            formatted_ai_text = f"*🤖 IA Concierge:*\n\n{ai_reply}"
        target_dest = remote_jid if ("@lid" in str(remote_jid) or "@g.us" in str(remote_jid)) else phone_number
        await evolution_service.send_text_message(
            instance_name=instance_name,
            number=target_dest,
            text=formatted_ai_text
        )
        _conversation_ai_timestamps[conversation.id] = time.time()

        # Dispatch Native WhatsApp Location Card right below the text reply
        if should_send_location:
            loc_name = "Servweld / Servsolda"
            loc_addr = "SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226"
            loc_lat = -15.820418
            loc_lng = -47.956467
            target_inst = instance_name or (whatsapp_number.instancia_evolution_api if whatsapp_number else "")
            if target_inst:
                try:
                    await evolution_service.send_location_message(
                        instance_name=target_inst,
                        number=contact.telefone,
                        latitude=loc_lat,
                        longitude=loc_lng,
                        name=loc_name,
                        address=loc_addr
                    )
                    logger.info(f"Successfully sent native location card to {contact.telefone} via instance '{target_inst}'")
                except Exception as loc_err:
                    logger.warning(f"Failed to send native location card: {loc_err}")

        # Broadcast AI message to WebSocket clients with ISO Z timestamp
        ts_str = ai_msg.timestamp.isoformat() + "Z" if hasattr(ai_msg.timestamp, "isoformat") else str(ai_msg.timestamp)
        await ws_manager.broadcast_to_department(
            tenant_id=tenant_id,
            whatsapp_number_id=whatsapp_number.id,
            message_data={
                "type": "NEW_MESSAGE",
                "conversation_id": conversation.id,
                "remetente": MessageSender.IA.value,
                "conteudo": ai_reply,
                "timestamp": ts_str,
                "conversation_status": getattr(conversation.status, 'value', str(conversation.status))
            }
        )
        _in_flight_ai_conversations.pop(conv_id, None)

    else:
        await db.commit()

    return {"status": "success"}
