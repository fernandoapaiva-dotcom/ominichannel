import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.models import (
    Conversation, ConversationStatus, Message, MessageSender, MessageType,
    WhatsAppNumber, Tenant
)
from app.services.evolution_service import evolution_service
from app.services.gdrive_service import gdrive_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("business_hours_service")

# Timezone America/Sao_Paulo (Brasília)
BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

class BusinessHoursService:
    @staticmethod
    def get_brasilia_now() -> datetime:
        """Returns the current datetime in America/Sao_Paulo timezone."""
        return datetime.now(BRASILIA_TZ)

    @staticmethod
    def is_within_business_hours(dt: Optional[datetime] = None) -> bool:
        """
        Evaluates whether the given datetime (or now) is within commercial business hours.
        Rules (Seção 1 e 3):
        - Timezone: America/Sao_Paulo (Brasília)
        - Business Days: Monday (0) to Friday (4).
        - SATURDAY (5) IS NOT A BUSINESS DAY.
        - SUNDAY (6) IS NOT A BUSINESS DAY.
        - Commercial Hours: 08:00:00 to 18:00:00.
        """
        if dt is None:
            local_dt = datetime.now(BRASILIA_TZ)
        else:
            if dt.tzinfo is None:
                from datetime import timezone
                local_dt = dt.replace(tzinfo=timezone.utc).astimezone(BRASILIA_TZ)
            else:
                local_dt = dt.astimezone(BRASILIA_TZ)

        weekday = local_dt.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
        
        # Sábado e Domingo NÃO são dias úteis
        if weekday >= 5:
            return False

        # Horário comercial: 08:00 às 18:00
        current_time = local_dt.time()
        start_time = time(8, 0, 0)
        end_time = time(18, 0, 0)

        return start_time <= current_time < end_time

    @staticmethod
    def get_out_of_hours_message(customer_name: str, protocol_number: str) -> str:
        """
        Returns the official standard out-of-office message (Seção 3).
        """
        from app.services.gemini_service import sanitize_customer_name
        clean_name = sanitize_customer_name(customer_name)
        return (
            f"🌙 *ATENDIMENTO FORA DO EXPEDIENTE*\n\n"
            f"Olá, {clean_name}! No momento nossa equipe humana está fora do horário comercial.\n\n"
            f"⏰ *Horário de Atendimento da Servweld:*\n"
            f"• Segunda a Sexta-feira: das 08:00 às 18:00 (Horário de Brasília)\n"
            f"• Sábados, Domingos e Feriados: Fechado\n\n"
            f"🔢 *Protocolo do seu chamado:* {protocol_number}\n\n"
            f"Sua mensagem foi registrada com sucesso! Retornaremos o seu atendimento no próximo dia útil a partir das 08:00."
        )

    @staticmethod
    def get_shift_closing_message(protocol_number: str) -> str:
        """
        Returns the shift closing message sent at 18:00 (Seção 4 - Job das 18:00).
        """
        return (
            f"⏰ *ENCERRAMENTO DO EXPEDIENTE COMERCIAL (18:00)*\n\n"
            f"Informamos que nosso expediente de atendimento encerrou às 18:00.\n\n"
            f"O seu atendimento (Protocolo: {protocol_number}) foi registrado e será retomado com prioridade pela nossa equipe no próximo dia útil a partir das 08:00.\n\n"
            f"Agradecemos a sua compreensão e desejamos um ótimo descanso!"
        )

    async def execute_18h_shift_closing_job(self) -> Dict[str, Any]:
        """
        Job das 18:00 (Horário de Brasília):
        - Scans all ongoing conversations in COM_HUMANO or AGUARDANDO_ATENDENTE.
        - Dispatches the shift closing notice to the customer on WhatsApp.
        - Adds system audit message in timeline.
        - Updates status to ENCERRADA_FORA_EXPEDIENTE.
        - Exports JSON backup.
        """
        now_br = self.get_brasilia_now()
        logger.info(f"[JOB 18:00] Iniciando encerramento de expediente comercial ({now_br.strftime('%Y-%m-%d %H:%M:%S %Z')})...")

        closed_count = 0
        async with AsyncSessionLocal() as db:
            try:
                stmt = (
                    select(Conversation)
                    .options(
                        selectinload(Conversation.contact),
                        selectinload(Conversation.whatsapp_number),
                        selectinload(Conversation.messages)
                    )
                    .where(
                        Conversation.status.in_([
                            ConversationStatus.COM_HUMANO,
                            ConversationStatus.AGUARDANDO_ATENDENTE
                        ])
                    )
                )
                res = await db.execute(stmt)
                active_convs = res.scalars().all()

                for conv in active_convs:
                    # Skip WhatsApp groups
                    if conv.contact and ("@g.us" in str(conv.contact.telefone) or len(str(conv.contact.telefone)) > 15):
                        continue

                    # CRITICAL SAFEGUARD: Closing message MUST ONLY be sent to conversations with an ACTIVE OPEN PROTOCOL!
                    # NEVER send closing messages to migrated chats, historical WhatsApp conversations, or chats without an open protocol!
                    if not conv.protocol_number or conv.protocol_number in ["S/N", "None", "", None]:
                        continue

                    extra = dict(conv.dados_adicionais or {})
                    if extra.get("is_migrated") or extra.get("migrated_from_whatsapp"):
                        continue

                    # Also ensure the conversation was active TODAY (within the last 12 hours)
                    if not conv.ultima_interacao_em or (datetime.utcnow() - conv.ultima_interacao_em).total_seconds() > 12 * 3600:
                        continue

                    proto = conv.protocol_number
                    closing_text = self.get_shift_closing_message(proto)

                    # 1. Send WhatsApp message to customer
                    if conv.contact and conv.whatsapp_number and conv.whatsapp_number.instancia_evolution_api:
                        try:
                            await evolution_service.send_text_message(
                                instance_name=conv.whatsapp_number.instancia_evolution_api,
                                number=conv.contact.telefone,
                                text=closing_text
                            )
                        except Exception as send_err:
                            logger.warning(f"Error sending 18h closing message to conversation #{conv.id}: {send_err}")

                    # 2. Add System Message in timeline
                    sys_msg = Message(
                        conversation_id=conv.id,
                        remetente="sistema",
                        conteudo=f"⏰ Atendimento pausado/encerrado pelo fim de expediente comercial das 18:00 (Horário de Brasília).",
                        tipo=MessageType.TEXTO,
                        timestamp=datetime.utcnow()
                    )
                    db.add(sys_msg)

                    # 3. Update Conversation Status
                    conv.status = ConversationStatus.ENCERRADA_FORA_EXPEDIENTE
                    conv.ultima_interacao_em = datetime.utcnow()
                    closed_count += 1

                    # 4. JSON Backup
                    try:
                        conv_export = {
                            "conversation_id": conv.id,
                            "tenant_id": conv.tenant_id,
                            "contact_phone": conv.contact.telefone if conv.contact else "",
                            "contact_name": conv.contact.nome if conv.contact else "",
                            "protocol_number": conv.protocol_number,
                            "status": "encerrada_fora_expediente",
                            "criado_em": conv.criado_em,
                            "ultima_interacao_em": conv.ultima_interacao_em,
                            "messages": [
                                {
                                    "id": m.id,
                                    "remetente": getattr(m.remetente, 'value', str(m.remetente)),
                                    "conteudo": m.conteudo,
                                    "tipo": getattr(m.tipo, 'value', str(m.tipo)),
                                    "timestamp": m.timestamp.isoformat() if m.timestamp else None
                                }
                                for m in (conv.messages or [])
                            ]
                        }
                        await gdrive_service.sync_conversation_to_drive(
                            tenant_drive_folder_id=None,
                            conversation_id=conv.id,
                            contact_phone=conv_export["contact_phone"],
                            conversation_data=conv_export
                        )
                    except Exception as b_err:
                        logger.warning(f"Error exporting backup on 18h shift closing: {b_err}")

                    # 5. Broadcast WS update
                    try:
                        await ws_manager.broadcast_to_department(
                            tenant_id=conv.tenant_id,
                            whatsapp_number_id=conv.whatsapp_number_id,
                            message_data={
                                "type": "NEW_MESSAGE",
                                "conversation_id": conv.id,
                                "status_updated": conv.status.value
                            }
                        )
                    except Exception:
                        pass

                await db.commit()
                logger.info(f"[JOB 18:00] Concluído com sucesso! {closed_count} atendimentos pausados/encerrados pelo fim do expediente.")
            except Exception as e:
                logger.error(f"[JOB 18:00] Erro ao executar job das 18:00: {e}")

        return {"status": "success", "closed_conversations": closed_count}

    @staticmethod
    def get_shift_opening_message(protocol_number: str) -> str:
        """
        Returns the shift reopening message sent at 08:00 on business days.
        """
        return (
            f"🌅 *INÍCIO DO EXPEDIENTE COMERCIAL (08:00)*\n\n"
            f"Bom dia! Nosso expediente comercial foi iniciado.\n\n"
            f"Estamos retomando o seu atendimento (Protocolo: {protocol_number}) agora mesmo com prioridade na nossa fila. Um de nossos especialistas entrará em contato em instantes!"
        )

    async def execute_08h_shift_opening_job(self) -> Dict[str, Any]:
        """
        Job das 08:00 (Horário de Brasília):
        - Scans conversations in ENCERRADA_FORA_EXPEDIENTE.
        - Automatically reopens them into AGUARDANDO_ATENDENTE.
        - Dispatches morning resumption notice to customer on WhatsApp.
        - Adds system audit message in timeline.
        - Drains pending queue via distribution_service.
        """
        from app.services.distribution_service import distribution_service
        now_br = self.get_brasilia_now()
        logger.info(f"[JOB 08:00] Retomando atendimentos pausados da noite anterior ({now_br.strftime('%Y-%m-%d %H:%M:%S %Z')})...")

        reopened_count = 0
        async with AsyncSessionLocal() as db:
            try:
                stmt = (
                    select(Conversation)
                    .options(
                        selectinload(Conversation.contact),
                        selectinload(Conversation.whatsapp_number)
                    )
                    .where(
                        Conversation.status == ConversationStatus.ENCERRADA_FORA_EXPEDIENTE
                    )
                )
                res = await db.execute(stmt)
                convs = res.scalars().all()

                for conv in convs:
                    if not conv.protocol_number or conv.protocol_number in ["S/N", "None", "", None]:
                        continue

                    extra = dict(conv.dados_adicionais or {})
                    if extra.get("is_migrated") or extra.get("migrated_from_whatsapp"):
                        continue

                    proto = conv.protocol_number
                    morning_text = self.get_shift_opening_message(proto)

                    # 1. Send WhatsApp message
                    if conv.contact and conv.whatsapp_number and conv.whatsapp_number.instancia_evolution_api:
                        try:
                            await evolution_service.send_text_message(
                                instance_name=conv.whatsapp_number.instancia_evolution_api,
                                number=conv.contact.telefone,
                                text=morning_text
                            )
                        except Exception as send_err:
                            logger.warning(f"Error sending 08h resumption message to #{conv.id}: {send_err}")

                    # 2. Add System Message
                    sys_msg = Message(
                        conversation_id=conv.id,
                        remetente="sistema",
                        conteudo=f"🌅 Atendimento retomado automaticamente pelo início de expediente comercial das 08:00 (Horário de Brasília).",
                        tipo=MessageType.TEXTO,
                        timestamp=datetime.utcnow()
                    )
                    db.add(sys_msg)

                    # 3. Put in AGUARDANDO_ATENDENTE
                    conv.status = ConversationStatus.AGUARDANDO_ATENDENTE
                    conv.assigned_user_id = None
                    conv.ultima_interacao_em = datetime.utcnow()
                    reopened_count += 1

                await db.commit()

                # 4. Drain and auto-assign pending queue across tenants/departments
                departments_stmt = select(WhatsAppNumber.tenant_id, WhatsAppNumber.id).where(WhatsAppNumber.status == True)
                d_res = await db.execute(departments_stmt)
                for t_id, wn_id in d_res.all():
                    try:
                        await distribution_service.process_pending_queue(db, t_id, wn_id)
                    except Exception:
                        pass

                logger.info(f"[JOB 08:00] Concluído com sucesso! {reopened_count} atendimentos retomados e enfileirados.")
            except Exception as e:
                logger.error(f"[JOB 08:00] Erro ao executar job das 08:00: {e}")

        return {"status": "success", "reopened_conversations": reopened_count}

