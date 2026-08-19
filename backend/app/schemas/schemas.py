from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
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

from pydantic import BaseModel, ConfigDict, Field, model_validator

class WhatsAppNumberBase(BaseModel):
    provider_type: str = "evolution"
    numero: str
    nome_departamento: str
    instancia_evolution_api: Optional[str] = None
    meta_phone_number_id: Optional[str] = None
    meta_waba_id: Optional[str] = None
    meta_access_token: Optional[str] = None
    status: bool = True

    @model_validator(mode="after")
    def validate_provider_fields(self):
        ptype = (self.provider_type or "evolution").lower()
        if ptype == "evolution":
            if not self.instancia_evolution_api or not self.instancia_evolution_api.strip():
                raise ValueError("Instância da Evolution API é obrigatória para o provedor 'evolution'.")
        elif ptype == "meta":
            if not self.meta_phone_number_id or not self.meta_phone_number_id.strip():
                raise ValueError("Phone Number ID é obrigatório para o provedor 'meta'.")
            if not self.meta_waba_id or not self.meta_waba_id.strip():
                raise ValueError("WABA ID é obrigatório para o provedor 'meta'.")
        return self

class WhatsAppNumberCreate(WhatsAppNumberBase):
    pass

class WhatsAppNumberResponse(BaseModel):
    id: int
    tenant_id: int
    provider_type: str = "evolution"
    numero: str
    nome_departamento: str
    instancia_evolution_api: Optional[str] = None
    meta_phone_number_id: Optional[str] = None
    meta_waba_id: Optional[str] = None
    meta_access_token_masked: Optional[str] = None
    status: bool = True
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
    foto_perfil_url: Optional[str] = None
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
    remetente: str
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_validator("remetente", mode="before")
    @classmethod
    def normalize_remetente(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.lower()
        if hasattr(v, "value"):
            return str(v.value).lower()
        return str(v).lower()

# Conversation Schemas
class ConversationResponse(BaseModel):
    id: int
    tenant_id: int
    whatsapp_number_id: int
    contact_id: int
    status: ConversationStatus
    assigned_user_id: Optional[int] = None
    assigned_user_name: Optional[str] = None
    resumo_ia: Optional[str] = None
    assunto_atual: Optional[str] = None
    criado_em: datetime
    ultima_interacao_em: datetime
    contact: Optional[ContactResponse] = None
    whatsapp_number: Optional[WhatsAppNumberResponse] = None
    messages: List[MessageResponse] = []
    model_config = ConfigDict(from_attributes=True)


class ConversationTransfer(BaseModel):
    para_user_id: Optional[int] = None
    para_whatsapp_number_id: Optional[int] = None
    motivo: Optional[str] = None
    gerar_resumo_ia: Optional[bool] = True

class ConversationStatusUpdate(BaseModel):
    status: ConversationStatus

class StartConversationPayload(BaseModel):
    whatsapp_number_id: int
    telefone: str
    nome: Optional[str] = None
    mensagem_inicial: Optional[str] = None

class ContactWithHistoryResponse(ContactBase):
    id: int
    tenant_id: int
    total_conversations: int = 0
    ultima_interacao: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# Tag & Segmentation Schemas
class TagCreate(BaseModel):
    nome: str
    cor_hex: str = "#10b981"

class TagResponse(BaseModel):
    id: int
    tenant_id: int
    nome: str
    cor_hex: str
    model_config = ConfigDict(from_attributes=True)

class ContactTagAssociatePayload(BaseModel):
    tag_ids: List[int]

class ContactSegmentCreate(BaseModel):
    nome: str
    descricao: Optional[str] = None
    whatsapp_number_id: Optional[int] = None
    dias_inativo: Optional[int] = None
    tag_ids: List[int] = []

class ContactSegmentResponse(BaseModel):
    id: int
    tenant_id: int
    nome: str
    descricao: Optional[str] = None
    regras: Dict[str, Any] = {}
    criado_em: datetime
    model_config = ConfigDict(from_attributes=True)

class SegmentPreviewRequest(BaseModel):
    whatsapp_number_id: Optional[int] = None
    dias_inativo: Optional[int] = None
    tag_ids: List[int] = []

# Integration Settings Schemas
class SaveIntegrationSettingsPayload(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model_name: Optional[str] = "gemini-2.5-flash"

    evolution_api_url: Optional[str] = None
    evolution_api_key: Optional[str] = None
    inatividade_minutos: Optional[int] = 30
    google_drive_folder_id: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None

class IntegrationSettingsMaskedResponse(BaseModel):
    gemini_configured: bool
    gemini_api_key_masked: str
    gemini_model_name: str
    evolution_api_url: str
    evolution_api_key_masked: str
    inatividade_minutos: int
    google_drive_connected: bool
    google_drive_folder_id: str
    google_client_id: str
    google_client_secret_masked: str

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

# Pix Key Schemas
class PixKeyCreate(BaseModel):
    titulo: str
    tipo_chave: str # CNPJ, CPF, EMAIL, TELEFONE, EVP
    chave: str
    favorecido: str
    cidade: str = "BRASILIA"
    descricao: Optional[str] = None
    ativo: bool = True

class PixKeyUpdate(BaseModel):
    titulo: Optional[str] = None
    tipo_chave: Optional[str] = None
    chave: Optional[str] = None
    favorecido: Optional[str] = None
    cidade: Optional[str] = None
    descricao: Optional[str] = None
    ativo: Optional[bool] = None

class PixKeyResponse(BaseModel):
    id: int
    tenant_id: int
    titulo: str
    tipo_chave: str
    chave: str
    favorecido: str
    cidade: str
    descricao: Optional[str] = None
    ativo: bool
    criado_em: datetime
    model_config = ConfigDict(from_attributes=True)
