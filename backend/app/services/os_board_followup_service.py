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

RITMO (pedido do usuário, depois de um disparo em rajada ter sobrecarregado o servidor): só manda
mensagem em horário comercial (08h-18h de Brasília) e distribui o que está pendente ao longo do
tempo que resta até as 18h, em vez de mandar tudo de uma vez - a cada ciclo (10 min), calcula quantas
mensagens estão na fila e quantos ciclos ainda cabem até o fim do expediente, e manda só a fatia
correspondente, com uma pausa curta entre uma e outra. Se a fila for maior do que dá pra esvaziar no
dia, o resto continua no próximo dia útil - nunca tenta "compensar" mandando mais rápido.

Só manda mensagem para O.S. com telefone conhecido (Contato da O.S. ou cadastro do cliente - ver
db_watcher.resolve_recipient) e computa o intervalo de 2 dias a partir do maior entre
"quando entrou na etapa" e "última cobrança enviada".
"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

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

CHECK_INTERVAL_SECONDS = 600      # varre a fila a cada 10 min
BUSINESS_START_HOUR = 8           # só manda entre 08h e 18h de Brasília
BUSINESS_END_HOUR = 18
MAX_PER_TICK = 8                  # teto de segurança, mesmo se a conta sugerir mais
PER_ITEM_GAP_SECONDS = 5          # respiro entre uma mensagem e outra dentro do mesmo ciclo
MAX_DESCARTE_PER_TICK = 3         # move pro "Desmanche e Descarte" aos poucos também


def _clean_phone(raw: Optional[str]) -> str:
    return "".join(filter(str.isdigit, raw or ""))


def _now_brt() -> datetime:
    # Brasília local (naive) - mesma convenção do Softsystem/quadro (ver os_board.now_brt); o servidor
    # roda em UTC, então datetime.utcnow() teria "agora" 3h à frente do horário que os eventos usam.
    return datetime.utcnow() - timedelta(hours=3)


def _ticks_left_today(now: datetime) -> int:
    """Quantos ciclos de CHECK_INTERVAL_SECONDS ainda cabem até as BUSINESS_END_HOUR de hoje."""
    end_of_window = now.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    remaining = (end_of_window - now).total_seconds()
    return max(1, math.ceil(remaining / CHECK_INTERVAL_SECONDS))


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


class _DueItem:
    __slots__ = ("kind", "row_id", "codos", "telefone", "nome", "dias_restantes", "prioridade")

    def __init__(self, kind, row_id, codos, telefone, nome, dias_restantes, prioridade):
        self.kind = kind  # "orcamento" | "retirada"
        self.row_id = row_id
        self.codos = codos
        self.telefone = telefone
        self.nome = nome
        self.dias_restantes = dias_restantes
        self.prioridade = prioridade  # quanto mais no passado, mais prioridade (vai primeiro)


async def _list_due_orcamento(now: datetime, cutoff: datetime, wn: WhatsAppNumber) -> List[_DueItem]:
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
                due.append(_DueItem("orcamento", row.id, row.codos, row.telefone, row.contato_nome or row.cliente, None, last_touch))
        return due


async def _list_due_retirada(now: datetime, cutoff: datetime, wn: WhatsAppNumber) -> Tuple[List[_DueItem], List[_DueItem]]:
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
            item = _DueItem("retirada", row.id, row.codos, row.telefone, row.contato_nome or row.cliente, dias_restantes, entrou_em or now)
            if dias_restantes <= 0:
                due_descarte.append(item)
                continue
            last_touch = row.last_nudge_at or row.ultimo_evento_em
            if last_touch and last_touch <= cutoff:
                due_nudge.append(item)
        return due_nudge, due_descarte


async def _send_item(wn: WhatsAppNumber, item: _DueItem, now: datetime) -> bool:
    phone = _clean_phone(item.telefone)
    if not phone:
        return False
    primeiro_nome = (item.nome or "Cliente").strip().split()[0].title()
    if item.kind == "orcamento":
        texto = (
            f"Olá, {primeiro_nome}! 👋 Só confirmando: você já pôde ver o orçamento da sua Ordem de Serviço "
            f"*#{item.codos}*? Posso liberar a execução do serviço? Responda *SIM* para aprovar ou *NÃO* caso ainda "
            f"não queira seguir. Qualquer dúvida, é só chamar por aqui! 😊"
        )
    else:
        texto = (
            f"Olá, {primeiro_nome}! 👋 Seu equipamento (O.S. *#{item.codos}*) já está pronto e à sua espera aqui na loja. "
            f"Conforme as Condições Gerais de Serviço, restam *{item.dias_restantes} dias* para a retirada - depois desse "
            f"prazo o equipamento pode ser considerado abandonado e encaminhado para desmonte, já que nosso espaço "
            f"físico é limitado e as peças usadas têm custo. Se tiver alguma dificuldade pra vir buscar, nos avise "
            f"que a gente vê uma solução juntos! 😊"
        )
    try:
        await _dispatch(wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, item.nome, texto)
        async with AsyncSessionLocal() as db2:
            row = await db2.get(OsBoardOrder, item.row_id)
            if row:
                row.last_nudge_at = now
                await db2.commit()
        logger.info(f"[OS BOARD FOLLOWUP] Cobrança de {item.kind} enviada - O.S. #{item.codos} ({phone})")
        return True
    except Exception as err:
        logger.error(f"[OS BOARD FOLLOWUP] Falha ao cobrar {item.kind} da O.S. #{item.codos}: {err}")
        return False


