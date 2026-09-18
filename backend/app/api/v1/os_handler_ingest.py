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
import json
import uuid
import base64
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
from app.api.v1.webhooks import notify_os_approval_result

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


def extract_text_visual_order(reader: PdfReader, y_tolerance: float = 10.0) -> str:
    """
    pypdf's plain page.extract_text() returns text in PDF CONTENT-STREAM order, which for
    this O.S. layout is NOT the visual reading order - confirmed against a real O.S. PDF:
    ALL field labels ("Cliente:", "Celular:", "Telefone:"...) come out first, then ALL their
    values come out afterwards in a separate block, with no reliable adjacency between a
    label and its own value. Every regex in this file (extract_field, extract_phone,
    extract_os_numero) depends on a label being immediately followed by its value, so this
    rebuilds actual visual order from each text fragment's (x, y) position instead: group
    fragments into lines by Y-proximity (label and value sit ~9.6pt apart vertically in the
    real sample, ordinary distinct lines sit ~11.4pt apart - 10.0 tolerance was verified
    against the real PDF to merge the former without merging the latter), then sort each
    line left-to-right by X.
    """
    frags = []

    def visitor(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            frags.append((tm[5], tm[4], text))

    for page in reader.pages:
        page.extract_text(visitor_text=visitor)

    frags.sort(key=lambda f: (-f[0], f[1]))

    lines = []
    current_line = []
    current_y = None
    for y, x, text in frags:
        if current_y is None or abs(y - current_y) <= y_tolerance:
            current_line.append((x, text))
            current_y = y if current_y is None else current_y
        else:
            lines.append(current_line)
            current_line = [(x, text)]
            current_y = y
    if current_line:
        lines.append(current_line)

    out_lines = []
    for line in lines:
        line.sort(key=lambda t: t[0])
        out_lines.append(" ".join(t[1] for t in line))
    return "\n".join(out_lines)


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


PURPOSE_BY_NATUREZA = {
    "orcamento": "para avaliação e elaboração do orçamento do reparo",
    "garantia_loja": "para atendimento em garantia",
    "garantia_fabrica": "para atendimento em garantia de fábrica",
}


def build_equip_receipt_line(natureza: str, full_text: str) -> Optional[str]:
    """
    A softer intro line placed right after the greeting, before the cost/warranty warnings -
    lets the customer know WHAT was received and WHY before hitting them with fees/terms.
    Not built for "locacao" (the store is handing equipment TO the customer there, not
    receiving one from them - "recebemos seu equipamento" wouldn't make sense).
    """
    purpose = PURPOSE_BY_NATUREZA.get(natureza)
    if not purpose:
        return None

    marca = extract_field(full_text, "Marca")
    modelo = extract_field(full_text, "Modelo")
    equip_bits = " ".join(b for b in [marca, modelo] if b)
    equip_display = f" *{equip_bits}*" if equip_bits else ""

    data_str = datetime.now().strftime("%d/%m/%Y")
    return f"📥 Hoje, {data_str}, recebemos o seu equipamento{equip_display} {purpose}."


async def resolve_tecnico_phone_by_name(db: AsyncSession, tenant_id: int, tech_name_raw: Optional[str]) -> Optional[str]:
    """
    Fuzzy-matches a technician name string against the registered AuthorizedTechnician
    table for this tenant. Returns None (not an error) if there's nothing to match or no
    confident match is found - callers treat this as best-effort, not required.
    """
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


async def resolve_tecnico_phone(db: AsyncSession, tenant_id: int, full_text: str) -> Optional[str]:
    """
    PDF-text variant (legacy /ingest endpoint): looks for a 'Técnico:'/'Diagnosticado
    por:'/'Responsável:' field on the O.S. text, then delegates the actual name matching to
    resolve_tecnico_phone_by_name(). The new DB-event endpoint gets the technician's name
    directly from Softsystem's own ORDEMSERVICO.TECNICOATENDIMENTO column instead.
    """
    tech_name_raw = None
    for label in ["Técnico Responsável", "Tecnico Responsavel", "Responsável Técnico", "Responsavel Tecnico", "Técnico", "Tecnico", "Diagnosticado por"]:
        tech_name_raw = extract_field(full_text, label)
        if tech_name_raw:
            break
    return await resolve_tecnico_phone_by_name(db, tenant_id, tech_name_raw)


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
    has_file = bool(saved_rel_path)
    sys_msg = Message(
        conversation_id=conversation.id,
        remetente=MessageSender.SISTEMA,
        conteudo=f"/uploads/{saved_rel_path}|Ordem_de_Servico.pdf|{note}" if has_file else note,
        tipo=MessageType.ARQUIVO if has_file else MessageType.TEXTO,
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
            "tipo": sys_msg.tipo.value,
            "status": "sent",
            "timestamp": sys_msg.timestamp.isoformat() + "Z",
            "agent_name": "Automação OS"
        }
    )


