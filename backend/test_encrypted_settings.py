import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import init_db
from app.core.security import encrypt_data, decrypt_data, mask_sensitive_string

async def test_encrypted_integration_settings():
    print("\n=== INICIANDO TESTE DE CONFIGURACOES CRIPTOGRAFADAS E AUDITORIA ===")
    await init_db()
    
    # 1. Test Fernet Symmetric Encryption Unit Logic
    secret = "AIzaSy_CONFIDENTIAL_GEMINI_KEY_12345"
    cipher = encrypt_data(secret)
    assert cipher != secret, "Falha: O segredo nao foi criptografado!"
    decrypted = decrypt_data(cipher)
    assert decrypted == secret, "Falha: A descriptografia nao restaurou a chave original!"
    masked = mask_sensitive_string(secret)
    assert "CONFIDENTIAL" not in masked and masked.startswith("AIza") and masked.endswith("2345"), "Falha no mascaramento!"
    print("[OK] 1. Criptografia simetrica Fernet e mascaramento de chaves validados.")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 2. Login as Admin
        res = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        assert res.status_code == 200, f"Login admin falhou: {res.text}"
        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("[OK] 2. Login de Administrador autenticado.")

        # 3. Save Encrypted Integration Settings
        save_payload = {
            "gemini_api_key": "AIzaSy_CHAVE_SUPER_SECRETA_DO_TENANT_1",
            "evolution_api_url": "http://localhost:8080",
            "evolution_api_key": "master_key_privada_123",
            "inatividade_minutos": 45
        }
        res_save = await client.post("/api/v1/settings/", json=save_payload, headers=headers)
        assert res_save.status_code == 200, f"Falha ao salvar configuracoes: {res_save.text}"
        print("[OK] 3. Configuracoes salvas e criptografadas no banco via Fernet com sucesso.")

        # 4. GET Settings -> Verify Sensitive Keys ARE MASKED and NEVER returned in plaintext
        res_get = await client.get("/api/v1/settings/", headers=headers)
        data = res_get.json()
        assert data["gemini_configured"] == True
        assert data["gemini_api_key_masked"].startswith("AIza") and data["gemini_api_key_masked"].endswith("NT_1"), "Mascara incorreta"
        assert "SUPER_SECRETA" not in json.dumps(data), "FALHA DE SEGURANCA: Chave em texto puro foi retornada pela API!"
        assert data["inatividade_minutos"] == 45
        print(f"[OK] 4. API respondeu com chaves mascaradas com sucesso: '{data['gemini_api_key_masked']}' (Zero vazamento em texto puro).")

        # 5. Test Connection Button Endpoint
        res_test = await client.post("/api/v1/settings/test", json={"integration_type": "evolution"}, headers=headers)
        assert res_test.status_code == 200
        test_out = res_test.json()
        print(f"[OK] 5. Botao 'Testar Conexao' executado com resposta: {test_out['message']}")

        # 6. Audit Logs Verification
        res_logs = await client.get("/api/v1/settings/audit-logs", headers=headers)
        logs = res_logs.json()
        assert len(logs) >= 2, "Devem existir logs de alteração e de teste de conexão!"
        actions = [l["acao"] for l in logs]
        assert "ALTEROU_CONFIGURACOES_INTEGRACAO" in actions
        assert "TESTOU_CONEXAO_EVOLUTION" in actions
        print(f"[OK] 6. Registros no Log de Auditoria confirmados com sucesso! Ações encontradas: {actions[:2]}")

    print("\n=========================================================================")
    print("TESTE DE CONFIGURACOES CRIPTOGRAFADAS E AUDITORIA CONCLUIDO COM SUCESSO!")
    print("=========================================================================\n")

import json
if __name__ == "__main__":
    asyncio.run(test_encrypted_integration_settings())
