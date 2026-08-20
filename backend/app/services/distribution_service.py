import logging
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import User, WhatsAppNumber, Conversation, ConversationStatus, user_number_access
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("distribution_service")

class DistributionService:
    @staticmethod
    async def assign_least_loaded_attendant(
        db: AsyncSession,
        tenant_id: int,
        whatsapp_number_id: int
    ) -> Optional[User]:
        """
        Distributes conversation to the active human attendant with the smallest open load (least loaded queue).
        Only considers active attendants explicitly assigned to the specific WhatsAppNumber/Department.
        Multi-tier Tie-breaker:
          1. Lowest count of open conversations (open_count asc)
          2. Attendant longest without receiving an active conversation (oldest last interaction asc)
          3. Lowest User ID (user.id asc)
        """
        # 1. Fetch active attendants assigned to this department
        attendants_query = (
            select(User)
            .join(user_number_access, user_number_access.c.user_id == User.id)
            .where(
                User.tenant_id == tenant_id,
                User.status == True,
                user_number_access.c.whatsapp_number_id == whatsapp_number_id
            )
            .order_by(User.id.asc())
        )
        res = await db.execute(attendants_query)
        eligible_users = res.scalars().all()

        if not eligible_users:
            logger.info(f"No active attendants found with access to department {whatsapp_number_id} in tenant {tenant_id}.")
            return None

        # 2. Count active open conversations & last interaction per eligible attendant
        eligible_user_ids = [u.id for u in eligible_users]
        load_query = (
            select(
                Conversation.assigned_user_id,
                func.count(Conversation.id).label("open_count"),
                func.max(Conversation.ultima_interacao_em).label("last_interaction")
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.assigned_user_id.in_(eligible_user_ids),
                Conversation.status.in_([
                    ConversationStatus.COM_HUMANO,
                    ConversationStatus.AGUARDANDO_ATENDENTE
                ])
            )
            .group_by(Conversation.assigned_user_id)
        )
        load_res = await db.execute(load_query)
        # load_stats: {user_id: (open_count, last_interaction_datetime)}
        load_stats = {row[0]: (row[1], row[2]) for row in load_res.all()}

        # 3. Sort eligible users by (open_count ASC, last_interaction ASC, user.id ASC)
        min_date = datetime.min
        sorted_candidates = sorted(
            eligible_users,
            key=lambda u: (
                load_stats.get(u.id, (0, min_date))[0],  # 1º Menor Carga
                load_stats.get(u.id, (0, min_date))[1] or min_date,  # 2º Mais antigo ocioso
                u.id  # 3º Menor ID
            )
        )

        best_user = sorted_candidates[0] if sorted_candidates else None
        if best_user:
            cur_load = load_stats.get(best_user.id, (0, min_date))[0]
            logger.info(f"Least load distribution: Dept {whatsapp_number_id} -> Attendant #{best_user.id} ({best_user.nome}) [Open Load: {cur_load}]")
        return best_user

    @staticmethod
    async def process_pending_queue(
        db: AsyncSession,
        tenant_id: int,
        whatsapp_number_id: Optional[int] = None
    ) -> List[Conversation]:
        """
        Drains conversations in AGUARDANDO_ATENDENTE and assigns them FIFO to newly available attendants.
        Called whenever an attendant closes a conversation, logs in, or in periodic queue background tasks.
        """
        query = (
            select(Conversation)
            .options(
                selectinload(Conversation.contact),
                selectinload(Conversation.whatsapp_number)
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.status == ConversationStatus.AGUARDANDO_ATENDENTE,
                Conversation.assigned_user_id.is_(None)
            )
            .order_by(Conversation.criado_em.asc())  # FIFO
        )
        if whatsapp_number_id:
            query = query.where(Conversation.whatsapp_number_id == whatsapp_number_id)

        res = await db.execute(query)
        pending_convs = res.scalars().all()

        assigned_convs = []
        for conv in pending_convs:
            attendant = await DistributionService.assign_least_loaded_attendant(
                db=db,
                tenant_id=tenant_id,
                whatsapp_number_id=conv.whatsapp_number_id
            )
            if attendant:
                conv.assigned_user_id = attendant.id
                conv.status = ConversationStatus.COM_HUMANO
                conv.ultima_interacao_em = datetime.utcnow()
                await db.flush()  # Immediately flush state so next iteration calculates re-balanced load accurately!
                assigned_convs.append(conv)
                logger.info(f"Auto-assigned pending conversation #{conv.id} to Attendant #{attendant.id} ({attendant.nome}).")

                # Broadcast assignment to attendant and department
                try:
                    await ws_manager.broadcast_to_department(
                        tenant_id=tenant_id,
                        whatsapp_number_id=conv.whatsapp_number_id,
                        message_data={
                            "type": "CONVERSATION_ASSIGNED",
                            "conversation_id": conv.id,
                            "assigned_user_id": attendant.id,
                            "assigned_user_name": attendant.nome,
                            "department": conv.whatsapp_number.nome_departamento if conv.whatsapp_number else "",
                            "status": "com_humano"
                        }
                    )
                except Exception as ws_err:
                    logger.warning(f"Failed to broadcast assignment WebSocket: {ws_err}")

        if assigned_convs:
            await db.commit()

        return assigned_convs

distribution_service = DistributionService()
