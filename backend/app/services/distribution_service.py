import logging
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import User, WhatsAppNumber, Conversation, ConversationStatus, user_number_access

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
        Tie-breaker: Attendant with lowest open count, followed by lowest user ID.
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

        # 2. Count active open conversations per eligible attendant
        eligible_user_ids = [u.id for u in eligible_users]
        load_query = (
            select(
                Conversation.assigned_user_id,
                func.count(Conversation.id).label("open_count")
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
        load_stats = {row[0]: row[1] for row in load_res.all()}

        # 3. Find attendant with minimum load
        best_user = None
        min_load = float("inf")

        for user in eligible_users:
            open_count = load_stats.get(user.id, 0)
            if open_count < min_load:
                min_load = open_count
                best_user = user

        if best_user:
            logger.info(f"Least load distribution: Dept {whatsapp_number_id} -> Attendant #{best_user.id} ({best_user.nome}) [Current Open Load: {min_load}]")
        return best_user

distribution_service = DistributionService()
