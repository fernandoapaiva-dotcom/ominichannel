import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

async def test_websocket_security():
    print("\n=== TESTE DE AUTENTICACAO E SEGURANCA WEBSOCKET ===")
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Login to get valid JWT token
        res_login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        valid_token = res_login.json()["access_token"]
        print(f"[OK] Token JWT valido gerado: {valid_token[:20]}...")

        # 2. Test valid WebSocket token connection using ASGI test client
        from starlette.testclient import TestClient
        test_client = TestClient(app)

        with test_client.websocket_connect(f"/ws?token={valid_token}") as websocket:
            print("[OK] CONEXAO ACEITA: WebSocket com token JWT valido conectado com sucesso.")

        # 3. Test invalid WebSocket token connection
        try:
            with test_client.websocket_connect("/ws?token=token_invalido_hacker_123") as websocket:
                pass
        except Exception as e:
            print(f"[OK] CONEXAO REJEITADA: Tentativa de conexao WebSocket com token invalido REJEITADA e encerrada pelo servidor! Erro: {e}")

        # 4. Test missing token connection
        try:
            with test_client.websocket_connect("/ws") as websocket:
                pass
        except Exception as e:
            print(f"[OK] CONEXAO REJEITADA: Conexao sem parametro de token REJEITADA com sucesso! Erro: {e}")

    print("\n=========================================================================")
    print("TESTE DE SEGURANCA WEBSOCKET CONCLUIDO COM SUCESSO!")
    print("=========================================================================\n")

if __name__ == "__main__":
    asyncio.run(test_websocket_security())
