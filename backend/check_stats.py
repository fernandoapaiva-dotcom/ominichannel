import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, Message
from sqlalchemy import select, func

async def check():
    async with AsyncSessionLocal() as db:
        c = await db.scalar(select(func.count(Conversation.id)))
        m = await db.scalar(select(func.count(Message.id)))
        print(f'Conversations: {c}')
        print(f'Messages: {m}')

if __name__ == "__main__":
    asyncio.run(check())
