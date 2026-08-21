import os
import uuid
import base64
import zipfile
import io
import re
import logging
import unicodedata
import httpx
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Conversation, Message, User, WhatsAppNumber, Contact, TransferLog,
    ConversationStatus, MessageSender, MessageType, user_number_access
)
from app.schemas.schemas import (
    ConversationResponse, MessageCreate, MessageResponse,
    ConversationTransfer, StartConversationPayload, ConversationStatusUpdate
)
from app.services.whatsapp_provider_service import WhatsAppProviderFactory
from app.services.settings_service import settings_service
from app.services.gemini_service import gemini_service
from app.services.evolution_service import evolution_service
from app.services.protocol_service import generate_daily_protocol
from app.services.distribution_service import distribution_service
from app.services.gdrive_service import gdrive_service
from app.api.websockets import manager as ws_manager

router = APIRouter(prefix="/conversations", tags=["Conversas e Mensagens"])

@router.get("/", response_model=List[ConversationResponse])
async def list_conversations(
    status_filter: Optional[ConversationStatus] = None,
    whatsapp_number_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    is_admin = current_user.role == "admin" or str(getattr(current_user.role, 'value', current_user.role)).lower() == "admin"
    if is_admin:
        wn_stmt = select(WhatsAppNumber.id).where(WhatsAppNumber.tenant_id == current_user.tenant_id)
    else:
        wn_stmt = (
            select(WhatsAppNumber.id)
            .join(user_number_access)
            .where(
                WhatsAppNumber.tenant_id == current_user.tenant_id,
                user_number_access.c.user_id == current_user.id
            )
        )
    wn_res = await db.execute(wn_stmt)
    accessible_wn_ids = wn_res.scalars().all()

    if not accessible_wn_ids:
        return []

    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.whatsapp_number_id.in_(accessible_wn_ids)
        )
    )

    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter)
    if whatsapp_number_id:
        if whatsapp_number_id not in accessible_wn_ids:
            raise HTTPException(status_code=403, detail="Acesso negado a este número de WhatsApp")
        stmt = stmt.where(Conversation.whatsapp_number_id == whatsapp_number_id)

    stmt = stmt.order_by(Conversation.ultima_interacao_em.desc())
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    user_ids = {c.assigned_user_id for c in conversations if c.assigned_user_id}
    contact_ids = {c.contact_id for c in conversations if c.contact_id}

    user_map = {}
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        user_map = {u.id: u.nome for u in u_res.scalars().all()}

    mem_map = {}
    if contact_ids:
        from app.models.models import ConversationMemory
        m_res = await db.execute(select(ConversationMemory).where(ConversationMemory.tenant_id == current_user.tenant_id, ConversationMemory.contact_id.in_(contact_ids)))
        mem_map = {m.contact_id: m.resumo_estruturado for m in m_res.scalars().all()}

    response_list = []
    for c in conversations:
        c_dict = ConversationResponse.model_validate(c).model_dump()
        c_dict["assigned_user_name"] = user_map.get(c.assigned_user_id)
        c_dict["resumo_ia"] = mem_map.get(c.contact_id)
        response_list.append(c_dict)

    return response_list


