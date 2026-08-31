import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import AuthorizedTechnician
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(AuthorizedTechnician))
        techs = res.scalars().all()
        print(f'Total de tecnicos: {len(techs)}')
        for t in techs:
            print(f'  ID={t.id} | nome={t.nome} | ativo={t.ativo} | tenant_id={t.tenant_id} | telefone={t.telefone}')

if __name__ == "__main__":
    asyncio.run(check())
