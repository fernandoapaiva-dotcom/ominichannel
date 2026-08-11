import asyncio
import os
import json
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.inactivity_service import InactivityService

async def run_integration_tests():
    print("=== INICIANDO TESTES AUTOMATIZADOS DE INTEGRACAO ===")
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        
        # 1. Test Admin Login
        res = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        assert res.status_code == 200, f"Admin login falhou: {res.text}"
        admin_token = res.json()["access_token"]
        print("[OK] 1. Login Admin realizado com sucesso.")

        # 2. Test Agent Login
        res = await client.post("/api/v1/auth/login", data={"username": "atendente1", "password": "senha123"})
        assert res.status_code == 200, f"Agent login falhou: {res.text}"
        agent_token = res.json()["access_token"]
        print("[OK] 2. Login Atendente realizado com sucesso.")

        # 3. Test WhatsApp Numbers Access (Admin sees 4, Agent sees 2)
        res_admin = await client.get("/api/v1/whatsapp-numbers/", headers={"Authorization": f"Bearer {admin_token}"})
        assert len(res_admin.json()) == 4, f"Admin deveria ver 4 numeros, viu {len(res_admin.json())}"
        
        res_agent = await client.get("/api/v1/whatsapp-numbers/", headers={"Authorization": f"Bearer {agent_token}"})
        assert len(res_agent.json()) == 2, f"Atendente deveria ver 2 numeros autorizados, viu {len(res_agent.json())}"
        print("[OK] 3. Controle de permissao de acesso N:N validado com sucesso!")

        # 4. Test Webhook Evolution API - Incoming Customer Message to Vendas
        webhook_payload = {
            "event": "messages.upsert",
            "instance": "instancia_vendas",
            "data": {
                "key": {
                    "remoteJid": "5511988887777@s.whatsapp.net",
                    "fromMe": False
                },
                "pushName": "Cliente Teste Silva",
                "message": {
                    "conversation": "Ola! Gostaria de saber os valores para alugar uma ferramenta de demolicao."
                }
            }
        }
        res_wh = await client.post("/api/v1/webhooks/evolution", json=webhook_payload)
        assert res_wh.status_code == 200, f"Webhook falhou: {res_wh.text}"
        print("[OK] 4. Webhook Evolution API processado com sucesso!")

        # 5. Check Conversation created and retrieved by agent
        res_convs = await client.get("/api/v1/conversations/", headers={"Authorization": f"Bearer {agent_token}"})
        convs = res_convs.json()
        assert len(convs) >= 1, "Nenhuma conversa encontrada para o atendente"
        target_conv = convs[0]
        print(f"[OK] 5. Conversa criada com ID: {target_conv['id']} | Status: {target_conv['status']}")

        # 6. Test Agent Sending Response to Customer
        res_msg = await client.post(
            f"/api/v1/conversations/{target_conv['id']}/messages",
            headers={"Authorization": f"Bearer {agent_token}"},
            json={"conversation_id": target_conv["id"], "remetente": "atendente", "conteudo": "Ola Silva! Temos otimas condicoes. Qual o periodo desejado?", "tipo": "texto"}
        )
        assert res_msg.status_code == 200, f"Envio de mensagem do atendente falhou: {res_msg.text}"
        print("[OK] 6. Resposta do atendente enviada com sucesso!")

        # 7. Test Inactivity & Backup Service
        service = InactivityService()
        await service.check_and_expire_idle_conversations()
        print("[OK] 7. Servico de verificacao de inatividade e backup JSON executado.")

    print("\n=======================================================")
    print("ALL INTEGRATION TESTS PASSED CLEANLY (100% SUCCESS)!")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(run_integration_tests())
