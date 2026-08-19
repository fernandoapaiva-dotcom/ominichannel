import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Request, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.models import (
    WhatsAppNumber, Contact, Conversation, Message, ConversationMemory,
    ConversationStatus, MessageSender, MessageType, WhatsAppGroup, User, UserRole
)

from app.services.evolution_service import evolution_service
from app.services.gemini_service import gemini_service
from app.services.rag_service import rag_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("webhooks")
router = APIRouter(prefix="/webhooks", tags=["Webhooks Integration"])

SEEN_WEBHOOK_KEYS = {}

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
            g_stmt = select(WhatsAppGroup).where(
                WhatsAppGroup.tenant_id == tenant_id,
                WhatsAppGroup.whatsapp_number_id == whatsapp_number.id,
                WhatsAppGroup.group_jid == remote_jid
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

        # Fetch RAG Context
        rag_context = await rag_service.search_context(tenant_id=tenant_id, query=text_content)

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

        from app.services.settings_service import settings_service
        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

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
        escalar_humano = ai_output["escalar_humano"]
        nova_memoria = ai_output["nova_memoria"]

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
            
            # Find and assign the least busy eligible operator
            assigned_user = await assign_least_busy_attendant(db, tenant_id, whatsapp_number.id)
            assigned_user_name = "Equipe"
            if assigned_user:
                conversation.assigned_user_id = assigned_user.id
                assigned_user_name = assigned_user.nome

            logger.info(f"Conversation {conversation.id} escalated and assigned to {assigned_user_name} (least busy operator).")

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
