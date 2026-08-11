import asyncio
import os
from app.core.database import AsyncSessionLocal, init_db
from app.services.rag_service import rag_service
from app.services.gemini_service import gemini_service
from app.services.settings_service import settings_service

async def test_live_gemini_rag_from_db():
    print("\n=== TESTE DE PONTA A PONTA: IA GEMINI COM RAG E CHAVE SALVA NO BANCO (DB) ===")

    await init_db()
    tenant_id = 1

    # 1. Fetch decrypted key directly from Database (IntegrationSettings table)
    async with AsyncSessionLocal() as db:
        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
        api_key_from_db = decrypted_settings.get("gemini_api_key")

    if not api_key_from_db or api_key_from_db.strip() == "":
        print("\n[ATENCAO] Nenhuma chave do Gemini encontrada na tabela IntegrationSettings no banco de dados!")
        print("Envie/Salve sua chave do Gemini via API ou informe no chat para executar este teste real.")
        return

    print(f"[OK] 1. Chave recuperada e descriptografada via Fernet do banco de dados: '{api_key_from_db[:4]}...****{api_key_from_db[-4:]}'")

    # 2. Index RAG Document in local ChromaDB
    doc_content = (
        "MANUAL DE COMPRAS E REGRAS DE LOCACAO 2026 - DEMOLICAO E COMERCIO:\n"
        "- Andaime Tubular 1,5m: R$ 120,00 a diaria por peça.\n"
        "- Taxa de Entrega e Frete na Grande SP: R$ 50,00 valor fixo.\n"
        "- Formas de pagamento aceitas: Pix à vista com 5% de desconto ou Cartao de Credito em ate 3x sem juros.\n"
        "- Horario de devolução: Ate as 17:00h do ultimo dia de contrato."
    )
    
    print("\n2. Indexando documento RAG no ChromaDB local...")
    await rag_service.add_document(
        tenant_id=tenant_id,
        doc_id="doc_andaimes_2026",
        content=doc_content,
        metadata={"titulo": "Regras Locacao Andaimes"}
    )
    print("[OK] Documento indexado no RAG com sucesso.")

    # 3. Customer query triggering RAG retrieval
    user_query = "Qual é o valor da diária do andaime tubular e quais as formas de pagamento aceitas?"
    print(f"\n3. Pergunta do Cliente: '{user_query}'")

    # 4. Retrieve RAG context
    rag_context = await rag_service.search_context(tenant_id=tenant_id, query=user_query)
    print(f"\n4. Contexto Relevante Extraido do RAG (ChromaDB):\n----------------------------------------\n{rag_context}\n----------------------------------------")

    # 5. Generate response with Gemini AI using the key from DB
    print("\n5. Chamando API Gemini (google.genai - modelo gemini-2.5-flash) com a chave do banco...")
    history = []
    output = await gemini_service.generate_concierge_response(
        customer_name="Marcos Cliente",
        department_name="Locação e Equipamentos",
        user_message=user_query,
        conversation_history=history,
        memory_summary=None,
        rag_context=rag_context,
        tenant_gemini_api_key=api_key_from_db
    )

    tokens = output.get("tokens", {})

    print("\n=========================================================================")
    print("OUTPUT REAL DA EXECUCAO DE PONTA A PONTA (IA + RAG + CHAVE DO BANCO):")
    print("=========================================================================")
    print(f"RESPOSTA CLIENTE: {output['resposta']}")
    print(f"ESCALAR HUMANO  : {output['escalar_humano']}")
    print(f"NOVA MEMORIA    : {output['nova_memoria']}")
    print("-------------------------------------------------------------------------")
    print("CONSUMO REAL DE TOKENS (METRICS GOOGLE GENAI):")
    print(f" - Tokens do Prompt (Contexto + RAG) : {tokens.get('prompt_tokens')} tokens")
    print(f" - Tokens da Resposta Gerada         : {tokens.get('response_tokens')} tokens")
    print(f" - TOTAL DE TOKENS CONSUMIDOS        : {tokens.get('total_tokens')} tokens")
    print("=========================================================================\n")

if __name__ == "__main__":
    asyncio.run(test_live_gemini_rag_from_db())
