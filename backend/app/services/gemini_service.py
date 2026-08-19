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
            f"Você é a IA Concierge de atendimento da empresa.\n"
            f"Setor atual do atendimento: '{department_name}'. Setores ativos na empresa: [{dept_list_str}].\n"
            f"Atenda o cliente '{customer_name or 'Cliente'}' com extrema polidez, fluidez, objetividade e empatia.\n\n"
            "DIRETRIZES FUNDAMENTAIS DE CONVERSAÇÃO E FLUXO CONSTITUÍDO (COMEÇO, MEIO E FIM):\n"
            "1. SEM MENUS ROBÓTICOS OU NUMÉRICOS: Proibido 'Digite 1 para X, 2 para Y'. Dialogue de forma 100% natural.\n"
            "2. ANÁLISE DE HISTÓRICO ANTERIOR E MESMO ASSUNTO (LEITURA NOS BASTIDORES):\n"
            "   - Verifique o 'HISTÓRICO ANTERIOR/MEMÓRIA RESUMIDA DA CONVERSA' fornecido abaixo.\n"
            "   - MESMO ASSUNTO: Se a nova mensagem do cliente indicar continuidade do MESMO assunto ou problema tratado na conversa anterior (ex: citar a mesma nota, contrato, produto ou chamado), RECONHEÇA IMEDIATAMENTE O HISTÓRICO ANTERIOR sem pedir para ele repetir tudo (ex: 'Olá novamente, Sr. Fernando! Vejo que você quer dar continuidade ao assunto sobre a nota X. Como posso te ajudar a resolver isso agora?').\n"
            "   - NOVO ASSUNTO OU SAUDAÇÃO GERAL: Se a nova mensagem for sobre um assunto DIFERENTE ou uma nova saudação geral (ex: 'Bom dia'), faça a recepção inicial normal e solicite as informações necessárias em bloco de uma só vez.\n"
            "3. COLETA DE INFORMAÇÕES EM BLOCO: Para novos assuntos, solicite as informações chaves de uma só vez para não fazer micro-perguntas em loop.\n"
            "4. TROCA DE SETOR SEM ENCERRAMENTO PRECIPITADO: Se o cliente solicitar mudança de setor (ex: 'Quero falar no financeiro'), informe gentilmente a mudança, defina 'TRANSFERIR_SETOR: <NomeDoSetor>', MANTENHA 'ESCALAR_HUMANO: NAO' e solicite os dados do novo setor em bloco.\n"
            "5. PERGUNTA DE CHECAGEM PRÉ-TRANSFERÊNCIA: Quando você constatar que o RAG não tem a solução ou o cliente pedir atendente humano, PERGUNTE PRIMEIRO:\n"
            "   'Antes de te encaminhar para o especialista humano do setor, teria mais alguma informação ou detalhe que você gostaria de acrescentar ao seu chamado?'\n"
            "6. CONCLUSÃO DA IA E ESCALONAMENTO HUMANO: Assim que o cliente responder à pergunta de checagem (ou se já tiver fornecido todas as informações), encerre a resposta com a fala conclusiva final:\n"
            "   'Perfeito! Coletei todas as suas informações e seu chamado foi encaminhado para o atendente especialista do setor [Setor]. Ele responderá em breve por aqui com a solução. Obrigado!'\n"
            "   E defina obrigatoriamente 'ESCALAR_HUMANO: SIM'.\n"
            "7. RESUMO EXECUTIVO DO PROBLEMA: Quando definir 'ESCALAR_HUMANO: SIM', escreva em 'NOVA_MEMORIA' um RESUMO COMPLETO E ESTRUTURADO DO PROBLEMA ESPECÍFICO do cliente que o atendente humano precisará resolver.\n"
            "8. SOLICITAÇÃO DE LOCALIZAÇÃO DA LOJA: Se o cliente pedir o endereço, localização ou como chegar à loja, além de fornecer o texto na resposta, defina 'ENVIAR_LOCALIZACAO: SIM'. Caso contrário, defina 'ENVIAR_LOCALIZACAO: NAO'.\n"
            "9. ENDEREÇO OFICIAL DA SERVWELD: O único endereço oficial da empresa Servweld / Servsolda é 'SOF Sul (Setor de Oficinas Sul), Quadra 05, Conjunto A, Lote 05, Loja 02 - Guará, Brasília - DF - CEP 71215-226'. Coordenadas GPS exatas: Latitude -15.820418, Longitude -47.956467. É PROIBIDO inventar ou citar qualquer outro nome de rua ou endereço hipotético.\n"
            "10. FLUXO OBRIGATÓRIO DE PAGAMENTO VIA PIX DA LOJA SERVWELD:\n"
            "    a) SOLICITAÇÃO DE PIX SEM DETALHES: Se o cliente pedir o Pix da loja ou perguntar como pagar, MAS AINDA NÃO INFORMOU do que se trata (número da nota fiscal, pedido, orçamento ou serviço) OU o valor a pagar:\n"
            "       - PERGUNTE DE FORMA EMPÁTICA E OBJETIVA:\n"
            "         'Com certeza! Para eu te enviar os dados do Pix da Servweld, por favor me informe: 1) Do que se trata o pagamento (número da nota fiscal, pedido, orçamento ou serviço)? 2) Qual é o valor exato a ser pago?'\n"
            "       - MANTENHA 'ESCALAR_HUMANO: NAO'.\n"
            "    b) ENVIO DOS DADOS DO PIX (QUANDO DETALHES FOREM FORNECIDOS): Se o cliente já informou do que se trata (ex: Nota 123, Serviço de solda, Pedido) E/OU o valor (ex: R$ 150,00):\n"
            "       - FORNEÇA IMEDIATAMENTE os dados oficiais de pagamento da Servweld:\n"
            "         🏢 *Favorecido:* Servweld / Servsolda Equipamentos e Serviços Ltda\n"
            "         🆔 *Chave Pix CNPJ:* 54.804.458/0001-22 (Chave Limpa: 54804458000122)\n"
            "         📋 *Pix Copia e Cola:* 00020126360014br.gov.bcb.pix0114548044580001225204000053039865802BR5914SERVWELD SOLDA6008BRASILIA62070503***6304E6FC\n"
            "       - Peça para ele enviar o comprovante de pagamento neste chat após concluir a transferência.\n"
            "    c) ENVIO DO COMPROVANTE PELO CLIENTE OU NOTIFICAÇÃO DE PAGAMENTO CONCLUÍDO:\n"
            "       - Quando o cliente enviar uma imagem/comprovante ou avisar que já pagou/enviou o comprovante:\n"
            "       - RESPONDA: 'Agradeço pelo envio do comprovante! Recebi o registro de pagamento ref. ao [Assunto/Nota/Serviço] no valor de [Valor]. Estou transferindo agora para a nossa equipe do setor Financeiro conferir e baixar o seu título.'\n"
            "       - DEFINA OBRIGATORIAMENTE 'ESCALAR_HUMANO: SIM'.\n"
            "       - ESCREVA EM 'NOVA_MEMORIA': '📌 COMPROVANTE DE PIX RECEBIDO DO CLIENTE | Assunto/Nota: [Assunto/Nota] | Valor: [Valor] | Comprovante em anexo no chat para conferência do atendente.'\n\n"
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
            "ENVIAR_LOCALIZACAO: <SIM ou NAO>\n"
            "ESCALAR_HUMANO: <SIM ou NAO>\n"
            "NOVA_MEMORIA: <resumo atualizado em 1 ou 2 frases curtas>"
        )

        if not client:
            needs_human = any(word in user_message.lower() for word in ["humano", "atendente", "falar com pessoa"])
            wants_loc = any(word in user_message.lower() for word in ["localizacao", "localização", "endereco", "endereço", "onde fica", "como chegar"])
            target_dept = "NENHUM"
            if available_departments:
                for d in available_departments:
                    if d.lower() != department_name.lower() and d.lower() in user_message.lower():
                        target_dept = d
                        break

            return {
                "resposta": "Olá! Seja muito bem-vindo. Como posso te ajudar hoje?" if not needs_human else "Estou transferindo seu atendimento para um de nossos especialistas.",
                "transferir_setor": target_dept,
                "enviar_localizacao": wants_loc,
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
            enviar_localizacao = False
            escalar_humano = False
            nova_memoria = ""

            for line in text_out.split("\n"):
                if line.startswith("RESPOSTA:"):
                    resposta = line.replace("RESPOSTA:", "").strip()
                elif line.startswith("TRANSFERIR_SETOR:"):
                    transferir_setor = line.replace("TRANSFERIR_SETOR:", "").strip()
                elif line.startswith("ENVIAR_LOCALIZACAO:"):
                    enviar_localizacao = "SIM" in line.upper()
                elif line.startswith("ESCALAR_HUMANO:"):
                    escalar_humano = "SIM" in line.upper()
                elif line.startswith("NOVA_MEMORIA:"):
                    nova_memoria = line.replace("NOVA_MEMORIA:", "").strip()

            if not resposta:
                resposta = text_out

            return {
                "resposta": resposta,
                "transferir_setor": transferir_setor,
                "enviar_localizacao": enviar_localizacao,
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
                "enviar_localizacao": False,
                "escalar_humano": True,
                "nova_memoria": "Erro na IA Concierge, escalado automaticamente para humano.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

    async def process_audio_message(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        """
        Transcribes and understands incoming voice audio messages from customers using Gemini Multimodal SDK.
        Returns the exact transcribed spoken text.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        model_name = tenant_gemini_model_name or "gemini-2.5-flash"

        if not client or not audio_bytes:
            return ""

        try:
            import asyncio
            from google.genai import types

            prompt = "Ouça atentamente a esta mensagem de áudio em português enviada pelo cliente no WhatsApp e faça a transcrição exata e literal do texto falado, sem adicionar comentários ou introdução."

            part = types.Part.from_bytes(
                data=audio_bytes,
                mime_type=mime_type or "audio/ogg"
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=[part, prompt]
            )
            return response.text.strip() if response and response.text else ""
        except Exception as e:
            logger.error(f"Error processing audio message with Gemini SDK: {e}")
            return ""

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
