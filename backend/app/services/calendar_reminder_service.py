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
    footer: str,
    event_id: Optional[int] = None,
    buttons: Optional[List[dict]] = None
) -> bool:
    try:
        clean_phone = "".join(filter(str.isdigit, employee_phone))
        if not clean_phone:
            return False
        if not clean_phone.startswith("55") and len(clean_phone) in [10, 11]:
            clean_phone = f"55{clean_phone}"

        # If specific instance(s) provided, strictly use them without falling back to other unselected departments
        candidates = [inst for inst in instances if inst]
        if not candidates:
            candidates = ["instancia_locacao", "instancia_tecnica", "instancia_vendas"]

        for inst_name in candidates:
            try:
                full_card = f"*{title}*\n\n{description}\n\n_{footer}_"
                res_txt = await evolution_service.send_text_message(
                    instance_name=inst_name,
                    number=clean_phone,
                    text=full_card
                )

                if res_txt and not res_txt.get("error"):
                    logger.info(f"Mensagem de tarefa enviada com sucesso para funcionário ({clean_phone}) via '{inst_name}'")
                    return True
            except Exception as inst_err:
                logger.warning(f"Tentativa via '{inst_name}' falhou: {inst_err}.")

        return False
    except Exception as e:
        logger.error(f"Erro ao enviar lembrete no WhatsApp do funcionário ({employee_phone}): {e}")
        return False

