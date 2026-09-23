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
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, OsBoardOrder, WhatsAppNumber

logger = logging.getLogger("os_board_followup")

NUDGE_INTERVAL_DAYS = 2
RETIRADA_PRAZO_DIAS = 90
EVENTO_ORCAMENTO_ENVIADO = 3
EVENTO_RETIRADA = 6
EVENTO_DESCARTE = 14

STUCK_DISPATCH_MIN_AGE_MINUTES = 15  # abaixo disso a tarefa de fundo pode só estar lenta (rajada, etc.)
STUCK_DISPATCH_MAX_AGE_HOURS = 48    # não tenta retomar disparos muito antigos (já resolvidos de outra forma)

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


async def _dispatch(
    tenant_id: int, whatsapp_number_id: int, instance_name: str, phone: str, contact_name: Optional[str], text: str,
    pending_marker: Optional[str] = None,
):
    """
    Manda o texto e registra no chat do cliente, reaproveitando o mesmo caminho do OS Handler. Quando
    `pending_marker` é passado (cobrança de aprovação de orçamento), marca a conversa como aguardando
    essa resposta (mesmo marcador CONFIRM_OS_APPROVAL: que o fluxo original usa) - sem isso, a
    resposta *Sim*/*Não* do cliente não tinha para onde ir e podia cair em outro fluxo pendente da
    mesma conversa (ex.: confirmação de tarefa de agenda), respondendo a pergunta errada.
    """
    from app.api.v1.os_handler_ingest import get_or_create_conversation, send_and_log_text
    from app.services.lid_resolver_service import resolve_and_bind_contact

    async with AsyncSessionLocal() as db:
        contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=contact_name)
        await db.flush()
        conversation = await get_or_create_conversation(db, tenant_id, contact.id, whatsapp_number_id)
        if pending_marker:
            conversation.assunto_atual = pending_marker
        await db.commit()
        await db.refresh(conversation)
        await send_and_log_text(db, tenant_id, whatsapp_number_id, instance_name, phone, conversation, text, delay_sec=1.5)


async def _get_whatsapp_number():
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
        )).scalar_one_or_none()


class _DueItem:
    __slots__ = ("kind", "row_id", "codos", "telefone", "nome", "tecnico", "dias_restantes", "prioridade")

    def __init__(self, kind, row_id, codos, telefone, nome, tecnico, dias_restantes, prioridade):
        self.kind = kind  # "orcamento" | "retirada"
        self.row_id = row_id
        self.codos = codos
        self.telefone = telefone
        self.nome = nome
        self.tecnico = tecnico
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
                due.append(_DueItem("orcamento", row.id, row.codos, row.telefone, row.contato_nome or row.cliente, row.tecnico, None, last_touch))
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
            item = _DueItem("retirada", row.id, row.codos, row.telefone, row.contato_nome or row.cliente, row.tecnico, dias_restantes, entrou_em or now)
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
    pending_marker = None
    if item.kind == "orcamento":
        from app.api.v1.os_handler_ingest import resolve_tecnico_phone_by_name
        tecnico_phone = None
        try:
            async with AsyncSessionLocal() as db_tec:
                tecnico_phone = await resolve_tecnico_phone_by_name(db_tec, wn.tenant_id, item.tecnico)
        except Exception:
            pass
        pending_marker = f"CONFIRM_OS_APPROVAL:{item.codos}||{tecnico_phone or ''}"
    try:
        await _dispatch(wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, item.nome, texto, pending_marker=pending_marker)
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


