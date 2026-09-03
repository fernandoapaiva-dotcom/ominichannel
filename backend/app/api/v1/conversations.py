import os
import asyncio
import uuid
import base64
import subprocess
import zipfile
import io
import re
import logging
import unicodedata
import httpx
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
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
from app.services.gemini_service import gemini_service, sanitize_customer_name
from app.services.evolution_service import evolution_service
from app.services.protocol_service import generate_daily_protocol
from app.services.distribution_service import distribution_service
from app.services.gdrive_service import gdrive_service
from app.api.websockets import manager as ws_manager

router = APIRouter(prefix="/conversations", tags=["Conversas e Mensagens"])

@router.get("/")
async def list_conversations(
    status_filter: Optional[ConversationStatus] = None,
    whatsapp_number_id: Optional[int] = None,
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # All attendants can view conversations across all departments of their tenant
    wn_stmt = select(WhatsAppNumber.id).where(WhatsAppNumber.tenant_id == current_user.tenant_id)
    wn_res = await db.execute(wn_stmt)
    accessible_wn_ids = wn_res.scalars().all()

    if not accessible_wn_ids:
        return []
    default_wn_id = accessible_wn_ids[0]

    # If search term is provided, auto-create placeholder conversations for contacts matching search that have no conversation yet
    if search and search.strip():
        term = f"%{search.strip()}%"
        existing_contact_ids_stmt = select(Conversation.contact_id).where(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.contact_id.isnot(None)
        )
        c_res = await db.execute(existing_contact_ids_stmt)
        existing_contact_ids = set(c_res.scalars().all())

        unlinked_contacts_stmt = select(Contact).where(
            Contact.tenant_id == current_user.tenant_id,
            or_(
                Contact.nome.ilike(term),
                Contact.telefone.ilike(term)
            )
        )
        if existing_contact_ids:
            unlinked_contacts_stmt = unlinked_contacts_stmt.where(Contact.id.notin_(existing_contact_ids))

        unlinked_contacts_res = await db.execute(unlinked_contacts_stmt)
        unlinked_contacts = unlinked_contacts_res.scalars().all()

        if unlinked_contacts:
            for u_contact in unlinked_contacts:
                new_conv = Conversation(
                    tenant_id=current_user.tenant_id,
                    whatsapp_number_id=whatsapp_number_id if whatsapp_number_id else default_wn_id,
                    contact_id=u_contact.id,
                    status=ConversationStatus.COM_HUMANO,
                    ultima_interacao_em=datetime.utcnow()
                )
                db.add(new_conv)
            await db.commit()

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

    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.join(Conversation.contact).where(
            or_(
                Contact.nome.ilike(term),
                Contact.telefone.ilike(term),
                Conversation.protocol_number.ilike(term),
                Conversation.assunto_atual.ilike(term)
            )
        ).order_by(Conversation.ultima_interacao_em.desc()).limit(100)
    else:
        stmt = stmt.order_by(Conversation.ultima_interacao_em.desc()).limit(150)

    result = await db.execute(stmt)
    conversations = result.scalars().all()

    user_ids = {c.assigned_user_id for c in conversations if c.assigned_user_id}
    user_map = {}
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        user_map = {u.id: u.nome for u in u_res.scalars().all()}

    response_list = []
    for c in conversations:
        contact_dict = None
        if c.contact:
            contact_dict = {
                "id": c.contact.id,
                "tenant_id": c.contact.tenant_id,
                "nome": c.contact.nome,
                "telefone": c.contact.telefone,
                "foto_perfil_url": c.contact.foto_perfil_url,
                "dados_adicionais": c.contact.dados_adicionais or {}
            }
        wn_dict = None
        if c.whatsapp_number:
            wn_dict = {
                "id": c.whatsapp_number.id,
                "tenant_id": c.whatsapp_number.tenant_id,
                "numero": c.whatsapp_number.numero,
                "nome_departamento": c.whatsapp_number.nome_departamento,
                "instancia_evolution_api": c.whatsapp_number.instancia_evolution_api,
                "provider_type": c.whatsapp_number.provider_type or "evolution",
                "status": c.whatsapp_number.status
            }
        msgs = []
        sorted_msgs = sorted((c.messages or []), key=lambda x: x.id)
        for m in sorted_msgs[-50:]:
            msgs.append({
                "id": m.id,
                "conversation_id": m.conversation_id,
                "remetente": m.remetente.value if hasattr(m.remetente, 'value') else str(m.remetente).lower(),
                "conteudo": m.conteudo,
                "tipo": m.tipo.value if hasattr(m.tipo, 'value') else str(m.tipo),
                "status": m.status or "sent",
                "whatsapp_msg_id": m.whatsapp_msg_id,
                "dados_adicionais": m.dados_adicionais or {},
                "timestamp": m.timestamp.isoformat() if m.timestamp else None
            })
        response_list.append({
            "id": c.id,
            "tenant_id": c.tenant_id,
            "whatsapp_number_id": c.whatsapp_number_id,
            "contact_id": c.contact_id,
            "protocol_number": c.protocol_number,
            "status": c.status.value if hasattr(c.status, 'value') else str(c.status),
            "assigned_user_id": c.assigned_user_id,
            "assigned_user_name": user_map.get(c.assigned_user_id),
            "assunto_atual": c.assunto_atual,
            "dados_adicionais": c.dados_adicionais or {},
            "criado_em": c.criado_em.isoformat() if c.criado_em else None,
            "ultima_interacao_em": c.ultima_interacao_em.isoformat() if c.ultima_interacao_em else None,
            "contact": contact_dict,
            "whatsapp_number": wn_dict,
            "messages": msgs
        })

    return response_list

class MarkAllReadPayload(BaseModel):
    whatsapp_number_id: Optional[int] = None

def resolve_remote_jid(conv: Conversation) -> str:
    raw = None
    if conv.contact and conv.contact.telefone:
        raw = str(conv.contact.telefone).strip()
    elif conv.dados_adicionais and "raw_phone" in conv.dados_adicionais:
        raw = str(conv.dados_adicionais["raw_phone"]).strip()
    
    if not raw:
        return ""
    
    if "@" in raw:
        return raw
    elif raw.startswith("120363") or "-" in raw or len(raw) > 15:
        return f"{raw}@g.us"
    else:
        return f"{raw}@s.whatsapp.net"

async def trigger_whatsapp_mark_read(db: AsyncSession, conv: Conversation, tenant_id: int):
    try:
        remote_jid = resolve_remote_jid(conv)
        if not remote_jid:
            return

        from sqlalchemy import func
        target_conv_ids = [conv.id]
        if conv.contact_id:
            c_stmt = select(Conversation.id).where(
                Conversation.tenant_id == tenant_id,
                Conversation.contact_id == conv.contact_id
            )
            c_res = await db.execute(c_stmt)
            target_conv_ids = [row[0] for row in c_res.all()]

        last_msg_stmt = (
            select(Message, WhatsAppNumber)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(WhatsAppNumber, WhatsAppNumber.id == Conversation.whatsapp_number_id)
            .where(
                Message.conversation_id.in_(target_conv_ids),
                func.lower(Message.remetente) == "cliente",
                Message.whatsapp_msg_id.isnot(None)
            )
            .order_by(Message.id.desc())
            .limit(1)
        )
        last_msg_res = await db.execute(last_msg_stmt)
        last_msg_row = last_msg_res.first()

        if last_msg_row:
            last_msg, wn = last_msg_row
            if wn and wn.instancia_evolution_api and last_msg.whatsapp_msg_id:
                decrypted = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
                asyncio.create_task(
                    evolution_service.mark_message_as_read(
                        instance_name=wn.instancia_evolution_api,
                        message_id=last_msg.whatsapp_msg_id,
                        remote_jid=remote_jid,
                        from_me=False,
                        custom_base_url=decrypted.get("evolution_api_url"),
                        custom_api_key=decrypted.get("evolution_api_key")
                    )
                )
    except Exception as err:
        logger.warning(f"Failed to trigger_whatsapp_mark_read for conv #{conv.id}: {err}")

@router.post("/mark_all_read")
async def mark_all_conversations_read(
    payload: Optional[MarkAllReadPayload] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Marks all client messages as read and flags conversations as read across the tenant (or selected department).
    Also sends read receipts to WhatsApp via Evolution API.
    """
    conv_stmt = select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.tenant_id == current_user.tenant_id)
    if payload and payload.whatsapp_number_id:
        conv_stmt = conv_stmt.where(Conversation.whatsapp_number_id == payload.whatsapp_number_id)

    conv_res = await db.execute(conv_stmt)
    convs = conv_res.scalars().all()
    conv_ids = [c.id for c in convs]
    if conv_ids:
        from sqlalchemy import update, func
        from sqlalchemy.orm.attributes import flag_modified
        upd_msgs = (
            update(Message)
            .where(
                Message.conversation_id.in_(conv_ids),
                func.lower(Message.remetente) == "cliente"
            )
            .values(status="read")
        )
        await db.execute(upd_msgs)

        for c in convs:
            extra = dict(c.dados_adicionais or {})
            extra["marked_as_read"] = True
            extra["pending_dismissed"] = True
            c.dados_adicionais = extra
            flag_modified(c, "dados_adicionais")

        await db.commit()

        # Trigger whatsapp mark read for each conversation in background
        for c in convs:
            await trigger_whatsapp_mark_read(db, c, current_user.tenant_id)

        # Broadcast WebSocket notification
        await ws_manager.broadcast_to_department(
            tenant_id=current_user.tenant_id,
            whatsapp_number_id=payload.whatsapp_number_id if payload else None,
            message_data={
                "type": "CONVERSATIONS_MARKED_READ",
                "whatsapp_number_id": payload.whatsapp_number_id if payload else None,
                "count": len(convs)
            }
        )

    return {
        "success": True,
        "marked_conversations_count": len(convs),
        "message": f"{len(convs)} conversas marcadas como lidas com sucesso!"
    }

@router.post("/{conversation_id}/mark_read")
async def mark_single_conversation_read(
    conversation_id: int,
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

    from sqlalchemy import update, func
    from sqlalchemy.orm.attributes import flag_modified
    
    # Mark all messages in all conversations of this contact as read
    target_conv_ids = [conv.id]
    if conv.contact_id:
        c_stmt = select(Conversation).where(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.contact_id == conv.contact_id
        )
        c_res = await db.execute(c_stmt)
        related_convs = c_res.scalars().all()
        target_conv_ids = [c.id for c in related_convs]
        for rc in related_convs:
            rc_extra = dict(rc.dados_adicionais or {})
            rc_extra["marked_as_read"] = True
            rc_extra["pending_dismissed"] = True
            rc.dados_adicionais = rc_extra
            flag_modified(rc, "dados_adicionais")

    upd_msgs = (
        update(Message)
        .where(
            Message.conversation_id.in_(target_conv_ids),
            func.lower(Message.remetente) == "cliente"
        )
        .values(status="read")
    )
    await db.execute(upd_msgs)

    extra = dict(conv.dados_adicionais or {})
    extra["marked_as_read"] = True
    extra["pending_dismissed"] = True
    conv.dados_adicionais = extra
    flag_modified(conv, "dados_adicionais")

    await db.commit()

    # Call Evolution API to mark messages as read on the WhatsApp device
    await trigger_whatsapp_mark_read(db, conv, current_user.tenant_id)

    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "MESSAGE_STATUS_UPDATE",
            "conversation_id": conv.id,
            "status": "read"
        }
    )

    return {"success": True, "message": "Conversa marcada como lida"}

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

    # Auto-resolve canonical registered WhatsApp number (handling 8 vs 9 digits in Brazil)
    if wn.instancia_evolution_api and (wn.provider_type or "evolution") != "meta":
        try:
            canonical_phone = await evolution_service.resolve_canonical_jid(wn.instancia_evolution_api, clean_phone)
            if canonical_phone and canonical_phone != clean_phone:
                clean_phone = canonical_phone
        except Exception as e:
            logger.debug(f"Could not auto-resolve canonical JID: {e}")

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
        inst_name = wn.instancia_evolution_api if wn else None
        if inst_name:
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

    inst_name = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else None
    if not inst_name:
        return {"message": "Instância do WhatsApp não configurada nesta conversa", "imported": 0}

    history_msgs = await evolution_service.fetch_chat_history(
        instance_name=inst_name,
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


@router.get("/link_preview")
async def get_url_link_preview(
    url: str = Query(..., description="Target URL to fetch OpenGraph preview for")
):
    """
    Fetches OpenGraph title, description, domain, and thumbnail image preview for a link.
    """
    from app.services.link_preview_service import link_preview_service
    preview = await link_preview_service.get_preview(url)
    return preview or {"url": url, "title": url, "description": None, "image": None, "domain": ""}


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
        Message.tipo.in_([MessageType.AUDIO, MessageType.IMAGEM, MessageType.VIDEO, MessageType.ARQUIVO])
    ).order_by(Message.timestamp.desc())
    
    res = await db.execute(stmt)
    return res.scalars().all()

@router.get("/messages/{message_id}/media")
async def get_message_media_stream(
    message_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    On-demand resolver/proxy for WhatsApp media.
    If message has a local /uploads/ URL, serves it.
    If message has an encrypted mmg.whatsapp.net URL or is pending download,
    automatically calls Evolution API to decrypt, downloads to /uploads/,
    updates DB, and streams the media.
    """
    stmt = (
        select(Message)
        .options(
            selectinload(Message.conversation).selectinload(Conversation.whatsapp_number),
            selectinload(Message.conversation).selectinload(Conversation.contact)
        )
        .where(Message.id == message_id)
    )
    res = await db.execute(stmt)
    msg = res.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")

    raw = msg.conteudo or ""
    media_path = raw.split("|")[0].strip() if "|" in raw else raw.strip()

    # If already a valid local file
    if media_path.startswith("/uploads/"):
        lpath = media_path.lstrip("/")
        if os.path.exists(lpath):
            return FileResponse(lpath)

    # If it's a WhatsApp mmg URL or missing local file, fetch from Evolution API
    if msg.whatsapp_msg_id and msg.conversation and msg.conversation.whatsapp_number:
        conv = msg.conversation
        inst_name = conv.whatsapp_number.instancia_evolution_api or "instancia_financeiro"
        remote_jid = conv.contact.telefone if conv.contact else None
        if remote_jid and not remote_jid.endswith("@s.whatsapp.net") and not remote_jid.endswith("@g.us"):
            remote_jid = f"{remote_jid}@g.us" if ("120363" in remote_jid or len(remote_jid) > 15) else f"{remote_jid}@s.whatsapp.net"

        from_me = (msg.remetente == MessageSender.ATENDENTE.value or msg.remetente == "atendente" or msg.remetente == "ia")

        instances_to_try = [inst_name] if inst_name else []

        b64_data = None
        for inst in instances_to_try:
            try:
                b64_data = await evolution_service.get_media_base64(
                    instance_name=inst,
                    message_id=msg.whatsapp_msg_id,
                    from_me=from_me,
                    remote_jid=remote_jid
                )
                if b64_data:
                    break
            except Exception as e:
                logger.error(f"Error fetching base64 on {inst}: {e}")

        if b64_data:
            ext = ".png"
            if msg.tipo == MessageType.VIDEO or msg.tipo == "video":
                ext = ".mp4"
            elif msg.tipo == MessageType.AUDIO or msg.tipo == "audio":
                ext = ".ogg"
            elif msg.tipo == MessageType.ARQUIVO or msg.tipo == "arquivo":
                ext = ".pdf"
            elif msg.tipo == MessageType.IMAGEM or msg.tipo == "imagem":
                ext = ".jpeg"

            try:
                os.makedirs("uploads", exist_ok=True)
                if "," in b64_data:
                    raw_bytes = base64.b64decode(b64_data.split(",")[1])
                else:
                    raw_bytes = base64.b64decode(b64_data)

                fname = f"{uuid.uuid4().hex}{ext}"
                fpath = os.path.join("uploads", fname)
                with open(fpath, "wb") as f:
                    f.write(raw_bytes)

                caption = raw.split("|", 1)[1] if "|" in raw else ""
                new_conteudo = f"/uploads/{fname}|{caption}" if caption else f"/uploads/{fname}"
                msg.conteudo = new_conteudo
                await db.commit()

                return FileResponse(fpath)
            except Exception as e:
                logger.error(f"Error caching media base64: {e}")

    # Fallback redirect if still external http
    if media_path.startswith("http") and not "mmg.whatsapp.net" in media_path:
        return RedirectResponse(url=media_path)

    raise HTTPException(status_code=404, detail="Mídia não disponível")

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

    is_admin = current_user.role == "admin" or str(getattr(current_user.role, 'value', current_user.role)).lower() == "admin"
    if conv.status == ConversationStatus.COM_HUMANO and conv.assigned_user_id and conv.assigned_user_id != current_user.id and not is_admin:
        u_stmt = select(User.nome).where(User.id == conv.assigned_user_id)
        u_res = await db.execute(u_stmt)
        assigned_name = u_res.scalar_one_or_none() or "outro atendente"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Este chamado está sendo atendido pelo atendente {assigned_name}. Apenas visualização permitida."
        )

    if not conv.assigned_user_id:
        conv.assigned_user_id = current_user.id

    raw_content = (msg_in.conteudo or "").strip()
    is_sticker = (
        str(msg_in.tipo).lower() in ("sticker", "figurinha") or
        raw_content.lower().endswith(".webp") or
        ("/uploads/" in raw_content and raw_content.lower().endswith(".webp"))
    )
    is_gif = (
        raw_content.lower().endswith(".gif") or
        "giphy.com" in raw_content.lower() or
        "tenor.com" in raw_content.lower()
    )
    is_media = (
        not is_sticker and not is_gif and (
            str(msg_in.tipo).lower() in (MessageType.IMAGEM, MessageType.VIDEO, MessageType.AUDIO, MessageType.ARQUIVO, "imagem", "video", "audio", "arquivo", "document", "documento") or
            "/uploads/" in raw_content or
            (raw_content.startswith("http") and any(raw_content.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".ogg", ".mp3", ".webm", ".m4a", ".pdf"]))
        )
    )

    actual_tipo = MessageType.IMAGEM if (is_sticker or is_gif) else msg_in.tipo
    clean_db_content = raw_content
    if "/uploads/" in raw_content:
        clean_db_content = "/uploads/" + raw_content.split("/uploads/")[-1]

    # 1. Immediate ACID DB commit (<15ms) so the message is never lost or delayed
    message = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=clean_db_content,
        tipo=actual_tipo,
        status="sent",
        timestamp=datetime.utcnow()
    )
    db.add(message)
    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()
    
    # Mark as read for attendant since attendant is currently speaking
    extra = dict(conv.dados_adicionais or {})
    extra["marked_as_read"] = True
    extra["pending_dismissed"] = True
    conv.dados_adicionais = extra
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(conv, "dados_adicionais")

    await db.commit()
    await db.refresh(message)

    tipo_str = actual_tipo.value if hasattr(actual_tipo, "value") else str(actual_tipo)

    # 2. Instant Real-time WebSocket Broadcast
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "id": message.id,
            "remetente": MessageSender.ATENDENTE.value,
            "conteudo": clean_db_content,
            "tipo": tipo_str,
            "status": "sent",
            "timestamp": str(message.timestamp),
            "agent_name": current_user.nome
        }
    )

    target_conv_id = conv.id
    target_tenant_id = current_user.tenant_id
    target_number_id = conv.whatsapp_number_id
    target_phone = conv.contact.telefone if conv.contact else ""
    target_instance_name = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else None
    agent_nome = current_user.nome or "Atendente"
    msg_id = message.id
    provider = WhatsAppProviderFactory.get_provider(conv.whatsapp_number)

    # 3. Background WhatsApp API Dispatch (Non-blocking async task with auto-retry)
    async def _async_dispatch_to_whatsapp():
        try:
            from app.core.database import AsyncSessionLocal
            send_res = {"success": False}
            wa_key_id = None

            # Retry loop: attempt up to 3 times before marking as failed
            for attempt in range(1, 4):
                try:
                    active_inst = target_instance_name

                    if is_sticker and active_inst:
                        sticker_media = raw_content
                        if "/uploads/" in raw_content:
                            fname = raw_content.split("/uploads/")[-1]
                            lpath = os.path.join("uploads", fname)
                            if os.path.exists(lpath):
                                with open(lpath, "rb") as f:
                                    sticker_media = base64.b64encode(f.read()).decode("utf-8")

                        send_res = await evolution_service.send_sticker(
                            instance_name=active_inst,
                            number=target_phone,
                            sticker_media=sticker_media
                        )
                    elif is_gif and active_inst:
                        send_res = await evolution_service.send_media_message(
                            instance_name=active_inst,
                            number=target_phone,
                            media_type="video",
                            mimetype="video/mp4",
                            media=raw_content,
                            file_name="animacao.mp4"
                        )
                    elif is_media and active_inst:
                        media_path = raw_content.split("|")[0].strip()
                        caption_text = raw_content.split("|")[1].strip() if "|" in raw_content else None
                        formatted_caption = f"*👤 {agent_nome}:*\n\n{caption_text}" if caption_text else f"*👤 {agent_nome}:*"

                        media_data = media_path
                        fname = "arquivo"
                        mimetype = "image/jpeg"
                        media_type = "image"

                        if "/uploads/" in media_path:
                            fname = media_path.split("/uploads/")[-1]
                            lpath = os.path.join("uploads", fname)
                            if os.path.exists(lpath):
                                with open(lpath, "rb") as f:
                                    media_data = base64.b64encode(f.read()).decode("utf-8")

                        f_lower = fname.lower()
                        if f_lower.endswith(".png"):
                            mimetype = "image/png"
                            media_type = "image"
                        elif f_lower.endswith((".jpg", ".jpeg")):
                            mimetype = "image/jpeg"
                            media_type = "image"
                        elif f_lower.endswith(".mp4"):
                            mimetype = "video/mp4"
                            media_type = "video"
                        elif f_lower.endswith((".webm", ".ogg", ".mp3", ".wav", ".m4a")):
                            mimetype = "audio/ogg"
                            media_type = "audio"
                        elif f_lower.endswith(".pdf"):
                            mimetype = "application/pdf"
                            media_type = "document"
                        else:
                            if str(msg_in.tipo).lower() in ("imagem", "image"):
                                media_type = "image"
                                mimetype = "image/jpeg"
                            elif str(msg_in.tipo).lower() == "video":
                                media_type = "video"
                                mimetype = "video/mp4"
                            elif str(msg_in.tipo).lower() == "audio":
                                media_type = "audio"
                                mimetype = "audio/ogg"
                            else:
                                media_type = "document"
                                mimetype = "application/octet-stream"

                        send_res = await evolution_service.send_media_message(
                            instance_name=active_inst,
                            number=target_phone,
                            media_type=media_type,
                            mimetype=mimetype,
                            media=media_data,
                            file_name=fname,
                            caption=formatted_caption
                        )
                    else:
                        formatted_whatsapp_text = f"*👤 {agent_nome}:*\n\n{msg_in.conteudo}"

                        # Extract mentions
                        mentioned_list = []
                        c_text = msg_in.conteudo or ""
                        import re

                        is_group_chat = bool(
                            target_phone and (
                                target_phone.startswith("120363") or
                                len("".join(filter(str.isdigit, target_phone))) > 15
                            )
                        )
                        if is_group_chat and any(k in c_text.lower() for k in ["@todos", "@everyone", "@all"]):
                            try:
                                g_info = await evolution_service.fetch_group_info(
                                    instance_name=active_inst,
                                    group_jid=target_phone if "@g.us" in target_phone else f"{target_phone}@g.us"
                                )
                                if g_info and "participants" in g_info:
                                    for p in g_info["participants"]:
                                        raw_p = p.get("phoneNumber") or p.get("id") or ""
                                        digits = "".join(filter(str.isdigit, raw_p.split("@")[0]))
                                        if len(digits) >= 8 and digits not in mentioned_list:
                                            mentioned_list.append(digits)
                            except Exception as ex:
                                logger.warning(f"Error resolving @todos participants: {ex}")

                        phone_mentions = re.findall(r"@(\d{10,15})", c_text)
                        for pm in phone_mentions:
                            if pm not in mentioned_list:
                                mentioned_list.append(pm)

                        send_res = await provider.send_text_message(
                            number=target_phone,
                            text=formatted_whatsapp_text,
                            mentioned=mentioned_list if mentioned_list else None
                        )

                    wa_key_id = send_res.get("key", {}).get("id") if isinstance(send_res.get("key"), dict) else send_res.get("id")
                    if send_res.get("success", False) or wa_key_id:
                        break
                except Exception as attempt_err:
                    logger.warning(f"Dispatch attempt {attempt} failed for msg #{msg_id}: {attempt_err}")

                if attempt < 3:
                    await asyncio.sleep(1.5)

            wa_key_id = send_res.get("key", {}).get("id") if isinstance(send_res.get("key"), dict) else send_res.get("id")
            final_status = "sent" if (send_res.get("success", False) or wa_key_id) else "failed"

            # Update DB record with WhatsApp Message ID
            async with AsyncSessionLocal() as bg_db:
                bg_m_stmt = select(Message).where(Message.id == msg_id)
                bg_m_res = await bg_db.execute(bg_m_stmt)
                db_msg = bg_m_res.scalar_one_or_none()
                if db_msg:
                    db_msg.whatsapp_msg_id = wa_key_id
                    db_msg.status = final_status
                    await bg_db.commit()

                # Mark customer's prior messages as read on WhatsApp since attendant is replying
                if final_status == "sent":
                    bg_c_stmt = select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == target_conv_id)
                    bg_c_res = await bg_db.execute(bg_c_stmt)
                    bg_conv = bg_c_res.scalar_one_or_none()
                    if bg_conv:
                        await trigger_whatsapp_mark_read(bg_db, bg_conv, target_tenant_id)

            # Broadcast status update if key id obtained or failed
            await ws_manager.broadcast_to_department(
                tenant_id=target_tenant_id,
                whatsapp_number_id=target_number_id,
                message_data={
                    "type": "MESSAGE_STATUS_UPDATE",
                    "conversation_id": target_conv_id,
                    "id": msg_id,
                    "status": final_status,
                    "whatsapp_msg_id": wa_key_id
                }
            )
        except Exception as bg_err:
            logger.error(f"Error in background WhatsApp dispatch: {bg_err}")

    asyncio.create_task(_async_dispatch_to_whatsapp())

    # 4. Trigger Smart Automation Engine (OS Handler & Custom Rules) in background
    from app.services.automation_service import automation_service
    asyncio.create_task(
        automation_service.process_and_dispatch_automation(
            tenant_id=current_user.tenant_id,
            conversation_id=conv.id,
            message_text=raw_content,
            from_me=True,
            contact_name=conv.contact.nome if conv.contact else "Cliente",
            instance_name=target_instance_name,
            recipient_phone=target_phone
        )
    )

    return message

