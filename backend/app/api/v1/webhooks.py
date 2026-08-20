import logging
import base64
import uuid
import os
import re
import httpx
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Request, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import (
    WhatsAppNumber, Contact, Conversation, Message, ConversationMemory,
    ConversationStatus, MessageSender, MessageType, WhatsAppGroup, User, UserRole, TransferLog
)

from app.services.evolution_service import evolution_service
from app.services.gemini_service import gemini_service
from app.services.rag_service import rag_service
from app.services.settings_service import settings_service
from app.services.protocol_service import generate_daily_protocol
from app.api.v1.conversations import generate_bacen_pix_string
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks Integration"])

SEEN_WEBHOOK_KEYS = {}

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

async def assign_least_busy_attendant(db: AsyncSession, tenant_id: int, whatsapp_number_id: int) -> Optional[User]:
    try:
        users_stmt = (
            select(User)
            .options(selectinload(User.whatsapp_numbers))
            .where(User.tenant_id == tenant_id, User.status == True)
        )
        users_res = await db.execute(users_stmt)
        users = users_res.scalars().all()

        eligible_users = []
        for u in users:
            role_str = getattr(u.role, 'value', str(u.role)).lower()
            if role_str == "admin":
                eligible_users.append(u)
            elif any(wn.id == whatsapp_number_id for wn in u.whatsapp_numbers):
                eligible_users.append(u)

        if not eligible_users:
            eligible_users = users

        if not eligible_users:
            return None

        user_workloads = {}
        for u in eligible_users:
            count_stmt = select(func.count(Conversation.id)).where(
                Conversation.tenant_id == tenant_id,
                Conversation.assigned_user_id == u.id,
                Conversation.status == ConversationStatus.COM_HUMANO
            )
            count_res = await db.execute(count_stmt)
            active_count = count_res.scalar() or 0
            user_workloads[u] = active_count

        best_user = min(eligible_users, key=lambda u: user_workloads.get(u, 0))
        return best_user
    except Exception as err:
        logger.error(f"Error in assign_least_busy_attendant: {err}")
        return None


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
    logger.info(f"[WEBHOOK RECEBIDO] Evento: '{event_type}' | Instancia: '{instance_name}' | Payload: {payload}")

    key = data.get("key", {}) if isinstance(data, dict) else {}
    msg_id = key.get("id") if isinstance(key, dict) else None
    
    # Deduplicate incoming webhooks (Evolution API sends duplicate events for same msg_id)
    if msg_id:
        dedup_key = f"{event_type}_{msg_id}"
        now_ts = datetime.utcnow().timestamp()
        # Clean cache older than 60s
        to_del = [k for k, ts in SEEN_WEBHOOK_KEYS.items() if now_ts - ts > 60]
        for k in to_del:
            del SEEN_WEBHOOK_KEYS[k]
        if dedup_key in SEEN_WEBHOOK_KEYS:
            logger.info(f"Ignoring duplicate webhook for key '{dedup_key}'")
            return {"status": "ignored", "reason": "Duplicate webhook payload"}
        SEEN_WEBHOOK_KEYS[dedup_key] = now_ts

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

    # Handle Incoming WhatsApp Call event (CALL / call / call.updated)
    is_call_event = (
        event_type in ["call", "CALL", "call.updated", "call_received"] or
        "call" in str(event_type).lower() or
        data.get("status") in ["offer", "ringing"] or
        "caller" in data
    )

    if is_call_event:
        status_call = data.get("status", "offer")
        # Only record new call offer / ringing events to avoid duplicate terminate logs
        if status_call not in ["offer", "ringing"]:
            return {"status": "ignored", "reason": f"Call status '{status_call}' ignored"}

        raw_phone = data.get("caller") or data.get("from") or data.get("chatId") or data.get("key", {}).get("remoteJid", "")
        raw_phone = raw_phone.split("@")[0] if "@" in str(raw_phone) else str(raw_phone)
        phone_number = "".join(filter(str.isdigit, raw_phone))


        is_video = data.get("isVideo", False)
        call_type_label = "Vídeo Chamada" if is_video else "Chamada de Voz por Telefone"
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

        # Find contact by phone or latest active conversation
        contact = None
        if phone_number and len(phone_number) >= 8:
            c_stmt = select(Contact).where(Contact.telefone.like(f"%{phone_number[-8:]}%"))
            c_res = await db.execute(c_stmt)
            contact = c_res.scalars().first()

        if not contact:
            # Fallback: get contact from latest active conversation of this whatsapp_number
            conv_recent = select(Conversation).options(selectinload(Conversation.contact)).where(
                Conversation.whatsapp_number_id == wn.id
            ).order_by(Conversation.ultima_interacao_em.desc())
            cr_res = await db.execute(conv_recent)
            conv_obj = cr_res.scalars().first()
            if conv_obj and conv_obj.contact:
                contact = conv_obj.contact

        if not contact:
            contact = Contact(
                tenant_id=wn.tenant_id,
                nome=push_name,
                telefone=phone_number or "Cliente",
                criado_em=datetime.utcnow()
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

        now = datetime.utcnow()
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

        # Check deduplication for call alert message (within 30s)
        recent_msg_stmt = select(Message).where(
            Message.conversation_id == conv.id,
            Message.conteudo.like("%O CLIENTE ESTÁ LIGANDO%")
        ).order_by(Message.timestamp.desc())
        recent_msg_res = await db.execute(recent_msg_stmt)
        last_call_msg = recent_msg_res.scalars().first()

        if last_call_msg and (now - last_call_msg.timestamp).total_seconds() < 30.0:
            return {"status": "ignored", "reason": "Call alert already logged recently"}

        # Register alert message in the chat timeline
        call_msg_text = (
            f"📞 *O CLIENTE ESTÁ LIGANDO VIA {call_type_label.upper()} DO WHATSAPP!*\n\n"
            f"⚠️ Chamada de voz em tempo real recebida do aplicativo do cliente.\n\n"
            f"👉 *Clique no botão '📹 Chamada Vídeo/Voz' no topo deste chat para abrir uma sala de atendimento ao vivo em HD com o cliente!*"
        )

        call_msg = Message(
            conversation_id=conv.id,
            remetente="cliente",
            tipo=MessageType.TEXTO,
            conteudo=call_msg_text,
            timestamp=now
        )
        db.add(call_msg)
        await db.commit()
        await db.refresh(call_msg)

        # Broadcast live call WebSocket alert
        try:
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
                msg_to_update = m_res.scalar_one_or_none()

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

    # Filter non-message events (send.message, chats.upsert, etc.)
    if norm_event not in ["messages.upsert", "messages_upsert"]:
        return {"status": "ignored", "reason": f"Event '{event_type}' is not a new incoming message"}

    key = data.get("key", {}) if isinstance(data, dict) else {}
    from_me = key.get("fromMe", False) if isinstance(key, dict) else False

    # Ignore messages sent by ourselves
    if from_me:
        return {"status": "ignored", "reason": "Outgoing message"}

    remote_jid = key.get("remoteJid", "") if isinstance(key, dict) else ""
    is_group = (
        "@g.us" in str(remote_jid).lower() or
        data.get("isGroup") is True or
        bool(key.get("participant")) or
        "@temp" in str(remote_jid).lower()
    )
    raw_phone = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    phone_number = "".join(filter(str.isdigit, raw_phone))
    push_name = data.get("pushName") or "Cliente"


    message_obj = data.get("message", {})

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

    # Extract text or media content
    text_content = (
        message_obj.get("conversation") or
        message_obj.get("extendedTextMessage", {}).get("text") or
        ""
    )

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
    media_base64 = data.get("base64") or (data.get("media", {}).get("base64") if isinstance(data.get("media"), dict) else None)

    # Check location payload
    loc_msg = message_obj.get("locationMessage")
    if loc_msg:
        msg_type = MessageType.LOCALIZACAO
        c_lat = loc_msg.get("degreesLatitude")
        c_lng = loc_msg.get("degreesLongitude")
        c_name = loc_msg.get("name") or loc_msg.get("address") or "Localização Compartilhada pelo Cliente"
        c_addr = loc_msg.get("address") or ""
        text_content = f"📍 *LOCALIZAÇÃO RECEBIDA DO CLIENTE*\n{c_name}\n{c_addr}\nhttps://maps.google.com/?q={c_lat},{c_lng}"

    if (img_msg or vid_msg or aud_msg or doc_msg or stk_msg) and not media_base64 and msg_id:
        try:
            media_base64 = await evolution_service.get_media_base64(instance_name, msg_id)
        except Exception as err:
            logger.error(f"Failed to fetch media base64 from Evolution API: {err}")

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
            if media_bytes:
                # Transcribe/understand voice audio note via Gemini Multimodal SDK
                try:
                    dec_sets = await settings_service.get_tenant_decrypted_settings(db, 1)
                    audio_transcription = await gemini_service.process_audio_message(
                        audio_bytes=media_bytes,
                        mime_type="audio/ogg",
                        tenant_gemini_api_key=dec_sets.get("gemini_api_key"),
                        tenant_gemini_model_name=dec_sets.get("gemini_model_name")
                    )
                    if audio_transcription:
                        caption = f"🎙️ *Transcrição do Áudio:*\n_{audio_transcription}_"
                except Exception as audio_err:
                    logger.error(f"Error transcribing customer audio note: {audio_err}")
        elif doc_msg:
            msg_type = MessageType.ARQUIVO
            caption = doc_msg.get("caption") or ""
            doc_filename = doc_msg.get("fileName") or "documento.pdf"
            ext = os.path.splitext(doc_filename)[1] or ".bin"

        # If base64 is present, ALWAYS save file to disk
        saved_media_url = None
        if media_bytes:
            try:
                os.makedirs("uploads", exist_ok=True)
                unique_name = f"{uuid.uuid4().hex}{ext}"
                media_path = os.path.join("uploads", unique_name)
                with open(media_path, "wb") as f:
                    f.write(media_bytes)

                saved_media_url = f"/uploads/{unique_name}"
            except Exception as e:
                logger.error(f"Error saving incoming media file: {e}")

        if saved_media_url:
            text_content = f"{saved_media_url}|{caption}" if caption else saved_media_url
        else:
            # Fallback to direct media URL if base64 decoding was not available
            target_obj = stk_msg or img_msg or vid_msg or aud_msg or doc_msg or {}
            fallback_url = target_obj.get("url") or target_obj.get("directPath") or ""
            if fallback_url:
                text_content = f"{fallback_url}|{caption}" if caption else fallback_url
            elif caption:
                text_content = caption
            elif stk_msg:
                text_content = "[Figurinha do WhatsApp]"

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

    # 2. Get or Create Contact (matching exact phone, 8/9 digit variants or suffix match)
    phone_variants = [phone_number]
    if len(phone_number) == 13 and phone_number.startswith("55"):
        # e.g., 55 61 9 8334 8333 -> variant without extra 9: 55 61 8334 8333
        phone_variants.append(phone_number[:4] + phone_number[5:])
    elif len(phone_number) == 12 and phone_number.startswith("55"):
        # e.g., 55 61 8334 8333 -> variant with 9: 55 61 9 8334 8333
        phone_variants.append(phone_number[:4] + "9" + phone_number[4:])

    if len(phone_number) >= 8 and not is_group:
        contact_stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            (Contact.telefone.in_(phone_variants) | Contact.telefone.like(f"%{phone_number[-8:]}%"))
        )
    else:
        contact_stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.telefone.in_(phone_variants)
        )
    contact_res = await db.execute(contact_stmt)
    contact = contact_res.scalars().first()

    profile_pic_url = data.get("profilePicUrl") or (data.get("sender") or {}).get("profilePicUrl") or (data.get("contact") or {}).get("profilePicUrl")

    # If message is from a WhatsApp Group, fetch official group subject / title
    if is_group:
        try:
            g_info = await asyncio.wait_for(
                evolution_service.fetch_group_info(whatsapp_number.instancia_evolution_api, remote_jid),
                timeout=2.5
            )
            if g_info and isinstance(g_info, dict):
                group_subject = g_info.get("subject") or g_info.get("name")
                if group_subject:
                    push_name = group_subject
                if g_info.get("pictureUrl"):
                    profile_pic_url = g_info.get("pictureUrl")
        except Exception:
            pass

    if not profile_pic_url and (not contact or not contact.foto_perfil_url) and whatsapp_number.instancia_evolution_api:
        try:
            profile_pic_url = await asyncio.wait_for(
                evolution_service.fetch_profile_picture_url(whatsapp_number.instancia_evolution_api, phone_number),
                timeout=2.0
            )
        except Exception:
            profile_pic_url = None

    if not contact:
        contact = Contact(tenant_id=tenant_id, telefone=phone_number, nome=push_name, foto_perfil_url=profile_pic_url)
        db.add(contact)
        await db.flush()
    else:
        if push_name and push_name != "Cliente" and (not contact.nome or contact.nome == "Cliente" or is_group):
            contact.nome = push_name
        if profile_pic_url and contact.foto_perfil_url != profile_pic_url:
            contact.foto_perfil_url = profile_pic_url

    # 3. Get or Create Conversation (Always reuse single active conversation for this contact across tenant)
    conv_stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
            Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO])
        )
        .order_by(Conversation.ultima_interacao_em.desc())
    )
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalars().first()

    if not conversation:
        # Also check if there is ANY conversation for this contact in tenant to reopen instead of duplicating
        any_conv_stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.contact_id == contact.id
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
                conversation.status = ConversationStatus.COM_IA
                conversation.protocol_number = await generate_daily_protocol(db, tenant_id)
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

    if not conversation.protocol_number:
        conversation.protocol_number = await generate_daily_protocol(db, tenant_id)

    conversation.ultima_interacao_em = datetime.utcnow()

    # 4. Save Customer Message with WhatsApp Message ID
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
    await db.commit()

    # Broadcast customer message via WebSockets to agents
    await ws_manager.broadcast_to_department(
        tenant_id=tenant_id,
        whatsapp_number_id=whatsapp_number.id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conversation.id,
            "remetente": MessageSender.CLIENTE.value,
            "conteudo": text_content,
            "timestamp": user_msg.timestamp.isoformat() + "Z" if hasattr(user_msg.timestamp, "isoformat") else str(user_msg.timestamp),
            "contact_name": contact.nome,
            "contact_phone": contact.telefone,
            "department": whatsapp_number.nome_departamento
        }
    )

    # Auto Re-engagement / Anti-Vacuum logic:
    # If conversation is currently COM_HUMANO, check if customer is sending a greeting or if human agent hasn't replied recently
    if conversation.status == ConversationStatus.COM_HUMANO:
        should_reactivate_ai = False

        text_lower = text_content.strip().lower()
        greetings = ["oi", "olá", "ola", "boa tarde", "bom dia", "boa noite", "oie", "opa", "atendimento", "ajuda", "falar com ia", "menu"]
        is_greeting = any(g in text_lower for g in greetings)

        # Query latest attendant message safely in async SQLAlchemy
        att_stmt = select(Message).where(
            Message.conversation_id == conversation.id,
            Message.remetente == MessageSender.ATENDENTE
        ).order_by(Message.timestamp.desc()).limit(1)
        att_res = await db.execute(att_stmt)
        last_attendant_msg = att_res.scalar_one_or_none()

        if not last_attendant_msg:
            should_reactivate_ai = True
        else:
            time_diff_min = (datetime.utcnow() - last_attendant_msg.timestamp).total_seconds() / 60.0
            if time_diff_min >= 3.0 or is_greeting:
                should_reactivate_ai = True

        if should_reactivate_ai:
            conversation.status = ConversationStatus.COM_IA
            logger.info(f"[IA REATIVADA AUTOMATICAMENTE] Conversa {conversation.id} com {contact.nome or contact.telefone} reativada para COM_IA.")
            await ws_manager.broadcast_to_department(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                message_data={
                    "type": "STATUS_CHANGE",
                    "conversation_id": conversation.id,
                    "status": "com_ia"
                }
            )



    # 5. Process AI Concierge response if conversation is with AI
    current_status_str = getattr(conversation.status, 'value', str(conversation.status))
    if current_status_str == ConversationStatus.COM_IA.value or conversation.status == ConversationStatus.COM_IA:


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

        # Fetch RAG Context (Geral + Department Specific)
        rag_context = await rag_service.search_context(
            tenant_id=tenant_id,
            query=text_content,
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

        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

        # Check if conversation was waiting for customer confirmation on sector transfer
        is_pending_transfer = (conversation.assunto_atual or "").startswith("CONFIRM_TRANSFER:")
        transfer_executed = False
        ai_output = None

        if is_pending_transfer:
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

        if not transfer_executed:
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
                    conversation.assunto_atual = f"CONFIRM_TRANSFER:{target_wn.id}:{intent_summary}"
                else:
                    ai_output = await gemini_service.generate_concierge_response(
                        customer_name=contact.nome or "Cliente",
                        department_name=whatsapp_number.nome_departamento,
                        user_message=text_content,
                        conversation_history=history,
                        memory_summary=memory_summary,
                        rag_context=rag_context,
                        available_departments=available_dept_names,
                        tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                        tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
                    )
            else:
                ai_output = await gemini_service.generate_concierge_response(
                    customer_name=contact.nome or "Cliente",
                    department_name=whatsapp_number.nome_departamento,
                    user_message=text_content,
                    conversation_history=history,
                    memory_summary=memory_summary,
                    rag_context=rag_context,
                    available_departments=available_dept_names,
                    tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
                    tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
                )

        ai_reply = ai_output["resposta"]
        transferir_setor = ai_output.get("transferir_setor", "NENHUM")
        enviar_localizacao = ai_output.get("enviar_localizacao", False)
        enviar_pix = ai_output.get("enviar_pix", False)
        escalar_humano = ai_output.get("escalar_humano", False)
        nova_memoria = ai_output.get("nova_memoria", "")

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

        # Save AI Response Text Message
        ai_msg = Message(
            conversation_id=conversation.id,
            remetente=MessageSender.IA,
            conteudo=ai_reply,
            tipo=MessageType.TEXTO,
            timestamp=datetime.utcnow()
        )
        db.add(ai_msg)

        # Dispatch Native WhatsApp Location Message if requested by customer/IA
        if enviar_localizacao:
            # Official Servweld location coordinates: SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF (-15.820418, -47.956467)
            loc_name = "Servweld / Servsolda"
            loc_addr = "SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226"
            loc_lat = -15.820418
            loc_lng = -47.956467

            # Try sending via incoming instance first (the exact line customer contacted), fallback to all tenant instances if needed
            instances_to_try = [instance_name] + [wn.instancia_evolution_api for wn in all_wns if wn.instancia_evolution_api != instance_name]
            
            loc_sent = False
            for inst in instances_to_try:
                if not inst:
                    continue
                res_loc = await evolution_service.send_location_message(
                    instance_name=inst,
                    number=contact.telefone,
                    latitude=loc_lat,
                    longitude=loc_lng,
                    name=loc_name,
                    address=loc_addr
                )
                if res_loc.get("success"):
                    logger.info(f"Successfully sent native location card to {contact.telefone} via instance '{inst}'")
                    loc_sent = True
                    break
                else:
                    logger.warning(f"Failed to send location via instance '{inst}': {res_loc.get('error')}")

            if loc_sent:
                # Record location message in conversation DB
                loc_db_msg = Message(
                    conversation_id=conversation.id,
                    remetente=MessageSender.IA,
                    conteudo=f"📍 *LOCALIZAÇÃO ENVIADA*\n{loc_name}\n{loc_addr}\nhttps://maps.google.com/?q={loc_lat},{loc_lng}",
                    tipo=MessageType.LOCALIZACAO,
                    timestamp=datetime.utcnow()
                )
                db.add(loc_db_msg)
            else:
                # Fallback: if native map card dispatch fails across all instances, ensure Google Maps link is included in text reply
                maps_link = f"https://maps.google.com/?q={loc_lat},{loc_lng}"
                if maps_link not in ai_reply:
                    ai_reply += f"\n\n📍 *Localização no Google Maps:* {maps_link}"

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
            conversation.status = ConversationStatus.COM_HUMANO
            
            # Find and assign the least busy eligible operator
            assigned_user = await assign_least_busy_attendant(db, tenant_id, whatsapp_number.id)
            assigned_user_name = "Equipe"
            if assigned_user:
                conversation.assigned_user_id = assigned_user.id
                assigned_user_name = assigned_user.nome

            logger.info(f"Conversation {conversation.id} escalated and assigned to {assigned_user_name} (least busy operator).")

            # Create pinned system transfer card
            sys_escalate_msg = Message(
                conversation_id=conversation.id,
                remetente="sistema",
                conteudo=f"📌 *RESUMO DA TRANSFERÊNCIA DA IA:*\n{nova_memoria or memory_summary or 'Cliente solicita atendimento com operador.'}",
                tipo=MessageType.TEXTO,
                timestamp=datetime.utcnow()
            )
            db.add(sys_escalate_msg)

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

        # Send AI reply back to WhatsApp via Evolution API with header
        formatted_ai_text = f"*🤖 IA Concierge:*\n\n{ai_reply}"
        await evolution_service.send_text_message(
            instance_name=instance_name,
            number=phone_number,
            text=formatted_ai_text
        )

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

    else:
        await db.commit()

    return {"status": "success"}
