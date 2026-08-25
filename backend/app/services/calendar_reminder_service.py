import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.models import CalendarEvent, WhatsAppNumber
from app.services.evolution_service import evolution_service

logger = logging.getLogger("calendar_reminder_service")

EVENT_TYPE_LABELS = {
    "entrega_gas": "🚚 Entrega de Gás / Mercadoria",
    "visita_tecnica": "🔧 Visita Técnica",
    "manutencao": "⚙️ Manutenção de Equipamento",
    "reuniao": "👥 Reunião / Alinhamento",
    "atendimento": "💬 Atendimento ao Cliente",
    "geral": "📅 Tarefa / Compromisso Geral"
}

async def send_whatsapp_to_employee(instance_name: str, employee_phone: str, message_text: str) -> bool:
    try:
        clean_phone = "".join(filter(str.isdigit, employee_phone))
        if not clean_phone:
            return False
        if not clean_phone.startswith("55") and len(clean_phone) in [10, 11]:
            clean_phone = f"55{clean_phone}"

        res = await evolution_service.send_text_message(
            instance_name=instance_name,
            phone_number=clean_phone,
            text=message_text
        )
        return bool(res)
    except Exception as e:
        logger.error(f"Erro ao enviar lembrete no WhatsApp do funcionário ({employee_phone}): {e}")
        return False

async def check_and_send_calendar_reminders():
    async with AsyncSessionLocal() as session:
        now_utc = datetime.utcnow()
        now_brt = now_utc - timedelta(hours=3)

        stmt = (
            select(CalendarEvent)
            .options(selectinload(CalendarEvent.contact))
            .where(
                CalendarEvent.status.in_(["pendente", "em_progresso"]),
                CalendarEvent.notify_whatsapp == True,
                CalendarEvent.employee_phone != None
            )
        )
        res = await session.execute(stmt)
        events = res.scalars().all()

        if not events:
            return

        stmt_w = select(WhatsAppNumber).where(WhatsAppNumber.ativo == True)
        res_w = await session.execute(stmt_w)
        whatsapp_numbers = res_w.scalars().all()

        tenant_instance_map = {}
        for wn in whatsapp_numbers:
            if wn.tenant_id not in tenant_instance_map and wn.instancia_evolution_api:
                tenant_instance_map[wn.tenant_id] = wn.instancia_evolution_api

        for ev in events:
            inst_name = tenant_instance_map.get(ev.tenant_id) or "instancia_vendas"
            emp_name = ev.employee_name or "Colaborador"
            emp_phone = ev.employee_phone
            type_label = EVENT_TYPE_LABELS.get(ev.event_type, "📅 Compromisso")

            client_info = "Não informado"
            if ev.contact:
                client_info = f"{ev.contact.nome or 'Cliente'} ({ev.contact.telefone or ''})".strip()

            event_time_brt = ev.start_time - timedelta(hours=3) if ev.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")
            confirm_url = f"http://localhost:8000/api/v1/calendar/confirm/{ev.confirmation_token}"

            # 1. Immediate creation notification
            if not ev.notified_creation:
                msg = (
                    f"🔔 *NOVO COMPROMISSO AGENDADO - LOJA*\n\n"
                    f"Olá, *{emp_name}*! A loja vinculou um novo compromisso a você:\n\n"
                    f"📌 *Tipo:* {type_label}\n"
                    f"🏷️ *Compromisso:* {ev.title}\n"
                    f"⏰ *Data e Hora:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n"
                    f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                    f"👉 *Por favor, confirme que visualizou clicando no link abaixo:*\n"
                    f"{confirm_url}"
                )
                success = await send_whatsapp_to_employee(inst_name, emp_phone, msg)
                if success:
                    ev.notified_creation = True
                    logger.info(f"Notificação de criação enviada para {emp_name} ({emp_phone}) - Evento #{ev.id}")

            # 2. Morning reminder on the day of the event
            is_same_day = (event_time_brt.date() == now_brt.date())
            if is_same_day and not ev.notified_day_of:
                status_txt = "✅ Confirmado por você" if ev.confirmed_by_employee else f"⚠️ Confirme o recebimento: {confirm_url}"
                msg = (
                    f"☀️ *LEMBRETE: COMPROMISSO HOJE - LOJA*\n\n"
                    f"Olá, *{emp_name}*! Lembramos que você tem um compromisso agendado para hoje:\n\n"
                    f"📌 *Tipo:* {type_label}\n"
                    f"🏷️ *Compromisso:* {ev.title}\n"
                    f"⏰ *Horário:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n"
                    f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                    f"Status: {status_txt}"
                )
                success = await send_whatsapp_to_employee(inst_name, emp_phone, msg)
                if success:
                    ev.notified_day_of = True
                    logger.info(f"Lembrete do dia enviado para {emp_name} ({emp_phone}) - Evento #{ev.id}")

            # 3. Hours before reminder (ex: 2h before)
            hours_before = ev.custom_reminder_hours or 2
            diff_seconds = (ev.start_time - now_utc).total_seconds()
            diff_hours = diff_seconds / 3600.0

            if 0 < diff_hours <= hours_before and not ev.notified_hours_before:
                msg = (
                    f"⏰ *ATENÇÃO: COMPROMISSO EM BREVE (em ~{max(1, int(round(diff_hours)))}h)*\n\n"
                    f"Olá, *{emp_name}*! Faltam poucas horas para o seu compromisso:\n\n"
                    f"📌 *Compromisso:* {ev.title}\n"
                    f"⏰ *Horário:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n\n"
                    f"Por favor, prepare-se para o atendimento/entrega!"
                )
                success = await send_whatsapp_to_employee(inst_name, emp_phone, msg)
                if success:
                    ev.notified_hours_before = True
                    logger.info(f"Lembrete de antecedência enviado para {emp_name} ({emp_phone}) - Evento #{ev.id}")

        await session.commit()

async def start_calendar_reminder_loop(interval_seconds: int = 60):
    logger.info("Calendar WhatsApp reminder background monitor task started.")
    while True:
        try:
            await check_and_send_calendar_reminders()
        except Exception as e:
            logger.error(f"Erro no loop de lembretes do calendário: {e}")
        await asyncio.sleep(interval_seconds)