@router.post("/messages/{message_id}/retry", response_model=MessageResponse)
async def retry_message_send(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retries sending a failed message to WhatsApp.
    """
    stmt = (
        select(Message)
        .options(selectinload(Message.conversation))
        .where(Message.id == message_id)
    )
    res = await db.execute(stmt)
    msg = res.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")

    conv = msg.conversation
    if not conv or conv.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.id == conv.whatsapp_number_id)
    wn_res = await db.execute(wn_stmt)
    wn = wn_res.scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=400, detail="Número de WhatsApp não configurado")

    msg.status = "sending"
    await db.commit()

    target_conv_id = conv.id
    target_tenant_id = current_user.tenant_id
    target_number_id = conv.whatsapp_number_id
    target_phone = conv.contact.telefone if conv.contact else ""
    target_instance_name = wn.instancia_evolution_api
    agent_nome = current_user.nome or "Atendente"
    provider = WhatsAppProviderFactory.get_provider(wn)
    raw_content = msg.conteudo or ""

    is_sticker = str(msg.tipo).lower() in ("sticker", "figurinha") or raw_content.lower().endswith(".webp")
    is_gif = raw_content.lower().endswith(".gif") or "giphy.com" in raw_content.lower() or "tenor.com" in raw_content.lower()
    is_media = not is_sticker and not is_gif and (
        str(msg.tipo).lower() in (MessageType.IMAGEM, MessageType.VIDEO, MessageType.AUDIO, MessageType.ARQUIVO, "imagem", "video", "audio", "arquivo", "document", "documento") or
        "/uploads/" in raw_content or
        (raw_content.startswith("http") and any(raw_content.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".ogg", ".mp3", ".pdf"]))
    )

    async def _async_retry_dispatch():
        try:
            send_res = {"success": False}
            wa_key_id = None

            for attempt in range(1, 4):
                try:
                    if is_sticker and target_instance_name:
                        sticker_media = raw_content
                        if "/uploads/" in raw_content:
                            fname = raw_content.split("/uploads/")[-1]
                            lpath = os.path.join("uploads", fname)
                            if os.path.exists(lpath):
                                with open(lpath, "rb") as f:
                                    sticker_media = base64.b64encode(f.read()).decode("utf-8")
                        send_res = await evolution_service.send_sticker(
                            instance_name=target_instance_name,
                            number=target_phone,
                            sticker_media=sticker_media
                        )
                    elif is_gif and target_instance_name:
                        send_res = await evolution_service.send_media_message(
                            instance_name=target_instance_name,
                            number=target_phone,
                            media_type="video",
                            mimetype="video/mp4",
                            media=raw_content,
                            file_name="animacao.mp4"
                        )
                    elif is_media and target_instance_name:
                        media_path = raw_content.split("|")[0].strip()
                        caption_text = raw_content.split("|")[1].strip() if "|" in raw_content else None
                        formatted_caption = f"*👤 {agent_nome}:*\n\n{caption_text}" if caption_text else None
                        fname = os.path.basename(media_path)
                        
                        media_data = media_path
                        if media_path.startswith("/uploads/"):
                            local_filepath = os.path.join("uploads", os.path.basename(media_path))
                            if os.path.exists(local_filepath):
                                with open(local_filepath, "rb") as f:
                                    media_data = base64.b64encode(f.read()).decode("utf-8")

                        ext = os.path.splitext(fname)[1].lower()
                        if ext in (".png", ".jpg", ".jpeg", ".webp"):
                            media_type = "image"
                            mimetype = f"image/{ext.replace('.', '')}"
                        elif ext in (".mp4", ".mov", ".avi"):
                            media_type = "video"
                            mimetype = "video/mp4"
                        elif ext in (".ogg", ".mp3", ".wav", ".m4a"):
                            media_type = "audio"
                            mimetype = "audio/ogg"
                        else:
                            media_type = "document"
                            mimetype = "application/octet-stream"

                        send_res = await evolution_service.send_media_message(
                            instance_name=target_instance_name,
                            number=target_phone,
                            media_type=media_type,
                            mimetype=mimetype,
                            media=media_data,
                            file_name=fname,
                            caption=formatted_caption
                        )
                    else:
                        formatted_whatsapp_text = raw_content if raw_content.startswith("*👤") else f"*👤 {agent_nome}:*\n\n{raw_content}"
                        send_res = await provider.send_text_message(
                            number=target_phone,
                            text=formatted_whatsapp_text
                        )

                    wa_key_id = send_res.get("key", {}).get("id") if isinstance(send_res.get("key"), dict) else send_res.get("id")
                    if send_res.get("success", False) or wa_key_id:
                        break
                except Exception as attempt_err:
                    logger.warning(f"Retry attempt {attempt} failed for msg #{message_id}: {attempt_err}")

                if attempt < 3:
                    await asyncio.sleep(1.5)

            wa_key_id = send_res.get("key", {}).get("id") if isinstance(send_res.get("key"), dict) else send_res.get("id")
            final_status = "sent" if (send_res.get("success", False) or wa_key_id) else "failed"

            from app.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as bg_db:
                bg_m_stmt = select(Message).where(Message.id == message_id)
                bg_m_res = await bg_db.execute(bg_m_stmt)
                db_msg = bg_m_res.scalar_one_or_none()
                if db_msg:
                    db_msg.whatsapp_msg_id = wa_key_id
                    db_msg.status = final_status
                    await bg_db.commit()

                if final_status == "sent":
                    bg_c_stmt = select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == target_conv_id)
                    bg_c_res = await bg_db.execute(bg_c_stmt)
                    bg_conv = bg_c_res.scalar_one_or_none()
                    if bg_conv:
                        await trigger_whatsapp_mark_read(bg_db, bg_conv, target_tenant_id)

            await ws_manager.broadcast_to_department(
                tenant_id=target_tenant_id,
                whatsapp_number_id=target_number_id,
                message_data={
                    "type": "MESSAGE_STATUS_UPDATE",
                    "conversation_id": target_conv_id,
                    "id": message_id,
                    "status": final_status,
                    "whatsapp_msg_id": wa_key_id
                }
            )
        except Exception as bg_err:
            logger.error(f"Error in background WhatsApp retry dispatch: {bg_err}")

    asyncio.create_task(_async_retry_dispatch())
    return msg


    # 4. Trigger Smart Automation Engine (OS Handler & Custom Rules) in background
    from app.services.automation_service import automation_service
    asyncio.create_task(
        automation_service.process_and_dispatch_automation(
            tenant_id=target_tenant_id,
            conversation_id=target_conv_id,
            message_text=raw_content,
            from_me=True,
            contact_name=conv.contact.nome if conv.contact else "Cliente",
            instance_name=target_instance_name,
            recipient_phone=target_phone
        )
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

    primary_inst = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else ""
    if not primary_inst:
        raise HTTPException(status_code=400, detail="Instância de WhatsApp não configurada para este setor.")

    res_loc = await evolution_service.send_location_message(
        instance_name=primary_inst,
        number=conv.contact.telefone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        name=payload.name,
        address=payload.address
    )

    if not res_loc.get("success"):
        dept_name = conv.whatsapp_number.nome_departamento if conv.whatsapp_number else "do setor"
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao enviar card de localização no WhatsApp. A instância de '{dept_name}' não está conectada no Painel Admin."
        )

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

@router.post("/{conversation_id}/presence")
async def send_conversation_presence(
    conversation_id: int,
    presence_in: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    presence_state = presence_in.get("presence", "composing")
    conv = await get_conversation_or_404(db, conversation_id, current_user.tenant_id)
    contact = await db.get(Contact, conv.contact_id)
    wn = await db.get(WhatsAppNumber, conv.whatsapp_number_id)
    
    if wn and wn.instancia_evolution_api and contact:
        clean_phone = contact.telefone.split("@")[0].split(":")[0]
        asyncio.create_task(
            evolution_service.send_presence(
                instance_name=wn.instancia_evolution_api,
                number=clean_phone,
                presence=presence_state
            )
        )
        asyncio.create_task(
            ws_manager.broadcast_to_tenant(current_user.tenant_id, {
                "type": "USER_PRESENCE",
                "conversation_id": conv.id,
                "phone": clean_phone,
                "presence": f"attendant_{presence_state}",
                "agent_name": current_user.nome
            })
        )
    return {"success": True, "presence": presence_state}

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

    primary_inst = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else ""
    if not primary_inst:
        raise HTTPException(status_code=400, detail="Instância de WhatsApp não configurada para este setor.")

    res_media = await evolution_service.send_media_message(
        instance_name=primary_inst,
        number=conv.contact.telefone,
        media_type="image",
        mimetype="image/png",
        media=base64_img,
        file_name="qrcode_pix.png",
        caption=formatted_caption
    )

    if not res_media.get("success"):
        dept_name = conv.whatsapp_number.nome_departamento if conv.whatsapp_number else "do setor"
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao enviar o QR Code do Pix no WhatsApp. A instância de '{dept_name}' não está conectada no Painel Admin."
        )

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

@router.post("/upload")
async def upload_general_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    os.makedirs("uploads", exist_ok=True)
    raw_ext = (os.path.splitext(file.filename)[1] or ".webm").lower()
    unique_base = uuid.uuid4().hex
    temp_filename = f"{unique_base}_raw{raw_ext}"
    temp_path = os.path.join("uploads", temp_filename)

    file_bytes = await file.read()
    with open(temp_path, "wb") as f:
        f.write(file_bytes)

    # Determine if file is audio — check extension AND MIME type
    # iOS/Safari records audio as .mp4 (audio-only MP4 with Opus codec)
    # Also check content_type for audio/* MIME types regardless of extension
    is_audio_ext = raw_ext in [".webm", ".ogg", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".mp4", ".3gp", ".3gpp"]
    is_audio_mime = (file.content_type or "").startswith("audio/")

    # For .mp4 specifically, use ffprobe to check if it's audio-only (no video stream)
    # This distinguishes audio recordings from actual video files
    if raw_ext == ".mp4" and not is_audio_mime:
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_streams", "-of", "json", temp_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8
            )
            if probe.returncode == 0:
                import json as _json
                probe_data = _json.loads(probe.stdout.decode())
                streams = probe_data.get("streams", [])
                has_video = any(s.get("codec_type") == "video" for s in streams)
                has_audio = any(s.get("codec_type") == "audio" for s in streams)
                if has_audio and not has_video:
                    is_audio_ext = True  # Audio-only mp4, treat as audio
                elif has_video:
                    is_audio_ext = False  # Real video file, do NOT convert
        except Exception as probe_err:
            logger.warning(f"ffprobe check failed for mp4: {probe_err}")

    if is_audio_ext or is_audio_mime:
        final_filename = f"{unique_base}.ogg"
        final_path = os.path.join("uploads", final_filename)
        try:
            cmd = [
                "ffmpeg", "-y", "-i", temp_path,
                "-vn",          # Drop any video stream
                "-c:a", "libopus",
                "-b:a", "32k",
                "-ar", "48000",
                "-ac", "1",
                "-application", "voip",
                final_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if res.returncode == 0 and os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                logger.info(f"[UPLOAD] Audio converted: {temp_path} -> {final_path} ({os.path.getsize(final_path)} bytes)")
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
                return {"url": f"/uploads/{final_filename}", "filename": final_filename}
            else:
                logger.error(f"[UPLOAD] ffmpeg failed (rc={res.returncode}): {res.stderr.decode()[:300]}")
        except Exception as err:
            logger.error(f"Error converting audio upload with ffmpeg: {err}")

    # Fallback for non-audio or if ffmpeg conversion failed
    unique_filename = f"{unique_base}{raw_ext}"
    final_path = os.path.join("uploads", unique_filename)
    if temp_path != final_path:
        os.rename(temp_path, final_path)

    return {"url": f"/uploads/{unique_filename}", "filename": file.filename}

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

    primary_inst = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else ""
    if not primary_inst:
        raise HTTPException(status_code=400, detail="Instância de WhatsApp não configurada para este setor.")

    from app.services.evolution_service import evolution_service
    send_res = await evolution_service.send_media_message(
        instance_name=primary_inst,
        number=conv.contact.telefone,
        media_type=media_type,
        mimetype=mimetype,
        media=base64_data,
        file_name=file.filename or unique_filename,
        caption=formatted_caption
    )

    is_success = send_res.get("success", False) or bool(send_res.get("key")) or bool(send_res.get("id")) or send_res.get("status") in ["PENDING", "SENT", "DELIVERED", 200, 201]
    if not is_success:
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
            gdrive_settings = await settings_service.get_tenant_decrypted_settings(db, conv.tenant_id)
            await gdrive_service.sync_conversation_to_drive(
                tenant_drive_folder_id=gdrive_settings.get("gdrive_folder_id") or "1Xv8qI4NLU9pjbbUvCZami3TfkgsjRfd0",
                conversation_id=conv.id,
                contact_phone=conv_export["contact_phone"],
                conversation_data=conv_export,
                refresh_token=gdrive_settings.get("gdrive_refresh_token", ""),
                client_id=gdrive_settings.get("google_client_id", ""),
                client_secret=gdrive_settings.get("google_client_secret", ""),
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

@router.post("/{conversation_id}/assume", response_model=ConversationResponse)
async def assume_conversation_control(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Allows an attendant (or admin) to intervene and assume control of an AI-handled or unassigned conversation.
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

    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    # Insert system audit message in the chat
    sys_msg = Message(
        conversation_id=conv.id,
        remetente=MessageSender.SISTEMA,
        conteudo=f"👤 *{current_user.nome}* assumiu o controle do atendimento.",
        tipo=MessageType.TEXTO,
        timestamp=datetime.utcnow()
    )
    db.add(sys_msg)
    await db.commit()
    await db.refresh(conv)

    # Broadcast WebSocket events
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "STATUS_CHANGE",
            "conversation_id": conv.id,
            "status": "com_humano",
            "assigned_user_id": current_user.id,
            "assigned_user_name": current_user.nome
        }
    )
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conv.id,
            "remetente": "sistema",
            "conteudo": sys_msg.conteudo,
            "timestamp": str(sys_msg.timestamp)
        }
    )

    c_dict = ConversationResponse.model_validate(conv).model_dump()
    c_dict["assigned_user_name"] = current_user.nome
    return c_dict

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


class CopilotChatRequest(BaseModel):
    user_prompt: str
    chat_history: Optional[List[Dict[str, str]]] = []


@router.post("/{conversation_id}/copilot-chat")
async def copilot_chat_for_conversation(
    conversation_id: int,
    payload: CopilotChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Interactive Copilot AI conversation for the human attendant:
    Answers technical questions, analyzes entire customer context, checks RAG knowledge base,
    and returns advice + ready-to-use message proposals.
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

    # Fetch conversation memory
    from app.models.models import ConversationMemory
    mem_res = await db.execute(
        select(ConversationMemory).where(
            ConversationMemory.tenant_id == current_user.tenant_id,
            ConversationMemory.contact_id == conv.contact_id
        )
    )
    memory = mem_res.scalar_one_or_none()
    memory_summary = memory.resumo_estruturado if memory else None

    # Query RAG context using both customer topic & attendant's prompt
    rag_context = ""
    try:
        from app.services.rag_service import rag_service
        search_query = f"{payload.user_prompt}"
        customer_msgs = [m for m in conv.messages if str(m.remetente).lower() == "cliente"]
        if customer_msgs:
            search_query += f" {customer_msgs[-1].conteudo or ''}"
        rag_res = await rag_service.query_relevant_context(current_user.tenant_id, search_query)
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

    result = await gemini_service.generate_copilot_consultation(
        attendant_name=current_user.nome or "Atendente",
        customer_name=customer_name,
        department_name=dept_name,
        conversation_history=history_dicts,
        copilot_chat_history=payload.chat_history or [],
        user_question=payload.user_prompt,
        rag_context=rag_context,
        memory_summary=memory_summary,
        customer_phone=conv.contact.telefone if conv.contact else None,
        protocol_number=conv.protocol_number,
        tenant_gemini_api_key=decrypted.get("gemini_api_key"),
        tenant_gemini_model_name=decrypted.get("gemini_model_name")
    )

    suggested_msg = result.get("suggested_message", "")
    answer_text = result.get("answer", "")

    # Detect if user prompt or suggestion relates to location
    prompt_lower = (payload.user_prompt or "").lower()
    combined_text = f"{prompt_lower} {suggested_msg.lower()} {answer_text.lower()}"
    has_location = (
        "localiza" in combined_text or
        "endereço" in combined_text or
        "endereco" in combined_text or
        "como chegar" in combined_text or
        "onde fica" in combined_text or
        "maps" in combined_text or
        "gps" in combined_text or
        "sof sul" in combined_text or
        "71215-226" in combined_text
    )

    location_payload = {
        "name": "Servweld / Servsolda",
        "address": "SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226",
        "latitude": -15.820418,
        "longitude": -47.956467
    } if has_location else None

    return {
        "success": True,
        "answer": answer_text,
        "suggested_message": suggested_msg,
        "has_location": bool(has_location),
        "location_data": location_payload
    }


class ReportAIErrorRequest(BaseModel):
    resposta_ia: Optional[str] = None
    resposta_correta: str
    categoria_erro: str = "outro" # alucinacao_nome, alucinacao_historico, tom_errado, informacao_incorreta, outro
    contexto_enviado: Optional[str] = None


@router.post("/{conversation_id}/report-ai-error")
async def report_ai_error(
    conversation_id: int,
    payload: ReportAIErrorRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Loop de melhoria contínua: Atendente marca erro em resposta da IA e informa a resposta correta.
    Salva na tabela correcoes_ia para revisão e extração de exemplos few-shot.
    """
    from app.models.models import AICorrection
    conv_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id
    )
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()

    correction = AICorrection(
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        protocolo=conv.protocol_number if conv else None,
        contexto_enviado=payload.contexto_enviado,
        resposta_ia=payload.resposta_ia,
        resposta_correta=payload.resposta_correta,
        categoria_erro=payload.categoria_erro,
        revisado=False,
        criado_em=datetime.utcnow()
    )
    db.add(correction)
    await db.commit()
    await db.refresh(correction)

    return {
        "success": True,
        "message": "Correção de IA registrada com sucesso no banco para revisão contínua.",
        "id": correction.id
    }


