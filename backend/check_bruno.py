import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, Contact, Message
from sqlalchemy import select, or_

async def check_brunos():
    async with AsyncSessionLocal() as db:
        # Search contacts
        c_stmt = select(Contact).where(Contact.nome.ilike("%bruno%"))
        c_res = await db.execute(c_stmt)
        contacts = c_res.scalars().all()
        print(f"--- CONTACTS MATCHING 'bruno': {len(contacts)} ---")
        for c in contacts:
            print(f"Contact ID: {c.id} | Nome: {c.nome} | Telefone: {c.telefone}")

        # Search conversations
        conv_stmt = select(Conversation).join(Contact).where(
            or_(Contact.nome.ilike("%bruno%"), Contact.telefone.ilike("%bruno%"))
        )
        conv_res = await db.execute(conv_stmt)
        convs = conv_res.scalars().all()
        print(f"\n--- CONVERSATIONS MATCHING 'bruno': {len(convs)} ---")
        for conv in convs:
            print(f"Conv ID: {conv.id} | Contact ID: {conv.contact_id} | Status: {conv.status} | Ultima Interacao: {conv.ultima_interacao_em}")

if __name__ == "__main__":
    asyncio.run(check_brunos())