async def dispatch_orcamento_messages(
    tenant_id: int, whatsapp_number_id: int, instance_name: str, phone: str,
    conversation_id: int, contact_name: str, os_numero: str, saved_rel_path: str,
    tecnico_phone: Optional[str], delay_sec: float
):
    """
    Background task: sends the multi-message orçamento-approval sequence (intro + PDF +
    approval question). Runs in its own DB session, decoupled from the request that
    triggered it - the anti-ban typing delays between messages easily add up past a normal
    HTTP client timeout (confirmed against the real folder watcher: its default 60s timeout
    was hit even though the send itself succeeded), so the endpoint returns immediately
    once this is scheduled instead of making the watcher wait for every message to land.
    """
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                logger.error(f"[OS HANDLER INGEST] Conversa #{conversation_id} não encontrada para despachar orçamento")
                return

            intro_msg = (
                f"Olá, {contact_name or 'Cliente'}! 👋 O diagnóstico da sua Ordem de Serviço "
                f"#{os_numero} está pronto. Segue o PDF com o orçamento do reparo. 📎"
            )
            approval_prompt = (
                f"Você *aprova* a execução do serviço pelo valor informado no orçamento? "
                f"Responda *SIM* para aprovar ou *NÃO* para recusar."
            )

            await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, intro_msg, delay_sec)

            abs_path = os.path.join("uploads", saved_rel_path)
            with open(abs_path, "rb") as f:
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

            await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, approval_prompt, delay_sec)

            conversation.assunto_atual = f"CONFIRM_OS_APPROVAL:{os_numero}|{saved_rel_path}|{tecnico_phone or ''}"
            await db.commit()

        logger.info(f"[OS HANDLER INGEST] Orçamento da O.S. #{os_numero} enviado para aprovação (conversa #{conversation_id})")
    except Exception as err:
        logger.error(f"[OS HANDLER INGEST] Erro ao despachar orçamento da O.S. #{os_numero}: {err}", exc_info=True)


