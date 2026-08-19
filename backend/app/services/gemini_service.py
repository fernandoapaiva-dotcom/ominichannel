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
        available_departments: Optional[List[str]] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates concierge response using tenant's dynamically configured Gemini API key and Model Name from DB.
        Zero hardcoded model strings. Supports fluid conversational initial reception without rigid menus
        and smart automatic sector/department redirection.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        model_name = tenant_gemini_model_name or "gemini-2.5-flash"

        dept_list_str = ", ".join(available_departments) if available_departments else department_name

        system_instruction = (
            f"Você é a IA Concierge de atendimento geral da empresa.\n"
            f"Você está atualmente atendendo na linha do setor '{department_name}', mas a empresa possui os seguintes setores ativos: [{dept_list_str}].\n"
            f"Atenda com extrema polidez, empatia e fluidez o cliente '{customer_name or 'Cliente'}'.\n\n"
            "DIRETRIZES DE RECEPÇÃO E TRIAGEM CONVERSACIONAL:\n"
            "1. NÃO USE MENUS ROBÓTICOS OU NUMÉRICOS (ex: PROIBIDO responder 'Digite 1 para X, 2 para Y').\n"
            "2. Faça uma recepção calorosa e natural, conversando como um humano atencioso para compreender o que o cliente realmente precisa.\n"
            "3. O cliente pode ter chamado no número do setor de '{department_name}', mas desejar assunto de outro setor (ex: Vendas, Locação, Financeiro, Assistência Técnica). Se a necessidade dele for claramente de outro setor da lista [{dept_list_str}], informe com gentileza que vai transferir a conversa para o setor correto e defina 'TRANSFERIR_SETOR: <NomeDoSetor>'. Se for para o setor atual ou um assunto geral, defina 'TRANSFERIR_SETOR: NENHUM'.\n"
            "4. Se o cliente solicitar falar com atendente humano ou se a dúvida for complexa e a base de conhecimento RAG não possuir a resposta necessária, diga que vai transferir para um especialista humano da equipe e defina 'ESCALAR_HUMANO: SIM'. Caso contrário, defina 'ESCALAR_HUMANO: NAO'.\n\n"
            f"{tenant_prompt or 'Resolva dúvidas com base no contexto fornecido.'}\n\n"
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
            "RESPOSTA: <sua resposta calorosa e conversacional ao cliente>\n"
            "TRANSFERIR_SETOR: <NomeExatoDoSetor ou NENHUM>\n"
            "ESCALAR_HUMANO: <SIM ou NAO>\n"
            "NOVA_MEMORIA: <resumo atualizado em 1 ou 2 frases curtas>"
        )

        if not client:
            needs_human = any(word in user_message.lower() for word in ["humano", "atendente", "falar com pessoa"])
            target_dept = "NENHUM"
            if available_departments:
                for d in available_departments:
                    if d.lower() != department_name.lower() and d.lower() in user_message.lower():
                        target_dept = d
                        break

            return {
                "resposta": "Olá! Seja muito bem-vindo. Como posso te ajudar hoje?" if not needs_human else "Estou transferindo seu atendimento para um de nossos especialistas.",
                "transferir_setor": target_dept,
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
            transferir_setor = "NENHUM"
            escalar_humano = False
            nova_memoria = ""

            for line in text_out.split("\n"):
                if line.startswith("RESPOSTA:"):
                    resposta = line.replace("RESPOSTA:", "").strip()
                elif line.startswith("TRANSFERIR_SETOR:"):
                    transferir_setor = line.replace("TRANSFERIR_SETOR:", "").strip()
                elif line.startswith("ESCALAR_HUMANO:"):
                    escalar_humano = "SIM" in line.upper()
                elif line.startswith("NOVA_MEMORIA:"):
                    nova_memoria = line.replace("NOVA_MEMORIA:", "").strip()

            if not resposta:
                resposta = text_out

            return {
                "resposta": resposta,
                "transferir_setor": transferir_setor,
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
                "transferir_setor": "NENHUM",
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
