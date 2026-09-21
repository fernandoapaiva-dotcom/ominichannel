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
import time
import base64
import asyncio
import logging
import difflib
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from pypdf import PdfReader

from app.core.config import settings
from app.core.database import get_db
from app.models.models import (
    Conversation, ConversationStatus, Message, MessageSender, MessageType,
    WhatsAppNumber, AuthorizedTechnician
)
from app.services.lid_resolver_service import resolve_and_bind_contact
from app.services.automation_service import automation_service, normalize_text, get_greeting
from app.services.evolution_service import evolution_service
from app.services.protocol_service import generate_daily_protocol
from app.services import os_burst_state
from app.api.websockets import manager as ws_manager
from app.api.v1.conversations import extract_evolution_msg_id
from app.api.v1.webhooks import notify_os_approval_result, send_os_pdf_after_confirmation, os_pdf_client_name

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
    os_numero = extract_os_numero(full_text)
    os_display = f" referente à *O.S. #{os_numero}*" if os_numero else ""

    data_str = datetime.now().strftime("%d/%m/%Y")
    return f"📥 Hoje, {data_str}, recebemos o seu equipamento{equip_display}{os_display}, {purpose}."


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
    phone: str, conversation: Conversation, msg_content: str, delay_sec: float,
    pre_send_check=None
):
    try:
        await evolution_service.send_presence(instance_name=instance_name, number=phone, presence="composing")
    except Exception as e:
        logger.debug(f"[OS HANDLER INGEST] Presence typing warning: {e}")
    await asyncio.sleep(delay_sec)

    send_res = await evolution_service.send_text_message(
        instance_name=instance_name, number=phone, text=msg_content, pre_send_check=pre_send_check
    )
    if isinstance(send_res, dict) and send_res.get("skipped"):
        return  # dispensada na última hora: nada foi enviado, nada a registrar
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
    Background task: sends the multi-message orçamento-approval sequence (intro [+ PDF when
    available] + approval question). Runs in its own DB session, decoupled from the request
    that triggered it - the anti-ban typing delays between messages easily add up past a
    normal HTTP client timeout (confirmed against the real folder watcher: its default 60s
    timeout was hit even though the send itself succeeded), so the endpoint returns
    immediately once this is scheduled instead of making the watcher wait for every message
    to land.

    O PDF é opcional aqui, não um bloqueio: o pedido explícito da loja é que a MUDANÇA DO
    EVENTO no Softsystem já dispare o aviso ao cliente, mesmo que o PDF do orçamento ainda
    não tenha sido gerado/salvo separadamente (esse é um passo manual à parte no processo
    deles). Quando o arquivo existir (`saved_rel_path` não vazio), ele é enviado também.
    """
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                logger.error(f"[OS HANDLER INGEST] Conversa #{conversation_id} não encontrada para despachar orçamento")
                return

            has_pdf = bool(saved_rel_path)
            intro_msg = (
                f"Olá, {contact_name or 'Cliente'}! 👋 O diagnóstico da sua Ordem de Serviço "
                f"#{os_numero} está pronto." + (" Segue o PDF com o orçamento do reparo. 📎" if has_pdf else "")
            )
            approval_prompt = (
                f"Você *aprova* a execução do serviço pelo valor informado no orçamento? "
                f"Responda *SIM* para aprovar ou *NÃO* para recusar."
            )

            await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, intro_msg, delay_sec)

            if has_pdf:
                abs_path = os.path.join("uploads", saved_rel_path)
                with open(abs_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                pdf_file_name = build_os_pdf_filename(
                    os_numero, os_pdf_client_name(conversation.dados_adicionais, os_numero, contact_name)
                )
                send_res = await evolution_service.send_media_message(
                    instance_name=instance_name, number=phone, media_type="document",
                    mimetype="application/pdf", media=b64, file_name=pdf_file_name,
                    skip_anti_ban_pacing=True
                )
                pdf_msg = Message(
                    conversation_id=conversation.id, remetente=MessageSender.SISTEMA,
                    conteudo=f"/uploads/{saved_rel_path}|{pdf_file_name}",
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
    equip_receipt_line: Optional[str] = None, codos: str = ""
):
    """Background task: sends the fase-1 informative messages + confirmation gate (see docstring above)."""
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                logger.error(f"[OS HANDLER INGEST] Conversa #{conversation_id} não encontrada para despachar abertura")
                return

            # Set the pending-confirmation marker BEFORE sending anything, not after - this
            # whole sequence takes ~70-90s in real time (typing-delay pacing between each
            # message), and a second O.S. for the same customer can arrive from Softsystem
            # well within that window (see check_and_extend_entrada_window). Without this,
            # dispatch_supplementary_entrada_item could find no marker yet to extend and
            # silently drop that O.S. out of the pending confirmation.
            conversation.assunto_atual = build_confirm_os_pdf_marker([codos], [saved_rel_path])
            await db.commit()

            info_messages = list(automation_service.format_os_templates(
                natureza, config, contact_name, detected_equip, valor_diagnostico
            ))
            # Insert right after the greeting (index 0), before the cost/warranty details -
            # a softer "we received your equipment today" line so the diagnostic-fee warning
            # doesn't land as the very first thing the customer reads.
            if equip_receipt_line and info_messages:
                info_messages.insert(1, equip_receipt_line)
            confirmation_prompt = automation_service.format_confirmation_prompt(natureza, config, valor_diagnostico)

            burst = os_burst_state.start(conversation_id)
            try:
                for msg_content in info_messages:
                    await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, msg_content, delay_sec)
                burst["info_done"] = True

                await db.refresh(conversation)
                if burst["early_yes"] and (conversation.assunto_atual or "").startswith("CONFIRM_OS_PDF:"):
                    # O cliente já disse "Sim" enquanto os termos saíam: essa é a confirmação dele (uma só).
                    # Libera o PDF agora, sem o pedido de "responda SIM".
                    codos_list, paths_list = parse_confirm_os_pdf_marker(conversation.assunto_atual)
                    conversation.assunto_atual = "Atendimento Concierge"
                    os_burst_state.mark_confirmed(conversation_id)
                    await db.commit()
                    ack = (
                        "Perfeito! Só um instante, já vou te enviar o PDF completo da sua Ordem de Serviço. 📎"
                        if len(codos_list) <= 1 else
                        "Perfeito! Só um instante, já vou te enviar os PDFs completos das suas Ordens de Serviço. 📎"
                    )
                    await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, ack, delay_sec)
                    asyncio.create_task(send_os_pdf_after_confirmation(
                        tenant_id=tenant_id, conversation_id=conversation_id, whatsapp_number_id=whatsapp_number_id,
                        instance_name=instance_name, recipient_phone=phone, pdf_relative_paths=paths_list,
                        os_numeros=codos_list, client_name=contact_name or ""
                    ))
                    logger.info(f"[OS HANDLER INGEST] 'Sim' antecipado honrado: PDF liberado ao fim dos termos - conversa #{conversation_id}")
                    return

                if confirmation_prompt:
                    # Só pede o "SIM" se ainda fizer sentido: se o cliente já confirmou depois de receber
                    # todos os termos (recebeu "Perfeito! ... PDF") ou recusou, o pedido chegaria
                    # redundante, depois da resposta.
                    await db.refresh(conversation)
                    still_pending = (conversation.assunto_atual or "").startswith("CONFIRM_OS_PDF:")
                    if burst["skip_prompt"] or not still_pending:
                        logger.info(f"[OS HANDLER INGEST] Pedido de confirmação dispensado (cliente já respondeu) - conversa #{conversation_id}")
                    else:
                        async def _prompt_still_needed() -> bool:
                            if burst["skip_prompt"]:
                                return False
                            async with AsyncSessionLocal() as check_db:
                                conv_now = await check_db.get(Conversation, conversation_id)
                                return bool(conv_now and (conv_now.assunto_atual or "").startswith("CONFIRM_OS_PDF:"))

                        await send_and_log_text(
                            db, tenant_id, whatsapp_number_id, instance_name, phone, conversation,
                            confirmation_prompt, delay_sec, pre_send_check=_prompt_still_needed
                        )
            finally:
                os_burst_state.finish(conversation_id, burst)

        logger.info(f"[OS HANDLER INGEST] O.S. '{natureza}' despachada para conversa #{conversation_id} ({phone})")
    except Exception as err:
        logger.error(f"[OS HANDLER INGEST] Erro ao despachar abertura da O.S. ({natureza}): {err}", exc_info=True)


async def dispatch_supplementary_entrada_item(
    tenant_id: int, whatsapp_number_id: int, instance_name: str, phone: str,
    conversation_id: int, natureza: str, config: dict, contact_name: str,
    detected_equip: str, valor_diagnostico: int, saved_rel_path: str, delay_sec: float,
    item_notice_line: str, codos: str, natureza_already_seen: bool
):
    """
    Background task for a second (or later) O.S. opened for the same customer within
    ENTRADA_WINDOW_SECONDS of the first one (see check_and_extend_entrada_window). The
    greeting and the "responda SIM" confirmation were already sent for the first item in
    this window, so this only adds what's genuinely new: a short notice for this specific
    equipment/O.S., plus - only the first time this natureza shows up in the window - that
    natureza's own terms (a different natureza can mean genuinely different conditions, e.g.
    orçamento vs. garantia).
    """
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                logger.error(f"[OS HANDLER INGEST] Conversa #{conversation_id} não encontrada para item suplementar de abertura")
                return

            messages = [item_notice_line] if item_notice_line else []
            if not natureza_already_seen:
                info_messages = automation_service.format_os_templates(
                    natureza, config, contact_name, detected_equip, valor_diagnostico
                )
                # info_messages[0] is always the greeting - already sent for the first item.
                messages.extend(info_messages[1:])

            for msg_content in messages:
                await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, msg_content, delay_sec)

            # Extend the still-pending confirmation to also cover this O.S. - one "Sim" from
            # the customer now answers for every item in the window. The first item's own
            # marker is set before it sends anything (see dispatch_abertura_messages), but a
            # couple of retries here is cheap insurance against any leftover race.
            for attempt in range(3):
                if (conversation.assunto_atual or "").startswith("CONFIRM_OS_PDF:"):
                    codos_list, paths_list = parse_confirm_os_pdf_marker(conversation.assunto_atual)
                    if str(codos) not in codos_list:
                        codos_list.append(str(codos))
                        paths_list.append(saved_rel_path or "")
                        conversation.assunto_atual = build_confirm_os_pdf_marker(codos_list, paths_list)
                        await db.commit()
                    break
                if attempt < 2:
                    await asyncio.sleep(2)
                    await db.refresh(conversation)
                elif saved_rel_path and os_burst_state.confirmed_recently(conversation_id):
                    # O cliente já confirmou nesta visita antes desta O.S. entrar no aviso: não há mais nada
                    # pendente para incluí-la, então o PDF dela sai direto (sem pedir "Sim" de novo).
                    asyncio.create_task(send_os_pdf_after_confirmation(
                        tenant_id=tenant_id, conversation_id=conversation_id, whatsapp_number_id=whatsapp_number_id,
                        instance_name=instance_name, recipient_phone=phone, pdf_relative_paths=[saved_rel_path],
                        os_numeros=[str(codos)], client_name=contact_name or ""
                    ))
                    logger.info(f"[OS HANDLER INGEST] O.S. #{codos} suplementar: cliente já tinha confirmado - PDF enviado direto (conversa #{conversation_id})")
                else:
                    logger.warning(f"[OS HANDLER INGEST] O.S. #{codos} suplementar: nenhuma confirmação CONFIRM_OS_PDF pendente encontrada para incluir (conversa #{conversation_id})")

        logger.info(f"[OS HANDLER INGEST] Item suplementar da O.S. #{codos} ('{natureza}') incorporado à confirmação pendente (conversa #{conversation_id})")
    except Exception as err:
        logger.error(f"[OS HANDLER INGEST] Erro ao despachar item suplementar da O.S. #{codos}: {err}", exc_info=True)


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
    os_numero = extract_os_numero(full_text) or ""

    asyncio.create_task(dispatch_abertura_messages(
        tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
        natureza, config, contact_name, detected_equip, valor_diagnostico, saved_rel_path, delay_sec,
        equip_receipt_line, os_numero
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
    4: "visita_tecnica",
    5: "locacao",
    # (histórico: 4 = "Visita Técnica" não tinha template próprio antes - caía no fallback de
    # "natureza não reconhecida" (nota manual), como qualquer tipo desconhecido.
}

# Nome do tipo de O.S. como o cliente lê (mesmos nomes da lista "Tipo OS" do Softsystem)
TIPO_OS_LABEL = {
    1: "Orçamento",
    2: "Garantia de Fábrica",
    3: "Garantia de Loja",
    4: "Visita Técnica",
    5: "Equipamento de Locação",
}


def build_equipamento_display(marca: Optional[str], modelo: Optional[str], descricao: Optional[str]) -> str:
    """"*MARCA MODELO* (DESCRIÇÃO)" - só com o que existir, pros avisos de progresso."""
    marca_modelo = " ".join(p for p in [marca, modelo] if p)
    partes = []
    if marca_modelo:
        partes.append(f"*{marca_modelo}*")
    if descricao:
        partes.append(f"({descricao})")
    return " ".join(partes)


# CODTIPOEVENTOOS (tabela TIPOEVENTOOS do Softsystem, aba "Eventos" da O.S.)
EVENTO_ENTRADA = 1
EVENTO_ORC_AGUARDANDO_APROVACAO = 3
EVENTO_ORC_APROVADO = 15
EVENTO_ORC_NAO_APROVADO = 16

# Serializa a checagem "já foi despachado?" + a marcação em si (ver check_os_dispatch_state/
# mark_os_dispatched abaixo). Sem isso, várias chamadas praticamente simultâneas pra mesma
# O.S. - visto de verdade em produção: sync do Google Drive gerando múltiplos eventos de
# arquivo quase juntos para o mesmo PDF - todas liam "ainda não despachado" antes de
# qualquer uma conseguir salvar sua marca, e cada uma disparava a sequência completa de
# novo. O processo roda como uma única instância (fork_mode, sem workers), então um lock em
# memória do processo já resolve.
_os_dispatch_lock = asyncio.Lock()

# A customer dropping off several pieces of equipment turns into several separate O.S.'s in
# Softsystem (confirmed with the shop: each equipment = its own O.S., never grouped under
# one). Without this, each one independently fires the full greeting + terms + "responda
# SIM" sequence, so the customer gets the same greeting repeated N times and has to reply
# SIM once per item. Tracks, per conversation, a short sliding window: the first O.S. still
# gets the full sequence immediately (an event alone must still trigger a prompt reply -
# never silently delayed), but any further O.S. for the SAME conversation while the window
# is open only adds what's actually new (see check_and_extend_entrada_window /
# dispatch_supplementary_entrada_item) instead of repeating everything. Real attendant
# workflow is too irregular for a fixed total duration (an attendant can get pulled away
# mid-batch to help another customer) - each new item slides the window forward instead.
_open_entrada_windows: Dict[int, Dict[str, Any]] = {}
ENTRADA_WINDOW_SECONDS = 120


def check_and_extend_entrada_window(conversation_id: int, natureza: str):
    """
    Returns None if no window was open (fresh visit - caller sends the full sequence and
    this call has now opened the window). Otherwise returns True if `natureza` was already
    seen in this window (caller sends only a short per-item notice) or False if it's a new
    natureza within an already-open window (caller sends that natureza's own terms, but not
    another greeting or another "responda SIM"). Always slides the window's expiry forward.
    """
    now = time.time()
    window = _open_entrada_windows.get(conversation_id)
    if not window or window["expires_at"] <= now:
        _open_entrada_windows[conversation_id] = {"naturezas": {natureza}, "expires_at": now + ENTRADA_WINDOW_SECONDS}
        return None
    already_seen = natureza in window["naturezas"]
    window["naturezas"].add(natureza)
    window["expires_at"] = now + ENTRADA_WINDOW_SECONDS
    return already_seen


def build_os_pdf_filename(codos, client_name: Optional[str]) -> str:
    """"<nº da O.S.> - <cliente>.pdf" instead of a generic name, so the file is identifiable
    once it lands in the customer's own downloads/chat history."""
    safe_name = re.sub(r'[\\/:*?"<>|]', "", (client_name or "").strip()) or "Cliente"
    return f"{codos} - {safe_name}.pdf"


