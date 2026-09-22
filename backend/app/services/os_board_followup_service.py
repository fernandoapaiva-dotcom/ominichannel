"""
Cobrança automática das duas etapas da O.S. que dependem do cliente responder: aprovação do
orçamento e retirada do equipamento. Roda por cima do espelho do Quadro de Técnicos
(OsBoardOrder/OsBoardEvent - ver app/api/v1/os_board.py), que é alimentado pelo vigia da loja.

Regras (pedidas pelo usuário):
  - "Orçamento enviado" (evento 3, aguardando o cliente aprovar): se não respondeu, cobra de 2 em
    2 dias perguntando se pode executar o serviço. Some da lista assim que o cliente responde no
    WhatsApp - a resposta já é gravada no quadro na hora por record_board_event() (ver webhooks.py),
    então esta varredura nunca fica perguntando a quem já respondeu.
  - "Aguardando retirada" (evento 6): mesma cobrança de 2 em 2 dias, mas contando 90 dias corridos
    desde que entrou nessa etapa (prazo das Condições Gerais de Serviço) - a mensagem informa quantos
    dias faltam. Ao chegar a 0, o sistema move o card para "Desmanche e Descarte" (grava o mesmo
    evento 14 que o Softsystem usaria) e manda um aviso final. Isso só move o CARD do quadro (o
    Softsystem real não é alterado) - a decisão física continua sendo da loja.

Só manda mensagem para O.S. com telefone conhecido (Contato da O.S. ou cadastro do cliente - ver
db_watcher.resolve_recipient) e computa o intervalo de 2 dias a partir do maior entre
"quando entrou na etapa" e "última cobrança enviada" - por isso nunca manda em rajada: uma O.S. que
já esteja parada há 40 dias sem cobrança prévia recebe UMA mensagem agora, não 20 de uma vez.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import OsBoardOrder, WhatsAppNumber

logger = logging.getLogger("os_board_followup")

NUDGE_INTERVAL_DAYS = 2
RETIRADA_PRAZO_DIAS = 90
EVENTO_ORCAMENTO_ENVIADO = 3
EVENTO_RETIRADA = 6
EVENTO_DESCARTE = 14


def _clean_phone(raw: Optional[str]) -> str:
    return "".join(filter(str.isdigit, raw or ""))


async def _dispatch(tenant_id: int, whatsapp_number_id: int, instance_name: str, phone: str, contact_name: Optional[str], text: str):
    """Manda o texto e registra no chat do cliente, reaproveitando o mesmo caminho do OS Handler."""
    from app.api.v1.os_handler_ingest import get_or_create_conversation, send_and_log_text
    from app.services.lid_resolver_service import resolve_and_bind_contact

    async with AsyncSessionLocal() as db:
        contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=contact_name)
        await db.flush()
        conversation = await get_or_create_conversation(db, tenant_id, contact.id, whatsapp_number_id)
        await db.commit()
        await db.refresh(conversation)
        await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, text, delay_sec=1.5)


async def _get_whatsapp_number():
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
        )).scalar_one_or_none()


async def check_orcamento_pendente(now: datetime, cutoff: datetime, wn: WhatsAppNumber):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == wn.tenant_id,
            OsBoardOrder.situacao_evento == EVENTO_ORCAMENTO_ENVIADO,
            OsBoardOrder.paga.is_(False), OsBoardOrder.venda_codigo.is_(None),
            OsBoardOrder.telefone.isnot(None),
        ))).scalars().all()
        due = []
        for row in rows:
            last_touch = row.last_nudge_at or row.ultimo_evento_em
            if last_touch and last_touch <= cutoff:
                due.append((row.id, row.codos, row.telefone, row.contato_nome or row.cliente, row.cliente))

    sent = 0
    for row_id, codos, telefone, saudacao_nome, cliente in due:
        phone = _clean_phone(telefone)
        if not phone:
            continue
        primeiro_nome = (saudacao_nome or "Cliente").strip().split()[0].title()
        texto = (
            f"Olá, {primeiro_nome}! 👋 Só confirmando: você já pôde ver o orçamento da sua Ordem de Serviço "
            f"*#{codos}*? Posso liberar a execução do serviço? Responda *SIM* para aprovar ou *NÃO* caso ainda "
            f"não queira seguir. Qualquer dúvida, é só chamar por aqui! 😊"
        )
        try:
            await _dispatch(wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, saudacao_nome, texto)
            async with AsyncSessionLocal() as db2:
                row = await db2.get(OsBoardOrder, row_id)
                if row:
                    row.last_nudge_at = now
                    await db2.commit()
            sent += 1
            logger.info(f"[OS BOARD FOLLOWUP] Cobrança de aprovação enviada - O.S. #{codos} ({phone})")
        except Exception as err:
            logger.error(f"[OS BOARD FOLLOWUP] Falha ao cobrar aprovação da O.S. #{codos}: {err}")
    return sent


async def check_retirada_pendente(now: datetime, cutoff: datetime, wn: WhatsAppNumber):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == wn.tenant_id,
            OsBoardOrder.situacao_evento == EVENTO_RETIRADA,
            OsBoardOrder.paga.is_(False), OsBoardOrder.venda_codigo.is_(None),
            OsBoardOrder.telefone.isnot(None),
        ))).scalars().all()
        due_nudge, due_descarte = [], []
        for row in rows:
            entrou_em = row.ultimo_evento_em
            dias_passados = (now - entrou_em).days if entrou_em else 0
            dias_restantes = RETIRADA_PRAZO_DIAS - dias_passados
            info = (row.id, row.codos, row.telefone, row.contato_nome or row.cliente, dias_restantes)
            if dias_restantes <= 0:
                due_descarte.append(info)
                continue
            last_touch = row.last_nudge_at or row.ultimo_evento_em
            if last_touch and last_touch <= cutoff:
                due_nudge.append(info)

    sent = 0
    for row_id, codos, telefone, saudacao_nome, dias_restantes in due_nudge:
        phone = _clean_phone(telefone)
        if not phone:
            continue
        primeiro_nome = (saudacao_nome or "Cliente").strip().split()[0].title()
        texto = (
            f"Olá, {primeiro_nome}! 👋 Seu equipamento (O.S. *#{codos}*) já está pronto e à sua espera aqui na loja. "
            f"Conforme as Condições Gerais de Serviço, restam *{dias_restantes} dias* para a retirada - depois desse "
            f"prazo o equipamento pode ser considerado abandonado e encaminhado para desmonte, já que nosso espaço "
            f"físico é limitado e as peças usadas têm custo. Se tiver alguma dificuldade pra vir buscar, nos avise "
            f"que a gente vê uma solução juntos! 😊"
        )
        try:
            await _dispatch(wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, saudacao_nome, texto)
            async with AsyncSessionLocal() as db2:
                row = await db2.get(OsBoardOrder, row_id)
                if row:
                    row.last_nudge_at = now
                    await db2.commit()
            sent += 1
            logger.info(f"[OS BOARD FOLLOWUP] Cobrança de retirada enviada - O.S. #{codos} ({phone}), faltam {dias_restantes}d")
        except Exception as err:
            logger.error(f"[OS BOARD FOLLOWUP] Falha ao cobrar retirada da O.S. #{codos}: {err}")

    for row_id, codos, telefone, saudacao_nome, _dias in due_descarte:
        phone = _clean_phone(telefone)
        try:
            from app.api.v1.os_board import record_board_event
            async with AsyncSessionLocal() as db3:
                await record_board_event(db3, wn.tenant_id, codos, EVENTO_DESCARTE, now)
            logger.info(f"[OS BOARD FOLLOWUP] O.S. #{codos}: prazo de retirada esgotado - movida para Desmanche e Descarte")
            if phone:
                primeiro_nome = (saudacao_nome or "Cliente").strip().split()[0].title()
                texto = (
                    f"Olá, {primeiro_nome}. O prazo de {RETIRADA_PRAZO_DIAS} dias para retirada do equipamento da sua "
                    f"Ordem de Serviço *#{codos}* se encerrou sem retorno. Conforme as Condições Gerais de Serviço, ele "
                    f"está sujeito a ser considerado abandonado e encaminhado para desmonte. Se ainda tiver interesse "
                    f"em retirá-lo, entre em contato com a gente o quanto antes para vermos o que ainda é possível."
                )
                await _dispatch(wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, saudacao_nome, texto)
        except Exception as err:
            logger.error(f"[OS BOARD FOLLOWUP] Falha ao processar descarte da O.S. #{codos}: {err}")
    return sent


async def check_os_board_followups():
    wn = await _get_whatsapp_number()
    if not wn or not wn.instancia_evolution_api:
        return
    # Brasília local (naive) - mesma convenção do Softsystem/quadro (ver os_board.now_brt); o servidor
    # roda em UTC, então datetime.utcnow() teria "agora" 3h à frente do horário que os eventos usam.
    now = datetime.utcnow() - timedelta(hours=3)
    cutoff = now - timedelta(days=NUDGE_INTERVAL_DAYS)
    try:
        n1 = await check_orcamento_pendente(now, cutoff, wn)
        n2 = await check_retirada_pendente(now, cutoff, wn)
        if n1 or n2:
            logger.info(f"[OS BOARD FOLLOWUP] Ciclo concluído: {n1} cobrança(s) de aprovação, {n2} de retirada.")
    except Exception as err:
        logger.error(f"[OS BOARD FOLLOWUP] Erro no ciclo: {err}", exc_info=True)


async def start_os_board_followup_loop(interval_seconds: int = 3600):
    logger.info(f"Quadro de Técnicos: cobrança automática de aprovação/retirada iniciada ({interval_seconds}s de intervalo).")
    await asyncio.sleep(30)
    while True:
        try:
            await check_os_board_followups()
        except Exception as e:
            logger.error(f"[OS BOARD FOLLOWUP] Erro no loop: {e}")
        await asyncio.sleep(interval_seconds)
