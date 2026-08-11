from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_admin_user, get_password_hash
from app.models.models import User, WhatsAppNumber
from app.schemas.schemas import UserCreate, UserUpdate, UserResponse

router = APIRouter(prefix="/users", tags=["Gestão de Usuários e Permissões"])

@router.get("/", response_model=List[UserResponse])
async def list_users(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(User)
        .options(selectinload(User.whatsapp_numbers))
        .where(User.tenant_id == admin_user.tenant_id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    existing_stmt = select(User).where(User.login == user_in.login)
    existing_res = await db.execute(existing_stmt)
    if existing_res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Login já está em uso")

    new_user = User(
        tenant_id=admin_user.tenant_id,
        nome=user_in.nome,
        login=user_in.login,
        senha_hash=get_password_hash(user_in.senha),
        role=user_in.role,
        status=user_in.status
    )

    if user_in.whatsapp_number_ids:
        numbers_stmt = select(WhatsAppNumber).where(
            WhatsAppNumber.id.in_(user_in.whatsapp_number_ids),
            WhatsAppNumber.tenant_id == admin_user.tenant_id
        )
        numbers_res = await db.execute(numbers_stmt)
        new_user.whatsapp_numbers = numbers_res.scalars().all()

    db.add(new_user)
    await db.commit()
    
    stmt = select(User).options(selectinload(User.whatsapp_numbers)).where(User.id == new_user.id)
    res = await db.execute(stmt)
    return res.scalar_one()

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(User).options(selectinload(User.whatsapp_numbers)).where(
        User.id == user_id,
        User.tenant_id == admin_user.tenant_id
    )
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if user_in.login and user_in.login != user.login:
        chk_stmt = select(User).where(User.login == user_in.login, User.id != user_id)
        chk_res = await db.execute(chk_stmt)
        if chk_res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Login já utilizado por outro usuário")
        user.login = user_in.login

    if user_in.nome:
        user.nome = user_in.nome
    if user_in.senha and user_in.senha.strip() != "":
        user.senha_hash = get_password_hash(user_in.senha)
    if user_in.role:
        user.role = user_in.role
    if user_in.status is not None:
        user.status = user_in.status

    if user_in.whatsapp_number_ids is not None:
        numbers_stmt = select(WhatsAppNumber).where(
            WhatsAppNumber.id.in_(user_in.whatsapp_number_ids),
            WhatsAppNumber.tenant_id == admin_user.tenant_id
        )
        numbers_res = await db.execute(numbers_stmt)
        user.whatsapp_numbers = numbers_res.scalars().all()

    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: int,
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    if user_id == admin_user.id:
        raise HTTPException(status_code=400, detail="Você não pode excluir seu próprio usuário logado.")

    stmt = select(User).where(
        User.id == user_id,
        User.tenant_id == admin_user.tenant_id
    )
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    await db.delete(user)
    await db.commit()
    return {"status": "success", "message": "Usuário excluído com sucesso"}
