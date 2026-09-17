"""
Endpoint de ingestão de PDF da Ordem de Serviço (O.S.) para a Assistência Técnica.

O ERP Softsystem, usado na loja, salva um PDF da O.S. numa pasta local do computador
da loja a cada abertura/atualização. Um "vigia de pasta" separado (rodando fora deste
backend, no próprio PC da loja) detecta o novo arquivo e envia (POST multipart) para
este endpoint, autenticado por uma API key compartilhada (não há usuário logado do lado
de quem chama, então não usamos o JWT normal - ver verify_os_handler_key).

O texto do PDF é a única fonte confiável de telefone do cliente e da natureza da O.S.
(orçamento / garantia de loja / garantia de fábrica / locação) - o Softsystem não expõe
isso de outra forma (confirmado com o proprietário da loja). Por isso o fluxo aqui:
1. Salva o PDF em uploads/os_files/.
2. Extrai o texto com pypdf e lê os campos "Cliente:", "Celular:"/"Telefone:" e "Equipamento:".
3. Detecta a natureza por palavra-chave (mesma lógica de normalização usada no OS Handler
   de mensagens de chat, em automation_service.py).
4. Resolve/cria o Contact e a Conversation do cliente na instância fixa da Assistência
   Técnica (settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID).
5. Se a natureza foi reconhecida: envia as mensagens informativas (mesmos templates do OS
   Handler) + a pergunta de confirmação de leitura das condições, e marca a conversa como
   aguardando essa confirmação (Conversation.assunto_atual = "CONFIRM_OS_PDF:<arquivo>").
   O PDF completo só é enviado depois que o cliente confirmar (ver webhooks.py, bloco
   is_pending_os_pdf, e send_os_pdf_after_confirmation).
6. Se a natureza NÃO foi reconhecida (ex.: um tipo de documento ainda não mapeado, como a
   futura O.S. de aprovação de orçamento do técnico - fase 2), não descarta: registra uma
   nota de sistema na conversa e avisa o atendente por WebSocket para tratamento manual.
"""
import os
import re
import io
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pypdf import PdfReader

from app.core.config import settings
from app.core.database import get_db
from app.models.models import Conversation, ConversationStatus, Message, MessageSender, MessageType, WhatsAppNumber
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


def detect_natureza(norm_text: str) -> Optional[str]:
    for status, kws in NATUREZA_KEYWORDS.items():
        if any(kw in norm_text for kw in kws):
            return status
    return None


def extract_field(text: str, label: str) -> Optional[str]:
    m = re.search(rf"{label}\s*:\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_phone(text: str) -> Optional[str]:
    """Prefers 'Celular:', falls back to 'Telefone:'. Normalizes to digits with country code."""
    for label in ["Celular", "Telefone"]:
        raw = extract_field(text, label)
        if not raw:
            continue
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 8:
            continue
        if not digits.startswith("55") and len(digits) in (10, 11):
            digits = "55" + digits
        return digits
    return None


@router.post("/ingest", dependencies=[Depends(verify_os_handler_key)])
async def ingest_os_pdf(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    os.makedirs(os.path.join("uploads", UPLOAD_SUBDIR), exist_ok=True)
    saved_filename = f"{uuid.uuid4().hex}.pdf"
    saved_rel_path = f"{UPLOAD_SUBDIR}/{saved_filename}"
    abs_path = os.path.join("uploads", saved_rel_path)
    with open(abs_path, "wb") as f:
        f.write(file_bytes)

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        logger.error(f"[OS HANDLER INGEST] Erro ao ler PDF ({abs_path}): {e}")
        raise HTTPException(status_code=422, detail="Não foi possível ler o conteúdo do PDF")

    phone = extract_phone(full_text)
    if not phone:
        raise HTTPException(status_code=422, detail="Telefone do cliente não encontrado no PDF (campos Celular:/Telefone:)")

    client_name = extract_field(full_text, "Cliente")
    equipamento = extract_field(full_text, "Equipamento")
    norm_text = normalize_text(full_text)
    natureza = detect_natureza(norm_text)

    wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
    whatsapp_number = (await db.execute(wn_stmt)).scalar_one_or_none()
    if not whatsapp_number:
        logger.error("[OS HANDLER INGEST] ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID não configurado corretamente")
        raise HTTPException(status_code=500, detail="Instância de Assistência Técnica não configurada no servidor")

    tenant_id = whatsapp_number.tenant_id
    instance_name = whatsapp_number.instancia_evolution_api

    contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=client_name)
    await db.flush()

    # Get-or-create Conversation (same pattern as the live webhook handler)
    conv_stmt = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.contact_id == contact.id,
        Conversation.whatsapp_number_id == whatsapp_number.id,
        Conversation.status.in_([ConversationStatus.COM_IA, ConversationStatus.COM_HUMANO])
    ).order_by(Conversation.ultima_interacao_em.desc())
    conversation = (await db.execute(conv_stmt)).scalars().first()

    if not conversation:
        any_conv_stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.contact_id == contact.id,
            Conversation.whatsapp_number_id == whatsapp_number.id
        ).order_by(Conversation.ultima_interacao_em.desc())
        conversation = (await db.execute(any_conv_stmt)).scalars().first()
        if conversation:
            conversation.status = ConversationStatus.COM_HUMANO
        else:
            proto = await generate_daily_protocol(db, tenant_id)
            conversation = Conversation(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number.id,
                contact_id=contact.id,
                protocol_number=proto,
                status=ConversationStatus.COM_HUMANO,
                assunto_atual="Atendimento Concierge"
            )
            db.add(conversation)
            await db.flush()

    if not natureza:
        # Unrecognized document type - don't drop it silently, flag for manual handling.
        note = (
            f"📄 Um novo documento de O.S. foi recebido do Softsystem, mas o tipo não pôde "
            f"ser identificado automaticamente. Verifique o arquivo e envie ao cliente manualmente "
            f"se necessário."
        )
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
            whatsapp_number_id=whatsapp_number.id,
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
        return {
            "status": "unrecognized_natureza",
            "phone": phone,
            "conversation_id": conversation.id,
            "file": f"/uploads/{saved_rel_path}"
        }

    # Natureza recognized: send the informative templates + confirmation gate, hold the PDF.
    config = await automation_service.get_tenant_automations(db, tenant_id)
    os_cfg = config.get("os_handler", {})

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

    delay_ms = os_cfg.get("typing_delay_ms", 2000)
    delay_sec = max(0.5, float(delay_ms) / 1000.0)

    for msg_content in all_messages:
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
            whatsapp_number_id=whatsapp_number.id,
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

    conversation.assunto_atual = f"CONFIRM_OS_PDF:{saved_rel_path}"
    await db.commit()

    logger.info(f"[OS HANDLER INGEST] O.S. '{natureza}' processada para conversa #{conversation.id} ({phone})")
    return {
        "status": "success",
        "natureza": natureza,
        "phone": phone,
        "conversation_id": conversation.id
    }
