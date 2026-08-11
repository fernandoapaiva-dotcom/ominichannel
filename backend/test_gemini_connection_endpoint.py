import asyncio
import os
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import settings

async def test_gemini_button():
    print("\n=== TESTE DO BOTAO 'TESTAR CONEXAO' DO GEMINI (API LIVE) ===")

    # Get API key from env or setting
    key_to_test = os.environ.get("GEMINI_API_KEY") or settings.GEMINI_API_KEY

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Login Admin
        res_login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        token = res_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        if not key_to_test:
            print("\n[AVISO] GEMINI_API_KEY nao foi encontrada no ambiente!")
            print("Para testar com uma chave gratuita real do Gemini, defina GEMINI_API_KEY='sua_chave' em backend/.env.")
            print("Executando requisicao de teste sem chave para demonstrar retorno do sistema:")
            res_test = await client.post(
                "/api/v1/settings/test",
                json={"integration_type": "gemini", "test_key": ""},
                headers=headers
            )
            print(f"Status Code: {res_test.status_code}")
            print(f"Resposta JSON: {res_test.json()}")
            return

        print(f"\nDisparando teste de conexao real para Google Gemini (google.genai SDK)...")
        res_test = await client.post(
            "/api/v1/settings/test",
            json={"integration_type": "gemini", "test_key": key_to_test},
            headers=headers
        )

        print("\n=======================================================")
        print("OUTPUT REAL RETORNADO PELO BOTAO 'TESTAR CONEXAO':")
        print("=======================================================")
        print(f"Status Code: {res_test.status_code}")
        print(f"Resposta JSON: {res_test.json()}")
        print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(test_gemini_button())
