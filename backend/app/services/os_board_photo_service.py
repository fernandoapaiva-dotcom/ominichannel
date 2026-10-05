"""
Foto de O.S. tirada direto no sistema (câmera do navegador) - substitui o fluxo manual antigo de
tirar foto no celular e sincronizar pro Google Fotos só pra guardar referência interna. Ao
receber uma foto (ver handle_os_photo_upload, chamado tanto pelo quadro administrativo quanto
pelo Portal do Técnico):

  1. Salva local em uploads/ e cria a linha em OsBoardPhoto (resposta já pode voltar pro
     atendente/técnico aqui - os três envios abaixo rodam em segundo plano, melhor esforço).
  2. Sobe pro Google Drive da loja, numa subpasta "Fotos_OS/{empresa}_{codos}" dentro da pasta
     já configurada em Integrações (mesmo mecanismo do backup diário - ver gdrive_service).
  3. Manda a foto pro cliente dono da O.S. no WhatsApp (mesmo telefone que o quadro já usa pra
     cobrança de aprovação/retirada - ver os_board_followup_service).
  4. Enfileira o anexo de volta na aba "Arquivos" da própria O.S. no Softsystem (o backend não
     alcança a pasta de rede da loja nem o Firebird direto - só o vigia, de dentro da loja - ver
     SoftsystemPendingFileAttach e tools/os_db_watcher/db_watcher.py::poll_pending_file_attachs).

Cada um dos três é independente: a falha de um (ex.: Drive sem credencial configurada) não
impede os outros, e cada status fica registrado em OsBoardPhoto pra auditoria.
"""
import os
import uuid
import base64
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import OsBoardOrder, OsBoardPhoto, SoftsystemPendingFileAttach, WhatsAppNumber

logger = logging.getLogger("os_board_photo_service")

GDRIVE_ROOT_FOLDER_NAME = "Fotos_OS"
FALLBACK_GDRIVE_FOLDER_ID = "1Xv8qI4NLU9pjbbUvCZami3TfkgsjRfd0"  # Drive da servsoldabrasilia@gmail.com, mesmo fallback do resto do sistema

# Mandar várias fotos seguidas (ex.: 4-5 ângulos do equipamento na recepção) repetindo a saudação
# completa em cada uma ficava repetitivo/estranho pro cliente - só a primeira de uma "leva" (mesma
# O.S., enviada nos últimos N minutos) leva o "Olá, fulano!"; as próximas da mesma leva são mais
# enxutas. Documento (PDF, ex. nota fiscal de garantia) sempre identifica o que é, mesmo sem a
# saudação, porque sem isso o cliente não sabe do que se trata (diferente de foto, que fala por si).
RECENT_BATCH_WINDOW_MINUTES = 10


def _clean_phone(raw: Optional[str]) -> str:
    return "".join(filter(str.isdigit, raw or ""))


async def handle_os_photo_upload(
    tenant_id: int, codos: int, file_bytes: bytes, original_filename: str, content_type: str, uploaded_by: str,
    send_to_customer: bool = True,
) -> dict:
    """
    `send_to_customer=False` é pro caso da representante de fábrica (pedido do usuário em
    05/10/2026): quando o cliente traz o equipamento pra acionar garantia de fábrica, ele
    apresenta a NOTA FISCAL DE COMPRA (prova de garantia) - esse documento é anexado na O.S. e
    enviado pra fábrica junto do laudo, mas NUNCA deve ir pro WhatsApp do próprio cliente (ele já
    tem o original, não faz sentido mandar de volta). Continua subindo pro Drive e anexando no
    Softsystem normalmente - só o envio por WhatsApp é pulado.
    """
    async with AsyncSessionLocal() as db:
        order = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
        ))).scalars().first()
        if not order:
            raise ValueError(f"O.S. #{codos} não encontrada no quadro")

        os.makedirs("uploads", exist_ok=True)
        ext = os.path.splitext(original_filename or "")[1] or ".jpg"
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join("uploads", unique_filename)
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        mimetype = content_type or "image/jpeg"
        photo = OsBoardPhoto(
            tenant_id=tenant_id, empresa=order.empresa, loja=order.loja, codos=codos,
            file_url=f"/uploads/{unique_filename}", mimetype=mimetype,
            original_filename=original_filename, uploaded_by=uploaded_by,
            whatsapp_status="pending" if send_to_customer else "nao_enviar",
        )
        db.add(photo)
        await db.commit()
        await db.refresh(photo)

        order_snapshot = {
            "empresa": order.empresa, "loja": order.loja, "codos": order.codos,
            "telefone": order.telefone, "contato_nome": order.contato_nome or order.cliente,
        }

    # Melhor esforço, em paralelo - nenhum bloqueia a resposta nem os outros dois.
    if send_to_customer:
        asyncio.create_task(_send_whatsapp(photo.id, tenant_id, order_snapshot, file_path, mimetype, original_filename))
    asyncio.create_task(_upload_drive(photo.id, tenant_id, order_snapshot, file_path, mimetype))
    asyncio.create_task(_enqueue_softsystem_attach(photo.id, tenant_id, order_snapshot, file_path, original_filename, uploaded_by))

    return {
        "id": photo.id, "codos": codos, "file_url": photo.file_url,
        "uploaded_by": uploaded_by, "criado_em": photo.criado_em.isoformat(),
        "gdrive_status": photo.gdrive_status, "whatsapp_status": photo.whatsapp_status,
        "softsystem_status": photo.softsystem_status,
    }


