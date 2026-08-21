from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, cast, String
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Contact, Conversation, Message, User
from app.schemas.schemas import ContactWithHistoryResponse, ConversationResponse

router = APIRouter(prefix="/contacts", tags=["Histórico de Clientes & Contatos"])

@router.get("/", response_model=List[ContactWithHistoryResponse])
async def list_contacts(
    q: Optional[str] = Query(None, description="Busca por nome, telefone ou número de protocolo"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists tenant contacts with conversation counts and universal search filter (nome, telefone ou protocolo).
    """
    stmt = (
        select(
            Contact,
            func.count(Conversation.id).label("total_conversations"),
            func.max(Conversation.ultima_interacao_em).label("ultima_interacao")
        )
        .outerjoin(Conversation, (Conversation.contact_id == Contact.id) & (Conversation.tenant_id == current_user.tenant_id))
        .where(Contact.tenant_id == current_user.tenant_id)
        .group_by(Contact.id)
    )

    if q and q.strip():
        clean_q = q.strip()
        search = f"%{clean_q}%"
        proto_clean = clean_q.replace('#', '').strip()
        proto_search = f"%{proto_clean}%"

        proto_conv_subq = (
            select(Conversation.contact_id)
            .where(
                Conversation.tenant_id == current_user.tenant_id,
                or_(
                    Conversation.protocol_number.ilike(proto_search),
                    cast(Conversation.dados_adicionais, String).ilike(proto_search)
                )
            )
        )

        proto_msg_subq = (
            select(Conversation.contact_id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.tenant_id == current_user.tenant_id,
                Message.conteudo.ilike(proto_search)
            )
        )

        stmt = stmt.where(
            or_(
                Contact.nome.ilike(search),
                Contact.telefone.like(search),
                Contact.id.in_(proto_conv_subq),
                Contact.id.in_(proto_msg_subq)
            )
        )

    stmt = stmt.order_by(func.max(Conversation.ultima_interacao_em).desc().nulls_last(), Contact.id.desc())
    res = await db.execute(stmt)
    rows = res.all()

    output = []
    for contact, count_convs, last_inter in rows:
        c_dict = {
            "id": contact.id,
            "tenant_id": contact.tenant_id,
            "telefone": contact.telefone,
            "nome": contact.nome,
            "dados_adicionais": contact.dados_adicionais,
            "total_conversations": count_convs or 0,
            "ultima_interacao": last_inter
        }
        output.append(ContactWithHistoryResponse(**c_dict))

    return output

@router.get("/{contact_id}/conversations", response_model=List[ConversationResponse])
async def get_contact_conversation_history(
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches all historical conversations and full message transcripts for a specific contact.
    """
    contact_stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.tenant_id == current_user.tenant_id
    )
    c_res = await db.execute(contact_stmt)
    contact = c_res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.contact_id == contact_id,
            Conversation.tenant_id == current_user.tenant_id
        )
        .order_by(Conversation.ultima_interacao_em.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()

from pydantic import BaseModel

class UpdateContactPayload(BaseModel):
    nome: str

@router.put("/{contact_id}")
async def update_contact(
    contact_id: int,
    payload: UpdateContactPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates contact's name.
    """
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    contact = res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    contact.nome = payload.nome.strip()
    await db.commit()
    await db.refresh(contact)
    return {
        "status": "success",
        "message": "Nome do contato atualizado com sucesso",
        "id": contact.id,
        "nome": contact.nome,
        "telefone": contact.telefone
    }
