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

@router.post("/evolution")
async def receive_evolution_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook handler for Evolution API incoming WhatsApp messages.
    """
    payload = await request.json()
    event_type = payload.get("event")
    data = payload.get("data", {})
    instance_name = payload.get("instance") or data.get("instance")
    key = data.get("key", {})
    from_me = key.get("fromMe", False)

    # Ignore messages sent by ourselves
    if from_me:
        return {"status": "ignored", "reason": "Outgoing message"}

    remote_jid = key.get("remoteJid", "")
    phone_number = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid
    push_name = data.get("pushName") or "Cliente"

    # Extract text content
    message_obj = data.get("message", {})
    text_content = (
        message_obj.get("conversation") or
        message_obj.get("extendedTextMessage", {}).get("text") or
        ""
    )

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

    # 2. Get or Create Contact
    contact_stmt = select(Contact).where(Contact.tenant_id == tenant_id, Contact.telefone == phone_number)
    contact_res = await db.execute(contact_stmt)
    contact = contact_res.scalar_one_or_none()

    if not contact:
        contact = Contact(tenant_id=tenant_id, telefone=phone_number, nome=push_name)
        db.add(contact)
        await db.flush()

    # 3. Get or Create Conversation
    conv_stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.whatsapp_number_id == whatsapp_number.id,
            Conversation.contact_id == contact.id,
            Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO])
        )
    )
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalar_one_or_none()

    if not conversation:
        conversation = Conversation(
            tenant_id=tenant_id,
            whatsapp_number_id=whatsapp_number.id,
            contact_id=contact.id,
            status=ConversationStatus.COM_IA,
            assunto_atual="Atendimento Inicial Concierge"
        )
        db.add(conversation)
        await db.flush()

    conversation.ultima_interacao_em = datetime.utcnow()

    # 4. Save Customer Message
    user_msg = Message(
        conversation_id=conversation.id,
        remetente=MessageSender.CLIENTE,
        conteudo=text_content,
        tipo=MessageType.TEXTO,
        timestamp=datetime.utcnow()
    )
    db.add(user_msg)
    await db.flush()

    # Broadcast customer message via WebSockets to agents
    await ws_manager.broadcast_to_department(
        tenant_id=tenant_id,
        whatsapp_number_id=whatsapp_number.id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conversation.id,
            "remetente": MessageSender.CLIENTE.value,
            "conteudo": text_content,
            "timestamp": str(user_msg.timestamp),
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

        await db.commit()

        # Send AI reply back to WhatsApp via Evolution API
        await evolution_service.send_text_message(
            instance_name=instance_name,
            number=phone_number,
            text=ai_reply
        )

        # Broadcast AI message to WebSocket clients
        await ws_manager.broadcast_to_department(
            tenant_id=tenant_id,
            whatsapp_number_id=whatsapp_number.id,
            message_data={
                "type": "NEW_MESSAGE",
                "conversation_id": conversation.id,
                "remetente": MessageSender.IA.value,
                "conteudo": ai_reply,
                "timestamp": str(ai_msg.timestamp),
                "conversation_status": conversation.status.value
            }
        )

    else:
        await db.commit()

    return {"status": "success"}
