from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import TenantPixKey, User, UserRole
from app.schemas.schemas import PixKeyCreate, PixKeyUpdate, PixKeyResponse

router = APIRouter(prefix="/pix-keys", tags=["Cadastro e Gerenciador de Chaves Pix"])

@router.get("/", response_model=List[PixKeyResponse])
async def list_pix_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists all configured Pix keys for the tenant.
    """
    stmt = (
        select(TenantPixKey)
        .where(TenantPixKey.tenant_id == current_user.tenant_id)
        .order_by(TenantPixKey.id.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/", response_model=PixKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_pix_key(
    payload: PixKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a new Pix key for the tenant.
    """
    pix_item = TenantPixKey(
        tenant_id=current_user.tenant_id,
        titulo=payload.titulo.strip(),
        tipo_chave=payload.tipo_chave.upper().strip(),
        chave=payload.chave.strip(),
        favorecido=payload.favorecido.strip(),
        cidade=payload.cidade.strip() or "BRASILIA",
        descricao=payload.descricao.strip() if payload.descricao else None,
        ativo=payload.ativo
    )
    db.add(pix_item)
    await db.commit()
    await db.refresh(pix_item)
    return pix_item

@router.put("/{key_id}", response_model=PixKeyResponse)
async def update_pix_key(
    key_id: int,
    payload: PixKeyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates an existing Pix key.
    """
    stmt = select(TenantPixKey).where(
        TenantPixKey.id == key_id,
        TenantPixKey.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    pix_item = res.scalar_one_or_none()
    if not pix_item:
        raise HTTPException(status_code=404, detail="Chave Pix não encontrada")

    if payload.titulo is not None:
        pix_item.titulo = payload.titulo.strip()
    if payload.tipo_chave is not None:
        pix_item.tipo_chave = payload.tipo_chave.upper().strip()
    if payload.chave is not None:
        pix_item.chave = payload.chave.strip()
    if payload.favorecido is not None:
        pix_item.favorecido = payload.favorecido.strip()
    if payload.cidade is not None:
        pix_item.cidade = payload.cidade.strip()
    if payload.descricao is not None:
        pix_item.descricao = payload.descricao.strip()
    if payload.ativo is not None:
        pix_item.ativo = payload.ativo

    await db.commit()
    await db.refresh(pix_item)
    return pix_item

@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pix_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes a Pix key.
    """
    stmt = select(TenantPixKey).where(
        TenantPixKey.id == key_id,
        TenantPixKey.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    pix_item = res.scalar_one_or_none()
    if not pix_item:
        raise HTTPException(status_code=404, detail="Chave Pix não encontrada")

    await db.delete(pix_item)
    await db.commit()
    return None
