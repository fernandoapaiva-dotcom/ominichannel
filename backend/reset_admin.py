import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import User
from app.core.security import get_password_hash
from sqlalchemy import select, update

async def reset_pwd():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.login == 'admin'))
        user = res.scalars().first()
        if not user:
            print("Usuário 'admin' não encontrado.")
            return
        
        await db.execute(update(User).where(User.login == 'admin').values(senha_hash=get_password_hash('admin123')))
        await db.commit()
        print("Senha resetada com sucesso para 'admin123'")

if __name__ == "__main__":
    asyncio.run(reset_pwd())
