import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

async def test_evo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res_login = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        token = res_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        res_test = await client.post("/api/v1/settings/test", json={
            "integration_type": "evolution",
            "test_url": "http://localhost:8080",
            "test_key": "42a24fa6-403d-4c7b-b30a-9359e9a4f783"
        }, headers=headers)
        print("RESULTADO DO TESTE DE CONEXÃO COM EVOLUTION API REAL:")
        print(res_test.json())

if __name__ == "__main__":
    asyncio.run(test_evo())