async def send_immediate_creation_notification(event_id: int):
    """Sends immediate WhatsApp notification with complete task details to all assigned employees upon event creation."""
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

            # Fetch active department numbers registered for the tenant
            stmt_w = select(WhatsAppNumber).where(WhatsAppNumber.status == True, WhatsAppNumber.tenant_id == ev.tenant_id)
            res_w = await session.execute(stmt_w)
            wns = res_w.scalars().all()

            # 1. Strictly resolve selected department instance on event
            ordered_inst_names = []
            if ev.whatsapp_instance:
                ordered_inst_names = [ev.whatsapp_instance]
            elif ev.whatsapp_number_id:
                for w in wns:
                    if w.id == ev.whatsapp_number_id and w.instancia_evolution_api:
                        ordered_inst_names = [w.instancia_evolution_api]
                        break

            # 2. If no department was explicitly chosen, use smart fallback based on event type keywords
            if not ordered_inst_names:
                type_keywords = {
                    "visita_tecnica": ["tecnica", "assistencia", "suporte", "servico"],
                    "manutencao": ["tecnica", "manutencao", "assistencia", "oficina"],
                    "entrega_gas": ["locacao", "gas", "entrega", "logistica"],
                    "vendas": ["vendas", "comercial", "loja", "atendimento"],
                    "atendimento": ["atendimento", "vendas", "recepcao"],
                    "financeiro": ["financeiro", "cobranca", "contas"]
                }
                keywords = type_keywords.get(ev.event_type, [])

                preferred_instances = []
                other_instances = []
                for w in wns:
                    inst = w.instancia_evolution_api
                    if not inst:
                        continue
                    dept_name_lower = (w.nome_departamento or "").lower()
                    inst_lower = inst.lower()

                    if any(kw in dept_name_lower or kw in inst_lower for kw in keywords):
                        if inst not in preferred_instances:
                            preferred_instances.append(inst)
                    else:
                        if inst not in other_instances and inst not in preferred_instances:
                            other_instances.append(inst)

                ordered_inst_names = preferred_instances or other_instances

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

            phone_list = [p.strip() for p in (ev.employee_phone or "").replace(';', ',').replace('/', ',').split(',') if p.strip()]
            name_list = [n.strip() for n in (ev.employee_name or "").replace(';', ',').replace('/', ',').split(',') if n.strip()]

            sent_any = False
            for idx, raw_phone in enumerate(phone_list):
                emp_name = name_list[idx] if idx < len(name_list) else (name_list[0] if name_list else "Colaborador")
                title = "🔔 NOVA ATIVIDADE AGENDADA"
                description = (
                    f"Olá, *{emp_name}*! Uma nova atividade foi atribuída a você na agenda:\n\n"
                    f"📌 *Tipo:* {type_label}\n"
                    f"🏷️ *Atividade:* {ev.title}\n"
                    f"⏰ *Data e Hora:* {time_str}\n"
                    f"👤 *Cliente:* {client_info}\n"
                    f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}"
                )
                footer = "Servsolda • Sistema de Tarefas"

                success = await send_whatsapp_to_employee(ordered_inst_names, raw_phone, title, description, footer, event_id=ev.id)
                if success:
                    sent_any = True
                    logger.info(f"Notificação de tarefa enviada para {emp_name} ({raw_phone}) via {ordered_inst_names} - Evento #{ev.id}")

            if sent_any:
                ev.notified_creation = True
                await session.commit()
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

        wn_id_map = {wn.id: wn.instancia_evolution_api for wn in whatsapp_numbers if wn.instancia_evolution_api}
        tenant_instance_map = {}
        for wn in whatsapp_numbers:
            if wn.tenant_id not in tenant_instance_map:
                tenant_instance_map[wn.tenant_id] = []
            if wn.instancia_evolution_api:
                tenant_instance_map[wn.tenant_id].append(wn.instancia_evolution_api)

        for ev in events:
            # Strictly select instance if chosen on event
            inst_list = []
            if ev.whatsapp_instance:
                inst_list = [ev.whatsapp_instance]
            elif ev.whatsapp_number_id and ev.whatsapp_number_id in wn_id_map:
                inst_list = [wn_id_map[ev.whatsapp_number_id]]
            else:
                inst_list = tenant_instance_map.get(ev.tenant_id, [])

            type_label = EVENT_TYPE_LABELS.get(ev.event_type, "📅 Atividade")

            client_info = "Não informado"
            if ev.contact:
                client_info = f"{ev.contact.nome or 'Cliente'} ({ev.contact.telefone or ''})".strip()

            event_time_brt = ev.start_time if ev.start_time else now_brt
            time_str = event_time_brt.strftime("%d/%m/%Y às %H:%M")

            phone_list = [p.strip() for p in (ev.employee_phone or "").replace(';', ',').replace('/', ',').split(',') if p.strip()]
            name_list = [n.strip() for n in (ev.employee_name or "").replace(';', ',').replace('/', ',').split(',') if n.strip()]

            # 1. Immediate creation notification fallback
            if not ev.notified_creation:
                sent_any = False
                for idx, raw_phone in enumerate(phone_list):
                    emp_name = name_list[idx] if idx < len(name_list) else (name_list[0] if name_list else "Colaborador")
                    title = "🔔 NOVA ATIVIDADE AGENDADA"
                    description = (
                        f"Olá, *{emp_name}*! Uma nova atividade foi atribuída a você na agenda:\n\n"
                        f"📌 *Tipo:* {type_label}\n"
                        f"🏷️ *Atividade:* {ev.title}\n"
                        f"⏰ *Data e Hora:* {time_str}\n"
                        f"👤 *Cliente:* {client_info}\n"
                        f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}"
                    )
                    footer = "Servsolda • Sistema de Tarefas"
                    if await send_whatsapp_to_employee(inst_list, raw_phone, title, description, footer, event_id=ev.id):
                        sent_any = True
                if sent_any:
                    ev.notified_creation = True

            # 2. Morning reminder on the day of the event
            is_same_day = (event_time_brt.date() == now_brt.date())
            if is_same_day and not ev.notified_day_of:
                sent_any = False
                for idx, raw_phone in enumerate(phone_list):
                    emp_name = name_list[idx] if idx < len(name_list) else (name_list[0] if name_list else "Colaborador")
                    title = "☀️ LEMBRETE: COMPROMISSO HOJE"
                    description = (
                        f"Olá, *{emp_name}*! Lembramos que você tem um compromisso agendado para hoje:\n\n"
                        f"📌 *Tipo:* {type_label}\n"
                        f"🏷️ *Compromisso:* {ev.title}\n"
                        f"⏰ *Horário:* {time_str}\n"
                        f"👤 *Cliente:* {client_info}\n"
                        f"📝 *Detalhes:* {ev.description or 'Sem observações adicionais.'}"
                    )
                    footer = "Servsolda • Sistema de Tarefas"
                    if await send_whatsapp_to_employee(inst_list, raw_phone, title, description, footer, event_id=ev.id):
                        sent_any = True
                if sent_any:
                    ev.notified_day_of = True

            # 3. Hours before reminder (ex: 2h before)
            hours_before = ev.custom_reminder_hours or 2
            diff_seconds = (ev.start_time - now_utc).total_seconds()
            diff_hours = diff_seconds / 3600.0

            if 0 < diff_hours <= hours_before and not ev.notified_hours_before:
                sent_any = False
                for idx, raw_phone in enumerate(phone_list):
                    emp_name = name_list[idx] if idx < len(name_list) else (name_list[0] if name_list else "Colaborador")
                    title = f"⏰ ATENÇÃO: COMPROMISSO EM BREVE (~{max(1, int(round(diff_hours)))}h)"
                    description = (
                        f"Olá, *{emp_name}*! Faltam poucas horas para o seu compromisso:\n\n"
                        f"📌 *Compromisso:* {ev.title}\n"
                        f"⏰ *Horário:* {time_str}\n"
                        f"👤 *Cliente:* {client_info}\n\n"
                        f"Por favor, prepare-se para o atendimento/entrega!"
                    )
                    footer = "Servsolda • Sistema de Tarefas"
                    if await send_whatsapp_to_employee(inst_list, raw_phone, title, description, footer, event_id=ev.id):
                        sent_any = True
                if sent_any:
                    ev.notified_hours_before = True

        await session.commit()

async def start_calendar_reminder_loop(interval_seconds: int = 60):
    logger.info("Calendar WhatsApp reminder background monitor task started.")
    while True:
        try:
            await check_and_send_calendar_reminders()
        except Exception as e:
            logger.error(f"Erro no loop de lembretes do calendário: {e}")
        await asyncio.sleep(interval_seconds)