def parse_confirm_os_pdf_marker(marker: str) -> tuple:
    """
    "CONFIRM_OS_PDF:<codos1>,<codos2>,...|<path1>,<path2>,..." - a list instead of a single
    O.S., because a customer dropping off several pieces of equipment at once gets ONE
    combined confirmation covering every O.S. opened in that same visit (see
    queue_entrada_for_batch) instead of one "responda SIM" per item.
    """
    body = marker.split(":", 1)[1]
    codos_part, _, paths_part = body.partition("|")
    codos_list = codos_part.split(",") if codos_part else []
    paths_list = paths_part.split(",") if paths_part else []
    while len(paths_list) < len(codos_list):
        paths_list.append("")
    return codos_list, paths_list


def build_confirm_os_pdf_marker(codos_list: List[str], paths_list: List[str]) -> str:
    return f"CONFIRM_OS_PDF:{','.join(str(c) for c in codos_list)}|{','.join(paths_list)}"


def check_os_dispatch_state(conversation: Conversation, codos: int, flow: str) -> dict:
    """
    Two independent watchers can report the same O.S.: the DB watcher reacts the instant the
    event changes (info texts go out even with no PDF yet, by design - see
    dispatch_orcamento_messages), and the folder watcher reacts whenever the PDF file itself
    shows up in the shared folder, whenever that happens to be. Without this, a PDF arriving
    later would replay the whole info+confirmation sequence a second time.
    Returns the existing dispatch record for this O.S.+flow, or {} if never dispatched.
    """
    os_dispatched = (conversation.dados_adicionais or {}).get("os_dispatched", {})
    record = os_dispatched.get(str(codos)) or {}
    return record if record.get("flow") == flow else {}


