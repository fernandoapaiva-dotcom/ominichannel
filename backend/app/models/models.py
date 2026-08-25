import enum
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    String, Text, Integer, ForeignKey, DateTime, Boolean, Enum, JSON, Table, Column, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ATENDENTE = "atendente"

class ConversationStatus(str, enum.Enum):
    COM_IA = "com_ia"
    COM_HUMANO = "com_humano"
    AGUARDANDO_ATENDENTE = "aguardando_atendente"
    ENCERRADA = "encerrada"
    ENCERRADA_FORA_EXPEDIENTE = "encerrada_fora_expediente"
    EXPIRADA_POR_INATIVIDADE = "expirada_por_inatividade"

class MessageSender(str, enum.Enum):
    CLIENTE = "cliente"
    IA = "ia"
    ATENDENTE = "atendente"
    SISTEMA = "sistema"

class MessageType(str, enum.Enum):
    TEXTO = "texto"
    AUDIO = "audio"
    IMAGEM = "imagem"
    VIDEO = "video"
    ARQUIVO = "arquivo"
    LOCALIZACAO = "localizacao"

# N:N Join Table for User permissions to WhatsAppNumbers
user_number_access = Table(
    "user_number_access",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("whatsapp_number_id", Integer, ForeignKey("whatsapp_numbers.id", ondelete="CASCADE"), primary_key=True)
)

class Tenant(Base):
    __tablename__ = "tenants"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    pasta_google_drive_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    config_geral: Mapped[Dict[str, Any]] = mapped_column(JSON, default=lambda: {"inatividade_minutos": 30, "prompt_concierge": "Você é um assistente virtual atencioso e eficiente."})
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[List["User"]] = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    whatsapp_numbers: Mapped[List["WhatsAppNumber"]] = relationship("WhatsAppNumber", back_populates="tenant", cascade="all, delete-orphan")
    settings: Mapped[List["IntegrationSettings"]] = relationship("IntegrationSettings", back_populates="tenant", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="tenant", cascade="all, delete-orphan")

class WhatsAppNumber(Base):
    __tablename__ = "whatsapp_numbers"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    numero: Mapped[str] = mapped_column(String(50), nullable=False)
    nome_departamento: Mapped[str] = mapped_column(String(100), nullable=False)
    descricao_roteamento: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_type: Mapped[str] = mapped_column(String(20), default="evolution", nullable=False)
    instancia_evolution_api: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    meta_phone_number_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    meta_waba_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    meta_access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="whatsapp_numbers")
    users: Mapped[List["User"]] = relationship("User", secondary=user_number_access, back_populates="whatsapp_numbers")

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    login: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    foto_perfil_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ATENDENTE)
    status: Mapped[bool] = mapped_column(Boolean, default=True)
    
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")
    whatsapp_numbers: Mapped[List[WhatsAppNumber]] = relationship("WhatsAppNumber", secondary=user_number_access, back_populates="users")

# N:N Join Table for Contact Tags
contact_tag_access = Table(
    "contact_tag_access",
    Base.metadata,
    Column("contact_id", Integer, ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
)

class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(50), nullable=False)
    cor_hex: Mapped[str] = mapped_column(String(10), default="#10b981")

    contacts: Mapped[List["Contact"]] = relationship("Contact", secondary=contact_tag_access, back_populates="tags")

class ContactSegment(Base):
    __tablename__ = "contact_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    descricao: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    regras: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Contact(Base):
    __tablename__ = "contacts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    telefone: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    nome: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    foto_perfil_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    dados_adicionais: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)

    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="contact")
    tags: Mapped[List["Tag"]] = relationship("Tag", secondary=contact_tag_access, back_populates="contacts")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    whatsapp_number_id: Mapped[int] = mapped_column(Integer, ForeignKey("whatsapp_numbers.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    protocol_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    status: Mapped[ConversationStatus] = mapped_column(Enum(ConversationStatus), default=ConversationStatus.COM_IA, index=True)
    assigned_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assunto_atual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dados_adicionais: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ultima_interacao_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    contact: Mapped["Contact"] = relationship("Contact", back_populates="conversations")
    whatsapp_number: Mapped["WhatsAppNumber"] = relationship("WhatsAppNumber")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.timestamp")

class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    remetente: Mapped[str] = mapped_column(String(50), nullable=False)
    conteudo: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[MessageType] = mapped_column(Enum(MessageType), default=MessageType.TEXTO)
    status: Mapped[Optional[str]] = mapped_column(String(50), default="delivered", nullable=True)
    whatsapp_msg_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    dados_adicionais: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")

class ConversationMemory(Base):
    __tablename__ = "conversation_memories"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    resumo_estruturado: Mapped[str] = mapped_column(Text, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TransferLog(Base):
    __tablename__ = "transfer_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    de_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    para_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    de_whatsapp_number_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("whatsapp_numbers.id", ondelete="SET NULL"), nullable=True)
    para_whatsapp_number_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("whatsapp_numbers.id", ondelete="SET NULL"), nullable=True)
    motivo: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    de_whatsapp_number: Mapped[Optional["WhatsAppNumber"]] = relationship("WhatsAppNumber", foreign_keys=[de_whatsapp_number_id])
    para_whatsapp_number: Mapped[Optional["WhatsAppNumber"]] = relationship("WhatsAppNumber", foreign_keys=[para_whatsapp_number_id])

# Business Hours / Expediente Configuration
class BusinessHours(Base):
    __tablename__ = "business_hours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    dias_uteis: Mapped[List[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4]) # 0=Segunda ... 4=Sexta (Sábado NÃO é útil)
    horario_abertura: Mapped[str] = mapped_column(String(10), default="08:00")
    horario_fechamento: Mapped[str] = mapped_column(String(10), default="18:00")
    fuso_horario: Mapped[str] = mapped_column(String(50), default="America/Sao_Paulo")
    feriados_nacionais: Mapped[List[str]] = mapped_column(JSON, default=list) # Formato ['2026-01-01', '2026-04-21', ...]
    mensagem_fora_expediente: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mensagem_encerramento_dia: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant")

# Dynamic Encrypted Integration Settings
class IntegrationSettings(Base):
    __tablename__ = "integration_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    integration_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True) # gemini, evolution, gdrive, general
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="settings")

# Audit Log
class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    acao: Mapped[str] = mapped_column(String(100), nullable=False)
    detalhes: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="audit_logs")