async def dispatch_abertura_messages(
    tenant_id: int, whatsapp_number_id: int, instance_name: str, phone: str,
    conversation_id: int, natureza: str, config: dict, contact_name: str,
    detected_equip: str, valor_diagnostico: int, saved_rel_path: str, delay_sec: float,
    equip_receipt_line: Optional[str] = None
):
    """Background task: sends the fase-1 informative messages + confirmation gate (see docstring above)."""
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                logger.error(f"[OS HANDLER INGEST] Conversa #{conversation_id} não encontrada para despachar abertura")
                return

            info_messages = list(automation_service.format_os_templates(
                natureza, config, contact_name, detected_equip, valor_diagnostico
            ))
            # Insert right after the greeting (index 0), before the cost/warranty details -
            # a softer "we received your equipment today" line so the diagnostic-fee warning
            # doesn't land as the very first thing the customer reads.
            if equip_receipt_line and info_messages:
                info_messages.insert(1, equip_receipt_line)
            confirmation_prompt = automation_service.format_confirmation_prompt(natureza, config, valor_diagnostico)
            all_messages = info_messages + ([confirmation_prompt] if confirmation_prompt else [])

            for msg_content in all_messages:
                await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, msg_content, delay_sec)

            conversation.assunto_atual = f"CONFIRM_OS_PDF:{saved_rel_path}"
            await db.commit()

        logger.info(f"[OS HANDLER INGEST] O.S. '{natureza}' despachada para conversa #{conversation_id} ({phone})")
    except Exception as err:
        logger.error(f"[OS HANDLER INGEST] Erro ao despachar abertura da O.S. ({natureza}): {err}", exc_info=True)


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
        full_text = extract_text_visual_order(reader)
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
    contact_name = contact.nome  # captured before commit expires ORM attributes (async-unsafe to lazy-load after)
    conversation = await get_or_create_conversation(db, tenant_id, contact.id, whatsapp_number.id)
    await db.commit()
    await db.refresh(conversation)

    config = await automation_service.get_tenant_automations(db, tenant_id)
    os_cfg = config.get("os_handler", {})
    delay_ms = os_cfg.get("typing_delay_ms", 2000)
    delay_sec = max(0.5, float(delay_ms) / 1000.0)

    if origem == "orcamento":
        # FASE 2: O.S. alimentada com o laudo/valor do técnico - o cliente precisa VER o
        # PDF pra decidir, então ele é enviado direto (não fica retido como na fase 1).
        os_numero = extract_os_numero(full_text) or "?"
        tecnico_phone = await resolve_tecnico_phone(db, tenant_id, full_text)

        asyncio.create_task(dispatch_orcamento_messages(
            tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
            contact_name, os_numero, saved_rel_path, tecnico_phone, delay_sec
        ))

        logger.info(f"[OS HANDLER INGEST] Orçamento da O.S. #{os_numero} agendado para envio (conversa #{conversation.id})")
        return {"status": "queued", "flow": "orcamento", "os_numero": os_numero, "phone": phone, "conversation_id": conversation.id}

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
    equip_receipt_line = build_equip_receipt_line(natureza, full_text)

    asyncio.create_task(dispatch_abertura_messages(
        tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
        natureza, config, contact_name, detected_equip, valor_diagnostico, saved_rel_path, delay_sec,
        equip_receipt_line
    ))

    logger.info(f"[OS HANDLER INGEST] O.S. '{natureza}' agendada para envio (conversa #{conversation.id}, {phone})")
    return {"status": "queued", "flow": "abertura", "natureza": natureza, "phone": phone, "conversation_id": conversation.id}


# ============================================================================
# Ingestão via banco Firebird do Softsystem (substitui a leitura de PDF acima
# para quem já está usando o vigia de banco - tools/os_db_watcher/). O PDF
# continua sendo enviado ao cliente quando disponível, mas TODOS os dados
# (telefone, natureza, equipamento, técnico) vêm direto das tabelas do
# Softsystem, lidas pelo vigia (só leitura, nunca escreve no banco deles) -
# elimina toda a fragilidade de extrair campos de texto de PDF.
# ============================================================================

# CODTIPOORDEMSERVICO (tabela TIPOORDEMSERVICO do Softsystem) -> chave interna de natureza
NATUREZA_CODE_MAP = {
    1: "orcamento",
    2: "garantia_fabrica",
    3: "garantia_loja",
    5: "locacao",
    # 4 = "Visita Técnica" não tem template próprio ainda - cai no fallback de
    # "natureza não reconhecida" (nota manual), como qualquer tipo desconhecido.
}

# CODTIPOEVENTOOS (tabela TIPOEVENTOOS do Softsystem, aba "Eventos" da O.S.)
EVENTO_ENTRADA = 1
EVENTO_ORC_AGUARDANDO_APROVACAO = 3
EVENTO_ORC_APROVADO = 15
EVENTO_ORC_NAO_APROVADO = 16


