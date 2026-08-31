import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import WhatsAppNumber
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(WhatsAppNumber))
        wns = res.scalars().all()
        for w in wns:
            print(f"ID: {w.id}, Dept: {w.nome_departamento}, Instancia: {w.instancia_evolution_api}, Status: {w.status}")

if __name__ == "__main__":
    asyncio.run(main())
