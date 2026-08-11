import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, init_db
from app.core.security import get_password_hash
from app.models.models import Tenant, WhatsAppNumber, User, UserRole

async def seed_database():
    await init_db()
    async with AsyncSessionLocal() as db:
        # 1. Create Default Tenant
        tenant_stmt = select(Tenant).where(Tenant.nome == "Loja Modelo Demolição e Comercio")
        res = await db.execute(tenant_stmt)
        tenant = res.scalar_one_or_none()

        if not tenant:
            tenant = Tenant(
                nome="Loja Modelo Demolição e Comercio",
                pasta_google_drive_id="1ABC_GoogleDriveFolderID_Sample",
                config_geral={"inatividade_minutos": 30, "prompt_concierge": "Atenda os clientes da loja com cordialidade."}
            )
            db.add(tenant)
            await db.commit()
            await db.refresh(tenant)
            print(f"Tenant criado com ID: {tenant.id}")

        # 2. Create 4 WhatsApp Numbers / Departments
        departments = [
            ("Vendas e E-commerce", "5511999990001", "instancia_vendas"),
            ("Assistência Técnica", "5511999990002", "instancia_tecnica"),
            ("Financeiro", "5511999990003", "instancia_financeiro"),
            ("Locação", "5511999990004", "instancia_locacao")
        ]

        created_numbers = []
        for dept_name, phone, inst in departments:
            wn_stmt = select(WhatsAppNumber).where(WhatsAppNumber.instancia_evolution_api == inst)
            wn_res = await db.execute(wn_stmt)
            wn = wn_res.scalar_one_or_none()
            if not wn:
                wn = WhatsAppNumber(
                    tenant_id=tenant.id,
                    numero=phone,
                    nome_departamento=dept_name,
                    instancia_evolution_api=inst,
                    status=True
                )
                db.add(wn)
                await db.flush()
                print(f"Número cadastrado: {dept_name} ({phone})")
            created_numbers.append(wn)

        await db.commit()

        # 3. Create Admin User
        admin_stmt = select(User).where(User.login == "admin")
        admin_res = await db.execute(admin_stmt)
        admin = admin_res.scalar_one_or_none()
        if not admin:
            admin = User(
                tenant_id=tenant.id,
                nome="Administrador Geral",
                login="admin",
                senha_hash=get_password_hash("admin123"),
                role=UserRole.ADMIN,
                status=True
            )
            db.add(admin)
            print("Usuário Admin criado: login 'admin' | senha 'admin123'")

        # 4. Create Agent User (Access to Vendas & Financeiro only)
        atendente_stmt = select(User).where(User.login == "atendente1")
        atendente_res = await db.execute(atendente_stmt)
        atendente = atendente_res.scalar_one_or_none()
        if not atendente:
            atendente = User(
                tenant_id=tenant.id,
                nome="Carlos Atendente",
                login="atendente1",
                senha_hash=get_password_hash("senha123"),
                role=UserRole.ATENDENTE,
                status=True
            )
            # Give access only to Vendas and Financeiro
            atendente.whatsapp_numbers = [created_numbers[0], created_numbers[2]]
            db.add(atendente)
            print("Usuário Atendente criado: login 'atendente1' | senha 'senha123'")

        await db.commit()

if __name__ == "__main__":
    asyncio.run(seed_database())
