from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Contact, Conversation, User
from app.schemas.schemas import ContactWithHistoryResponse, ConversationResponse

router = APIRouter(prefix="/contacts", tags=["Histórico de Clientes & Contatos"])

@router.get("/", response_model=List[ContactWithHistoryResponse])
async def list_contacts(
    q: Optional[str] = Query(None, description="Busca por nome ou telefone"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists tenant contacts with conversation counts and search filter.
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
        search = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.nome.ilike(search),
                Contact.telefone.like(search)
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
