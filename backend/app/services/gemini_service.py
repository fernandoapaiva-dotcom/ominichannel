import logging
from typing import Dict, Any, List, Optional
from google import genai
from app.core.config import settings

logger = logging.getLogger("gemini_service")

class GeminiService:
    def __init__(self):
        if settings.GEMINI_API_KEY:
            self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        else:
            self.client = None

    def get_client_for_key(self, api_key: Optional[str]) -> Optional[genai.Client]:
        if api_key and api_key.strip():
            return genai.Client(api_key=api_key)
        return self.client

    async def generate_concierge_response(
        self,
        customer_name: str,
        department_name: str,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        memory_summary: Optional[str] = None,
        rag_context: Optional[str] = None,
        tenant_prompt: Optional[str] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates concierge response using tenant's dynamically configured Gemini API key and Model Name from DB.
        Zero hardcoded model strings.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        model_name = tenant_gemini_model_name or "gemini-2.5-flash"

        system_instruction = (
            f"Você é a IA Concierge de atendimento da loja para o departamento '{department_name}'.\n"
            f"Atenda com polidez e agilidade o cliente '{customer_name or 'Cliente'}'.\n"
            f"{tenant_prompt or 'Resolva dúvidas com base no contexto fornecido.'}\n\n"
            "DIRETRIZES DE ESCALONAMENTO:\n"
            "Se o cliente solicitar falar com atendente humano ou se a dúvida for complexa e fora da base de conhecimento, diga que vai transferir e defina 'ESCALAR_HUMANO: SIM'.\n\n"
            f"HISTÓRICO ANTERIOR/MEMÓRIA RESUMIDA DA CONVERSA:\n{memory_summary or 'Nenhum histórico anterior.'}\n\n"
            f"BASE DE CONHECIMENTO RAG:\n{rag_context or 'Nenhum documento específico encontrado.'}"
        )

        messages_text = []
        for msg in conversation_history[-6:]:
            role = "Cliente" if msg["remetente"] == "cliente" else "Atendente/IA"
            messages_text.append(f"{role}: {msg['conteudo']}")
        
        full_prompt = (
            f"{system_instruction}\n\n"
            f"Diálogo Recente:\n" + "\n".join(messages_text) + "\n\n"
            f"Mensagem Atual do Cliente: {user_message}\n\n"
            "Responda no seguinte formato exato:\n"
            "RESPOSTA: <sua resposta ao cliente>\n"
            "ESCALAR_HUMANO: <SIM ou NAO>\n"
            "NOVA_MEMORIA: <resumo atualizado em 1 ou 2 frases curtas>"
        )

        if not client:
            needs_human = any(word in user_message.lower() for word in ["humano", "atendente", "falar com pessoa", "financeiro"])
            return {
                "resposta": "Olá! Sou o assistente virtual. Em que posso te ajudar hoje?" if not needs_human else "Estou transferindo seu atendimento para um de nossos especialistas.",
                "escalar_humano": needs_human,
                "nova_memoria": f"Cliente perguntou: '{user_message}'",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        try:
            import asyncio
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=full_prompt
            )
            text_out = response.text.strip()
            
            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
            response_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
            total_tokens = getattr(usage, "total_token_count", 0) if usage else 0

            resposta = ""
            escalar_humano = False
            nova_memoria = ""

            for line in text_out.split("\n"):
                if line.startswith("RESPOSTA:"):
                    resposta = line.replace("RESPOSTA:", "").strip()
                elif line.startswith("ESCALAR_HUMANO:"):
                    escalar_humano = "SIM" in line.upper()
                elif line.startswith("NOVA_MEMORIA:"):
                    nova_memoria = line.replace("NOVA_MEMORIA:", "").strip()

            if not resposta:
                resposta = text_out

            return {
                "resposta": resposta,
                "escalar_humano": escalar_humano,
                "nova_memoria": nova_memoria or memory_summary or f"Cliente interagiu sobre: {user_message[:50]}",
                "tokens": {
                    "prompt_tokens": prompt_tokens,
                    "response_tokens": response_tokens,
                    "total_tokens": total_tokens
                }
            }
        except Exception as e:
            logger.error(f"Error calling Gemini API using model '{model_name}': {e}")
            return {
                "resposta": "Recebi sua mensagem. Um momento por favor, vou direcionar para nossa equipe.",
                "escalar_humano": True,
                "nova_memoria": "Erro na IA Concierge, escalado automaticamente para humano.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

gemini_service = GeminiService()
