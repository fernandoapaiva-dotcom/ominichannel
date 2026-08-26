import os
import base64
from datetime import datetime, timedelta
from typing import Optional
import jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.models.models import User, UserRole
from app.schemas.schemas import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

# --- Fernet Symmetric Encryption Helpers ---
def _get_fernet_key() -> bytes:
    master_key = os.environ.get("ENCRYPTION_MASTER_KEY", settings.SECRET_KEY)
    key_bytes = master_key.encode("utf-8")
    if len(key_bytes) < 32:
        key_bytes = key_bytes.ljust(32, b"0")
    else:
        key_bytes = key_bytes[:32]
    return base64.urlsafe_b64encode(key_bytes)

_FERNET_INSTANCE: Optional[Fernet] = None

def _get_fernet() -> Fernet:
    global _FERNET_INSTANCE
    if _FERNET_INSTANCE is None:
        _FERNET_INSTANCE = Fernet(_get_fernet_key())
    return _FERNET_INSTANCE

def encrypt_data(plain_text: str) -> str:
    if not plain_text:
        return ""
    return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_data(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        return _get_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""

def mask_sensitive_string(val: str) -> str:
    if not val:
        return "Nao configurado"
    if len(val) <= 8:
        return "*******"
    return f"{val[:4]}...****{val[-4:]}"

# --- CSRF OAuth State Protection ---
def create_oauth_state(tenant_id: int, user_id: int) -> str:
    payload = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "type": "oauth_state",
        "exp": datetime.utcnow() + timedelta(minutes=10)
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def verify_oauth_state(state_token: str) -> dict:
    try:
        payload = jwt.decode(state_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "oauth_state":
            raise ValueError("Token state invalido")
        return payload
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ataque CSRF detectado ou parâmetro 'state' do Google OAuth2 inválido/expirado."
        )

# --- JWT Auth Helpers ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token de autenticação inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = payload.get("sub")
        tenant_id: int = payload.get("tenant_id")
        role: str = payload.get("role")
        if user_id is None or tenant_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=user_id, tenant_id=tenant_id, role=UserRole(role))
    except jwt.PyJWTError:
        raise credentials_exception

    stmt = select(User).where(User.id == token_data.user_id, User.tenant_id == token_data.tenant_id, User.status == True)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user

async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores"
        )
    return current_user
