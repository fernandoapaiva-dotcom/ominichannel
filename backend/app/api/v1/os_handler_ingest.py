"""
Endpoint de ingestão de PDF da Ordem de Serviço (O.S.) para a Assistência Técnica.

O ERP Softsystem, usado na loja, salva um PDF em duas pastas diferentes do computador
da loja, cada uma com um momento e um sentido diferente:
  - ABERTURA: quando a O.S. é aberta (o cliente trouxe o equipamento) - Orçamento,
    Garantia de Loja, Garantia de Fábrica ou Locação.
  - ORCAMENTO: quando o técnico já fez o laudo e a O.S. é alimentada com o valor do
    reparo, aguardando a aprovação do cliente para executar o serviço.

Um "vigia de pasta" separado (rodando fora deste backend, no próprio PC da loja) observa
as duas pastas e envia (POST multipart, campo `origem` = "abertura" ou "orcamento") para
este endpoint, autenticado por uma API key compartilhada (não há usuário logado do lado
de quem chama, então não usamos o JWT normal - ver verify_os_handler_key).

Fluxo ABERTURA (fase 1):
1. Extrai telefone/cliente/equipamento/natureza do PDF.
2. Envia os avisos da natureza (mesmos templates do OS Handler de chat) + a pergunta de
   confirmação de leitura das condições, e marca a conversa como aguardando essa
   confirmação (Conversation.assunto_atual = "CONFIRM_OS_PDF:<arquivo>"). O PDF completo
   só é enviado depois que o cliente confirmar (ver webhooks.py, bloco is_pending_os_pdf).

Fluxo ORCAMENTO (fase 2):
1. Extrai telefone/cliente/nº da O.S./técnico responsável do PDF.
2. Envia o PDF do orçamento direto pro cliente (aqui ele PRECISA ver o valor pra decidir)
   + a pergunta de aprovação, marcando a conversa como aguardando essa resposta
   (Conversation.assunto_atual = "CONFIRM_OS_APPROVAL:<nº os>|<arquivo>|<tel técnico>").
3. Quando o cliente responde (ver webhooks.py, bloco is_pending_os_approval): avisa o
   grupo "SERV - SOLICITAÇÃO DE O.S." com nº da O.S., cliente e se foi aprovado ou não, e
   manda o PDF do orçamento pro técnico responsável (se identificado no PDF).

Documento de tipo não reconhecido em nenhum dos dois fluxos não é descartado - vira nota
manual na conversa pro atendente tratar.
"""
import os
import re
import io
import uuid
import asyncio
import logging
import difflib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pypdf import PdfReader

from app.core.config import settings
from app.core.database import get_db
from app.models.models import (
    Conversation, ConversationStatus, Message, MessageSender, MessageType,
    WhatsAppNumber, AuthorizedTechnician
)
from app.services.lid_resolver_service import resolve_and_bind_contact
from app.services.automation_service import automation_service, normalize_text
from app.services.evolution_service import evolution_service
from app.services.protocol_service import generate_daily_protocol
from app.api.websockets import manager as ws_manager
from app.api.v1.conversations import extract_evolution_msg_id

logger = logging.getLogger("os_handler_ingest")
router = APIRouter(prefix="/os-handler", tags=["OS Handler - Ingestão de PDF"])

UPLOAD_SUBDIR = "os_files"

NATUREZA_KEYWORDS = {
    "orcamento": ["orcamento"],
    "garantia_loja": ["garantia de loja", "garantia loja"],
    "garantia_fabrica": ["garantia de fabrica", "garantia fabrica"],
    "locacao": ["locacao"],
}


def verify_os_handler_key(x_os_handler_key: str = Header(...)):
    if not x_os_handler_key or x_os_handler_key != settings.OS_HANDLER_INGEST_API_KEY:
        raise HTTPException(status_code=401, detail="Chave de API inválida (X-OS-Handler-Key)")


def detect_natureza(full_text: str) -> Optional[str]:
    """
    Looks for the natureza keyword ONLY in the document's header region (before the
    "Cliente:"/"Condições Gerais" section starts), never in the full text. The O.S. layout
    printed here has a boilerplate "Condições Gerais de Serviço" clause that mentions
    "orçamento" repeatedly REGARDLESS of the document's actual type (garantia, locação...) -
    scanning the whole PDF would misclassify almost everything as "orcamento" just because
    that word appears somewhere in the fine print. The natureza badge itself lives in the
    header, next to "Nº DA OS"/"DATA EMISSÃO", based on the one sample seen so far.
    """
    lower_text = full_text.lower()
    header_end = len(full_text)
    for marker in ["cliente:", "condições gerais", "condicoes gerais", "prezado"]:
        idx = lower_text.find(marker)
        if idx != -1:
            header_end = min(header_end, idx)
    header_text = normalize_text(full_text[:header_end])

    for status, kws in NATUREZA_KEYWORDS.items():
        if any(kw in header_text for kw in kws):
            return status
    return None


