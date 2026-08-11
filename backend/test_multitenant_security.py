import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.models import Tenant, User, WhatsAppNumber, Contact, Conversation, ConversationStatus, UserRole

async def seed_multitenant_data():
    async with AsyncSessionLocal() as db:
        # Create Tenant A
        res_a = await db.execute(select(Tenant).where(Tenant.nome == "Tenant A - Loja Matriz"))
        tenant_a = res_a.scalar_one_or_none()
        if not tenant_a:
            tenant_a = Tenant(nome="Tenant A - Loja Matriz")
            db.add(tenant_a)
            await db.flush()

        # Create Tenant B
        res_b = await db.execute(select(Tenant).where(Tenant.nome == "Tenant B - Loja Filial Concorrente"))
        tenant_b = res_b.scalar_one_or_none()
        if not tenant_b:
            tenant_b = Tenant(nome="Tenant B - Loja Filial Concorrente")
            db.add(tenant_b)
            await db.flush()

        # Create Admin User for Tenant A
        res_ua = await db.execute(select(User).where(User.login == "admin_tenant_a"))
        user_a = res_ua.scalar_one_or_none()
        if not user_a:
            user_a = User(
                tenant_id=tenant_a.id,
                nome="Admin Tenant A",
                login="admin_tenant_a",
                senha_hash=get_password_hash("password_a"),
                role=UserRole.ADMIN
            )
            db.add(user_a)

        # Create Admin User for Tenant B
        res_ub = await db.execute(select(User).where(User.login == "admin_tenant_b"))
        user_b = res_ub.scalar_one_or_none()
        if not user_b:
            user_b = User(
                tenant_id=tenant_b.id,
                nome="Admin Tenant B",
                login="admin_tenant_b",
                senha_hash=get_password_hash("password_b"),
                role=UserRole.ADMIN
            )
            db.add(user_b)

        # Create WhatsApp Number & Conversation for Tenant A
        res_wn_a = await db.execute(select(WhatsAppNumber).where(WhatsAppNumber.instancia_evolution_api == "instancia_tenant_a"))
        wn_a = res_wn_a.scalar_one_or_none()
        if not wn_a:
            wn_a = WhatsAppNumber(
                tenant_id=tenant_a.id,
                numero="5511911111111",
                nome_departamento="Vendas Matriz",
                instancia_evolution_api="instancia_tenant_a"
            )
            db.add(wn_a)
            await db.flush()

        res_c_a = await db.execute(select(Contact).where(Contact.tenant_id == tenant_a.id, Contact.telefone == "5511999998888"))
        contact_a = res_c_a.scalar_one_or_none()
        if not contact_a:
            contact_a = Contact(tenant_id=tenant_a.id, telefone="5511999998888", nome="Cliente Exclusivo Tenant A")
            db.add(contact_a)
            await db.flush()

        res_conv_a = await db.execute(select(Conversation).where(Conversation.tenant_id == tenant_a.id))
        conv_a = res_conv_a.scalar_one_or_none()
        if not conv_a:
            conv_a = Conversation(
                tenant_id=tenant_a.id,
                whatsapp_number_id=wn_a.id,
                contact_id=contact_a.id,
                status=ConversationStatus.COM_HUMANO,
                assunto_atual="Dados Confidenciais Tenant A"
            )
            db.add(conv_a)
            await db.flush()

        await db.commit()
        return conv_a.id

async def test_cross_tenant_security():
    print("\n=== INICIANDO TESTE DE SEGURANCA E ISOLAMENTO MULTITENANT ===")
    
    target_conv_id = await seed_multitenant_data()
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Login User Tenant A
        res_a = await client.post("/api/v1/auth/login", data={"username": "admin_tenant_a", "password": "password_a"})
        token_a = res_a.json()["access_token"]
        
        # 2. Login User Tenant B
        res_b = await client.post("/api/v1/auth/login", data={"username": "admin_tenant_b", "password": "password_b"})
        token_b = res_b.json()["access_token"]
        print("[OK] Logins efetuados para Tenant A e Tenant B.")

        # 3. Tenant A user accesses conversation target_conv_id -> Should succeed (HTTP 200)
        res_access_a = await client.get(f"/api/v1/conversations/{target_conv_id}", headers={"Authorization": f"Bearer {token_a}"})
        assert res_access_a.status_code == 200, f"Tenant A falhou em acessar seu proprio recurso: {res_access_a.text}"
        print(f"[OK] Tenant A acessou com sucesso a conversa ID {target_conv_id} (HTTP 200).")

        # 4. CROSS-TENANT VIOLATION TEST: Tenant B user attempts to access Tenant A conversation target_conv_id
        res_cross_access = await client.get(f"/api/v1/conversations/{target_conv_id}", headers={"Authorization": f"Bearer {token_b}"})
        
        # Expecting 404 (or 403) error blocking cross-tenant data leak
        assert res_cross_access.status_code in [404, 403], f"FALHA DE SEGURANCA: Tenant B conseguiu acessar recurso do Tenant A! Status Code: {res_cross_access.status_code}"
        print(f"[OK] TENTATIVA NEGADA: Usuario do Tenant B tentou acessar conversa do Tenant A (ID {target_conv_id}) e recebeu erro HTTP {res_cross_access.status_code} ({res_cross_access.json().get('detail')}).")

        # 5. List conversations test: Tenant B user lists conversations -> Must NOT see Tenant A's conversation
        res_list_b = await client.get("/api/v1/conversations/", headers={"Authorization": f"Bearer {token_b}"})
        tenant_b_convs = res_list_b.json()
        
        leaked_ids = [c["id"] for c in tenant_b_convs if c["id"] == target_conv_id]
        assert len(leaked_ids) == 0, f"FALHA DE SEGURANCA: Conversa do Tenant A vazou na listagem do Tenant B! {leaked_ids}"
        print(f"[OK] VAZAMENTO ZERO: Listagem de conversas do Tenant B nao retornou nenhuma conversa do Tenant A (Total retornado para Tenant B: {len(tenant_b_convs)}).")

    print("\n=========================================================================")
    print("TESTE DE SEGURANCA MULTITENANT CONCLUIDO: ISOLAMENTO TOTAL CONFIRMADO!")
    print("=========================================================================\n")

if __name__ == "__main__":
    asyncio.run(test_cross_tenant_security())