# WhatsApp Groups AI Control
class WhatsAppGroup(Base):
    __tablename__ = "whatsapp_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    whatsapp_number_id: Mapped[int] = mapped_column(Integer, ForeignKey("whatsapp_numbers.id", ondelete="CASCADE"), index=True)
    group_jid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    ia_ativa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    whatsapp_number: Mapped["WhatsAppNumber"] = relationship("WhatsAppNumber")

# Dynamic Scalable Pix Key Registry
class TenantPixKey(Base):
    __tablename__ = "tenant_pix_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    titulo: Mapped[str] = mapped_column(String(100), nullable=False)
    tipo_chave: Mapped[str] = mapped_column(String(50), nullable=False) # CNPJ, CPF, EMAIL, TELEFONE, EVP
    chave: Mapped[str] = mapped_column(String(255), nullable=False)
    favorecido: Mapped[str] = mapped_column(String(150), nullable=False)
    cidade: Mapped[str] = mapped_column(String(100), default="BRASILIA")
    descricao: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Authorized Technicians and Store Employees
class AuthorizedTechnician(Base):
    __tablename__ = "authorized_technicians"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    telefone: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cargo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # Técnico, Vendedor, Consultor, Entregador, etc.
    departamento: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # Assistência Técnica, Vendas, Locação, etc.
    especialidade: Mapped[Optional[str]] = mapped_column(String(255), nullable=True) # Ex: "Inversores, MIG/MAG, TIG, Entrega de Gás"
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant")

# Continuous Improvement / Feedback Loop Table (correcoes_ia)
class AICorrection(Base):
    __tablename__ = "correcoes_ia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    protocolo: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contexto_enviado: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resposta_ia: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resposta_correta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    categoria_erro: Mapped[str] = mapped_column(String(50), default="outro") # alucinacao_nome, alucinacao_historico, tom_errado, informacao_incorreta, outro
    revisado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant")
    conversation: Mapped[Optional["Conversation"]] = relationship("Conversation")

# User Tasks & Calendar Events (Google Calendar Style)
class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), default="geral") # visita_tecnica, entrega_gas, manutencao, reuniao, geral
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    color: Mapped[str] = mapped_column(String(50), default="#10b981") # Hex color code
    priority: Mapped[str] = mapped_column(String(50), default="media") # baixa, media, alta, urgente
    status: Mapped[str] = mapped_column(String(50), default="pendente") # pendente, em_progresso, concluido, cancelado
    reminder_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Store Employee Assignment & WhatsApp Reminders
    employee_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("authorized_technicians.id", ondelete="SET NULL"), nullable=True)
    employee_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    employee_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    notify_whatsapp: Mapped[bool] = mapped_column(Boolean, default=True)
    notified_creation: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_day_of: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_hours_before: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_reminder_hours: Mapped[int] = mapped_column(Integer, default=2)

    # Employee Confirmation Status (e.g. Visualized / Check)
    confirmed_by_employee: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    confirmation_token: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Department WhatsApp Instance Assignment
    whatsapp_number_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("whatsapp_numbers.id", ondelete="SET NULL"), nullable=True)
    whatsapp_instance: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant")
    user: Mapped["User"] = relationship("User")
    contact: Mapped[Optional["Contact"]] = relationship("Contact")
    conversation: Mapped[Optional["Conversation"]] = relationship("Conversation")
    employee: Mapped[Optional["AuthorizedTechnician"]] = relationship("AuthorizedTechnician")
    whatsapp_number: Mapped[Optional["WhatsAppNumber"]] = relationship("WhatsAppNumber")