def extract_field(text: str, label: str) -> Optional[str]:
    m = re.search(rf"{label}\s*:\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_phone(text: str) -> Optional[str]:
    """
    Prefers 'Celular:', falls back to 'Telefone:'. Normalizes to digits with country code.
    Uses a phone-shaped character class ([\\d()\\s.-]) rather than "everything up to the next
    newline" - on the real O.S. layout, 'Telefone:', 'Celular:' and 'Contato:' all sit on the
    SAME visual row, and PDF text extraction flattens that row into one line, so a greedy
    to-end-of-line match would swallow the literal word "Contato" right after the digits.
    """
    for label in ["Celular", "Telefone"]:
        m = re.search(rf"{label}\s*:\s*([\d\(\)\s\.\-]{{7,20}})", text, re.IGNORECASE)
        if not m:
            continue
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) < 8:
            continue
        if not digits.startswith("55") and len(digits) in (10, 11):
            digits = "55" + digits
        return digits
    return None


def extract_os_numero(text: str) -> Optional[str]:
    """Matches 'Nº DA OS 1924' / 'N° DA OS: 1924' / 'No DA OS 1924' etc."""
    m = re.search(r"N[ºo°]\s*(?:DA\s*)?O\.?S\.?\s*:?\s*(\d+)", text, re.IGNORECASE)
    return m.group(1) if m else None


async def resolve_tecnico_phone(db: AsyncSession, tenant_id: int, full_text: str) -> Optional[str]:
    """
    Best-effort: looks for a 'Técnico:'/'Diagnosticado por:'/'Responsável:' field on the
    O.S. and fuzzy-matches it against the registered AuthorizedTechnician names for this
    tenant. Returns None (not an error) if no field or no confident match is found - the
    approval flow still works without it, it just skips the direct DM to the technician.
    """
    tech_name_raw = None
    for label in ["Técnico Responsável", "Tecnico Responsavel", "Responsável Técnico", "Responsavel Tecnico", "Técnico", "Tecnico", "Diagnosticado por"]:
        tech_name_raw = extract_field(full_text, label)
        if tech_name_raw:
            break
    if not tech_name_raw:
        return None

    res = await db.execute(select(AuthorizedTechnician).where(
        AuthorizedTechnician.tenant_id == tenant_id,
        AuthorizedTechnician.ativo == True
    ))
    technicians = res.scalars().all()
    if not technicians:
        return None

    norm_target = normalize_text(tech_name_raw)
    names = {normalize_text(t.nome): t for t in technicians}
    # Exact/substring match first, then fuzzy
    for norm_name, tech in names.items():
        if norm_name in norm_target or norm_target in norm_name:
            return tech.telefone
    close = difflib.get_close_matches(norm_target, list(names.keys()), n=1, cutoff=0.7)
    if close:
        return names[close[0]].telefone
    return None


def save_uploaded_pdf(file_bytes: bytes) -> str:
    os.makedirs(os.path.join("uploads", UPLOAD_SUBDIR), exist_ok=True)
    saved_filename = f"{uuid.uuid4().hex}.pdf"
    saved_rel_path = f"{UPLOAD_SUBDIR}/{saved_filename}"
    with open(os.path.join("uploads", saved_rel_path), "wb") as f:
        f.write(file_bytes)
    return saved_rel_path