async def _set_photo_status(photo_id: int, **fields):
    async with AsyncSessionLocal() as db:
        photo = await db.get(OsBoardPhoto, photo_id)
        if not photo:
            return
        for k, v in fields.items():
            setattr(photo, k, v)
        await db.commit()


async def _is_first_in_recent_batch(tenant_id: int, codos: int, exclude_photo_id: int) -> bool:
    """Essa é a primeira foto/arquivo desta O.S. enviado nos últimos RECENT_BATCH_WINDOW_MINUTES
    minutos? Se não for, é a 2ª+ de uma mesma "leva" (ex.: o atendente tirou 4 fotos seguidas da
    recepção do equipamento) - usado pra não repetir a saudação completa em cada uma."""
    async with AsyncSessionLocal() as db:
        cutoff = datetime.utcnow() - timedelta(minutes=RECENT_BATCH_WINDOW_MINUTES)
        count = (await db.execute(select(func.count(OsBoardPhoto.id)).where(
            OsBoardPhoto.tenant_id == tenant_id, OsBoardPhoto.codos == codos,
            OsBoardPhoto.id != exclude_photo_id, OsBoardPhoto.criado_em >= cutoff,
        ))).scalar()
        return not count


def _build_caption(is_first: bool, is_image: bool, nome: str, codos: int, filename: str) -> str:
    if is_image:
        if is_first:
            return f"📷 Olá, {nome}! Segue uma foto do seu equipamento na nossa assistência técnica (O.S. *#{codos}*)."
        return ""  # 2ª+ foto da mesma leva: sem legenda repetida, a imagem já fala por si
    # Documento (PDF, ex. nota fiscal de garantia, manual, etc.) - sempre identifica o que é, porque
    # ao contrário de uma foto, sem isso o cliente não sabe do que se trata.
    if is_first:
        return f"📄 Olá, {nome}! Segue um documento referente à sua Ordem de Serviço *#{codos}*: {filename}"
    return f"📄 {filename}"