@router.get("/ai-corrections/list")
async def list_ai_corrections(
    revisado: Optional[bool] = None,
    categoria_erro: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from app.models.models import AICorrection
    conditions = [AICorrection.tenant_id == current_user.tenant_id]
    if revisado is not None:
        conditions.append(AICorrection.revisado == revisado)
    if categoria_erro:
        conditions.append(AICorrection.categoria_erro == categoria_erro)

    stmt = (
        select(AICorrection)
        .where(*conditions)
        .order_by(AICorrection.criado_em.desc())
        .limit(100)
    )
    res = await db.execute(stmt)
    items = res.scalars().all()
    return [
        {
            "id": c.id,
            "conversation_id": c.conversation_id,
            "protocolo": c.protocolo,
            "resposta_ia": c.resposta_ia,
            "resposta_correta": c.resposta_correta,
            "categoria_erro": c.categoria_erro,
            "revisado": c.revisado,
            "criado_em": c.criado_em.isoformat() if c.criado_em else None
        }
        for c in items
    ]


class EditMessageRequest(BaseModel):
    new_text: str


@router.put("/messages/{message_id}")
async def edit_message_endpoint(
    message_id: int,
    payload: EditMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Edits a sent message both locally in database and on WhatsApp via Evolution API.
    """
    stmt = (
        select(Message)
        .options(
            selectinload(Message.conversation).selectinload(Conversation.whatsapp_number),
            selectinload(Message.conversation).selectinload(Conversation.contact)
        )
        .where(Message.id == message_id)
    )
    res = await db.execute(stmt)
    msg = res.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada")

    conv = msg.conversation
    if not conv or conv.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Acesso negado a esta conversa")

    # Update in Evolution API if WhatsApp message id is present
    if msg.whatsapp_msg_id and conv.whatsapp_number and conv.contact:
        inst = conv.whatsapp_number.instancia_evolution_api
        phone = conv.contact.telefone

        # Determine WhatsApp text: if sent by attendant, keep attendant header
        whatsapp_new_text = payload.new_text
        if msg.remetente in ["atendente", MessageSender.ATENDENTE.value]:
            agent_nome = current_user.nome if current_user and current_user.nome else "Atendente"
            whatsapp_new_text = f"*👤 {agent_nome}:*\n\n{payload.new_text}"

        try:
            edit_res = await evolution_service.edit_message(
                instance_name=inst,
                number=phone,
                message_id=msg.whatsapp_msg_id,
                new_text=whatsapp_new_text
            )
            logger.info(f"Evolution API message edit result for msg {msg.id}: {edit_res}")
        except Exception as err:
            logger.error(f"Could not edit message on WhatsApp instance: {err}")

    # Update local DB
    msg.conteudo = payload.new_text
    msg.status = "edited"
    await db.commit()

    # Broadcast via WebSockets
    await ws_manager.broadcast_to_department(
        tenant_id=conv.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "MESSAGE_EDITED",
            "conversation_id": conv.id,
            "message_id": msg.id,
            "new_text": payload.new_text,
            "status": "edited"
        }
    )

    return {
        "success": True,
        "message_id": msg.id,
        "new_text": payload.new_text,
        "status": "edited"
    }


async def dispatch_whatsapp_notification(
    db: AsyncSession,
    conv: Conversation,
    text: str,
    tenant_id: int
) -> Dict[str, Any]:
    if not conv.contact or not conv.contact.telefone:
        return {"success": False, "error": "Contato sem telefone"}

    provider = WhatsAppProviderFactory.get_provider(conv.whatsapp_number)
    try:
        send_res = await provider.send_text_message(
            number=conv.contact.telefone,
            text=text
        )
        return send_res
    except Exception as e:
        logger.warning(f"Error dispatching WhatsApp protocol message: {e}")
        return {"success": False, "error": str(e)}


@router.post("/{conversation_id}/open_protocol")
async def open_conversation_protocol(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually opens a formal service protocol on the ongoing conversation.
    Sends WhatsApp notification to the customer and registers protocol milestone.
    """
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
        .where(Conversation.id == conversation_id, Conversation.tenant_id == current_user.tenant_id)
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    new_protocol = await generate_daily_protocol(db, current_user.tenant_id)
    conv.protocol_number = new_protocol
    conv.status = ConversationStatus.COM_HUMANO
    conv.assigned_user_id = current_user.id
    conv.ultima_interacao_em = datetime.utcnow()

    clean_cust_name = sanitize_customer_name(conv.contact.nome if conv.contact else "Cliente")
    dept_name = conv.whatsapp_number.nome_departamento if conv.whatsapp_number else "Atendimento"
    whatsapp_text = (
        f"📋 *Servweld - Protocolo de Atendimento*\n\n"
        f"Olá, {clean_cust_name}! Seu atendimento formal foi iniciado com sucesso.\n\n"
        f"🔢 *Protocolo do seu chamado:* #{new_protocol}\n"
        f"👤 *Atendente:* {current_user.nome}\n"
        f"🏢 *Setor:* {dept_name}\n\n"
        f"Como podemos te ajudar hoje?"
    )

    # Dispatch to customer's WhatsApp
    wa_res = await dispatch_whatsapp_notification(db, conv, whatsapp_text, current_user.tenant_id)
    wa_key_id = wa_res.get("key", {}).get("id") if isinstance(wa_res.get("key"), dict) else wa_res.get("id")

    # Message in chat
    sys_msg = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=whatsapp_text,
        tipo=MessageType.TEXTO,
        status="sent" if wa_res.get("success") else "pending",
        whatsapp_msg_id=wa_key_id,
        timestamp=datetime.utcnow()
    )
    db.add(sys_msg)

    # Opening Divider Marker
    divider_msg = Message(
        conversation_id=conv.id,
        remetente=MessageSender.SISTEMA,
        conteudo=f"PROTOCOLO FORMAL ABERTO: #{new_protocol} Atendimento formal iniciado por {current_user.nome}. Notificação enviada ao cliente.",
        tipo=MessageType.TEXTO,
        timestamp=datetime.utcnow()
    )
    db.add(divider_msg)

    await db.commit()
    await db.refresh(conv)

    # Broadcast real-time update
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "conversation_updated",
            "conversation_id": conv.id,
            "protocol_number": new_protocol,
            "status": conv.status.value,
            "assigned_user_id": conv.assigned_user_id
        }
    )

    return {
        "success": True,
        "protocol_number": new_protocol,
        "message": f"Protocolo #{new_protocol} aberto e notificação enviada ao cliente com sucesso!"
    }