async def ingest_db_event_common(
    db: AsyncSession,
    cod_tipo_evento: int,
    codos: int,
    cliente_nome: Optional[str],
    cliente_telefone: str,
    natureza_codigo: Optional[int],
    equip_marca: Optional[str],
    equip_modelo: Optional[str],
    equip_descricao: Optional[str],
    equip_defeito: Optional[str],
    tecnico_nome: Optional[str],
    saved_rel_path: Optional[str]
):
    phone = re.sub(r"\D", "", cliente_telefone or "")
    if not phone.startswith("55") and len(phone) in (10, 11):
        phone = "55" + phone
    if len(phone) < 12:
        raise HTTPException(status_code=422, detail=f"Telefone inválido recebido do banco: {cliente_telefone!r}")

    wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
    whatsapp_number = (await db.execute(wn_stmt)).scalar_one_or_none()
    if not whatsapp_number:
        raise HTTPException(status_code=500, detail="Instância de Assistência Técnica não configurada no servidor")

    tenant_id = whatsapp_number.tenant_id
    instance_name = whatsapp_number.instancia_evolution_api

    contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=cliente_nome)
    await db.flush()
    contact_name = contact.nome
    conversation = await get_or_create_conversation(db, tenant_id, contact.id, whatsapp_number.id)
    await db.commit()
    await db.refresh(conversation)

    config = await automation_service.get_tenant_automations(db, tenant_id)
    os_cfg = config.get("os_handler", {})
    delay_ms = os_cfg.get("typing_delay_ms", 2000)
    delay_sec = max(0.5, float(delay_ms) / 1000.0)

    equip_display = " ".join(b for b in [equip_marca, equip_modelo] if b)

    if cod_tipo_evento == EVENTO_ENTRADA:
        natureza = NATUREZA_CODE_MAP.get(natureza_codigo)
        if not natureza:
            await flag_unrecognized_document(
                db, tenant_id, whatsapp_number.id, conversation, saved_rel_path or "",
                f"📄 Nova O.S. #{codos} recebida do Softsystem, mas a natureza (código {natureza_codigo}) "
                f"não tem um modelo de mensagem configurado ainda. Verifique manualmente."
            )
            return {"status": "unrecognized_natureza", "codos": codos, "phone": phone, "conversation_id": conversation.id}

        detected_equip, valor_diagnostico = ("Equipamento", 100)
        if natureza == "orcamento" and (equip_descricao or equip_defeito):
            detected_equip, valor_diagnostico = automation_service.resolve_diagnostic_price(
                equip_descricao or equip_defeito or "", os_cfg.get("diagnostic_prices", {})
            )

        purpose = PURPOSE_BY_NATUREZA.get(natureza)
        equip_receipt_line = None
        if purpose:
            equip_bits = f" *{equip_display}*" if equip_display else ""
            data_str = datetime.now().strftime("%d/%m/%Y")
            equip_receipt_line = f"📥 Hoje, {data_str}, recebemos o seu equipamento{equip_bits} {purpose}."

        asyncio.create_task(dispatch_abertura_messages(
            tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
            natureza, config, contact_name, detected_equip, valor_diagnostico,
            saved_rel_path or "", delay_sec, equip_receipt_line
        ))
        logger.info(f"[OS DB EVENT] ENTRADA - O.S. #{codos} '{natureza}' agendada (conversa #{conversation.id})")
        return {"status": "queued", "flow": "abertura", "natureza": natureza, "codos": codos, "conversation_id": conversation.id}

    if cod_tipo_evento == EVENTO_ORC_AGUARDANDO_APROVACAO:
        if not saved_rel_path:
            await flag_unrecognized_document(
                db, tenant_id, whatsapp_number.id, conversation, "",
                f"📄 Orçamento da O.S. #{codos} pronto para aprovação, mas o PDF ainda não foi "
                f"encontrado na pasta compartilhada. Verifique e envie manualmente se necessário."
            )
            return {"status": "pdf_not_found", "codos": codos, "conversation_id": conversation.id}

        tecnico_phone = await resolve_tecnico_phone_by_name(db, tenant_id, tecnico_nome)
        asyncio.create_task(dispatch_orcamento_messages(
            tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
            contact_name, str(codos), saved_rel_path, tecnico_phone, delay_sec
        ))
        logger.info(f"[OS DB EVENT] ORC AGUARDANDO APROVACAO - O.S. #{codos} agendada (conversa #{conversation.id})")
        return {"status": "queued", "flow": "orcamento", "codos": codos, "conversation_id": conversation.id}

    if cod_tipo_evento in (EVENTO_ORC_APROVADO, EVENTO_ORC_NAO_APROVADO):
        # O atendente marcou o resultado direto no Softsystem (em vez de - ou além de - o
        # cliente responder pelo WhatsApp). Só avisa o grupo/técnico, não manda nada pro
        # cliente aqui (ele já sabe o resultado, foi ele quem informou).
        aprovado = cod_tipo_evento == EVENTO_ORC_APROVADO
        tecnico_phone = await resolve_tecnico_phone_by_name(db, tenant_id, tecnico_nome)
        asyncio.create_task(notify_os_approval_result(
            tenant_id=tenant_id, conversation_id=conversation.id,
            whatsapp_number_id=whatsapp_number.id, instance_name=instance_name,
            os_numero=str(codos), client_name=contact_name or "Cliente",
            aprovado=aprovado, pdf_relative_path=saved_rel_path or "", tecnico_phone=tecnico_phone
        ))
        logger.info(f"[OS DB EVENT] Resultado do orçamento da O.S. #{codos} notificado (aprovado={aprovado})")
        return {"status": "queued", "flow": "approval_result", "codos": codos, "conversation_id": conversation.id}

    # Qualquer outro tipo de evento: aviso simples de progresso, se houver um configurado.
    msg = automation_service.format_evento_message(cod_tipo_evento, config, contact_name)
    if not msg:
        return {"status": "no_template", "codos": codos, "cod_tipo_evento": cod_tipo_evento, "conversation_id": conversation.id}

    asyncio.create_task(_send_evento_message_background(
        tenant_id, whatsapp_number.id, instance_name, phone, conversation.id, msg
    ))
    logger.info(f"[OS DB EVENT] Evento tipo {cod_tipo_evento} - O.S. #{codos} agendado (conversa #{conversation.id})")
    return {"status": "queued", "flow": "evento_progresso", "codos": codos, "conversation_id": conversation.id}