async def get_or_create_conversation(db: AsyncSession, tenant_id: int, contact_id: int, whatsapp_number_id: int) -> Conversation:
    conv_stmt = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.contact_id == contact_id,
        Conversation.whatsapp_number_id == whatsapp_number_id,
        Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO])
    ).order_by(Conversation.ultima_interacao_em.desc())
    conversation = (await db.execute(conv_stmt)).scalars().first()
    if conversation:
        return conversation

    any_conv_stmt = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.contact_id == contact_id,
        Conversation.whatsapp_number_id == whatsapp_number_id
    ).order_by(Conversation.ultima_interacao_em.desc())
    conversation = (await db.execute(any_conv_stmt)).scalars().first()
    if conversation:
        conversation.status = ConversationStatus.COM_HUMANO
        return conversation

    proto = await generate_daily_protocol(db, tenant_id)
    conversation = Conversation(
        tenant_id=tenant_id,
        whatsapp_number_id=whatsapp_number_id,
        contact_id=contact_id,
        protocol_number=proto,
        status=ConversationStatus.COM_HUMANO,
        assunto_atual="Atendimento Concierge"
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def send_and_log_text(
    db: AsyncSession, tenant_id: int, whatsapp_number_id: int, instance_name: str,
    phone: str, conversation: Conversation, msg_content: str, delay_sec: float
):
    try:
        await evolution_service.send_presence(instance_name=instance_name, number=phone, presence="composing")
    except Exception as e:
        logger.debug(f"[OS HANDLER INGEST] Presence typing warning: {e}")
    await asyncio.sleep(delay_sec)

    send_res = await evolution_service.send_text_message(instance_name=instance_name, number=phone, text=msg_content)
    saved_msg = Message(
        conversation_id=conversation.id,
        remetente=MessageSender.SISTEMA,
        conteudo=msg_content,
        tipo=MessageType.TEXTO,
        status="sent",
        whatsapp_msg_id=extract_evolution_msg_id(send_res) if isinstance(send_res, dict) else None,
        timestamp=datetime.utcnow()
    )
    db.add(saved_msg)
    conversation.ultima_interacao_em = datetime.utcnow()
    await db.commit()
    await db.refresh(saved_msg)

    await ws_manager.broadcast_to_department(
        tenant_id=tenant_id,
        whatsapp_number_id=whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conversation.id,
            "id": saved_msg.id,
            "remetente": MessageSender.SISTEMA.value,
            "conteudo": msg_content,
            "tipo": MessageType.TEXTO.value,
            "status": "sent",
            "timestamp": saved_msg.timestamp.isoformat() + "Z",
            "agent_name": "Automação OS"
        }
    )


async def flag_unrecognized_document(
    db: AsyncSession, tenant_id: int, whatsapp_number_id: int,
    conversation: Conversation, saved_rel_path: str, note: str
):
    sys_msg = Message(
        conversation_id=conversation.id,
        remetente=MessageSender.SISTEMA,
        conteudo=f"/uploads/{saved_rel_path}|Ordem_de_Servico.pdf|{note}",
        tipo=MessageType.ARQUIVO,
        status="sent",
        timestamp=datetime.utcnow()
    )
    db.add(sys_msg)
    conversation.ultima_interacao_em = datetime.utcnow()
    await db.commit()
    await db.refresh(sys_msg)
    await ws_manager.broadcast_to_department(
        tenant_id=tenant_id,
        whatsapp_number_id=whatsapp_number_id,
        message_data={
            "type": "NEW_MESSAGE",
            "conversation_id": conversation.id,
            "id": sys_msg.id,
            "remetente": MessageSender.SISTEMA.value,
            "conteudo": sys_msg.conteudo,
            "tipo": MessageType.ARQUIVO.value,
            "status": "sent",
            "timestamp": sys_msg.timestamp.isoformat() + "Z",
            "agent_name": "Automação OS"
        }
    )