def mark_os_dispatched(conversation: Conversation, codos: int, flow: str, pdf_sent: bool):
    extra = dict(conversation.dados_adicionais or {})
    os_dispatched = dict(extra.get("os_dispatched", {}))
    os_dispatched[str(codos)] = {"flow": flow, "pdf_sent": pdf_sent}
    extra["os_dispatched"] = os_dispatched
    conversation.dados_adicionais = extra
    flag_modified(conversation, "dados_adicionais")


async def deliver_late_pdf(
    db: AsyncSession, tenant_id: int, whatsapp_number_id: int, instance_name: str,
    phone: str, conversation: Conversation, codos: int, saved_rel_path: str, pending_prefix: str,
    client_name: Optional[str] = None
):
    """
    The info+confirmation texts for this O.S. were already sent (by whichever watcher got
    there first) - this call is just the PDF showing up in the shared folder afterwards.
    If the customer hasn't answered the confirmation yet, quietly attach the real path to
    the pending marker (it goes out the normal way once they reply). Otherwise (already
    confirmed/declined, or a human took over) send it now as a standalone courtesy follow-up
    - nothing about the info/fee texts gets repeated either way.
    """
    if (conversation.assunto_atual or "").startswith(pending_prefix):
        if pending_prefix == "CONFIRM_OS_PDF:":
            # The pending marker may cover several O.S.'s opened together for the same
            # customer visit (see queue_entrada_for_batch) - only this one's slot gets
            # filled in, the others stay exactly as they were.
            codos_list, paths_list = parse_confirm_os_pdf_marker(conversation.assunto_atual)
            codos_str = str(codos)
            if codos_str in codos_list:
                paths_list[codos_list.index(codos_str)] = saved_rel_path
            else:
                codos_list.append(codos_str)
                paths_list.append(saved_rel_path)
            conversation.assunto_atual = build_confirm_os_pdf_marker(codos_list, paths_list)
        else:
            parts = conversation.assunto_atual.split(":", 1)[1].split("|")
            os_numero = parts[0] if len(parts) > 0 else str(codos)
            tecnico_phone = parts[2] if len(parts) > 2 else ""
            conversation.assunto_atual = f"CONFIRM_OS_APPROVAL:{os_numero}|{saved_rel_path}|{tecnico_phone}"
        await db.commit()
        return True

    abs_path = os.path.join("uploads", saved_rel_path)
    with open(abs_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    pdf_file_name = build_os_pdf_filename(codos, os_pdf_client_name(conversation.dados_adicionais, codos, client_name))

    async def _try_send():
        return await evolution_service.send_media_message(
            instance_name=instance_name, number=phone, media_type="document",
            mimetype="application/pdf", media=b64,
            file_name=pdf_file_name, skip_anti_ban_pacing=True
        )

    # A transient failure here (empty error string from a dropped connection, seen for real
    # in production) must never be recorded as a successful send - one retry, then log loudly
    # if it still fails, since silently marking it "sent" leaves no trail for anyone to notice
    # the customer never actually got the file.
    send_res = await _try_send()
    if not (isinstance(send_res, dict) and send_res.get("success")):
        logger.warning(f"[OS DB EVENT] Falha ao entregar PDF da O.S. #{codos} de primeira, tentando de novo: {send_res}")
        send_res = await _try_send()

    success = isinstance(send_res, dict) and send_res.get("success")
    if not success:
        logger.error(f"[OS DB EVENT] Falha ao entregar PDF da O.S. #{codos} pro cliente após 2 tentativas: {send_res}")
        return False

    pdf_msg = Message(
        conversation_id=conversation.id, remetente=MessageSender.SISTEMA,
        conteudo=f"/uploads/{saved_rel_path}|{pdf_file_name}", tipo=MessageType.ARQUIVO, status="sent",
        whatsapp_msg_id=extract_evolution_msg_id(send_res),
        timestamp=datetime.utcnow()
    )
    db.add(pdf_msg)
    await db.commit()
    return True


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
    saved_rel_path: Optional[str],
    obs: Optional[str] = None,
    eventos_anteriores: Optional[List[int]] = None,
    razao_social: Optional[str] = None
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
    if razao_social and razao_social.strip():
        # O PDF sai com a Razão Social da O.S., não com o nome do contato da conversa
        extra_rs = dict(conversation.dados_adicionais or {})
        mapping_rs = dict(extra_rs.get("os_razao_social", {}))
        mapping_rs[str(codos)] = razao_social.strip()
        extra_rs["os_razao_social"] = mapping_rs
        conversation.dados_adicionais = extra_rs
        flag_modified(conversation, "dados_adicionais")
    await db.commit()
    await db.refresh(conversation)

    config = await automation_service.get_tenant_automations(db, tenant_id)
    os_cfg = config.get("os_handler", {})
    delay_ms = os_cfg.get("typing_delay_ms", 2000)
    delay_sec = max(0.5, float(delay_ms) / 1000.0)

    equip_display = " ".join(b for b in [equip_marca, equip_modelo] if b)

    if cod_tipo_evento == EVENTO_ENTRADA:
        async with _os_dispatch_lock:
            # The lock only serializes execution order - `conversation` was loaded into THIS
            # request's own session before the lock was even acquired, so without refreshing
            # here, a request that waited for the lock still sees pre-lock data and wrongly
            # treats an O.S. another concurrent request just dispatched as brand new. Seen for
            # real: the DB-event watcher and the folder watcher both reacting to the same
            # real-world change (event changed + PDF saved close together) produced two
            # identical, correctly-numbered dispatches instead of being deduplicated.
            await db.refresh(conversation)
            existing = check_os_dispatch_state(conversation, codos, "abertura")
            if existing:
                if saved_rel_path and not existing.get("pdf_sent"):
                    delivered = await deliver_late_pdf(
                        db, tenant_id, whatsapp_number.id, instance_name, phone, conversation,
                        codos, saved_rel_path, "CONFIRM_OS_PDF:", contact_name
                    )
                    if not delivered:
                        return {"status": "pdf_delivery_failed", "flow": "abertura", "codos": codos, "conversation_id": conversation.id}
                    mark_os_dispatched(conversation, codos, "abertura", pdf_sent=True)
                    await db.commit()
                    logger.info(f"[OS DB EVENT] ENTRADA - O.S. #{codos} já tinha sido avisada; PDF entregue agora (conversa #{conversation.id})")
                    return {"status": "pdf_delivered", "flow": "abertura", "codos": codos, "conversation_id": conversation.id}
                return {"status": "already_dispatched", "flow": "abertura", "codos": codos, "conversation_id": conversation.id}

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
                equip_receipt_line = f"📥 Hoje, {data_str}, recebemos o seu equipamento{equip_bits} referente à *O.S. #{codos}*, {purpose}."

            mark_os_dispatched(conversation, codos, "abertura", pdf_sent=bool(saved_rel_path))
            await db.commit()
            natureza_already_seen = check_and_extend_entrada_window(conversation.id, natureza)

        if natureza_already_seen is None:
            # Fresh visit for this conversation - full sequence, exactly as before.
            asyncio.create_task(dispatch_abertura_messages(
                tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
                natureza, config, contact_name, detected_equip, valor_diagnostico,
                saved_rel_path or "", delay_sec, equip_receipt_line, str(codos)
            ))
            logger.info(f"[OS DB EVENT] ENTRADA - O.S. #{codos} '{natureza}' agendada (conversa #{conversation.id})")
        else:
            # Another O.S. for the same customer within ENTRADA_WINDOW_SECONDS of a previous
            # one - see check_and_extend_entrada_window - only sends what's actually new.
            item_notice_line = equip_receipt_line or f"📥 Também recebemos sua Ordem de Serviço *#{codos}*."
            asyncio.create_task(dispatch_supplementary_entrada_item(
                tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
                natureza, config, contact_name, detected_equip, valor_diagnostico,
                saved_rel_path or "", delay_sec, item_notice_line, str(codos), natureza_already_seen
            ))
            logger.info(f"[OS DB EVENT] ENTRADA - O.S. #{codos} '{natureza}' agrupada como item suplementar (conversa #{conversation.id})")
        return {"status": "queued", "flow": "abertura", "natureza": natureza, "codos": codos, "conversation_id": conversation.id}

    if cod_tipo_evento == EVENTO_ORC_AGUARDANDO_APROVACAO:
        async with _os_dispatch_lock:
            # See the identical comment in the EVENTO_ENTRADA branch above - refresh is
            # required here too, for the same reason.
            await db.refresh(conversation)
            existing = check_os_dispatch_state(conversation, codos, "orcamento")
            if existing:
                if saved_rel_path and not existing.get("pdf_sent"):
                    delivered = await deliver_late_pdf(
                        db, tenant_id, whatsapp_number.id, instance_name, phone, conversation,
                        codos, saved_rel_path, "CONFIRM_OS_APPROVAL:", contact_name
                    )
                    if not delivered:
                        return {"status": "pdf_delivery_failed", "flow": "orcamento", "codos": codos, "conversation_id": conversation.id}
                    mark_os_dispatched(conversation, codos, "orcamento", pdf_sent=True)
                    await db.commit()
                    logger.info(f"[OS DB EVENT] ORC AGUARDANDO APROVACAO - O.S. #{codos} já tinha sido avisada; PDF entregue agora (conversa #{conversation.id})")
                    return {"status": "pdf_delivered", "flow": "orcamento", "codos": codos, "conversation_id": conversation.id}
                return {"status": "already_dispatched", "flow": "orcamento", "codos": codos, "conversation_id": conversation.id}

            # A mudança do evento no Softsystem já dispara o aviso, mesmo sem o PDF do orçamento
            # ainda salvo (isso é um passo manual separado no processo da loja) - o arquivo é
            # enviado quando disponível, mas não é um requisito pra avisar o cliente.
            if not saved_rel_path:
                logger.info(f"[OS DB EVENT] O.S. #{codos}: PDF do orçamento ainda não encontrado, avisando o cliente mesmo assim.")

            tecnico_phone = await resolve_tecnico_phone_by_name(db, tenant_id, tecnico_nome)
            mark_os_dispatched(conversation, codos, "orcamento", pdf_sent=bool(saved_rel_path))
            await db.commit()
        asyncio.create_task(dispatch_orcamento_messages(
            tenant_id, whatsapp_number.id, instance_name, phone, conversation.id,
            contact_name, str(codos), saved_rel_path or "", tecnico_phone, delay_sec
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
    msg = await automation_service.build_evento_message(
        db, tenant_id, cod_tipo_evento, config, contact_name,
        ctx={
            "os_numero": str(codos),
            "tipo_os": TIPO_OS_LABEL.get(natureza_codigo, ""),
            "equipamento": build_equipamento_display(equip_marca, equip_modelo, equip_descricao),
        },
        obs=obs, eventos_anteriores=eventos_anteriores
    )
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
        saved_rel_path=saved_rel_path,
        obs=data.get("obs"),
        eventos_anteriores=[int(c) for c in (data.get("eventos_anteriores") or [])],
        razao_social=data.get("cliente_razao_social")
    )
