import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List
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

async def send_whatsapp_to_employee(
    instances: List[str],
    employee_phone: str,
    title: str,
    description: str,
    footer: str = "Servsolda • Sistema de Tarefas",
    event_id: Optional[int] = None
) -> bool:
    try:
        clean_phone = "".join(filter(str.isdigit, employee_phone))
        if not clean_phone:
            return False
        if not clean_phone.startswith("55") and len(clean_phone) in [10, 11]:
            clean_phone = f"55{clean_phone}"

        # Fetch live instances from Evolution API to prioritize truly connected ('open') instances
        open_instances = []
        try:
            ping_data = await evolution_service.ping_server()
            if ping_data.get("success") and ping_data.get("data"):
                for inst_info in ping_data["data"]:
                    if inst_info.get("connectionStatus") == "open":
                        open_instances.append(inst_info.get("name"))
        except Exception as ping_err:
            logger.warning(f"Não foi possível obter instâncias online: {ping_err}")

        # Combine instances, prioritizing open ones
        ordered_candidates = []
        for inst in open_instances:
            if inst and inst not in ordered_candidates:
                ordered_candidates.append(inst)

        for inst in instances:
            if inst and inst not in ordered_candidates:
                ordered_candidates.append(inst)

        for default_inst in ["instancia_locacao", "instancia_vendas", "instancia_tecnica", "instancia_financeiro"]:
            if default_inst not in ordered_candidates:
                ordered_candidates.append(default_inst)

        buttons = [
            {
                "type": "reply",
                "displayText": "✅ Confirmar Visualização",
                "id": f"confirm_task_{event_id}" if event_id else "confirm_task"
            }
        ]

        for inst_name in ordered_candidates:
            try:
                res = await evolution_service.send_button_message(
                    instance_name=inst_name,
                    number=clean_phone,
                    title=title,
                    description=description,
                    footer=footer,
                    buttons=buttons
                )
                if res and not res.get("error") and (res.get("key") or res.get("messageId") or res.get("success")):
                    logger.info(f"Lembrete com botão enviado com sucesso para funcionário ({clean_phone}) via instância '{inst_name}'")
                    return True
            except Exception as inst_err:
                logger.warning(f"Tentativa via '{inst_name}' falhou: {inst_err}. Tentando próxima instância...")

        return False
    except Exception as e:
        logger.error(f"Erro ao enviar lembrete no WhatsApp do funcionário ({employee_phone}): {e}")
        return False