async def _resume_stuck_orcamento_dispatches(wn: WhatsAppNumber, now_utc: datetime) -> int:
    """
    dispatch_orcamento_messages (os_handler_ingest.py) é uma tarefa de fundo "fire-and-forget":
    se o processo reiniciar bem no meio dela (foi exatamente o que aconteceu com a O.S. #1934 do
    Cleniton em 23/09/2026, derrubada por um `pm2 restart` concorrente), ela morre em silêncio,
    sem registrar erro nenhum, e o cliente nunca recebe a pergunta de aprovação - só o aviso
    inicial (e às vezes o PDF). Pedido do usuário: "seria bom o sistema perceber quando as
    tarefas automatizadas foram paradas no meio, pra retomar e finalizar".

    Detecção: mark_os_dispatched grava um registro em dados_adicionais.os_dispatched ANTES da
    tarefa de fundo rodar. Se esse registro já tem mais de STUCK_DISPATCH_MIN_AGE_MINUTES e a
    O.S. ainda está em "Orçamento enviado" no quadro (ninguém respondeu nem foi decidido no
    Softsystem), mas a conversa nunca chegou no marcador CONFIRM_OS_APPROVAL esperado, a tarefa
    nunca terminou de perguntar. Retoma mandando só a pergunta de aprovação - nunca reenvia o
    aviso inicial nem o PDF, pra não arriscar duplicar o que já possa ter saído antes de travar.
    """
    from app.api.v1.os_handler_ingest import send_and_log_text

    cutoff_min = now_utc - timedelta(minutes=STUCK_DISPATCH_MIN_AGE_MINUTES)
    cutoff_max = now_utc - timedelta(hours=STUCK_DISPATCH_MAX_AGE_HOURS)
    resumed = 0
    async with AsyncSessionLocal() as db:
        conversations = (await db.execute(select(Conversation).where(
            Conversation.tenant_id == wn.tenant_id,
            Conversation.whatsapp_number_id == wn.id,
            Conversation.ultima_interacao_em >= cutoff_max,
        ))).scalars().all()

        for conversation in conversations:
            extra = dict(conversation.dados_adicionais or {})
            os_dispatched = dict(extra.get("os_dispatched", {}))
            changed = False

            for codos_str, record in os_dispatched.items():
                if record.get("flow") != "orcamento" or record.get("resumed_at"):
                    continue
                dispatched_at_raw = record.get("dispatched_at")
                if not dispatched_at_raw:
                    continue
                try:
                    dispatched_at = datetime.fromisoformat(dispatched_at_raw)
                except ValueError:
                    continue
                if not (cutoff_max <= dispatched_at <= cutoff_min):
                    continue  # nova demais (pode só estar lenta) ou velha demais (já não é confiável retomar)

                expected_prefix = f"CONFIRM_OS_APPROVAL:{codos_str}|"
                if (conversation.assunto_atual or "").startswith(expected_prefix):
                    continue  # pergunta já foi feita certinho, só esperando o cliente responder

                try:
                    codos_int = int(codos_str)
                except ValueError:
                    continue
                board_row = (await db.execute(select(OsBoardOrder).where(
                    OsBoardOrder.tenant_id == wn.tenant_id, OsBoardOrder.codos == codos_int
                ))).scalars().first()
                if not board_row or board_row.situacao_evento != EVENTO_ORCAMENTO_ENVIADO:
                    continue  # já foi respondido/decidido por outro caminho - nada a retomar

                contact = await db.get(Contact, conversation.contact_id)
                phone = _clean_phone(contact.telefone) if contact else None
                if not phone:
                    continue

                approval_prompt = (
                    "Você *aprova* a execução do serviço pelo valor informado no orçamento? "
                    "Responda *SIM* para aprovar ou *NÃO* para recusar."
                )
                try:
                    await send_and_log_text(
                        db, wn.tenant_id, wn.id, wn.instancia_evolution_api, phone,
                        conversation, approval_prompt, delay_sec=1.5
                    )
                    pdf_rel_path = record.get("pdf_rel_path", "")
                    tecnico_phone = record.get("tecnico_phone") or ""
                    conversation.assunto_atual = f"CONFIRM_OS_APPROVAL:{codos_str}|{pdf_rel_path}|{tecnico_phone}"
                    record["resumed_at"] = now_utc.isoformat()
                    os_dispatched[codos_str] = record
                    changed = True
                    resumed += 1
                    logger.warning(
                        f"[OS BOARD FOLLOWUP] Retomada automática: disparo da O.S. #{codos_str} estava "
                        f"travado (conversa #{conversation.id}) - pergunta de aprovação reenviada."
                    )
                except Exception as err:
                    logger.error(f"[OS BOARD FOLLOWUP] Falha ao retomar disparo travado da O.S. #{codos_str}: {err}")

            if changed:
                extra["os_dispatched"] = os_dispatched
                conversation.dados_adicionais = extra
                flag_modified(conversation, "dados_adicionais")
                await db.commit()

    return resumed


async def check_os_board_followups():
    wn = await _get_whatsapp_number()
    if not wn or not wn.instancia_evolution_api:
        return
    now = _now_brt()
    if not (BUSINESS_START_HOUR <= now.hour < BUSINESS_END_HOUR):
        return  # fora do horário comercial (08h-18h) - não manda nada agora, só retoma no próximo dia útil

    try:
        resumed = await _resume_stuck_orcamento_dispatches(wn, datetime.utcnow())
        if resumed:
            logger.info(f"[OS BOARD FOLLOWUP] {resumed} disparo(s) travado(s) retomado(s) neste ciclo.")
    except Exception as err:
        logger.error(f"[OS BOARD FOLLOWUP] Erro ao verificar disparos travados: {err}", exc_info=True)

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
