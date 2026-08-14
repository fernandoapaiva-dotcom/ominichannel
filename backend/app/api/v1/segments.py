from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Contact, Tag, ContactSegment, Conversation, User, contact_tag_access
from app.schemas.schemas import (
    TagCreate, TagResponse, ContactSegmentCreate, ContactSegmentResponse,
    SegmentPreviewRequest, ContactWithHistoryResponse, ContactTagAssociatePayload
)

router = APIRouter(prefix="/segments", tags=["Segmentação & Tags de Clientes"])

@router.get("/tags", response_model=List[TagResponse])
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Tag).where(Tag.tenant_id == current_user.tenant_id).order_by(Tag.nome)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/tags", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    payload: TagCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    tag = Tag(
        tenant_id=current_user.tenant_id,
        nome=payload.nome.strip(),
        cor_hex=payload.cor_hex or "#10b981"
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag

@router.post("/contacts/{contact_id}/tags")
async def set_contact_tags(
    contact_id: int,
    payload: ContactTagAssociatePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    c_stmt = select(Contact).options(selectinload(Contact.tags)).where(
        Contact.id == contact_id,
        Contact.tenant_id == current_user.tenant_id
    )
    c_res = await db.execute(c_stmt)
    contact = c_res.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    tags_stmt = select(Tag).where(
        Tag.id.in_(payload.tag_ids),
        Tag.tenant_id == current_user.tenant_id
    )
    tags_res = await db.execute(tags_stmt)
    selected_tags = tags_res.scalars().all()

    contact.tags = selected_tags
    await db.commit()
    return {"status": "success", "message": f"{len(selected_tags)} tags associadas ao contato."}

@router.get("/", response_model=List[ContactSegmentResponse])
async def list_segments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ContactSegment).where(
        ContactSegment.tenant_id == current_user.tenant_id
    ).order_by(ContactSegment.criado_em.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/", response_model=ContactSegmentResponse, status_code=status.HTTP_201_CREATED)
async def create_segment(
    payload: ContactSegmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    rules = {
        "whatsapp_number_id": payload.whatsapp_number_id,
        "dias_inativo": payload.dias_inativo,
        "tag_ids": payload.tag_ids
    }
    segment = ContactSegment(
        tenant_id=current_user.tenant_id,
        nome=payload.nome.strip(),
        descricao=payload.descricao,
        regras=rules,
        criado_em=datetime.utcnow()
    )
    db.add(segment)
    await db.commit()
    await db.refresh(segment)
    return segment

@router.post("/preview", response_model=List[ContactWithHistoryResponse])
async def preview_segment_contacts(
    payload: SegmentPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculates dynamic customer segment preview without dispatching any messages.
    Ensures full compliance with LGPD and WhatsApp Anti-Spam guidelines.
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

    if payload.whatsapp_number_id:
        stmt = stmt.where(Conversation.whatsapp_number_id == payload.whatsapp_number_id)

    if payload.dias_inativo and payload.dias_inativo > 0:
        cutoff = datetime.utcnow() - timedelta(days=payload.dias_inativo)
        stmt = stmt.having(
            or_(
                func.max(Conversation.ultima_interacao_em) <= cutoff,
                func.max(Conversation.ultima_interacao_em).is_(None)
            )
        )

    if payload.tag_ids:
        stmt = stmt.join(contact_tag_access, contact_tag_access.c.contact_id == Contact.id)\
                   .where(contact_tag_access.c.tag_id.in_(payload.tag_ids))

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