async def send_immediate_creation_notification(event_id: int):
    """Sends immediate WhatsApp notification with interactive button to the assigned employee upon event creation."""
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(CalendarEvent)
                .options(selectinload(CalendarEvent.contact))
                .where(CalendarEvent.id == event_id)
            )
            res = await session.execute(stmt)
            ev = res.scalar_one_or_none()

            if not ev or not ev.notify_whatsapp or not ev.employee_phone:
                return

            stmt_w = select(WhatsAppNumber).where(WhatsAppNumber.status == True, WhatsAppNumber.tenant_id == ev.tenant_id)
            res_w = await session.execute(stmt_w)
            wns = res_w.scalars().all()
            inst_names = [w.instancia_evolution_api for w in wns if w.instancia_evolution_api]

            emp_name = ev.employee_name or "Colaborador"
            emp_phone = ev.employee_phone
            type_label = EVENT_TYPE_LABELS.get(ev.event_type, "📅 Compromisso")

            client_info = "Não informado"
            if ev.contact:
                client_info = f"{ev.contact.nome or 'Cliente'} ({ev.contact.telefone or ''})".strip()

            now_utc = datetime.utcnow()
            now_brt = now_utc - timedelta(hours=3)
            event_time_brt = ev.start_time - timedelta(hours=3) if ev.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")

            title = "🔔 NOVO COMPROMISSO AGENDADO"
            description = (
                f"Olá, *{emp_name}*! A loja vinculou um novo compromisso a você:\n\n"
                f"📌 *Tipo:* {type_label}\n"
                f"🏷️ *Compromisso:* {ev.title}\n"
                f"⏰ *Data e Hora:* {time_str}\n"
                f"👤 *Cliente:* {client_info}\n"
                f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                f"👉 *Clique no botão abaixo para confirmar que visualizou:*"
            )
            footer = "Servsolda • Sistema de Tarefas"

            success = await send_whatsapp_to_employee(inst_names, emp_phone, title, description, footer, event_id=ev.id)
            if success:
                ev.notified_creation = True
                await session.commit()
                logger.info(f"Notificação imediata com botão enviada para {emp_name} ({emp_phone}) - Evento #{ev.id}")
    except Exception as e:
        logger.error(f"Erro ao enviar notificação imediata do evento #{event_id}: {e}")

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

        stmt_w = select(WhatsAppNumber).where(WhatsAppNumber.status == True)
        res_w = await session.execute(stmt_w)
        whatsapp_numbers = res_w.scalars().all()

        tenant_instance_map = {}
        for wn in whatsapp_numbers:
            if wn.tenant_id not in tenant_instance_map:
                tenant_instance_map[wn.tenant_id] = []
            if wn.instancia_evolution_api:
                tenant_instance_map[wn.tenant_id].append(wn.instancia_evolution_api)

        for ev in events:
            inst_list = tenant_instance_map.get(ev.tenant_id, [])
            emp_name = ev.employee_name or "Colaborador"
            emp_phone = ev.employee_phone
            type_label = EVENT_TYPE_LABELS.get(ev.event_type, "📅 Compromisso")

            client_info = "Não informado"
            if ev.contact:
                client_info = f"{ev.contact.nome or 'Cliente'} ({ev.contact.telefone or ''})".strip()

            event_time_brt = ev.start_time - timedelta(hours=3) if ev.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")

            # 1. Immediate creation notification
            if not ev.notified_creation:
                title = "🔔 NOVO COMPROMISSO AGENDADO"
                description = (
                    f"Olá, *{emp_name}*! A loja vinculou um novo compromisso a você:\n\n"
                    f"📌 *Tipo:* {type_label}\n"
                    f"🏷️ *Compromisso:* {ev.title}\n"
                    f"⏰ *Data e Hora:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n"
                    f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                    f"👉 *Clique no botão abaixo para confirmar que visualizou:*"
                )
                footer = "Servsolda • Sistema de Tarefas"
                success = await send_whatsapp_to_employee(inst_list, emp_phone, title, description, footer, event_id=ev.id)
                if success:
                    ev.notified_creation = True
                    logger.info(f"Notificação de criação enviada para {emp_name} ({emp_phone}) - Evento #{ev.id}")

            # 2. Morning reminder on the day of the event
            is_same_day = (event_time_brt.date() == now_brt.date())
            if is_same_day and not ev.notified_day_of:
                status_txt = "✅ Confirmado por você" if ev.confirmed_by_employee else "⏳ Aguardando sua confirmação"
                title = "☀️ LEMBRETE: COMPROMISSO HOJE"
                description = (
                    f"Olá, *{emp_name}*! Lembramos que você tem um compromisso agendado para hoje:\n\n"
                    f"📌 *Tipo:* {type_label}\n"
                    f"🏷️ *Compromisso:* {ev.title}\n"
                    f"⏰ *Horário:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n"
                    f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                    f"Status: {status_txt}"
                )
                footer = "Servsolda • Sistema de Tarefas"
                success = await send_whatsapp_to_employee(inst_list, emp_phone, title, description, footer, event_id=ev.id)
                if success:
                    ev.notified_day_of = True
                    logger.info(f"Lembrete do dia enviado para {emp_name} ({emp_phone}) - Evento #{ev.id}")

            # 3. Hours before reminder (ex: 2h before)
            hours_before = ev.custom_reminder_hours or 2
            diff_seconds = (ev.start_time - now_utc).total_seconds()
            diff_hours = diff_seconds / 3600.0

            if 0 < diff_hours <= hours_before and not ev.notified_hours_before:
                title = f"⏰ ATENÇÃO: COMPROMISSO EM BREVE (~{max(1, int(round(diff_hours)))}h)"
                description = (
                    f"Olá, *{emp_name}*! Faltam poucas horas para o seu compromisso:\n\n"
                    f"📌 *Compromisso:* {ev.title}\n"
                    f"⏰ *Horário:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n\n"
                    f"Por favor, prepare-se para o atendimento/entrega!"
                )
                footer = "Servsolda • Sistema de Tarefas"
                success = await send_whatsapp_to_employee(inst_list, emp_phone, title, description, footer, event_id=ev.id)
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
