import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import Conversation

async def generate_daily_protocol(db: AsyncSession, tenant_id: int) -> str:
    """
    Generates a sequential daily protocol in the format AAAAMMDD-XXXX (e.g., 20260820-0001).
    Guarantees unique sequential numbering per day for the tenant by calculating the true numeric max.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    today_str = now.strftime("%Y%m%d")
    prefix = f"{today_str}-"
    
    stmt = (
        select(Conversation.protocol_number)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.protocol_number.like(f"{prefix}%")
        )
    )
    res = await db.execute(stmt)
    all_protos = res.scalars().all()
    
    max_seq = 0
    for p in all_protos:
        if p and "-" in p:
            parts = p.split("-")
            if len(parts) >= 2 and parts[0] == today_str:
                try:
                    seq = int(parts[1])
                    if seq > max_seq:
                        max_seq = seq
                except ValueError:
                    pass
                    
    next_seq = max_seq + 1
    return f"{prefix}{next_seq:04d}"