async def _send_whatsapp(photo_id: int, tenant_id: int, order: dict, file_path: str, mimetype: str, original_filename: str):
    phone = _clean_phone(order.get("telefone"))
    if not phone:
        await _set_photo_status(photo_id, whatsapp_status="sem_telefone")
        return
    try:
        async with AsyncSessionLocal() as db:
            wn = (await db.execute(select(WhatsAppNumber).where(
                WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID
            ))).scalar_one_or_none()
        if not wn or not wn.instancia_evolution_api:
            await _set_photo_status(photo_id, whatsapp_status="failed")
            return

        from app.services.evolution_service import evolution_service
        from app.api.v1.os_handler_ingest import get_or_create_conversation, extract_evolution_msg_id
        from app.services.lid_resolver_service import resolve_and_bind_contact
        from app.models.models import Message, MessageSender, MessageType

        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        primeiro_nome = (order.get("contato_nome") or "Cliente").strip().split()[0].title()
        media_type = "image" if mimetype.startswith("image/") else "document"
        is_first = await _is_first_in_recent_batch(tenant_id, order["codos"], photo_id)
        caption = _build_caption(is_first, media_type == "image", primeiro_nome, order["codos"], original_filename or "arquivo")
        send_res = await evolution_service.send_media_message(
            instance_name=wn.instancia_evolution_api, number=phone, media_type=media_type,
            mimetype=mimetype, media=b64, file_name=original_filename or "foto.jpg",
            caption=caption, skip_anti_ban_pacing=True,
        )
        success = isinstance(send_res, dict) and send_res.get("success")
        if not success:
            logger.warning(f"[OS BOARD PHOTO] Falha ao enviar foto da O.S. #{order['codos']} pro cliente, tentando de novo: {send_res}")
            send_res = await evolution_service.send_media_message(
                instance_name=wn.instancia_evolution_api, number=phone, media_type=media_type,
                mimetype=mimetype, media=b64, file_name=original_filename or "foto.jpg",
                caption=caption, skip_anti_ban_pacing=True,
            )
            success = isinstance(send_res, dict) and send_res.get("success")

        if not success:
            logger.error(f"[OS BOARD PHOTO] Falha ao entregar foto da O.S. #{order['codos']} pro cliente após 2 tentativas: {send_res}")
            await _set_photo_status(photo_id, whatsapp_status="failed")
            return

        async with AsyncSessionLocal() as db:
            contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=order.get("contato_nome"))
            await db.flush()
            conversation = await get_or_create_conversation(db, tenant_id, contact.id, wn.id)
            msg = Message(
                conversation_id=conversation.id, remetente=MessageSender.SISTEMA,
                conteudo=f"/{file_path.replace(os.sep, '/')}",
                tipo=MessageType.IMAGEM if media_type == "image" else MessageType.ARQUIVO,
                status="sent", whatsapp_msg_id=extract_evolution_msg_id(send_res), timestamp=datetime.utcnow(),
            )
            db.add(msg)
            await db.commit()
        await _set_photo_status(photo_id, whatsapp_status="done")
    except Exception as e:
        logger.error(f"[OS BOARD PHOTO] Erro ao enviar foto da O.S. #{order.get('codos')} pro cliente: {e}", exc_info=True)
        await _set_photo_status(photo_id, whatsapp_status="failed")


async def _upload_drive(photo_id: int, tenant_id: int, order: dict, file_path: str, mimetype: str):
    try:
        from app.services.settings_service import settings_service
        from app.services.gdrive_service import gdrive_service

        async with AsyncSessionLocal() as db:
            gset = await settings_service.get_tenant_decrypted_settings(db, tenant_id)

        refresh_token = gset.get("gdrive_refresh_token")
        client_id = gset.get("google_client_id")
        client_secret = gset.get("google_client_secret")
        if not refresh_token or not client_id or not client_secret:
            await _set_photo_status(photo_id, gdrive_status="failed")
            return

        root_folder_id = gset.get("gdrive_folder_id") or FALLBACK_GDRIVE_FOLDER_ID
        fotos_folder_id = await asyncio.to_thread(
            gdrive_service.get_or_create_media_folder, root_folder_id, client_id, refresh_token, client_secret, GDRIVE_ROOT_FOLDER_NAME
        )
        os_folder_id = await asyncio.to_thread(
            gdrive_service.get_or_create_media_folder, fotos_folder_id, client_id, refresh_token, client_secret,
            f"{order['empresa']}_{order['codos']}"
        )
        drive_filename = f"OS_{order['codos']}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{os.path.splitext(file_path)[1]}"
        await asyncio.to_thread(
            gdrive_service.upload_file_to_drive, os_folder_id, file_path, drive_filename, client_id, refresh_token, client_secret, mimetype
        )
        await _set_photo_status(photo_id, gdrive_status="done")
    except Exception as e:
        logger.error(f"[OS BOARD PHOTO] Erro ao subir foto da O.S. #{order.get('codos')} pro Google Drive: {e}", exc_info=True)
        await _set_photo_status(photo_id, gdrive_status="failed")


async def _enqueue_softsystem_attach(photo_id: int, tenant_id: int, order: dict, file_path: str, original_filename: str, uploaded_by: str):
    try:
        ext = os.path.splitext(original_filename or file_path)[1] or ".jpg"
        descricao = (original_filename or os.path.basename(file_path))[:100]
        operador = (uploaded_by or "SISTEMA").strip()[:30].upper() or "SISTEMA"
        abs_path = os.path.abspath(file_path)

        async with AsyncSessionLocal() as db:
            db.add(SoftsystemPendingFileAttach(
                tenant_id=tenant_id, photo_id=photo_id, empresa=order["empresa"], loja=order["loja"],
                codos=order["codos"], source_path=abs_path, descricao=descricao, extensao=ext, operador=operador,
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"[OS BOARD PHOTO] Erro ao enfileirar anexo no Softsystem pra O.S. #{order.get('codos')}: {e}", exc_info=True)
        await _set_photo_status(photo_id, softsystem_status="failed")
