from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Conversation, Message, User, WhatsAppNumber, TransferLog,
    ConversationStatus, MessageSender, MessageType, user_number_access
)
from app.schemas.schemas import ConversationResponse, MessageCreate, MessageResponse, ConversationTransfer
from app.services.evolution_service import evolution_service
from app.api.websockets import manager as ws_manager

router = APIRouter(prefix="/conversations", tags=["Conversas e Mensagens"])

@router.get("/", response_model=List[ConversationResponse])
async def list_conversations(
    status_filter: Optional[ConversationStatus] = None,
    whatsapp_number_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role == "admin":
        wn_stmt = select(WhatsAppNumber.id).where(WhatsAppNumber.tenant_id == current_user.tenant_id)
    else:
        wn_stmt = (
            select(WhatsAppNumber.id)
            .join(user_number_access)
            .where(
                WhatsAppNumber.tenant_id == current_user.tenant_id,
                user_number_access.c.user_id == current_user.id
            )
        )
    wn_res = await db.execute(wn_stmt)
    accessible_wn_ids = wn_res.scalars().all()

    if not accessible_wn_ids:
        return []

    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.whatsapp_number_id.in_(accessible_wn_ids)
        )
    )

    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter)
    if whatsapp_number_id:
        if whatsapp_number_id not in accessible_wn_ids:
            raise HTTPException(status_code=403, detail="Acesso negado a este número de WhatsApp")
        stmt = stmt.where(Conversation.whatsapp_number_id == whatsapp_number_id)

    stmt = stmt.order_by(Conversation.ultima_interacao_em.desc())
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_detail(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    return conv

@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_agent_message(
    conversation_id: int,
    msg_in: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Sends a message from a human agent to the customer via Evolution API.
    Enforces delivery error checking: if Evolution API fails, message is NOT saved as delivered.
    """
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # 1. Attempt Dispatch to WhatsApp via Evolution API first
    evo_res = await evolution_service.send_text_message(
        instance_name=conv.whatsapp_number.instancia_evolution_api,
        number=conv.contact.telefone,
        text=msg_in.conteudo
    )

    # 2. If delivery failed and not in test/mock override, raise HTTP error and do not commit message
    if not evo_res.get("success", False):
        error_detail = evo_res.get("error", "Erro de conexão com a Evolution API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao enviar mensagem no WhatsApp (Evolution API): {error_detail}"
        )

    # 3. Save Message only after successful delivery confirmation
    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    message = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=msg_in.conteudo,
        tipo=msg_in.tipo,
        timestamp=datetime.utcnow()
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # 4. Broadcast real-time update
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "remetente": MessageSender.ATENDENTE.value,
            "conteudo": msg_in.conteudo,
            "timestamp": str(message.timestamp),
            "agent_name": current_user.nome
        }
    )

    return message

@router.post("/{conversation_id}/transfer")
async def transfer_conversation(
    conversation_id: int,
    transfer_in: ConversationTransfer,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    old_user_id = conv.assigned_user_id
    conv.assigned_user_id = transfer_in.para_user_id

    log = TransferLog(
        conversation_id=conv.id,
        de_user_id=old_user_id,
        para_user_id=transfer_in.para_user_id,
        motivo=transfer_in.motivo,
        timestamp=datetime.utcnow()
    )
    db.add(log)
    await db.commit()

    return {"status": "success", "message": "Conversa transferida com sucesso"}
