import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

async def test_crud_admin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        print("=== INICIANDO TESTES DE PUT E DELETE (DEPARTAMENTOS E USUARIOS) ===")

        # 1. Login Admin
        res_login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        assert res_login.status_code == 200
        token = res_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("[OK] 1. Login Admin realizado.")

        # 2. Create, Update and Delete WhatsApp Number
        res_create_num = await client.post("/api/v1/whatsapp-numbers/", json={
            "nome_departamento": "Departamento Temp Teste",
            "numero": "5511988887777",
            "instancia_evolution_api": "instancia_temp_test",
            "status": True
        }, headers=headers)
        assert res_create_num.status_code == 201
        num_data = res_create_num.json()
        num_id = num_data["id"]
        print(f"[OK] 2.1 Número criado com ID {num_id}.")

        res_update_num = await client.put(f"/api/v1/whatsapp-numbers/{num_id}", json={
            "nome_departamento": "Departamento Editado Teste",
            "numero": "5511988887788",
            "instancia_evolution_api": "instancia_editada_test",
            "status": True
        }, headers=headers)
        assert res_update_num.status_code == 200
        assert res_update_num.json()["nome_departamento"] == "Departamento Editado Teste"
        print("[OK] 2.2 Número atualizado via PUT com sucesso.")

        res_del_num = await client.delete(f"/api/v1/whatsapp-numbers/{num_id}", headers=headers)
        assert res_del_num.status_code == 200
        print("[OK] 2.3 Número excluído via DELETE com sucesso.")

        # 3. Create, Update and Delete User
        res_create_user = await client.post("/api/v1/users/", json={
            "nome": "Atendente Temp Teste",
            "login": "atendente_temp_test",
            "senha": "senha_temp_test",
            "role": "atendente",
            "status": True,
            "whatsapp_number_ids": []
        }, headers=headers)
        assert res_create_user.status_code == 201
        u_data = res_create_user.json()
        user_id = u_data["id"]
        print(f"[OK] 3.1 Atendente criado com ID {user_id}.")

        res_update_user = await client.put(f"/api/v1/users/{user_id}", json={
            "nome": "Atendente Editado Teste",
            "login": "atendente_temp_test",
            "role": "atendente",
            "status": True
        }, headers=headers)
        assert res_update_user.status_code == 200
        assert res_update_user.json()["nome"] == "Atendente Editado Teste"
        print("[OK] 3.2 Atendente atualizado via PUT com sucesso.")

        res_del_user = await client.delete(f"/api/v1/users/{user_id}", headers=headers)
        assert res_del_user.status_code == 200
        print("[OK] 3.3 Atendente excluído via DELETE com sucesso.")

    print("\n=========================================================================")
    print("TESTE DE PUT E DELETE FINALIZADO COM 100% DE SUCESSO!")
    print("=========================================================================")

if __name__ == "__main__":
    asyncio.run(test_crud_admin())
