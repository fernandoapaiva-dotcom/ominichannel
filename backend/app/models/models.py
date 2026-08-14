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
    ENCERRADA = "encerrada"
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
    nome: Mapped[str] = mapped_column(String(150), nullable=False)
    login: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
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
    dados_adicionais: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)

    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="contact")
    tags: Mapped[List["Tag"]] = relationship("Tag", secondary=contact_tag_access, back_populates="contacts")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    whatsapp_number_id: Mapped[int] = mapped_column(Integer, ForeignKey("whatsapp_numbers.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    status: Mapped[ConversationStatus] = mapped_column(Enum(ConversationStatus), default=ConversationStatus.COM_IA, index=True)
    assigned_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assunto_atual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
    motivo: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
