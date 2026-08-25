import re
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import AuthorizedTechnician, User, UserRole
from app.schemas.schemas import AuthorizedTechnicianCreate, AuthorizedTechnicianUpdate, AuthorizedTechnicianResponse

router = APIRouter(prefix="/technicians", tags=["Técnicos Autorizados (Copiloto RAG)"])

def clean_phone_digits(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('55') and len(digits) >= 12:
        return digits
    elif len(digits) in [10, 11]:
        return f"55{digits}"
    return digits

@router.get("/", response_model=List[AuthorizedTechnicianResponse])
async def list_technicians(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists all authorized technicians for the tenant.
    """
    stmt = (
        select(AuthorizedTechnician)
        .where(AuthorizedTechnician.tenant_id == current_user.tenant_id)
        .order_by(AuthorizedTechnician.nome.asc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/", response_model=AuthorizedTechnicianResponse, status_code=status.HTTP_201_CREATED)
async def create_technician(
    payload: AuthorizedTechnicianCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Registers a new authorized technician who will receive deep RAG repair assistance.
    """
    clean_phone = clean_phone_digits(payload.telefone)
    if not clean_phone or len(clean_phone) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telefone inválido. Informe o DDD e o número com ou sem DDI (ex: 5561999998888 ou 61999998888)."
        )

    # Check for duplicate phone in same tenant
    check_stmt = select(AuthorizedTechnician).where(
        AuthorizedTechnician.tenant_id == current_user.tenant_id,
        AuthorizedTechnician.telefone == clean_phone
    )
    check_res = await db.execute(check_stmt)
    existing = check_res.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Já existe um técnico cadastrado com o telefone {clean_phone} ({existing.nome})."
        )

    tech = AuthorizedTechnician(
        tenant_id=current_user.tenant_id,
        nome=payload.nome.strip(),
        telefone=clean_phone,
        cargo=payload.cargo.strip() if payload.cargo else None,
        departamento=payload.departamento.strip() if payload.departamento else None,
        especialidade=payload.especialidade.strip() if payload.especialidade else None,
        ativo=payload.ativo
    )
    db.add(tech)
    await db.commit()
    await db.refresh(tech)
    return tech

@router.put("/{tech_id}", response_model=AuthorizedTechnicianResponse)
async def update_technician(
    tech_id: int,
    payload: AuthorizedTechnicianUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates an authorized technician / store employee.
    """
    stmt = select(AuthorizedTechnician).where(
        AuthorizedTechnician.id == tech_id,
        AuthorizedTechnician.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    tech = res.scalar_one_or_none()
    if not tech:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")

    if payload.nome is not None:
        tech.nome = payload.nome.strip()
    if payload.telefone is not None:
        clean_phone = clean_phone_digits(payload.telefone)
        if not clean_phone or len(clean_phone) < 10:
            raise HTTPException(status_code=400, detail="Telefone inválido.")
        tech.telefone = clean_phone
    if payload.cargo is not None:
        tech.cargo = payload.cargo.strip() if payload.cargo else None
    if payload.departamento is not None:
        tech.departamento = payload.departamento.strip() if payload.departamento else None
    if payload.especialidade is not None:
        tech.especialidade = payload.especialidade.strip() if payload.especialidade else None
    if payload.ativo is not None:
        tech.ativo = payload.ativo

    await db.commit()
    await db.refresh(tech)
    return tech

@router.delete("/{tech_id}", status_code=status.HTTP_200_OK)
async def delete_technician(
    tech_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes an authorized technician.
    """
    stmt = select(AuthorizedTechnician).where(
        AuthorizedTechnician.id == tech_id,
        AuthorizedTechnician.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    tech = res.scalar_one_or_none()
    if not tech:
        raise HTTPException(status_code=404, detail="Técnico não encontrado")

    await db.delete(tech)
    await db.commit()
    return {"status": "success", "message": "Técnico removido com sucesso"}
