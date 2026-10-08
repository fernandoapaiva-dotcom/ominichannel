"""
Reenvio automático de mensagens de texto que falharam de verdade (Message.status == "failed").

Antes de 29/09/2026, send_and_log_text (os_handler_ingest.py) gravava "sent" sem checar se a
Evolution API realmente confirmou o envio - qualquer falha (instância desconectada, servidor
sobrecarregado, etc.) ficava invisível: a mensagem aparecia como enviada no chat, mas o cliente
nunca recebia nada. Isso já foi corrigido lá (agora tenta 2x e grava "failed" se não conseguir),
mas sem ALGUÉM reenviando essas mensagens depois, "failed" só troca "mentira silenciosa" por
"falha visível que precisa alguém notar e reenviar na mão" - achado em produção no mesmo dia,
O.S. #1815 (Rodilson) e #33156 (Pedro Ferreira), ambas teve que reenviar manualmente.

Este vigia varre "failed" recentes a cada poucos minutos e tenta de novo sozinho - mesmo padrão já
usado pro PDF (tools/os_db_watcher/db_watcher.py, retry_pending_folder_pdfs) e pros disparos presos
de O.S. (os_board_followup_service._resume_stuck_os_dispatches), só que aqui é genérico: cobre
QUALQUER mensagem de texto do sistema que falhou, não só um fluxo específico.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Message, MessageSender, MessageType, Conversation, Contact, WhatsAppNumber, OsBoardOrder, SoftsystemPendingWrite
from app.services.evolution_service import evolution_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("failed_message_retry")

CHECK_INTERVAL_SECONDS = 300   # varre a cada 5 min
MAX_AGE_HOURS = 48             # não tenta reenviar algo muito antigo (já resolvido de outro jeito, ou sem sentido mandar agora)
PER_ITEM_GAP_SECONDS = 2       # respiro entre um reenvio e outro, mesmo motivo do os_board_followup_service


def _is_invalid_number_error(res) -> bool:
    """Evolution API devolve {'error': [{'jid':..., 'exists': False, ...}]} quando o número de
    WhatsApp simplesmente não existe - reenviar não vai adiantar nunca, é erro permanente."""
    if not isinstance(res, dict):
        return False
    err = res.get("error")
    if isinstance(err, list):
        return any(isinstance(e, dict) and e.get("exists") is False for e in err)
    return False


def _resolve_codos_for_conversation(conversation: Conversation, msg_content: str) -> Optional[int]:
    """
    Tenta descobrir qual O.S. essa mensagem/conversa é sobre, tentando os jeitos que os
    diferentes fluxos do sistema guardam isso (nenhum é universal sozinho):
    1. dados_adicionais.os_dispatched (fluxo de abertura/evento_progresso) - pega o mais recente.
    2. assunto_atual, formato "CONFIRM_OS_APPROVAL:1858||..." ou "CONFIRM_OS_PDF:...".
    3. Como último recurso, o próprio texto da mensagem quase sempre cita "*#1858*".
    """
    extra = conversation.dados_adicionais or {}
    os_dispatched = extra.get("os_dispatched") or {}
    if os_dispatched:
        try:
            return int(max(os_dispatched.items(), key=lambda kv: kv[1].get("dispatched_at") or "")[0])
        except (ValueError, TypeError):
            pass

    assunto = conversation.assunto_atual or ""
    m = re.search(r'CONFIRM_OS_(?:APPROVAL|PDF|TRANSFER):(\d+)', assunto)
    if m:
        return int(m.group(1))

    m = re.search(r'#(\d{3,7})\b', msg_content or "")
    if m:
        return int(m.group(1))

    return None


async def _register_invalid_number_in_softsystem(db, conversation: Conversation, contact: Contact, msg_content: str):
    """
    Avisa no Softsystem (campo de defeito/observação da O.S., sem mudar a etapa) que o WhatsApp
    do cliente não existe - pedido do usuário em 07/10/2026, pra equipe ver direto na O.S. e
    corrigir o telefone, em vez de só descobrir quando o cliente reclamar que não recebeu nada.
    """
    codos = _resolve_codos_for_conversation(conversation, msg_content)
    if not codos:
        return  # não deu pra descobrir a O.S. dessa conversa - nada pra registrar no Softsystem

    order = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == conversation.tenant_id, OsBoardOrder.codos == int(codos)
    ))).scalars().first()
    if not order:
        return

    db.add(SoftsystemPendingWrite(
        tenant_id=conversation.tenant_id, empresa=order.empresa, loja=order.loja, codos=order.codos,
        write_type="nota_defeito", cod_evento=0,
        obs=f"⚠️ WhatsApp do cliente ({contact.telefone}) inválido/não existe - mensagens automáticas não estão chegando. Verificar telefone.",
        requested_by="SISTEMA",
    ))
    logger.info(f"[FAILED RETRY] O.S. #{codos}: aviso de número inválido enfileirado pro Softsystem.")


async def _retry_once() -> int:
    reenviadas = 0
    async with AsyncSessionLocal() as db:
        cutoff = datetime.utcnow() - timedelta(hours=MAX_AGE_HOURS)
        rows = (await db.execute(select(Message).where(
            Message.status == "failed",
            Message.remetente == MessageSender.SISTEMA.value,
            Message.tipo == MessageType.TEXTO,
            Message.timestamp >= cutoff,
        ).order_by(Message.timestamp))).scalars().all()

        for msg in rows:
            conversation = await db.get(Conversation, msg.conversation_id)
            if not conversation:
                continue
            contact = await db.get(Contact, conversation.contact_id)
            wn = await db.get(WhatsAppNumber, conversation.whatsapp_number_id)
            if not contact or not contact.telefone or not wn or not wn.instancia_evolution_api:
                continue

            try:
                res = await evolution_service.send_text_message(
                    instance_name=wn.instancia_evolution_api, number=contact.telefone, text=msg.conteudo
                )
            except Exception as err:
                logger.error(f"[FAILED RETRY] Erro inesperado reenviando mensagem #{msg.id}: {err}")
                continue

            success = isinstance(res, dict) and res.get("success")
            if success:
                from app.api.v1.conversations import extract_evolution_msg_id
                msg.status = "sent"
                msg.whatsapp_msg_id = extract_evolution_msg_id(res)
                await db.commit()
                reenviadas += 1
                logger.info(f"[FAILED RETRY] Mensagem #{msg.id} (conversa #{conversation.id}) reenviada com sucesso.")
                try:
                    await ws_manager.broadcast({
                        "type": "MESSAGE_STATUS_UPDATE",
                        "conversation_id": conversation.id,
                        "message_id": msg.id,
                        "status": "sent",
                        "whatsapp_msg_id": msg.whatsapp_msg_id,
                    })
                except Exception as err:
                    logger.debug(f"[FAILED RETRY] Broadcast falhou (não impede o reenvio): {err}")
            elif _is_invalid_number_error(res):
                # Erro permanente - reenviar de novo a cada 5min pra sempre não resolve nada,
                # só lota o log. Marca como terminal e avisa no Softsystem, uma vez só.
                msg.status = "failed_invalid_number"
                await _register_invalid_number_in_softsystem(db, conversation, contact, msg.conteudo)
                await db.commit()
                logger.warning(f"[FAILED RETRY] Mensagem #{msg.id}: número de WhatsApp inválido ({contact.telefone}). Parando de tentar reenviar.")
            else:
                logger.warning(f"[FAILED RETRY] Mensagem #{msg.id} falhou de novo: {res}")

            await asyncio.sleep(PER_ITEM_GAP_SECONDS)

    return reenviadas


async def start_failed_message_retry_loop():
    logger.info(f"Reenvio automático de mensagens com falha iniciado (varredura a cada {CHECK_INTERVAL_SECONDS}s).")
    while True:
        try:
            n = await _retry_once()
            if n:
                logger.info(f"[FAILED RETRY] {n} mensagem(ns) reenviada(s) com sucesso nesta varredura.")
        except Exception as err:
            logger.error(f"[FAILED RETRY] Erro na varredura: {err}", exc_info=True)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
