from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from app.models.models import UserRole, ConversationStatus, MessageSender, MessageType

# Token schemas
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    user_id: int
    tenant_id: int
    role: UserRole

# Tenant Schemas
class TenantBase(BaseModel):
    nome: str
    pasta_google_drive_id: Optional[str] = None
    config_geral: Optional[Dict[str, Any]] = Field(default_factory=dict)

class TenantCreate(TenantBase):
    pass

class TenantResponse(TenantBase):
    id: int
    criado_em: datetime
    model_config = ConfigDict(from_attributes=True)

# WhatsAppNumber Schemas
class WhatsAppNumberBase(BaseModel):
    numero: str
    nome_departamento: str
    instancia_evolution_api: str
    status: bool = True

class WhatsAppNumberCreate(WhatsAppNumberBase):
    pass

class WhatsAppNumberResponse(WhatsAppNumberBase):
    id: int
    tenant_id: int
    model_config = ConfigDict(from_attributes=True)

# User Schemas
class UserBase(BaseModel):
    nome: str
    login: str
    role: UserRole = UserRole.ATENDENTE
    status: bool = True

class UserCreate(UserBase):
    senha: str
    whatsapp_number_ids: List[int] = []

class UserUpdate(BaseModel):
    nome: Optional[str] = None
    login: Optional[str] = None
    senha: Optional[str] = None
    role: Optional[UserRole] = None
    status: Optional[bool] = None
    whatsapp_number_ids: Optional[List[int]] = None

class UserResponse(UserBase):
    id: int
    tenant_id: int
    whatsapp_numbers: List[WhatsAppNumberResponse] = []
    model_config = ConfigDict(from_attributes=True)

class UserLogin(BaseModel):
    login: str
    senha: str

# Contact Schemas
class ContactBase(BaseModel):
    telefone: str
    nome: Optional[str] = None
    dados_adicionais: Optional[Dict[str, Any]] = None

class ContactResponse(ContactBase):
    id: int
    tenant_id: int
    model_config = ConfigDict(from_attributes=True)

# Message Schemas
class MessageBase(BaseModel):
    conteudo: str
    tipo: MessageType = MessageType.TEXTO

class MessageCreate(MessageBase):
    conversation_id: int
    remetente: MessageSender

class MessageResponse(MessageBase):
    id: int
    conversation_id: int
    remetente: MessageSender
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)

# Conversation Schemas
class ConversationResponse(BaseModel):
    id: int
    tenant_id: int
    whatsapp_number_id: int
    contact_id: int
    status: ConversationStatus
    assigned_user_id: Optional[int] = None
    assunto_atual: Optional[str] = None
    criado_em: datetime
    ultima_interacao_em: datetime
    contact: Optional[ContactResponse] = None
    whatsapp_number: Optional[WhatsAppNumberResponse] = None
    messages: List[MessageResponse] = []
    model_config = ConfigDict(from_attributes=True)

class ConversationTransfer(BaseModel):
    para_user_id: Optional[int] = None
    motivo: str

# Integration Settings Schemas
class SaveIntegrationSettingsPayload(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model_name: Optional[str] = "gemini-3.1-flash-lite"
    evolution_api_url: Optional[str] = None
    evolution_api_key: Optional[str] = None
    inatividade_minutos: Optional[int] = 30
    google_drive_folder_id: Optional[str] = None

class IntegrationSettingsMaskedResponse(BaseModel):
    gemini_configured: bool
    gemini_api_key_masked: str
    gemini_model_name: str
    evolution_api_url: str
    evolution_api_key_masked: str
    inatividade_minutos: int
    google_drive_connected: bool
    google_drive_folder_id: str

class TestIntegrationRequest(BaseModel):
    integration_type: str # 'gemini' or 'evolution'
    test_key: Optional[str] = None
    test_url: Optional[str] = None
    test_model: Optional[str] = None

class TestIntegrationResponse(BaseModel):
    success: bool
    message: str

class AuditLogResponse(BaseModel):
    id: int
    tenant_id: int
    user_name: Optional[str]
    acao: str
    detalhes: str
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)
