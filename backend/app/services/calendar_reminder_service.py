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
    event_id: Optional[int] = None,
    buttons: Optional[List[dict]] = None
) -> bool:
    try:
        clean_phone = "".join(filter(str.isdigit, employee_phone))
        if not clean_phone:
            return False
        if not clean_phone.startswith("55") and len(clean_phone) in [10, 11]:
            clean_phone = f"55{clean_phone}"

        # Fetch live instances from Evolution API to prioritize truly connected ('open') instances
        open_instances = set()
        try:
            ping_data = await evolution_service.ping_server()
            if ping_data.get("success") and ping_data.get("data"):
                for inst_info in ping_data["data"]:
                    if inst_info.get("connectionStatus") == "open":
                        open_instances.add(inst_info.get("name"))
        except Exception as ping_err:
            logger.warning(f"Não foi possível obter instâncias online: {ping_err}")

        # Combine instances, prioritizing open ones that were requested for this department
        ordered_candidates = []
        for inst in instances:
            if inst in open_instances and inst not in ordered_candidates:
                ordered_candidates.append(inst)

        for inst in open_instances:
            if inst and inst not in ordered_candidates:
                ordered_candidates.append(inst)

        for inst in instances:
            if inst and inst not in ordered_candidates:
                ordered_candidates.append(inst)

        if not ordered_candidates:
            ordered_candidates = ["instancia_locacao", "instancia_tecnica"]

        if buttons is None:
            buttons = [
                {
                    "type": "reply",
                    "displayText": "👀 Confirmar Visualização",
                    "id": f"confirm_view_task_{event_id}" if event_id else "confirm_view_task"
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
                if res and not res.get("error") and (res.get("key") or res.get("messageId") or res.get("status") or res.get("success")):
                    logger.info(f"Lembrete com botão enviado com sucesso para funcionário ({clean_phone}) via instância de departamento '{inst_name}'")
                    return True
            except Exception as inst_err:
                logger.warning(f"Tentativa com botão via '{inst_name}' falhou: {inst_err}. Tentando envio direto em texto...")

            # Fallback direct text message
            try:
                full_text = f"*{title}*\n\n{description}\n\n_{footer}_"
                res_txt = await evolution_service.send_text_message(
                    instance_name=inst_name,
                    number=clean_phone,
                    text=full_text
                )
                if res_txt and not res_txt.get("error") and (res_txt.get("key") or res_txt.get("id") or res_txt.get("success")):
                    logger.info(f"Lembrete em texto enviado com sucesso para funcionário ({clean_phone}) via '{inst_name}'")
                    return True
            except Exception as txt_err:
                logger.warning(f"Tentativa em texto via '{inst_name}' falhou: {txt_err}.")

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
                .options(selectinload(CalendarEvent.contact), selectinload(CalendarEvent.conversation))
                .where(CalendarEvent.id == event_id)
            )
            res = await session.execute(stmt)
            ev = res.scalar_one_or_none()

            if not ev or not ev.notify_whatsapp or not ev.employee_phone:
                return

            # Fetch all active department numbers registered for the tenant dynamically
            stmt_w = select(WhatsAppNumber).where(WhatsAppNumber.status == True, WhatsAppNumber.tenant_id == ev.tenant_id)
            res_w = await session.execute(stmt_w)
            wns = res_w.scalars().all()

            preferred_instances = []
            other_instances = []

            # 1. Explicitly selected department instance on event
            if ev.whatsapp_instance:
                preferred_instances.append(ev.whatsapp_instance)
            elif ev.whatsapp_number_id:
                for w in wns:
                    if w.id == ev.whatsapp_number_id and w.instancia_evolution_api:
                        preferred_instances.append(w.instancia_evolution_api)
                        break

            # 2. Dynamic prioritization based on linked conversation or event_type keywords
            type_keywords = {
                "visita_tecnica": ["tecnica", "assistencia", "suporte", "servico"],
                "manutencao": ["tecnica", "manutencao", "assistencia", "oficina"],
                "entrega_gas": ["locacao", "gas", "entrega", "logistica"],
                "vendas": ["vendas", "comercial", "loja", "atendimento"],
                "atendimento": ["atendimento", "vendas", "recepcao"],
                "financeiro": ["financeiro", "cobranca", "contas"]
            }
            keywords = type_keywords.get(ev.event_type, [])

            for w in wns:
                inst = w.instancia_evolution_api
                if not inst:
                    continue
                dept_name_lower = (w.nome_departamento or "").lower()
                inst_lower = inst.lower()

                # If matches the event type keywords
                if any(kw in dept_name_lower or kw in inst_lower for kw in keywords):
                    if inst not in preferred_instances:
                        preferred_instances.append(inst)
                else:
                    if inst not in other_instances and inst not in preferred_instances:
                        other_instances.append(inst)

            ordered_inst_names = preferred_instances + other_instances

            emp_name = ev.employee_name or "Colaborador"
            emp_phone = ev.employee_phone
            type_label = EVENT_TYPE_LABELS.get(ev.event_type, "📅 Atividade")

            client_info = "Não informado"
            if ev.contact:
                client_info = f"{ev.contact.nome or 'Cliente'} ({ev.contact.telefone or ''})".strip()
            elif ev.contact_name or ev.contact_phone:
                client_info = f"{ev.contact_name or 'Cliente'}"
                if ev.contact_phone:
                    client_info += f" ({ev.contact_phone})"

            now_utc = datetime.utcnow()
            now_brt = now_utc - timedelta(hours=3)
            event_time_brt = ev.start_time if ev.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")

            title = "🔔 NOVA ATIVIDADE LANÇADA PARA VOCÊ"
            description = (
                f"Olá, *{emp_name}*! A empresa lançou uma nova atividade atribuída a você:\n\n"
                f"📌 *Tipo:* {type_label}\n"
                f"🏷️ *Atividade:* {ev.title}\n"
                f"⏰ *Data e Hora:* {time_str}\n"
                f"👤 *Cliente:* {client_info}\n"
                f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                f"👉 *Clique no botão abaixo ou responda \"CONFIRMAR\" para confirmar que visualizou:*"
            )
            footer = "Servsolda • Sistema de Tarefas"

            buttons = [
                {
                    "type": "reply",
                    "displayText": "👀 Confirmar Visualização",
                    "id": f"confirm_view_task_{ev.id}"
                }
            ]

            success = await send_whatsapp_to_employee(ordered_inst_names, emp_phone, title, description, footer, event_id=ev.id, buttons=buttons)
            if success:
                ev.notified_creation = True
                await session.commit()
                logger.info(f"Notificação imediata com botão de visualização enviada para {emp_name} ({emp_phone}) - Evento #{ev.id}")
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
                CalendarEvent.notify_whatsapp == True,
                CalendarEvent.employee_phone != None,
                CalendarEvent.status.in_(["pendente", "em_progresso"]),
                CalendarEvent.start_time >= (now_utc - timedelta(days=1))
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
            type_label = EVENT_TYPE_LABELS.get(ev.event_type, "📅 Atividade")

            client_info = "Não informado"
            if ev.contact:
                client_info = f"{ev.contact.nome or 'Cliente'} ({ev.contact.telefone or ''})".strip()

            event_time_brt = ev.start_time if ev.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")

            # 1. Immediate creation notification
            if not ev.notified_creation:
                title = "🔔 NOVA ATIVIDADE LANÇADA PARA VOCÊ"
                description = (
                    f"Olá, *{emp_name}*! A empresa lançou uma nova atividade atribuída a você:\n\n"
                    f"📌 *Tipo:* {type_label}\n"
                    f"🏷️ *Atividade:* {ev.title}\n"
                    f"⏰ *Data e Hora:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n"
                    f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}\n\n"
                    f"👉 *Clique no botão abaixo ou responda \"CONFIRMAR\" para registrar que visualizou:*"
                )
                footer = "Servsolda • Sistema de Tarefas"
                buttons = [
                    {
                        "type": "reply",
                        "displayText": "👀 Confirmar Visualização",
                        "id": f"confirm_view_task_{ev.id}"
                    }
                ]
                success = await send_whatsapp_to_employee(inst_list, emp_phone, title, description, footer, event_id=ev.id, buttons=buttons)
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