@router.post("/start", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def start_new_conversation(
    payload: StartConversationPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Starts a new conversation with a phone number (creates Contact if not existing).
    Dispatches initial message via the department's configured WhatsApp Provider if provided.
    """
    clean_phone = "".join(filter(str.isdigit, payload.telefone))
    if not clean_phone or len(clean_phone) < 8:
        raise HTTPException(status_code=400, detail="Número de telefone inválido.")

    # 1. Verify access to requested department
    wn_stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.id == payload.whatsapp_number_id,
        WhatsAppNumber.tenant_id == current_user.tenant_id
    )
    wn_res = await db.execute(wn_stmt)
    wn = wn_res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=404, detail="Departamento / Número de WhatsApp não encontrado")

    # 2. Find or create Contact (matching phone variants with/without 9th digit)
    phone_variants = [clean_phone]
    if len(clean_phone) == 13 and clean_phone.startswith("55"):
        phone_variants.append(clean_phone[:4] + clean_phone[5:])
    elif len(clean_phone) == 12 and clean_phone.startswith("55"):
        phone_variants.append(clean_phone[:4] + "9" + clean_phone[4:])

    contact_stmt = select(Contact).where(
        Contact.tenant_id == current_user.tenant_id,
        Contact.telefone.in_(phone_variants)
    )
    contact_res = await db.execute(contact_stmt)
    contact = contact_res.scalars().first()

    if not contact:
        contact = Contact(
            tenant_id=current_user.tenant_id,
            telefone=clean_phone,
            nome=payload.nome or f"Contato {clean_phone[-4:]}"
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
    elif payload.nome and (not contact.nome or contact.nome.startswith("Contato ")):
        contact.nome = payload.nome
        await db.commit()

    # 3. Find active conversation or create new
    conv_stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.whatsapp_number_id == wn.id,
            Conversation.contact_id == contact.id
        )
        .order_by(Conversation.criado_em.desc())
    )
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalars().first()

    now = datetime.utcnow()
    if not conv:
        proto = await generate_daily_protocol(db, current_user.tenant_id)
        conv = Conversation(
            tenant_id=current_user.tenant_id,
            whatsapp_number_id=wn.id,
            contact_id=contact.id,
            protocol_number=proto,
            status=ConversationStatus.COM_HUMANO,
            assigned_user_id=current_user.id,
            criado_em=now,
            ultima_interacao_em=now
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    else:
        if not conv.protocol_number or conv.status in [ConversationStatus.ENCERRADA, ConversationStatus.EXPIRADA_POR_INATIVIDADE, ConversationStatus.ENCERRADA_FORA_EXPEDIENTE]:
            conv.protocol_number = await generate_daily_protocol(db, current_user.tenant_id)
        conv.status = ConversationStatus.COM_HUMANO
        conv.assigned_user_id = current_user.id
        conv.ultima_interacao_em = now
        await db.commit()

    # 4. Dispatch initial message if provided
    if payload.mensagem_inicial and payload.mensagem_inicial.strip():
        provider = WhatsAppProviderFactory.get_provider(wn)
        send_res = await provider.send_text_message(
            number=clean_phone,
            text=payload.mensagem_inicial.strip()
        )
        if send_res.get("success", False):
            msg = Message(
                conversation_id=conv.id,
                remetente=MessageSender.ATENDENTE,
                conteudo=payload.mensagem_inicial.strip(),
                tipo=MessageType.TEXTO,
                timestamp=now
            )
            db.add(msg)
            await db.commit()

    # 5. Automatically fetch and sync historical WhatsApp messages from Evolution API
    try:
        inst_name = wn.instancia_evolution_api or "instancia_locacao"
        history_msgs = await evolution_service.fetch_chat_history(
            instance_name=inst_name,
            phone=clean_phone,
            limit=100
        )
        if history_msgs:
            existing_stmt = select(Message.conteudo, Message.timestamp).where(Message.conversation_id == conv.id)
            existing_res = await db.execute(existing_stmt)
            existing_set = {(m[0], m[1]) for m in existing_res.all()}

            added_any = False
            for hm in history_msgs:
                if (hm["conteudo"], hm["timestamp"]) not in existing_set:
                    new_m = Message(
                        conversation_id=conv.id,
                        remetente=hm["remetente"],
                        conteudo=hm["conteudo"],
                        tipo=hm["tipo"],
                        timestamp=hm["timestamp"]
                    )
                    db.add(new_m)
                    added_any = True

            if added_any:
                latest_ts = history_msgs[-1]["timestamp"]
                if latest_ts > conv.ultima_interacao_em:
                    conv.ultima_interacao_em = latest_ts
                await db.commit()
    except Exception as e:
        print(f"Auto-sync WhatsApp history error: {e}")

    # Re-fetch full object with relations
    res_stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(Conversation.id == conv.id)
    )
    final_res = await db.execute(res_stmt)
    return final_res.scalar_one()

@router.post("/{conversation_id}/sync-history")
async def sync_conversation_whatsapp_history(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number)
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou acesso negado")

    if not conv.contact or not conv.contact.telefone:
        return {"message": "Contato sem número de telefone para busca", "imported": 0}

    inst_name = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else "instancia_locacao"
    history_msgs = await evolution_service.fetch_chat_history(
        instance_name=inst_name or "instancia_locacao",
        phone=conv.contact.telefone,
        limit=100
    )

    existing_stmt = select(Message.conteudo, Message.timestamp).where(Message.conversation_id == conv.id)
    existing_res = await db.execute(existing_stmt)
    existing_set = {(m[0], m[1]) for m in existing_res.all()}

    imported = 0
    for hm in history_msgs:
        if (hm["conteudo"], hm["timestamp"]) not in existing_set:
            new_m = Message(
                conversation_id=conv.id,
                remetente=hm["remetente"],
                conteudo=hm["conteudo"],
                tipo=hm["tipo"],
                timestamp=hm["timestamp"]
            )
            db.add(new_m)
            imported += 1

    if imported > 0:
        latest_ts = history_msgs[-1]["timestamp"]
        if latest_ts > conv.ultima_interacao_em:
            conv.ultima_interacao_em = latest_ts
        await db.commit()

    return {"message": f"Sincronização concluída! {imported} mensagens importadas.", "imported": imported}

PATTERNS = [
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4})\s*,?\s*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\s*-\s*([^:]+):\s*(.*)$", re.IGNORECASE),
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\]\s*([^:]+):\s*(.*)$", re.IGNORECASE)
]

@router.post("/{conversation_id}/import-backup-file")
async def import_whatsapp_backup_file(
    conversation_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number)
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou acesso negado")

    content_bytes = await file.read()
    txt_content = ""

    if file.filename and file.filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content_bytes)) as z:
                txt_files = [f for f in z.namelist() if f.endswith(".txt")]
                if txt_files:
                    txt_bytes = z.read(txt_files[0])
                    txt_content = txt_bytes.decode("utf-8", errors="ignore")
                else:
                    raise HTTPException(status_code=400, detail="Nenhum arquivo .txt de conversa encontrado dentro do .zip")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao descompactar .zip: {e}")
    else:
        try:
            txt_content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            txt_content = content_bytes.decode("latin-1", errors="ignore")

    contact_name = conv.contact.nome if (conv.contact and conv.contact.nome) else ""
    lines = txt_content.splitlines()

    parsed = []
    current_msg = None

    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue

        matched = False
        for p in PATTERNS:
            m = p.match(clean_line)
            if m:
                matched = True
                date_str, time_str, sender_raw, text = m.groups()
                sender_raw = sender_raw.strip()

                if contact_name and (contact_name.lower() in sender_raw.lower() or sender_raw.lower() in contact_name.lower()):
                    remetente = "cliente"
                elif any(t in sender_raw.lower() for t in ["atendente", "suporte", "vendas", "locação", "empresa"]):
                    remetente = "atendente"
                else:
                    remetente = "cliente"

                dt = datetime.utcnow()
                try:
                    parts = date_str.split("/")
                    if len(parts) == 3:
                        day, month, year = parts[0], parts[1], parts[2]
                        if len(year) == 2:
                            year = "20" + year
                        clean_dt_str = f"{day.zfill(2)}/{month.zfill(2)}/{year} {time_str}"
                        if len(time_str.split(":")) == 2:
                            dt = datetime.strptime(clean_dt_str, "%d/%m/%Y %H:%M")
                        else:
                            dt = datetime.strptime(clean_dt_str, "%d/%m/%Y %H:%M:%S")
                except Exception:
                    dt = datetime.utcnow()

                current_msg = {
                    "remetente": remetente,
                    "conteudo": text.strip(),
                    "tipo": "texto",
                    "timestamp": dt
                }
                parsed.append(current_msg)
                break

        if not matched and current_msg and clean_line:
            current_msg["conteudo"] += "\n" + clean_line

    if not parsed:
        return {"message": "Nenhuma mensagem válida no formato de exportação do WhatsApp foi encontrada no arquivo.", "imported": 0}

    existing_stmt = select(Message.conteudo, Message.timestamp).where(Message.conversation_id == conv.id)
    existing_res = await db.execute(existing_stmt)
    existing_set = {(m[0], m[1]) for m in existing_res.all()}

    imported = 0
    for p_msg in parsed:
        if (p_msg["conteudo"], p_msg["timestamp"]) not in existing_set:
            new_m = Message(
                conversation_id=conv.id,
                remetente=p_msg["remetente"],
                conteudo=p_msg["conteudo"],
                tipo=p_msg["tipo"],
                timestamp=p_msg["timestamp"]
            )
            db.add(new_m)
            imported += 1

    if imported > 0:
        latest_ts = parsed[-1]["timestamp"]
        if latest_ts > conv.ultima_interacao_em:
            conv.ultima_interacao_em = latest_ts
        await db.commit()

    return {"message": f"Backup do WhatsApp importado com sucesso! {imported} mensagens adicionadas.", "imported": imported}

@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation_detail(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    return conv

@router.get("/{conversation_id}/media", response_model=List[MessageResponse])
async def get_conversation_media_files(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns media messages (audio, image, file) for a specific conversation.
    """
    stmt = select(Message).join(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id,
        Message.tipo.in_([MessageType.AUDIO, MessageType.IMAGEM, MessageType.ARQUIVO])
    ).order_by(Message.timestamp.desc())
    
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_agent_message(
    conversation_id: int,
    msg_in: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Sends a message from a human agent to the customer via the department's configured provider.
    Enforces delivery error checking before committing to DB.
    """
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    raw_content = (msg_in.conteudo or "").strip()
    is_sticker = (
        msg_in.tipo in (MessageType.IMAGEM, "sticker", "figurinha") or
        raw_content.lower().endswith(".webp") or
        ("/uploads/" in raw_content and raw_content.lower().endswith(".webp"))
    )
    is_gif = (
        raw_content.lower().endswith(".gif") or
        "giphy.com" in raw_content.lower() or
        "tenor.com" in raw_content.lower()
    )

    actual_tipo = MessageType.IMAGEM if (is_sticker or is_gif) else msg_in.tipo
    clean_db_content = raw_content
    if "/uploads/" in raw_content:
        clean_db_content = "/uploads/" + raw_content.split("/uploads/")[-1]

    # 1. Dispatch via provider factory
    send_res = {"success": False}
    if is_sticker and conv.whatsapp_number and conv.whatsapp_number.instancia_evolution_api:
        sticker_media = raw_content
        if "/uploads/" in raw_content:
            fname = raw_content.split("/uploads/")[-1]
            lpath = os.path.join("uploads", fname)
            if os.path.exists(lpath):
                with open(lpath, "rb") as f:
                    sticker_media = base64.b64encode(f.read()).decode("utf-8")

        send_res = await evolution_service.send_sticker(
            instance_name=conv.whatsapp_number.instancia_evolution_api,
            number=conv.contact.telefone,
            sticker_media=sticker_media
        )
    elif is_gif and conv.whatsapp_number and conv.whatsapp_number.instancia_evolution_api:
        send_res = await evolution_service.send_media_message(
            instance_name=conv.whatsapp_number.instancia_evolution_api,
            number=conv.contact.telefone,
            media_type="video",
            mimetype="video/mp4",
            media=raw_content,
            file_name="animacao.mp4"
        )
    else:
        provider = WhatsAppProviderFactory.get_provider(conv.whatsapp_number)
        agent_name = current_user.nome or "Atendente"
        formatted_whatsapp_text = f"*👤 {agent_name}:*\n\n{msg_in.conteudo}"

        send_res = await provider.send_text_message(
            number=conv.contact.telefone,
            text=formatted_whatsapp_text
        )

        # If delivery failed and provider is Evolution, attempt failover to other active connected instances of the tenant
        if not send_res.get("success", False) and getattr(conv.whatsapp_number, "provider_type", "evolution") != "meta":
            wn_all_stmt = select(WhatsAppNumber).where(
                WhatsAppNumber.tenant_id == current_user.tenant_id,
                WhatsAppNumber.status == True
            )
            wn_all_res = await db.execute(wn_all_stmt)
            all_wns = wn_all_res.scalars().all()

            for alt_wn in all_wns:
                if not alt_wn.instancia_evolution_api or alt_wn.id == conv.whatsapp_number_id:
                    continue
                if is_sticker:
                    alt_res = await evolution_service.send_sticker(
                        instance_name=alt_wn.instancia_evolution_api,
                        number=conv.contact.telefone,
                        sticker_media=sticker_media
                    )
                elif is_gif:
                    alt_res = await evolution_service.send_media_message(
                        instance_name=alt_wn.instancia_evolution_api,
                        number=conv.contact.telefone,
                        media_type="video",
                        mimetype="video/mp4",
                        media=raw_content,
                        file_name="animacao.mp4"
                    )
                else:
                    alt_res = await evolution_service.send_text_message(
                        instance_name=alt_wn.instancia_evolution_api,
                        number=conv.contact.telefone,
                        text=formatted_whatsapp_text
                    )
                if alt_res.get("success"):
                    logger.info(f"Agent message delivered to {conv.contact.telefone} via failover instance '{alt_wn.instancia_evolution_api}'")
                    send_res = alt_res
                    break

    # 2. If delivery failed across all instances, raise HTTP error and do not commit message
    if not send_res.get("success", False):
        error_detail = send_res.get("error", "Falha de conexão com o Provedor WhatsApp")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao enviar mensagem no WhatsApp: {error_detail}. Verifique se a instância de WhatsApp do setor está conectada (QR Code) no Painel Admin."
        )

    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    wa_key_id = send_res.get("key", {}).get("id") if isinstance(send_res.get("key"), dict) else send_res.get("id")

    message = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=clean_db_content,
        tipo=actual_tipo,
        status="sent",
        whatsapp_msg_id=wa_key_id,
        timestamp=datetime.utcnow()
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # 4. Broadcast real-time update
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "id": message.id,
            "remetente": MessageSender.ATENDENTE.value,
            "conteudo": msg_in.conteudo,
            "status": message.status,
            "whatsapp_msg_id": message.whatsapp_msg_id,
            "timestamp": str(message.timestamp),
            "agent_name": current_user.nome
        }
    )

    return message

class ReactionPayload(BaseModel):
    reaction: str

@router.post("/{conversation_id}/messages/{message_id}/reaction")
async def react_to_message(
    conversation_id: int,
    message_id: int,
    payload: ReactionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Dispatches a native WhatsApp emoji reaction to a message.
    """
    stmt = select(Conversation).options(
        selectinload(Conversation.contact),
        selectinload(Conversation.whatsapp_number)
    ).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    m_stmt = select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    m_res = await db.execute(m_stmt)
    msg = m_res.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")

    wa_msg_id = msg.whatsapp_msg_id
    if wa_msg_id and conv.whatsapp_number and conv.whatsapp_number.instancia_evolution_api:
        from_me = (msg.remetente == MessageSender.ATENDENTE.value or msg.remetente == "atendente" or msg.remetente == "ia")
        await evolution_service.send_reaction(
            instance_name=conv.whatsapp_number.instancia_evolution_api,
            number=conv.contact.telefone,
            message_id=wa_msg_id,
            reaction_emoji=payload.reaction,
            from_me=from_me
        )

    msg_extra = dict(msg.dados_adicionais or {})
    msg_extra["reaction"] = payload.reaction
    msg.dados_adicionais = msg_extra
    await db.commit()

    await ws_manager.broadcast({
        "type": "MESSAGE_REACTION_UPDATE",
        "conversation_id": conversation_id,
        "message_id": message_id,
        "reaction": payload.reaction
    })

    return {"status": "success", "reaction": payload.reaction}

class LocationPayload(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float

@router.post("/{conversation_id}/send-location", response_model=MessageResponse)
async def send_location_in_conversation(
    conversation_id: int,
    payload: LocationPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Dispatches native WhatsApp Location Map Card to the customer with multi-instance failover.
    """
    stmt = select(Conversation).options(
        selectinload(Conversation.contact),
        selectinload(Conversation.whatsapp_number)
    ).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # Try primary department instance first, fallback to all active tenant instances
    wn_all_stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.tenant_id == current_user.tenant_id,
        WhatsAppNumber.status == True
    )
    wn_all_res = await db.execute(wn_all_stmt)
    all_wns = wn_all_res.scalars().all()

    primary_inst = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else ""
    instances_to_try = [primary_inst] + [wn.instancia_evolution_api for wn in all_wns if wn.instancia_evolution_api != primary_inst]

    loc_sent = False
    for inst in instances_to_try:
        if not inst:
            continue
        res_loc = await evolution_service.send_location_message(
            instance_name=inst,
            number=conv.contact.telefone,
            latitude=payload.latitude,
            longitude=payload.longitude,
            name=payload.name,
            address=payload.address
        )
        if res_loc.get("success"):
            loc_sent = True
            break

    if not loc_sent:
        raise HTTPException(status_code=502, detail="Falha ao enviar card de localização no WhatsApp. Verifique a conexão no Painel Admin.")

    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    message = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=f"📍 *LOCALIZAÇÃO ENVIADA*\n{payload.name}\n{payload.address}\nhttps://maps.google.com/?q={payload.latitude},{payload.longitude}",
        tipo=MessageType.LOCALIZACAO,
        timestamp=datetime.utcnow()
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "remetente": MessageSender.ATENDENTE.value,
            "conteudo": message.conteudo,
            "timestamp": str(message.timestamp),
            "agent_name": current_user.nome
        }
    )

    return message

def generate_bacen_pix_string(key: str, merchant_name: str, merchant_city: str, amount: Optional[float] = None) -> str:
    clean_key = key.replace('.', '').replace('/', '').replace('-', '').replace(' ', '') if '@' not in key else key
    field26 = f"0014br.gov.bcb.pix01{len(clean_key):02d}{clean_key}"
    
    name_clean = unicodedata.normalize('NFD', merchant_name).encode('ascii', 'ignore').decode('ascii').upper()[:25]
    city_clean = unicodedata.normalize('NFD', merchant_city).encode('ascii', 'ignore').decode('ascii').upper()[:15]
    
    amount_str = f"{amount:.2f}" if amount and amount > 0 else ""
    field54 = f"54{len(amount_str):02d}{amount_str}" if amount_str else ""

    payload_no_crc = (
        "000201"
        f"26{len(field26):02d}{field26}"
        "52040000"
        "5303986"
        f"{field54}"
        "5802BR"
        f"59{len(name_clean):02d}{name_clean}"
        f"60{len(city_clean):02d}{city_clean}"
        "62070503***"
        "6304"
    )
    
    crc = 0xFFFF
    for char in payload_no_crc:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    crc_hex = f"{crc & 0xFFFF:04X}"
    return payload_no_crc + crc_hex

class SendPixPayload(BaseModel):
    title: str
    key_type: str
    key: str
    favorecido: str
    cidade: str = "BRASILIA"
    amount: Optional[float] = None

@router.post("/{conversation_id}/send-pix", response_model=MessageResponse)
async def send_pix_in_conversation(
    conversation_id: int,
    payload: SendPixPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates official BACEN EMV Co payload & QR code image, sending it to the customer as a native WhatsApp IMAGE message with caption!
    """
    stmt = select(Conversation).options(
        selectinload(Conversation.contact),
        selectinload(Conversation.whatsapp_number)
    ).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # Generate BACEN EMV Co payload
    bacen_payload = generate_bacen_pix_string(
        key=payload.key,
        merchant_name=payload.favorecido,
        merchant_city=payload.cidade,
        amount=payload.amount
    )

    # Fetch QR Code image bytes from qrserver API
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={bacen_payload}"
    file_bytes = None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(qr_image_url, timeout=10.0)
            if r.status_code == 200:
                file_bytes = r.content
    except Exception as e:
        logger.error(f"Error fetching QR Code image: {e}")

    if not file_bytes:
        raise HTTPException(status_code=502, detail="Falha ao gerar a imagem do QR Code Pix")

    # Format caption
    amount_text = f"\n💵 *Valor a Pagar:* R$ {payload.amount:.2f}".replace('.', ',') if payload.amount and payload.amount > 0 else ""
    caption_text = (
        f"💸 *DADOS PARA PAGAMENTO VIA PIX SERVWELD*\n\n"
        f"📌 *Identificador:* {payload.title}\n"
        f"🏢 *Favorecido:* {payload.favorecido}"
        f"{amount_text}\n"
        f"🆔 *Chave Pix ({payload.key_type}):* {payload.key}\n\n"
        f"📋 *PIX COPIA E COLA (Copie e cole no App do Banco):*\n"
        f"{bacen_payload}\n\n"
        f"📲 *Escaneie o QR Code acima pelo app do seu Banco.*\n"
        f"⚠️ *Importante:* Após realizar a transferência, envie o comprovante neste chat para validação."
    )

    base64_img = base64.b64encode(file_bytes).decode('utf-8')
    agent_name = current_user.nome or "Atendente"
    formatted_caption = f"*👤 {agent_name}:*\n\n{caption_text}"

    # Failover instance try
    wn_all_stmt = select(WhatsAppNumber).where(
        WhatsAppNumber.tenant_id == current_user.tenant_id,
        WhatsAppNumber.status == True
    )
    wn_all_res = await db.execute(wn_all_stmt)
    all_wns = wn_all_res.scalars().all()

    primary_inst = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else ""
    instances_to_try = [primary_inst] + [wn.instancia_evolution_api for wn in all_wns if wn.instancia_evolution_api != primary_inst]

    img_sent = False
    for inst in instances_to_try:
        if not inst:
            continue
        res_media = await evolution_service.send_media_message(
            instance_name=inst,
            number=conv.contact.telefone,
            media_type="image",
            mimetype="image/png",
            media=base64_img,
            file_name="qrcode_pix.png",
            caption=formatted_caption
        )
        if res_media.get("success"):
            img_sent = True
            break

    if not img_sent:
        raise HTTPException(status_code=502, detail="Falha ao enviar a imagem do Pix no WhatsApp. Verifique se a instância está conectada.")

    # Record message in DB
    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    # Save to uploads folder for web display
    os.makedirs("uploads", exist_ok=True)
    unique_fn = f"pix_{uuid.uuid4().hex}.png"
    up_path = os.path.join("uploads", unique_fn)
    with open(up_path, "wb") as f:
        f.write(file_bytes)

    msg = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=f"/uploads/{unique_fn}|{caption_text}",
        tipo=MessageType.IMAGEM,
        timestamp=datetime.utcnow()
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "remetente": MessageSender.ATENDENTE.value,
            "conteudo": msg.conteudo,
            "timestamp": str(msg.timestamp),
            "agent_name": current_user.nome
        }
    )

    return msg

@router.post("/{conversation_id}/media", response_model=MessageResponse)
async def send_agent_media(
    conversation_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # 1. Save uploaded file to disk
    os.makedirs("uploads", exist_ok=True)
    file_ext = os.path.splitext(file.filename)[1] or ""
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    file_path = os.path.join("uploads", unique_filename)

    file_bytes = await file.read()
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    file_url = f"/uploads/{unique_filename}"

    # 2. Determine MessageType and Evolution media_type
    mimetype = file.content_type or "application/octet-stream"
    if mimetype.startswith("image/"):
        msg_type = MessageType.IMAGEM
        media_type = "image"
    elif mimetype.startswith("video/"):
        msg_type = MessageType.VIDEO
        media_type = "video"
    elif mimetype.startswith("audio/"):
        msg_type = MessageType.AUDIO
        media_type = "audio"
    else:
        msg_type = MessageType.ARQUIVO
        media_type = "document"

    # 3. Send via Evolution API
    agent_name = current_user.nome or "Atendente"
    formatted_caption = f"*👤 {agent_name}:*\n\n{caption}" if caption else f"*👤 {agent_name}:*"
    base64_data = base64.b64encode(file_bytes).decode('utf-8')

    from app.services.evolution_service import evolution_service
    send_res = await evolution_service.send_media_message(
        instance_name=conv.whatsapp_number.instancia_evolution_api or "instancia_locacao",
        number=conv.contact.telefone,
        media_type=media_type,
        mimetype=mimetype,
        media=base64_data,
        file_name=file.filename or unique_filename,
        caption=formatted_caption
    )

    if not send_res.get("success", False):
        error_detail = send_res.get("error", "Falha de conexão ao enviar mídia no WhatsApp")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao enviar arquivo no WhatsApp: {error_detail}"
        )

    # 4. Save Message in DB
    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    db_content = f"{file_url}|{caption}" if caption else file_url

    message = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=db_content,
        tipo=msg_type,
        timestamp=datetime.utcnow()
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # 5. Broadcast real-time update
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "remetente": MessageSender.ATENDENTE.value,
            "conteudo": db_content,
            "tipo": msg_type.value,
            "timestamp": str(message.timestamp),
            "agent_name": current_user.nome
        }
    )

    return message

@router.post("/{conversation_id}/transfer")
async def transfer_conversation(
    conversation_id: int,
    transfer_in: ConversationTransfer,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).options(selectinload(Conversation.contact)).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    old_user_id = conv.assigned_user_id
    old_wn_id = conv.whatsapp_number_id
    target_desc = ""

    # 1. Update Department/Sector if provided
    if transfer_in.para_whatsapp_number_id:
        wn_stmt = select(WhatsAppNumber).where(
            WhatsAppNumber.id == transfer_in.para_whatsapp_number_id,
            WhatsAppNumber.tenant_id == current_user.tenant_id
        )
        wn_res = await db.execute(wn_stmt)
        wn_target = wn_res.scalar_one_or_none()
        if wn_target:
            conv.whatsapp_number_id = wn_target.id
            target_desc += f"Setor: {wn_target.nome_departamento}"

    # 2. Update Attendant User if provided
    if transfer_in.para_user_id:
        u_stmt = select(User).where(
            User.id == transfer_in.para_user_id,
            User.tenant_id == current_user.tenant_id
        )
        u_res = await db.execute(u_stmt)
        u_target = u_res.scalar_one_or_none()
        if u_target:
            conv.assigned_user_id = u_target.id
            if target_desc:
                target_desc += f" | Atendente: {u_target.nome}"
            else:
                target_desc += f"Atendente: {u_target.nome}"
    else:
        # If transferring to sector without specific user, unassign current user
        if transfer_in.para_whatsapp_number_id:
            conv.assigned_user_id = None

    if not target_desc:
        target_desc = "Fila Geral de Atendimento"

    conv.status = ConversationStatus.COM_HUMANO
    conv.ultima_interacao_em = datetime.utcnow()

    log = TransferLog(
        conversation_id=conv.id,
        de_user_id=old_user_id,
        para_user_id=transfer_in.para_user_id,
        de_whatsapp_number_id=old_wn_id,
        para_whatsapp_number_id=conv.whatsapp_number_id,
        motivo=transfer_in.motivo or "Transferência de Atendimento",
        timestamp=datetime.utcnow()
    )
    db.add(log)

    # 3. Generate AI Summary if requested
    ai_summary = ""
    if transfer_in.gerar_resumo_ia is not False:
        # Fetch all previous messages of the conversation
        msg_stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.timestamp.asc())
        msg_res = await db.execute(msg_stmt)
        messages_list = msg_res.scalars().all()

        history_dicts = [
            {"remetente": m.remetente, "conteudo": m.conteudo or ""}
            for m in messages_list
            if str(m.remetente).lower() != "sistema"
        ]

        decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
        customer_name = conv.contact.nome if (conv.contact and conv.contact.nome) else "Cliente"

        ai_summary = await gemini_service.summarize_conversation_for_transfer(
            customer_name=customer_name,
            messages_history=history_dicts,
            tenant_gemini_api_key=decrypted.get("gemini_api_key"),
            tenant_gemini_model_name=decrypted.get("gemini_model_name")
        )

        # Attach summary as a system message in the chat
        summary_message_text = (
            f"🤖 *RESUMO DA IA PARA TRANSFERÊNCIA*\n"
            f"📍 *Destino*: {target_desc}\n"
            f"👤 *Transferido por*: {current_user.nome}\n"
            f"💬 *Motivo*: {transfer_in.motivo or 'Nenhum motivo informado'}\n\n"
            f"{ai_summary}"
        )

        sys_msg = Message(
            conversation_id=conv.id,
            remetente="sistema",
            tipo="texto",
            conteudo=summary_message_text,
            timestamp=datetime.utcnow()
        )
        db.add(sys_msg)

    await db.commit()
    await db.refresh(conv)

    # Broadcast WebSocket message event
    try:
        from app.api.websockets import manager
        await manager.broadcast({
            "type": "conversation_updated",
            "conversation_id": conv.id,
            "status": conv.status.value,
            "whatsapp_number_id": conv.whatsapp_number_id,
            "assigned_user_id": conv.assigned_user_id
        })
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Conversa transferida com sucesso para {target_desc}",
        "resumo_ia": ai_summary
    }

