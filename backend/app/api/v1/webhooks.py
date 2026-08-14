import logging
from datetime import datetime
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import (
    WhatsAppNumber, Contact, Conversation, Message, ConversationMemory,
    ConversationStatus, MessageSender, MessageType
)
from app.services.evolution_service import evolution_service
from app.services.gemini_service import gemini_service
from app.services.rag_service import rag_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks Integration"])

SEEN_WEBHOOK_KEYS = {}

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
        now_ts = datetime.utcnow().timestamp()
        # Clean cache older than 60s
        to_del = [k for k, ts in SEEN_WEBHOOK_KEYS.items() if now_ts - ts > 60]
        for k in to_del:
            del SEEN_WEBHOOK_KEYS[k]
        if msg_id in SEEN_WEBHOOK_KEYS:
            logger.info(f"Ignoring duplicate webhook for msg_id '{msg_id}'")
            return {"status": "ignored", "reason": "Duplicate webhook payload"}
        SEEN_WEBHOOK_KEYS[msg_id] = now_ts

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

    key = data.get("key", {}) if isinstance(data, dict) else {}
    from_me = key.get("fromMe", False) if isinstance(key, dict) else False

    # Ignore messages sent by ourselves
    if from_me:
        return {"status": "ignored", "reason": "Outgoing message"}

    remote_jid = key.get("remoteJid", "") if isinstance(key, dict) else ""
    raw_phone = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
    phone_number = "".join(filter(str.isdigit, raw_phone))
    if len(phone_number) == 12 and phone_number.startswith("55") and phone_number[4] != "9":
        phone_number = phone_number[:4] + "9" + phone_number[4:]
    # Normalize Brazilian cell numbers: if 13 digits starting with 55+DDD+9+8digits, check 12 digit variant without 9 or vice versa to align contact
    push_name = data.get("pushName") or "Cliente"

    # Extract text or media content
    message_obj = data.get("message", {})
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

    msg_id = key.get("id", "") if isinstance(key, dict) else ""
    media_base64 = data.get("base64") or (data.get("media", {}).get("base64") if isinstance(data.get("media"), dict) else None)

    if (img_msg or vid_msg or aud_msg or doc_msg) and not media_base64 and msg_id:
        try:
            from app.services.evolution_service import evolution_service
            media_base64 = await evolution_service.get_media_base64(instance_name, msg_id)
        except Exception as err:
            logger.error(f"Failed to fetch media base64 from Evolution API: {err}")

    if img_msg or vid_msg or aud_msg or doc_msg:
        caption = ""
        ext = ""
        if img_msg:
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
        elif doc_msg:
            msg_type = MessageType.ARQUIVO
            caption = doc_msg.get("caption") or ""
            doc_filename = doc_msg.get("fileName") or "documento.pdf"
            ext = os.path.splitext(doc_filename)[1] or ".bin"

        # If base64 is present, save file to disk
        if media_base64:
            try:
                import base64
                import os
                import uuid
                os.makedirs("uploads", exist_ok=True)
                if "," in media_base64:
                    media_bytes = base64.b64decode(media_base64.split(",")[1])
                else:
                    media_bytes = base64.b64decode(media_base64)
                unique_name = f"{uuid.uuid4().hex}{ext}"
                media_path = os.path.join("uploads", unique_name)
                with open(media_path, "wb") as f:
                    f.write(media_bytes)

                media_url = f"/uploads/{unique_name}"
                text_content = f"{media_url}|{caption}" if caption else media_url
            except Exception as e:
                logger.error(f"Error decoding incoming media base64: {e}")

        # Fallback to direct media URL if base64 decoding was not available
        if not text_content:
            target_obj = img_msg or vid_msg or aud_msg or doc_msg or {}
            fallback_url = target_obj.get("url") or ""
            if fallback_url:
                text_content = f"{fallback_url}|{caption}" if caption else fallback_url
            elif caption:
                text_content = caption

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

    # 2. Get or Create Contact (matching exact phone or normalized variant)
    phone_variants = [phone_number]
    if len(phone_number) == 13 and phone_number.startswith("55"):
        # e.g., 55 61 9 8334 8333 -> variant without extra 9: 55 61 8334 8333
        phone_variants.append(phone_number[:4] + phone_number[5:])
    elif len(phone_number) == 12 and phone_number.startswith("55"):
        # e.g., 55 61 8334 8333 -> variant with 9: 55 61 9 8334 8333
        phone_variants.append(phone_number[:4] + "9" + phone_number[4:])

    contact_stmt = select(Contact).where(
        Contact.tenant_id == tenant_id,
        Contact.telefone.in_(phone_variants)
    )
    contact_res = await db.execute(contact_stmt)
    contact = contact_res.scalars().first()

    if not contact:
        contact = Contact(tenant_id=tenant_id, telefone=phone_number, nome=push_name)
        db.add(contact)
        await db.flush()
    elif push_name and push_name != "Cliente" and (not contact.nome or contact.nome == "Cliente"):
        contact.nome = push_name

    # 3. Get or Create Conversation (Always reuse open/existing active conversation for this contact and department)
    conv_stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.whatsapp_number_id == whatsapp_number.id,
            Conversation.contact_id == contact.id,
            Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO])
        )
        .order_by(Conversation.ultima_interacao_em.desc())
    )
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalars().first()

    if not conversation:
        # Also check if there is ANY conversation for this contact to reopen instead of duplicating
        any_conv_stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.whatsapp_number_id == whatsapp_number.id,
                Conversation.contact_id == contact.id
            )
            .order_by(Conversation.ultima_interacao_em.desc())
        )
        any_conv_res = await db.execute(any_conv_stmt)
        conversation = any_conv_res.scalars().first()

        if conversation:
            conversation.status = ConversationStatus.COM_IA
        else:
            conversation = Conversation(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                contact_id=contact.id,
                status=ConversationStatus.COM_IA,
                assunto_atual="Atendimento Concierge"
            )
            db.add(conversation)
            await db.flush()

    conversation.ultima_interacao_em = datetime.utcnow()

    # 4. Save Customer Message
    user_msg = Message(
        conversation_id=conversation.id,
        remetente=MessageSender.CLIENTE,
        conteudo=text_content,
        tipo=msg_type,
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

    # 5. Process AI Concierge response if conversation is with AI
    if conversation.status == ConversationStatus.COM_IA:
        # Fetch Memory Summary
        mem_stmt = select(ConversationMemory).where(
            ConversationMemory.tenant_id == tenant_id,
            ConversationMemory.contact_id == contact.id
        )
        mem_res = await db.execute(mem_stmt)
        memory = mem_res.scalar_one_or_none()
        memory_summary = memory.resumo_estruturado if memory else ""

        # Fetch RAG Context
        rag_context = await rag_service.search_context(tenant_id=tenant_id, query=text_content)

        # Fetch recent messages for AI context
        msg_stmt = select(Message).where(Message.conversation_id == conversation.id).order_by(Message.timestamp.desc()).limit(6)
        msg_res = await db.execute(msg_stmt)
        recent_msgs = list(reversed(msg_res.scalars().all()))

        history = [
            {"remetente": m.remetente.value, "conteudo": m.conteudo}
            for m in recent_msgs
        ]

        from app.services.settings_service import settings_service
        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

        ai_output = await gemini_service.generate_concierge_response(
            customer_name=contact.nome or "Cliente",
            department_name=whatsapp_number.nome_departamento,
            user_message=text_content,
            conversation_history=history,
            memory_summary=memory_summary,
            rag_context=rag_context,
            tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
            tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
        )

        ai_reply = ai_output["resposta"]
        escalar_humano = ai_output["escalar_humano"]
        nova_memoria = ai_output["nova_memoria"]

        # Save AI Response
        ai_msg = Message(
            conversation_id=conversation.id,
            remetente=MessageSender.IA,
            conteudo=ai_reply,
            tipo=MessageType.TEXTO,
            timestamp=datetime.utcnow()
        )
        db.add(ai_msg)

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
            logger.info(f"Conversation {conversation.id} escalated to human agent.")
            
            # Broadcast high-priority escalation alert event to agents!
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
                    "message": f"🚨 ATENÇÃO: Nova conversa com {contact.nome or contact.telefone} no departamento '{whatsapp_number.nome_departamento}' aguardando atendente!"
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
                "conversation_status": conversation.status.value
            }
        )

    else:
        await db.commit()

    return {"status": "success"}