@router.post("/{conversation_id}/close_protocol")
async def close_conversation_protocol(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually closes/finalizes the active protocol on the ongoing conversation.
    Sends WhatsApp closing notification to customer and leaves chat open.
    """
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
        .where(Conversation.id == conversation_id, Conversation.tenant_id == current_user.tenant_id)
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    current_proto = conv.protocol_number or "ATUAL"
    clean_cust_name = sanitize_customer_name(conv.contact.nome if conv.contact else "Cliente")
    now_str = datetime.now().strftime("%d/%m/%Y às %H:%M")
    
    whatsapp_text = (
        f"🔒 *Servweld - Protocolo Finalizado*\n\n"
        f"Olá, {clean_cust_name}! Informamos que o seu atendimento referente ao *Protocolo #{current_proto}* foi finalizado por {current_user.nome}.\n\n"
        f"⭐ *Pesquisa de Satisfação:*\n"
        f"Como você avalia nosso atendimento de 1 a 5 estrelas? (Por favor, responda com uma nota de 1 a 5)\n\n"
        f"Agradecemos pela preferência! O canal permanece à disposição sempre que precisar."
    )

    # Dispatch to customer's WhatsApp
    wa_res = await dispatch_whatsapp_notification(db, conv, whatsapp_text, current_user.tenant_id)
    wa_key_id = wa_res.get("key", {}).get("id") if isinstance(wa_res.get("key"), dict) else wa_res.get("id")

    # Message in chat
    sys_msg = Message(
        conversation_id=conv.id,
        remetente=MessageSender.ATENDENTE,
        conteudo=whatsapp_text,
        tipo=MessageType.TEXTO,
        status="sent" if wa_res.get("success") else "pending",
        whatsapp_msg_id=wa_key_id,
        timestamp=datetime.utcnow()
    )
    db.add(sys_msg)

    # Closing Divider Milestone
    divider_msg = Message(
        conversation_id=conv.id,
        remetente=MessageSender.SISTEMA,
        conteudo=f"PROTOCOLO #{current_proto} FINALIZADO Atendimento concluído em {now_str} por {current_user.nome}. O canal de conversa permanece aberto e disponível para novas mensagens.",
        tipo=MessageType.TEXTO,
        timestamp=datetime.utcnow()
    )
    db.add(divider_msg)

    # Update conversation status
    conv.status = ConversationStatus.ENCERRADA
    conv.protocol_number = None
    conv.ultima_interacao_em = datetime.utcnow()

    if conv.contact_id:
        from app.models.models import ConversationMemory
        from sqlalchemy import delete
        await db.execute(
            delete(ConversationMemory).where(
                ConversationMemory.tenant_id == current_user.tenant_id,
                ConversationMemory.contact_id == conv.contact_id
            )
        )

    await db.commit()
    await db.refresh(conv)

    # Broadcast real-time update
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "conversation_updated",
            "conversation_id": conv.id,
            "protocol_number": None,
            "status": conv.status.value,
            "resumo_ia": None,
            "assigned_user_id": conv.assigned_user_id
        }
    )

    return {
        "success": True,
        "message": f"Protocolo #{current_proto} finalizado e notificação enviada ao cliente com sucesso!"
    }

@router.post("/{conversation_id}/toggle-pin")
async def toggle_pin_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Toggles the pinned status of a conversation (or group) specifically for the current logged-in user.
    """
    stmt = (
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    extra = dict(conv.dados_adicionais or {})
    pinned_users = list(extra.get("pinned_by_users") or [])
    user_id = current_user.id

    if user_id in pinned_users:
        pinned_users.remove(user_id)
        new_pinned = False
    else:
        pinned_users.append(user_id)
        new_pinned = True

    # Find all conversations of this contact to sync the pin across all threads
    sibling_stmt = select(Conversation).where(
        Conversation.tenant_id == current_user.tenant_id,
        Conversation.contact_id == conv.contact_id
    )
    sibling_res = await db.execute(sibling_stmt)
    all_convs = sibling_res.scalars().all() or [conv]

    from sqlalchemy.orm.attributes import flag_modified
    for c in all_convs:
        c_extra = dict(c.dados_adicionais or {})
        c_extra["pinned_by_users"] = pinned_users
        c_extra[f"pinned_user_{user_id}"] = new_pinned
        c_extra.pop("is_pinned", None)
        c.dados_adicionais = c_extra
        flag_modified(c, "dados_adicionais")

    await db.commit()

    # Broadcast WebSocket update
    await ws_manager.broadcast_to_department(
        tenant_id=current_user.tenant_id,
        whatsapp_number_id=conv.whatsapp_number_id,
        message_data={
            "type": "conversation_pinned_toggled",
            "conversation_id": conv.id,
            "contact_id": conv.contact_id,
            "user_id": user_id,
            "is_pinned": new_pinned
        }
    )

    return {
        "success": True,
        "conversation_id": conv.id,
        "contact_id": conv.contact_id,
        "user_id": user_id,
        "is_pinned": new_pinned,
        "pinned_by_users": pinned_users,
        "message": "Conversa fixada no topo com sucesso!" if new_pinned else "Conversa desfixada do topo!"
    }

@router.get("/{conversation_id}/participants")
async def get_conversation_participants(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches real WhatsApp Group participants and resolves their names from Contact database.
    """
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact), selectinload(Conversation.whatsapp_number))
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id
        )
    )
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    raw_phone = conv.contact.telefone if conv.contact else ""
    is_group = (
        raw_phone.startswith("120363") or
        len("".join(filter(str.isdigit, raw_phone))) > 15 or
        (conv.contact and "Servweld/Servsolda" in (conv.contact.nome or "")) or
        (conv.dados_adicionais or {}).get("is_group")
    )

    if not is_group:
        # For direct 1-on-1 chats, return the single contact
        return {
            "conversation_id": conv.id,
            "is_group": False,
            "subject": conv.contact.nome if conv.contact else "Cliente",
            "total_participants": 1,
            "participants": [
                {
                    "id": conv.contact.telefone if conv.contact else "",
                    "phone": conv.contact.telefone if conv.contact else "",
                    "lid": "",
                    "name": conv.contact.nome if conv.contact else "Cliente",
                    "avatar_url": conv.contact.foto_perfil_url if conv.contact else None,
                    "is_admin": False
                }
            ]
        }

    group_jid = raw_phone if "@g.us" in raw_phone else f"{raw_phone}@g.us"
    instance_name = conv.whatsapp_number.instancia_evolution_api if conv.whatsapp_number else None

    group_info = await evolution_service.fetch_group_info(
        instance_name=instance_name,
        group_jid=group_jid
    )

    participants_raw = (group_info or {}).get("participants", [])
    subject = (group_info or {}).get("subject") or (conv.contact.nome if conv.contact else "Grupo WhatsApp")

    mapped_participants = []
    for p in participants_raw:
        p_raw = p.get("phoneNumber") or p.get("id") or ""
        clean_digits = "".join(filter(str.isdigit, p_raw.split("@")[0]))
        lid_id = p.get("id", "").split("@")[0] if "@lid" in str(p.get("id", "")) else ""

        # Match contact by phone in DB
        c_stmt = select(Contact).where(
            Contact.tenant_id == current_user.tenant_id
        )
        if len(clean_digits) >= 8:
            c_stmt = c_stmt.where(Contact.telefone.like(f"%{clean_digits[-8:]}%"))
        else:
            c_stmt = c_stmt.where(Contact.telefone == clean_digits)

        c_res = await db.execute(c_stmt)
        matched_contact = c_res.scalars().first()

        name = matched_contact.nome if matched_contact and matched_contact.nome else None
        if not name:
            name = f"+{clean_digits}" if clean_digits else (p.get("id") or "Participante")

        mapped_participants.append({
            "id": p.get("id") or clean_digits,
            "phone": clean_digits,
            "lid": lid_id,
            "name": name,
            "avatar_url": matched_contact.foto_perfil_url if matched_contact else None,
            "is_admin": p.get("admin") in ["admin", "superadmin"]
        })

    # Sort participants: admins first, then alphabetically by name
    mapped_participants.sort(key=lambda x: (not x["is_admin"], x["name"].lower()))

    return {
        "conversation_id": conv.id,
        "is_group": True,
        "subject": subject,
        "total_participants": len(mapped_participants),
        "participants": mapped_participants
    }



