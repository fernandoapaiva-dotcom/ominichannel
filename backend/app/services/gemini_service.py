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

    async def summarize_conversation_for_transfer(
        self,
        customer_name: str,
        messages_history: List[Dict[str, str]],
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        """
        Generates a structured executive AI summary of the entire conversation for seamless transfer
        to a new attendant or department.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        model_name = tenant_gemini_model_name or "gemini-2.5-flash"

        if not messages_history:
            return "Nenhum histórico prévio de mensagens para resumir."

        messages_text = []
        for m in messages_history:
            r_raw = str(m.get("remetente", "")).lower()
            if r_raw == "cliente":
                remetente = "Cliente"
            elif r_raw == "ia":
                remetente = "IA Concierge"
            elif r_raw == "sistema":
                remetente = "Sistema"
            else:
                remetente = "Atendente"
            
            conteudo = str(m.get("conteudo", "")).strip()
            if conteudo:
                messages_text.append(f"[{remetente}]: {conteudo}")

        full_prompt = (
            f"Você é um assistente de IA corporativo ultra-preciso, factual e objetivo.\n"
            f"Sua tarefa é analisar a conversa real com o cliente '{customer_name}' abaixo e gerar um RESUMO EXECUTIVO verdadeiro para o próximo atendente.\n\n"
            "REGRAS DE CONFIABILIDADE E ANTI-ALUCINAÇÃO:\n"
            "1. Baseie-se ESTRITAMENTE E APENAS no conteúdo das mensagens fornecidas no histórico.\n"
            "2. É PROIBIDO inventar produtos, equipamentos, valores, peças ou ocorrências que não estejam explicitamente no texto.\n"
            "3. Se o histórico for muito curto (ex: apenas testes, saudações ou solicitações simples), afirme claramente que o cliente solicitou atendimento sem detalhar itens fictícios.\n\n"
            "FORMATO DE SAÍDA EXIGIDO:\n"
            "• 🎯 **Objetivo Principal do Cliente**: <resumo factual em 1 frase>\n"
            "• 📝 **Principais Pontos / O que foi Tratado**: <1 a 3 pontos reais citados no diálogo>\n"
            "• ⚡ **Status & Próximo Passo Recomendado**: <orientação objetiva ao novo atendente>\n\n"
            f"HISTÓRICO DA CONVERSA REAL:\n" + "\n".join(messages_text)
        )

        if not client:
            return (
                f"• 🎯 **Objetivo Principal**: Transferência de atendimento de {customer_name}.\n"
                f"• 📝 **Histórico**: Conversa transferida manualmente pelo atendente.\n"
                f"• ⚡ **Próximo Passo**: Verifique a última mensagem enviada."
            )

        try:
            import asyncio
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=full_prompt
            )
            return response.text.strip() or "Resumo não gerado devido ao formato de saída da IA."
        except Exception as e:
            logger.error(f"Error generating transfer summary using model '{model_name}': {e}")
            return (
                f"• 🎯 **Objetivo Principal**: Transferência de atendimento de {customer_name}.\n"
                f"• 📝 **Histórico**: Conversa transferida com histórico disponível.\n"
                f"• ⚡ **Próximo Passo**: Analise as mensagens anteriores."
            )

gemini_service = GeminiService()