@router.post("/ingest", dependencies=[Depends(verify_os_handler_key)])
async def ingest_os_pdf(
    file: UploadFile = File(...),
    origem: str = Form("abertura"),
    db: AsyncSession = Depends(get_db)
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    saved_rel_path = save_uploaded_pdf(file_bytes)

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        logger.error(f"[OS HANDLER INGEST] Erro ao ler PDF (uploads/{saved_rel_path}): {e}")
        raise HTTPException(status_code=422, detail="Não foi possível ler o conteúdo do PDF")

    phone = extract_phone(full_text)
    if not phone:
        raise HTTPException(status_code=422, detail="Telefone do cliente não encontrado no PDF (campos Celular:/Telefone:)")

    client_name = extract_field(full_text, "Cliente")

    wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
    whatsapp_number = (await db.execute(wn_stmt)).scalar_one_or_none()
    if not whatsapp_number:
        logger.error("[OS HANDLER INGEST] ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID não configurado corretamente")
        raise HTTPException(status_code=500, detail="Instância de Assistência Técnica não configurada no servidor")

    tenant_id = whatsapp_number.tenant_id
    instance_name = whatsapp_number.instancia_evolution_api

    contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=client_name)
    await db.flush()
    conversation = await get_or_create_conversation(db, tenant_id, contact.id, whatsapp_number.id)

    config = await automation_service.get_tenant_automations(db, tenant_id)
    os_cfg = config.get("os_handler", {})
    delay_ms = os_cfg.get("typing_delay_ms", 2000)
    delay_sec = max(0.5, float(delay_ms) / 1000.0)

    if origem == "orcamento":
        # FASE 2: O.S. alimentada com o laudo/valor do técnico - o cliente precisa VER o
        # PDF pra decidir, então ele é enviado direto (não fica retido como na fase 1).
        os_numero = extract_os_numero(full_text) or "?"
        tecnico_phone = await resolve_tecnico_phone(db, tenant_id, full_text)

        intro_msg = (
            f"Olá, {contact.nome or 'Cliente'}! 👋 O diagnóstico da sua Ordem de Serviço "
            f"#{os_numero} está pronto. Segue o PDF com o orçamento do reparo. 📎"
        )
        approval_prompt = (
            f"Você *aprova* a execução do serviço pelo valor informado no orçamento? "
            f"Responda *SIM* para aprovar ou *NÃO* para recusar."
        )

        await send_and_log_text(db, tenant_id, whatsapp_number.id, instance_name, phone, conversation, intro_msg, delay_sec)

        # Send the quote PDF directly (customer needs to see it to decide)
        abs_path = os.path.join("uploads", saved_rel_path)
        with open(abs_path, "rb") as f:
            import base64
            b64 = base64.b64encode(f.read()).decode("utf-8")
        send_res = await evolution_service.send_media_message(
            instance_name=instance_name, number=phone, media_type="document",
            mimetype="application/pdf", media=b64, file_name="Orcamento_OS.pdf",
            skip_anti_ban_pacing=True
        )
        pdf_msg = Message(
            conversation_id=conversation.id, remetente=MessageSender.SISTEMA,
            conteudo=f"/uploads/{saved_rel_path}|Orcamento_OS.pdf",
            tipo=MessageType.ARQUIVO, status="sent",
            whatsapp_msg_id=extract_evolution_msg_id(send_res) if isinstance(send_res, dict) else None,
            timestamp=datetime.utcnow()
        )
        db.add(pdf_msg)
        await db.commit()

        await send_and_log_text(db, tenant_id, whatsapp_number.id, instance_name, phone, conversation, approval_prompt, delay_sec)

        conversation.assunto_atual = f"CONFIRM_OS_APPROVAL:{os_numero}|{saved_rel_path}|{tecnico_phone or ''}"
        await db.commit()

        logger.info(f"[OS HANDLER INGEST] Orçamento da O.S. #{os_numero} enviado para aprovação (conversa #{conversation.id})")
        return {"status": "success", "flow": "orcamento", "os_numero": os_numero, "phone": phone, "conversation_id": conversation.id}

    # FASE 1: abertura da O.S.
    natureza = detect_natureza(full_text)
    if not natureza:
        await flag_unrecognized_document(
            db, tenant_id, whatsapp_number.id, conversation, saved_rel_path,
            "📄 Um novo documento de O.S. foi recebido do Softsystem, mas o tipo não pôde ser "
            "identificado automaticamente. Verifique o arquivo e envie ao cliente manualmente se necessário."
        )
        return {"status": "unrecognized_natureza", "phone": phone, "conversation_id": conversation.id, "file": f"/uploads/{saved_rel_path}"}

    equipamento = extract_field(full_text, "Equipamento")
    detected_equip, valor_diagnostico = ("Equipamento", 100)
    if natureza == "orcamento" and equipamento:
        detected_equip, valor_diagnostico = automation_service.resolve_diagnostic_price(
            equipamento, os_cfg.get("diagnostic_prices", {})
        )

    info_messages = automation_service.format_os_templates(
        natureza, config, contact.nome, detected_equip, valor_diagnostico
    )
    confirmation_prompt = automation_service.format_confirmation_prompt(natureza, config, valor_diagnostico)
    all_messages = list(info_messages) + ([confirmation_prompt] if confirmation_prompt else [])

    for msg_content in all_messages:
        await send_and_log_text(db, tenant_id, whatsapp_number.id, instance_name, phone, conversation, msg_content, delay_sec)

    conversation.assunto_atual = f"CONFIRM_OS_PDF:{saved_rel_path}"
    await db.commit()

    logger.info(f"[OS HANDLER INGEST] O.S. '{natureza}' processada para conversa #{conversation.id} ({phone})")
    return {"status": "success", "flow": "abertura", "natureza": natureza, "phone": phone, "conversation_id": conversation.id}