@router.put("/{conversation_id}/status")
async def update_conversation_status(
    conversation_id: int,
    payload: ConversationStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()

    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    old_status = conv.status
    conv.status = payload.status
    conv.ultima_interacao_em = datetime.utcnow()

    # If finalized (ENCERRADA), record system audit message and send optional CSAT survey
    if payload.status == ConversationStatus.ENCERRADA:
        # Pinned system message in timeline
        sys_msg = Message(
            conversation_id=conv.id,
            remetente="sistema",
            conteudo=f"🔒 Atendimento finalizado com sucesso por {current_user.nome or 'Atendente'}.",
            tipo=MessageType.TEXTO,
            timestamp=datetime.utcnow()
        )
        db.add(sys_msg)

        # Dispatch CSAT closing survey to customer on WhatsApp
        if conv.contact and conv.whatsapp_number and conv.whatsapp_number.instancia_evolution_api:
            # Don't send CSAT to groups or temporary numbers
            is_group = "@g.us" in str(conv.contact.telefone) or len(str(conv.contact.telefone)) > 15
            if not is_group:
                csat_text = (
                    f"✅ *Atendimento Finalizado*\n"
                    f"Protocolo: {conv.protocol_number or 'S/N'}\n\n"
                    f"Agradecemos o contato com a Servweld! Como você avalia o atendimento recebido?\n\n"
                    f"Por favor, responda com uma nota de 1 a 5:\n"
                    f"⭐ 1 - Muito Ruim\n"
                    f"⭐ 2 - Ruim\n"
                    f"⭐ 3 - Regular\n"
                    f"⭐ 4 - Bom\n"
                    f"⭐ 5 - Excelente"
                )
                try:
                    await evolution_service.send_text_message(
                        instance_name=conv.whatsapp_number.instancia_evolution_api,
                        number=conv.contact.telefone,
                        text=csat_text
                    )
                except Exception as send_err:
                    logger.warning(f"Failed to dispatch CSAT survey on finalization: {send_err}")

    await db.commit()

    # Auto-export conversation JSON backup
    if payload.status in [ConversationStatus.ENCERRADA, ConversationStatus.EXPIRADA_POR_INATIVIDADE]:
        try:
            conv_export = {
                "conversation_id": conv.id,
                "tenant_id": conv.tenant_id,
                "contact_phone": conv.contact.telefone if conv.contact else "",
                "contact_name": conv.contact.nome if conv.contact else "",
                "protocol_number": conv.protocol_number,
                "status": getattr(conv.status, 'value', str(conv.status)),
                "criado_em": conv.criado_em,
                "ultima_interacao_em": conv.ultima_interacao_em,
                "messages": [
                    {
                        "id": m.id,
                        "remetente": getattr(m.remetente, 'value', str(m.remetente)),
                        "conteudo": m.conteudo,
                        "tipo": getattr(m.tipo, 'value', str(m.tipo)),
                        "timestamp": m.timestamp.isoformat() if m.timestamp else None
                    }
                    for m in (conv.messages or [])
                ]
            }
            await gdrive_service.sync_conversation_to_drive(
                tenant_drive_folder_id=None,
                conversation_id=conv.id,
                contact_phone=conv_export["contact_phone"],
                conversation_data=conv_export
            )
        except Exception as b_err:
            logger.warning(f"Error exporting backup on finalization: {b_err}")

        # Automatically re-balance and assign any waiting conversations in queue to newly freed attendant
        try:
            await distribution_service.process_pending_queue(db, current_user.tenant_id, conv.whatsapp_number_id)
        except Exception as q_err:
            logger.warning(f"Error processing pending queue after finalization: {q_err}")

    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "status_updated": conv.status.value
        }
    )

    return {"status": "success", "new_status": conv.status.value}