async def _send_evento_message_background(
    tenant_id: int, whatsapp_number_id: int, instance_name: str, phone: str,
    conversation_id: int, msg_content: str
):
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                return
            await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, msg_content, 0.5)
    except Exception as err:
        logger.error(f"[OS DB EVENT] Erro ao enviar aviso de progresso: {err}", exc_info=True)


@router.post("/db-event", dependencies=[Depends(verify_os_handler_key)])
async def ingest_os_db_event(
    payload: str = Form(...),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Recebido do vigia de banco (tools/os_db_watcher/): um evento novo detectado na aba
    "Eventos" de uma O.S. no Softsystem (leitura direta do Firebird, só leitura). `payload`
    é uma string JSON com os campos já resolvidos pelo vigia (ver NATUREZA_CODE_MAP e
    EVENTO_* acima para os códigos esperados); `file`, quando presente, é o PDF da O.S.
    correspondente encontrado na pasta compartilhada no momento do evento.
    """
    try:
        data = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="payload não é um JSON válido")

    required = ["cod_tipo_evento", "codos", "cliente_telefone"]
    missing = [f for f in required if not data.get(f) and data.get(f) != 0]
    if missing:
        raise HTTPException(status_code=422, detail=f"Campos obrigatórios faltando: {missing}")

    saved_rel_path = None
    if file is not None:
        file_bytes = await file.read()
        if file_bytes:
            saved_rel_path = save_uploaded_pdf(file_bytes)

    return await ingest_db_event_common(
        db,
        cod_tipo_evento=int(data["cod_tipo_evento"]),
        codos=int(data["codos"]),
        cliente_nome=data.get("cliente_nome"),
        cliente_telefone=str(data["cliente_telefone"]),
        natureza_codigo=data.get("natureza_codigo"),
        equip_marca=data.get("equip_marca"),
        equip_modelo=data.get("equip_modelo"),
        equip_descricao=data.get("equip_descricao"),
        equip_defeito=data.get("equip_defeito"),
        tecnico_nome=data.get("tecnico_nome"),
        saved_rel_path=saved_rel_path
    )
