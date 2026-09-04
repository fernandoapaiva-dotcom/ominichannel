import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def do_update():
    async with AsyncSessionLocal() as session:
        # 1. Update contact ID 40
        await session.execute(text("UPDATE contacts SET nome = 'Cliente WhatsApp' WHERE id = 40"))
        
        # 2. Merge 4988 to 40
        await session.execute(text("UPDATE conversations SET contact_id = 40 WHERE contact_id = 4988"))
        await session.execute(text("DELETE FROM contacts WHERE id = 4988"))
        
        # 3. Update contact 4543
        await session.execute(text("UPDATE contacts SET nome = 'MS metalúrgica santos' WHERE id = 4543"))
        
        # 4. Replace raw LID digits with 'Cliente WhatsApp'
        await session.execute(text("""
            UPDATE contacts 
            SET nome = 'Cliente WhatsApp' 
            WHERE (nome = telefone OR LENGTH(nome) >= 14)
              AND LENGTH(telefone) >= 14
              AND telefone NOT LIKE '55%'
              AND telefone NOT LIKE '120363%'
              AND telefone NOT LIKE '%-%'
        """))
        
        await session.commit()
        print("ASYNC SESSION UPDATE COMPLETED 100% SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(do_update())