async def _process_descarte(wn: WhatsAppNumber, item: _DueItem, now: datetime):
    from app.api.v1.os_board import record_board_event
    try:
        async with AsyncSessionLocal() as db3:
            await record_board_event(db3, wn.tenant_id, item.codos, EVENTO_DESCARTE, now)
        logger.info(f"[OS BOARD FOLLOWUP] O.S. #{item.codos}: prazo de retirada esgotado - movida para Desmanche e Descarte")
        phone = _clean_phone(item.telefone)
        if phone:
            primeiro_nome = (item.nome or "Cliente").strip().split()[0].title()
            texto = (
                f"Olá, {primeiro_nome}. O prazo de {RETIRADA_PRAZO_DIAS} dias para retirada do equipamento da sua "
                f"Ordem de Serviço *#{item.codos}* se encerrou sem retorno. Conforme as Condições Gerais de Serviço, ele "
                f"está sujeito a ser considerado abandonado e encaminhado para desmonte. Se ainda tiver interesse "
                f"em retirá-lo, entre em contato com a gente o quanto antes para vermos o que ainda é possível."
            )
            await _dispatch(wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, item.nome, texto)
    except Exception as err:
        logger.error(f"[OS BOARD FOLLOWUP] Falha ao processar descarte da O.S. #{item.codos}: {err}")


async def check_os_board_followups():
    wn = await _get_whatsapp_number()
    if not wn or not wn.instancia_evolution_api:
        return
    now = _now_brt()
    if not (BUSINESS_START_HOUR <= now.hour < BUSINESS_END_HOUR):
        return  # fora do horário comercial (08h-18h) - não manda nada agora, só retoma no próximo dia útil

    cutoff = now - timedelta(days=NUDGE_INTERVAL_DAYS)
    try:
        due_orc = await _list_due_orcamento(now, cutoff, wn)
        due_ret, due_descarte = await _list_due_retirada(now, cutoff, wn)
        fila = sorted(due_orc + due_ret, key=lambda it: it.prioridade)  # mais atrasada primeiro

        if not fila and not due_descarte:
            return

        ticks_restantes = _ticks_left_today(now)
        lote = min(MAX_PER_TICK, max(1, math.ceil(len(fila) / ticks_restantes))) if fila else 0

        enviados = 0
        for item in fila[:lote]:
            if enviados:
                await asyncio.sleep(PER_ITEM_GAP_SECONDS)
            if await _send_item(wn, item, now):
                enviados += 1

        for item in due_descarte[:MAX_DESCARTE_PER_TICK]:
            await asyncio.sleep(PER_ITEM_GAP_SECONDS)
            await _process_descarte(wn, item, now)

        if enviados or due_descarte:
            logger.info(
                f"[OS BOARD FOLLOWUP] Ciclo: {enviados}/{len(fila)} cobrança(s) enviada(s) "
                f"(fila total, ~{ticks_restantes} ciclos até 18h) · {min(len(due_descarte), MAX_DESCARTE_PER_TICK)} descarte(s)."
            )
    except Exception as err:
        logger.error(f"[OS BOARD FOLLOWUP] Erro no ciclo: {err}", exc_info=True)


async def start_os_board_followup_loop(interval_seconds: int = CHECK_INTERVAL_SECONDS):
    logger.info(
        f"Quadro de Técnicos: cobrança automática de aprovação/retirada iniciada "
        f"({interval_seconds}s de intervalo, só entre {BUSINESS_START_HOUR}h e {BUSINESS_END_HOUR}h)."
    )
    await asyncio.sleep(30)
    while True:
        try:
            await check_os_board_followups()
        except Exception as e:
            logger.error(f"[OS BOARD FOLLOWUP] Erro no loop: {e}")
        await asyncio.sleep(interval_seconds)
