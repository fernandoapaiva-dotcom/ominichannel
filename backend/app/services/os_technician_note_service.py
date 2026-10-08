"""
Cobrança automática das observações que o dono deixa numa O.S. pro técnico responsável (ex.:
"a peça chegou, 07/10") - pedido do usuário em 07/10/2026: reenvia por WhatsApp de 2 em 2 dias
até alguém marcar como resolvido na tela, "pra não deixar o técnico esquecer". Mesmo ritmo e
mesmas regras de horário já usadas em os_board_followup_service.py (só manda em horário
comercial/dia útil, reaproveita as mesmas funções utilitárias) - esse serviço nasceu DEPOIS de
um disparo em rajada ter sobrecarregado o servidor, então o cuidado com ritmo se aplica aqui
também, mesmo sendo um volume bem menor (lembretes pra técnico, não cobrança de cliente).

Diferença chave pro followup de cliente: lá a resolução é automática (o evento muda sozinho no
Softsystem quando o cliente responde); aqui não existe esse sinal - resolução é SEMPRE manual
(OsTechnicianNote.resolved_at), por decisão explícita do usuário.
"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import OsTechnicianNote, WhatsAppNumber
from app.services.os_board_followup_service import (
    _now_brt, _clean_phone, _FERIADOS_NACIONAIS,
    BUSINESS_START_HOUR, BUSINESS_END_HOUR,
)

logger = logging.getLogger("os_technician_note")

NUDGE_INTERVAL_DAYS = 2
CHECK_INTERVAL_SECONDS = 600  # mesmo ritmo do followup de cliente - varre a cada 10 min
MAX_PER_TICK = 8
PER_ITEM_GAP_SECONDS = 5


async def _get_whatsapp_number():
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
        )).scalar_one_or_none()


async def _send_nudge(wn: WhatsAppNumber, note: OsTechnicianNote, codos: int, cliente: Optional[str]) -> bool:
    from app.api.v1.os_handler_ingest import resolve_tecnico_phone_by_name

    async with AsyncSessionLocal() as db:
        tecnico_phone = await resolve_tecnico_phone_by_name(db, wn.tenant_id, note.tecnico)
    phone = _clean_phone(tecnico_phone)
    if not phone:
        logger.warning(f"[NOTA TECNICO] O.S. #{codos}: não achei telefone do técnico '{note.tecnico}' - pulando lembrete.")
        return False

    texto = (
        f"🔔 *Lembrete* - O.S. #{codos}" + (f" ({cliente})" if cliente else "") + f":\n"
        f"{note.mensagem}\n\n"
        f"Anotado em {note.criado_em.strftime('%d/%m')}. Avise quando resolver pra marcarem como concluído no sistema."
    )
    try:
        from app.api.v1.os_handler_ingest import get_or_create_conversation, send_and_log_text
        from app.services.lid_resolver_service import resolve_and_bind_contact

        async with AsyncSessionLocal() as db2:
            contact = await resolve_and_bind_contact(db2, wn.tenant_id, phone, push_name=note.tecnico)
            await db2.flush()
            conversation = await get_or_create_conversation(db2, wn.tenant_id, contact.id, wn.id)
            await db2.commit()
            await send_and_log_text(db2, wn.tenant_id, wn.id, wn.instancia_evolution_api, phone, conversation, texto, delay_sec=1.5)

        async with AsyncSessionLocal() as db3:
            row = await db3.get(OsTechnicianNote, note.id)
            if row and not row.resolved_at:
                row.last_nudge_at = datetime.utcnow()
                await db3.commit()
        logger.info(f"[NOTA TECNICO] Lembrete da O.S. #{codos} enviado pra {note.tecnico} ({phone}).")
        return True
    except Exception as err:
        logger.error(f"[NOTA TECNICO] Falha ao mandar lembrete da O.S. #{codos} pra {note.tecnico}: {err}", exc_info=True)
        return False


async def _ticks_left_today(now: datetime) -> int:
    end_of_window = now.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    remaining = (end_of_window - now).total_seconds()
    return max(1, math.ceil(remaining / CHECK_INTERVAL_SECONDS))


async def check_technician_note_followups():
    wn = await _get_whatsapp_number()
    if not wn or not wn.instancia_evolution_api:
        return
    now = _now_brt()
    if now.weekday() >= 5:
        return
    if now.strftime("%Y-%m-%d") in _FERIADOS_NACIONAIS:
        return
    if not (BUSINESS_START_HOUR <= now.hour < BUSINESS_END_HOUR):
        return

    cutoff = datetime.utcnow() - timedelta(days=NUDGE_INTERVAL_DAYS)
    async with AsyncSessionLocal() as db:
        from app.models.models import OsBoardOrder
        rows = (await db.execute(select(OsTechnicianNote, OsBoardOrder.cliente).where(
            OsTechnicianNote.tenant_id == wn.tenant_id,
            OsTechnicianNote.resolved_at.is_(None),
        ).outerjoin(
            OsBoardOrder,
            (OsBoardOrder.tenant_id == OsTechnicianNote.tenant_id) &
            (OsBoardOrder.empresa == OsTechnicianNote.empresa) &
            (OsBoardOrder.loja == OsTechnicianNote.loja) &
            (OsBoardOrder.codos == OsTechnicianNote.codos)
        ))).all()

    due = []
    for note, cliente in rows:
        last_touch = note.last_nudge_at or note.criado_em
        if last_touch and last_touch <= cutoff:
            due.append((note, cliente))
    if not due:
        return

    ticks_restantes = await _ticks_left_today(now)
    lote = min(MAX_PER_TICK, max(1, math.ceil(len(due) / ticks_restantes)))

    enviados = 0
    for note, cliente in due[:lote]:
        if enviados:
            await asyncio.sleep(PER_ITEM_GAP_SECONDS)
        if await _send_nudge(wn, note, note.codos, cliente):
            enviados += 1

    if enviados:
        logger.info(f"[NOTA TECNICO] Ciclo: {enviados}/{len(due)} lembrete(s) enviado(s) (~{ticks_restantes} ciclos até 18h).")


async def start_technician_note_followup_loop(interval_seconds: int = CHECK_INTERVAL_SECONDS):
    logger.info(
        f"Cobrança automática de observações pro técnico iniciada "
        f"({interval_seconds}s de intervalo, só entre {BUSINESS_START_HOUR}h e {BUSINESS_END_HOUR}h)."
    )
    while True:
        try:
            await check_technician_note_followups()
        except Exception as err:
            logger.error(f"[NOTA TECNICO] Erro no ciclo: {err}", exc_info=True)
        await asyncio.sleep(interval_seconds)