@router.post("/{conversation_id}/suggest-reply")
async def suggest_reply_for_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates a draft suggestion for the human attendant to review before sending (Seção 2 - Botão 'Consultar IA').
    Does NOT send the message automatically.
    """
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.contact),
            selectinload(Conversation.whatsapp_number),
            selectinload(Conversation.messages)
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    # Fetch conversation memory summary if available
    from app.models.models import ConversationMemory
    mem_res = await db.execute(
        select(ConversationMemory).where(
            ConversationMemory.tenant_id == current_user.tenant_id,
            ConversationMemory.contact_id == conv.contact_id
        )
    )
    memory = mem_res.scalar_one_or_none()
    memory_summary = memory.resumo_estruturado if memory else None

    # Fetch RAG context from last customer message if available
    customer_msgs = [m for m in conv.messages if str(m.remetente).lower() == "cliente"]
    last_customer_text = customer_msgs[-1].conteudo if customer_msgs else ""
    rag_context = ""
    if last_customer_text:
        try:
            from app.services.rag_service import rag_service
            rag_res = await rag_service.query_relevant_context(current_user.tenant_id, last_customer_text)
            rag_context = rag_res if isinstance(rag_res, str) else ""
        except Exception:
            pass

    history_dicts = [
        {"remetente": getattr(m.remetente, 'value', str(m.remetente)), "conteudo": m.conteudo or ""}
        for m in sorted(conv.messages, key=lambda x: x.timestamp or datetime.min)
    ]

    decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
    customer_name = conv.contact.nome if (conv.contact and conv.contact.nome) else "Cliente"
    dept_name = conv.whatsapp_number.nome_departamento if conv.whatsapp_number else "Atendimento"

    suggestion = await gemini_service.generate_suggested_reply(
        customer_name=customer_name,
        department_name=dept_name,
        messages_history=history_dicts,
        memory_summary=memory_summary,
        rag_context=rag_context,
        tenant_gemini_api_key=decrypted.get("gemini_api_key"),
        tenant_gemini_model_name=decrypted.get("gemini_model_name")
    )

    return {
        "success": True,
        "suggested_reply": suggestion
    }