business_hours_service = BusinessHoursService()

async def start_business_hours_scheduler_loop(check_interval_seconds: int = 30):
    """
    Continuous background loop that checks Brasília time (America/Sao_Paulo).
    - Exactly at 08:00 on business days (Mon-Fri), triggers the 08:00 shift opening resumption job.
    - Exactly at 18:00 on business days (Mon-Fri), triggers the 18:00 shift closing job.
    """
    last_executed_18h: Optional[str] = None
    last_executed_08h: Optional[str] = None
    logger.info("Business hours (08:00 / 18:00) scheduler background loop started.")

    while True:
        try:
            now_br = BusinessHoursService.get_brasilia_now()
            today_str = now_br.strftime("%Y-%m-%d")
            weekday = now_br.weekday()  # 0=Mon ... 4=Fri (Sat=5, Sun=6)

            if weekday < 5:
                # 08:00 Morning Resumption Job
                if now_br.hour == 8 and now_br.minute == 0:
                    if last_executed_08h != today_str:
                        logger.info(f"[SCHEDULER 08:00] Triggering 08:00 morning shift opening job for {today_str}...")
                        await business_hours_service.execute_08h_shift_opening_job()
                        last_executed_08h = today_str

                # 18:00 Evening Shift Closing Job
                if now_br.hour == 18 and now_br.minute == 0:
                    if last_executed_18h != today_str:
                        logger.info(f"[SCHEDULER 18:00] Triggering 18:00 evening shift closing job for {today_str}...")
                        await business_hours_service.execute_18h_shift_closing_job()
                        last_executed_18h = today_str
        except Exception as e:
            logger.error(f"Error in business hours scheduler loop: {e}")

        await asyncio.sleep(check_interval_seconds)


