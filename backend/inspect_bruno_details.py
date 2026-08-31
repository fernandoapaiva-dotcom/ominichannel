import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, Contact, WhatsAppNumber
from sqlalchemy import select

async def inspect_bruno():
    async with AsyncSessionLocal() as db:
        # Check WhatsApp Numbers
        wns = (await db.execute(select(WhatsAppNumber))).scalars().all()
        print("--- WHATSAPP NUMBERS ---")
        for wn in wns:
            print(f"ID: {wn.id} | Nome: {wn.nome_departamento} | Numero: {wn.numero} | Instancia: {wn.instancia_evolution_api}")

        # Check Bruno De Miranda's Conversations
        stmt = select(Conversation).join(Contact).where(Contact.nome.ilike("%bruno de miranda%"))
        convs = (await db.execute(stmt)).scalars().all()
        print("\n--- BRUNO DE MIRANDA CONVERSATIONS ---")
        for c in convs:
            print(f"Conv ID: {c.id} | WN ID: {c.whatsapp_number_id} | Status: {c.status} | Last Interaction: {c.ultima_interacao_em} | dados_adicionais: {c.dados_adicionais}")

if __name__ == "__main__":
    asyncio.run(inspect_bruno())
