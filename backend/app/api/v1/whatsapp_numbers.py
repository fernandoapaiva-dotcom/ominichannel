from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_admin_user, get_current_user
from app.models.models import WhatsAppNumber, User, user_number_access
from app.schemas.schemas import WhatsAppNumberCreate, WhatsAppNumberResponse

router = APIRouter(prefix="/whatsapp-numbers", tags=["WhatsApp Numbers & Departments"])

@router.get("/", response_model=List[WhatsAppNumberResponse])
async def list_accessible_whatsapp_numbers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role == "admin":
        stmt = select(WhatsAppNumber).where(WhatsAppNumber.tenant_id == current_user.tenant_id)
    else:
        stmt = (
            select(WhatsAppNumber)
            .join(user_number_access)
            .where(
                WhatsAppNumber.tenant_id == current_user.tenant_id,
                user_number_access.c.user_id == current_user.id
            )
        )
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/", response_model=WhatsAppNumberResponse, status_code=status.HTTP_201_CREATED)
async def create_whatsapp_number(
    wn_in: WhatsAppNumberCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    wn = WhatsAppNumber(
        tenant_id=admin_user.tenant_id,
        numero=wn_in.numero,
        nome_departamento=wn_in.nome_departamento,
        instancia_evolution_api=wn_in.instancia_evolution_api,
        status=wn_in.status
    )
    db.add(wn)
    await db.commit()
    await db.refresh(wn)
    return wn

@router.put("/{number_id}", response_model=WhatsAppNumberResponse)
async def update_whatsapp_number(
    number_id: int,
    wn_in: WhatsAppNumberCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == number_id,
        WhatsAppNumber.tenant_id == admin_user.tenant_id
    )
    res = await db.execute(stmt)
    wn = res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Número de WhatsApp / Departamento não encontrado")

    wn.nome_departamento = wn_in.nome_departamento
    wn.numero = wn_in.numero
    wn.instancia_evolution_api = wn_in.instancia_evolution_api
    wn.status = wn_in.status

    await db.commit()
    await db.refresh(wn)
    return wn

@router.delete("/{number_id}", status_code=status.HTTP_200_OK)
async def delete_whatsapp_number(
    number_id: int,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == number_id,
        WhatsAppNumber.tenant_id == admin_user.tenant_id
    )
    res = await db.execute(stmt)
    wn = res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Número de WhatsApp / Departamento não encontrado")

    await db.delete(wn)
    await db.commit()
    return {"status": "success", "message": "Número de WhatsApp removido com sucesso"}
