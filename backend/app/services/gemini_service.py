import logging
import json
import re
import asyncio
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

    async def evaluate_department_routing(
        self,
        customer_name: str,
        current_department_name: str,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        departments: List[Dict[str, Any]],
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluates customer intent against explicit department boundaries defined in Seção 0.
        Calculates dynamic confidence score (0.0 to 1.0) and handles out-of-scope fallback safely.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"

        dept_descriptions_text = "\n".join([
            f"• SETOR: '{d.get('nome_departamento') or d.get('nome')}' (ID: {d.get('id')}):\n  {d.get('descricao_roteamento') or d.get('descricao')}"
            for d in departments
        ])

        system_instruction = (
            "Você é o Especialista de Triagem e Roteamento de Atendimento da empresa Servweld (Equipamentos de Solda, Corte, Assistência e Locação).\n"
            "Sua única função é classificar a real necessidade do cliente e determinar com máxima precisão o departamento correto.\n\n"
            "DIRETRIZES DE FRONTEIRA ENTRE DEPARTAMENTOS (SEÇÃO 0 - REGRAS DE NEGÓCIO GLOBAIS):\n\n"
            f"{dept_descriptions_text}\n\n"
            "REGRAS CRÍTICAS DE DESAMBIGUAÇÃO DE FRONTEIRA:\n"
            "1. LOCAÇÃO vs ASSISTÊNCIA TÉCNICA:\n"
            "   - Se o problema/defeito for em uma máquina ou item ALUGADO ('aluguei', 'máquina alugada', 'equipamento da locação', 'aluguel') -> Destino OBRIGATÓRIO: 'Locação'.\n"
            "   - Se o problema/defeito for em um produto COMPRADO pelo cliente (propriedade dele, garantia de compra, reparo de item próprio) -> Destino OBRIGATÓRIO: 'Assistência Técnica'.\n"
            "2. LOCAÇÃO vs FINANCEIRO:\n"
            "   - Se o cliente perguntar sobre valor de aluguel, prorrogação/renovação de contrato de locação ou parcelas do aluguel -> Destino OBRIGATÓRIO: 'Locação'.\n"
            "   - Se o cliente tratar de boletos bancários vencidos, notas fiscais, cobrança de dívidas gerais, estorno ou comprovante de pagamento de compras -> Destino OBRIGATÓRIO: 'Financeiro'.\n"
            "3. VENDAS vs OUTROS:\n"
            "   - Orçamentos de produtos novos, cotação de preços de venda, estoque de itens novos, compra de novos equipamentos -> Destino OBRIGATÓRIO: 'Vendas e E-commerce'.\n"
            "4. FORA DO ESCOPO OU MENSAGEM VAGA (REGRA DE FALLBACK / NÃO-FORÇAR DEPARTAMENTO):\n"
            "   - Se a mensagem do cliente NÃO tiver relação com produtos/serviços de solda, locação, assistência ou financeiro da empresa (ex: pedir comida, perguntar sobre outros assuntos, trânsito, piadas) OU for apenas uma saudação genérica vaga (ex: 'oi', 'bom dia') que ainda não revela a necessidade:\n"
            "     * NÃO force nenhum departamento!\n"
            "     * Defina: target_department_id = null, target_department_name = 'NENHUM', needs_transfer = false, requires_clarification = true, confidence = 0.0 a 0.3.\n\n"
            "CALIBRAÇÃO DINÂMICA DO CAMPO 'confidence' (NÃO USE VALOR FIXO):\n"
            "- 0.90 a 1.00: Intenção cristalina, explícita e inequívoca com termos diretos do setor.\n"
            "- 0.60 a 0.89: Intenção provável, mas com detalhes parciais ou ligeira ambiguidade contextual.\n"
            "- 0.20 a 0.59: Muito vaga, incompleta ou com sinais contraditórios.\n"
            "- 0.00: Totalmente fora do escopo do negócio ou irrelevante."
        )

        messages_text = []
        for msg in conversation_history[-4:]:
            role = "Cliente" if msg.get("remetente") == "cliente" else "Atendente/IA"
            messages_text.append(f"{role}: {msg.get('conteudo', '')}")

        full_prompt = (
            f"{system_instruction}\n\n"
            f"Setor Atual da Conversa: '{current_department_name}'\n"
            f"Cliente: '{customer_name or 'Cliente'}'\n"
            f"Histórico Recente:\n" + ("\n".join(messages_text) if messages_text else "Sem histórico anterior.") + "\n\n"
            f"Mensagem Atual do Cliente: \"{user_message}\"\n\n"
            "Responda ESTRITAMENTE em formato JSON com o seguinte schema:\n"
            "```json\n"
            "{\n"
            '  "target_department_id": <int ou null>,\n'
            '  "target_department_name": "<NomeExatoDoSetor ou NENHUM>",\n'
            '  "needs_transfer": <true ou false>,\n'
            '  "requires_clarification": <true ou false>,\n'
            '  "confidence": <float real calculado entre 0.0 e 1.0>,\n'
            '  "reason": "<justificativa concisa baseada nas regras>",\n'
            '  "customer_intent_summary": "<resumo da necessidade em 1 frase>"\n'
            "}\n"
            "```"
        )

        if not client:
            return {
                "target_department_id": None,
                "target_department_name": current_department_name,
                "needs_transfer": False,
                "requires_clarification": False,
                "confidence": 0.0,
                "reason": "Sem cliente Gemini configurado.",
                "customer_intent_summary": user_message
            }

        models_to_try = [primary_model]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        last_error = None
        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=full_prompt
                )
                raw_text = response.text.strip()
                
                # Extract JSON block
                json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(1))
                else:
                    json_start = raw_text.find("{")
                    json_end = raw_text.rfind("}")
                    if json_start != -1 and json_end != -1:
                        parsed = json.loads(raw_text[json_start:json_end+1])
                    else:
                        raise ValueError(f"No JSON found in response: {raw_text}")

                # Ensure confidence is float
                parsed["confidence"] = float(parsed.get("confidence", 0.0))

                t_name = str(parsed.get("target_department_name", "")).lower()
                if t_name in ("nenhum", "null", "none", "") or parsed.get("target_department_id") is None:
                    parsed["target_department_id"] = None
                    parsed["target_department_name"] = "NENHUM"
                    parsed["needs_transfer"] = False
                else:
                    for d in departments:
                        d_name = (d.get("nome_departamento") or d.get("nome") or "").lower()
                        if d_name in t_name or t_name in d_name:
                            parsed["target_department_id"] = d.get("id")
                            parsed["target_department_name"] = d.get("nome_departamento") or d.get("nome")
                            break

                    if current_department_name.lower() in str(parsed.get("target_department_name", "")).lower():
                        parsed["needs_transfer"] = False

                return parsed
            except Exception as e:
                last_error = e
                logger.warning(f"Model '{m_name}' error: {e}. Trying fallback if available...")
                await asyncio.sleep(0.5)

        logger.error(f"All Gemini models failed for department routing: {last_error}")
        return {
            "target_department_id": None,
            "target_department_name": current_department_name,
            "needs_transfer": False,
            "requires_clarification": True,
            "confidence": 0.0,
            "reason": f"Erro de roteamento: {last_error}",
            "customer_intent_summary": user_message
        }

    async def classify_confirmation_response(
        self,
        question_asked: str,
        customer_response: str,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        """
        Classifies customer response to a confirmation question as 'CONFIRMA', 'NEGA', or 'AMBIGUA' using Gemini.
        Understands natural Brazilian Portuguese subtleties (e.g. 'não, é isso mesmo', 'beleza 👍', 'show', 'manda ver', 'não precisa', 'talvez').
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.6-flash"

        prompt = (
            "Você é um classificador semântico de linguagem natural em português brasileiro.\n"
            "Analise a pergunta de confirmação que o sistema fez ao cliente e a resposta enviada pelo cliente no WhatsApp.\n\n"
            f"Pergunta Feita ao Cliente: \"{question_asked}\"\n"
            f"Resposta Enviada pelo Cliente: \"{customer_response}\"\n\n"
            "Classifique a resposta do cliente ESTRITAMENTE em uma das 3 categorias:\n"
            "- CONFIRMA: O cliente aceita, concorda, confirma a transferência ou diz que é isso mesmo (ex: 'sim', 'correto', 'isso', 'pode transferir', 'não, é isso mesmo', 'beleza', 'manda ver', '👍', 'show', 'por favor', 'bora').\n"
            "- NEGA: O cliente recusa a transferência, diz que é outro assunto, que não precisa ou que está errado (ex: 'não', 'nada a ver', 'é outro assunto', 'não quero vendas', 'errou', 'não precisa').\n"
            "- AMBIGUA: O cliente demonstra incerteza, hesitação, responde com algo desconexo ou pergunta algo novo sem confirmar nem negar (ex: 'talvez', 'não sei', 'quanto custa antes?', 'quem sabe').\n\n"
            "Responda APENAS com uma única palavra: CONFIRMA, NEGA ou AMBIGUA."
        )

        if not client:
            clean = customer_response.strip().lower()
            if any(w in clean for w in ["sim", "isso", "correto", "pode", "ok", "beleza"]):
                return "CONFIRMA"
            elif any(w in clean for w in ["não", "nao", "outro", "errado"]):
                return "NEGA"
            return "AMBIGUA"

        models_to_try = [primary_model]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=prompt
                )
                res_text = response.text.strip().upper()
                if "CONFIRMA" in res_text:
                    return "CONFIRMA"
                elif "NEGA" in res_text:
                    return "NEGA"
                else:
                    return "AMBIGUA"
            except Exception as e:
                logger.warning(f"Error classifying confirmation with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return "AMBIGUA"

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
        department_descriptions: Optional[Dict[str, str]] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"

        dept_desc_prompt = ""
        if department_descriptions:
            dept_desc_prompt = "\nFRONTEIRAS DOS DEPARTAMENTOS (SEÇÃO 0):\n" + "\n".join([
                f"- '{k}': {v}" for k, v in department_descriptions.items()
            ]) + "\n"

        dept_list_str = ", ".join(available_departments) if available_departments else department_name

        system_instruction = (
            f"Você é a IA Concierge de atendimento da empresa Servweld.\n"
            f"Setor atual do atendimento: '{department_name}'. Setores ativos na empresa: [{dept_list_str}].\n"
            f"{dept_desc_prompt}"
            f"Atenda o cliente '{customer_name or 'Cliente'}' com extrema polidez, fluidez, objetividade e empatia.\n\n"
            "DIRETRIZES FUNDAMENTAIS DE CONVERSAÇÃO E FLUXO CONSTITUÍDO (COMEÇO, MEIO E FIM):\n"
            "1. SEM MENUS ROBÓTICOS OU NUMÉRICOS: Proibido 'Digite 1 para X, 2 para Y'. Dialogue de forma 100% natural.\n"
            "2. ANÁLISE DE HISTÓRICO ANTERIOR E REABERTURA EM ATÉ 5 DIAS (OBRIGATÓRIO NA RESPOSTA):\n"
            "   - Verifique o 'HISTÓRICO ANTERIOR/MEMÓRIA RESUMIDA DA CONVERSA' fornecido abaixo.\n"
            "   - SE HOUVER HISTÓRICO ANTERIOR RECENTE E A MENSAGEM DO CLIENTE FOR APENAS UMA SAUDAÇÃO VAGA (ex: 'Oi', 'Olá', 'Bom dia', 'Tudo bem?'):\n"
            "     * SUA RESPOSTA AO CLIENTE DEVE OBRIGATORIAMENTE CITAR O ASSUNTO ANTERIOR E FAZER A PERGUNTA DE RETOMADA!\n"
            "     * Formato obrigatório: 'Olá, [Nome]! Tudo bem? Vi que conversamos recentemente sobre [resumo do assunto tratado antes]. Você gostaria de continuar esse assunto ou precisa de ajuda com uma nova solicitação?'\n"
            "     * NUNCA envie apenas uma saudação vazia se houver histórico anterior recente!\n"
            "   - CONTINUIDADE DIRETA: Se o cliente já indicar continuidade explícita daquele assunto, reconheça imediatamente sem pedir para repetir.\n"
            "   - NOVO ASSUNTO: Se o cliente indicar um novo tema, faça a recepção do novo assunto normalmente.\n"
            "3. FORA DO ESCOPO: Se o cliente fizer perguntas totalmente desconexas com a empresa (ex: 'Vocês vendem pizza?'), esclareça gentilmente os serviços e produtos que a Servweld atende (equipamentos de solda, corte, assistência, locação e financeiro).\n"
            "4. TROCA DE SETOR: Se o cliente necessitar de outro setor com base nas fronteiras (ex: problema em máquina alugada -> Locação; dúvida de boleto -> Financeiro), informe gentilmente a mudança, defina 'TRANSFERIR_SETOR: <NomeExatoDoSetor>', MANTENHA 'ESCALAR_HUMANO: NAO' e solicite os dados do novo setor em bloco.\n"
            "5. PERGUNTA DE CHECAGEM PRÉ-TRANSFERÊNCIA: Quando você constatar que o RAG não tem a solução ou o cliente pedir atendente humano, PERGUNTE PRIMEIRO:\n"
            "   'Antes de te encaminhar para o especialista humano do setor, teria mais alguma informação ou detalhe que você gostaria de acrescentar ao seu chamado?'\n"
            "6. CONCLUSÃO DA IA E ESCALONAMENTO HUMANO: Assim que o cliente responder à pergunta de checagem (ou se já tiver fornecido todas as informações), encerre a resposta com a fala conclusiva final e defina 'ESCALAR_HUMANO: SIM'.\n"
            "7. RESUMO EXECUTIVO DO PROBLEMA: Quando definir 'ESCALAR_HUMANO: SIM', escreva em 'NOVA_MEMORIA' um RESUMO COMPLETO E ESTRUTURADO DO PROBLEMA ESPECÍFICO do cliente que o atendente humano precisará resolver.\n"
            "8. SOLICITAÇÃO DE LOCALIZAÇÃO DA LOJA: Se o cliente pedir o endereço ou localização, além de fornecer o texto na resposta, defina 'ENVIAR_LOCALIZACAO: SIM'.\n"
            "9. ENDEREÇO OFICIAL DA SERVWELD: 'SOF Sul (Setor de Oficinas Sul), Quadra 05, Conjunto A, Lote 05, Loja 02 - Guará, Brasília - DF - CEP 71215-226'. Coordenadas GPS: Latitude -15.820418, Longitude -47.956467.\n"
            "10. FLUXO DE PAGAMENTO VIA PIX: Se o cliente pedir Pix, pergunte a nota/assunto e valor antes de enviar os dados oficiais CNPJ 54.804.458/0001-22.\n"
            "11. ATENDIMENTO 24/7 E RESOLUÇÃO AUTÔNOMA DA IA (NÃO ADIAR O QUE A IA PODE RESOLVER):\n"
            "   - Você opera 24 horas por dia, 7 dias por semana.\n"
            "   - Se o cliente fizer perguntas que você ou a base de conhecimento RAG podem resolver (ex: endereço da loja, horário de funcionamento, dúvidas técnicas sobre solda, catálogo de produtos, assistência ou formas de pagamento):\n"
            "     * RESPONDA A DÚVIDA IMEDIATAMENTE DE FORMA COMPLETA, NATURAL E CORDIAL.\n"
            "     * DEFINA 'ESCALAR_HUMANO: NAO'.\n"
            "     * NUNCA adie para o dia seguinte nem informe que a loja está fechada se a IA puder resolver a solicitação sozinha!\n"
            "   - SOMENTE defina 'ESCALAR_HUMANO: SIM' quando a demanda genuinamente exigir intervenção humana (ex: negociação de preços/descontos, fechamento de contrato complexo, liberação de crédito ou quando o cliente pedir explicitamente para falar com uma pessoa).\n"
            "12. COLETA CORDIAL DE NOME:\n"
            "   - Se o cliente ainda não informou o nome (nome está como 'Cliente' ou número), dê as boas-vindas e pergunte gentilmente o nome dele para um atendimento personalizado.\n\n"
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
            "ENVIAR_PIX: <SIM ou NAO>\n"
            "ESCALAR_HUMANO: <SIM ou NAO>\n"
            "NOVA_MEMORIA: <resumo atualizado em 1 ou 2 frases curtas>"
        )

        if not client:
            needs_human = any(word in user_message.lower() for word in ["humano", "atendente", "falar com pessoa"])
            wants_loc = any(word in user_message.lower() for word in ["localizacao", "localização", "endereco", "endereço", "onde fica", "como chegar"])
            wants_pix = any(word in user_message.lower() for word in ["pix", "chave pix", "pode enviar"])
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
                "enviar_pix": wants_pix,
                "escalar_humano": needs_human,
                "nova_memoria": f"Cliente perguntou: '{user_message}'",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        models_to_try = [primary_model]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        last_error = None
        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
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
                enviar_pix = False
                escalar_humano = False
                nova_memoria = ""

                for line in text_out.split("\n"):
                    if line.startswith("RESPOSTA:"):
                        resposta = line.replace("RESPOSTA:", "").strip()
                    elif line.startswith("TRANSFERIR_SETOR:"):
                        transferir_setor = line.replace("TRANSFERIR_SETOR:", "").strip()
                    elif line.startswith("ENVIAR_LOCALIZACAO:"):
                        enviar_localizacao = "SIM" in line.upper()
                    elif line.startswith("ENVIAR_PIX:"):
                        enviar_pix = "SIM" in line.upper()
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
                    "enviar_pix": enviar_pix,
                    "escalar_humano": escalar_humano,
                    "nova_memoria": nova_memoria or memory_summary or f"Cliente interagiu sobre: {user_message[:50]}",
                    "tokens": {
                        "prompt_tokens": prompt_tokens,
                        "response_tokens": response_tokens,
                        "total_tokens": total_tokens
                    }
                }
            except Exception as e:
                last_error = e
                logger.warning(f"Model '{m_name}' error: {e}. Trying fallback if available...")
                await asyncio.sleep(0.5)

        logger.error(f"All Gemini models failed for concierge: {last_error}")
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
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not client or not audio_bytes or len(audio_bytes) < 50:
            return {
                "transcription": "",
                "success": False,
                "fallback_message": "Não consegui compreender o áudio. Você poderia enviar sua mensagem por escrito ou gravar um novo áudio?",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        from google.genai import types

        prompt = (
            "Ouça atentamente este áudio em português enviado no WhatsApp. "
            "Transcreva exatamente o que foi falado pelo cliente, sem introduções ou comentários."
        )

        part = types.Part.from_bytes(
            data=audio_bytes,
            mime_type=mime_type or "audio/ogg"
        )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=[part, prompt]
                )
                text_out = response.text.strip() if response and response.text else ""
                usage = getattr(response, "usage_metadata", None)
                p_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
                c_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
                t_tokens = getattr(usage, "total_token_count", 0) if usage else 0

                if text_out:
                    return {
                        "transcription": text_out,
                        "success": True,
                        "fallback_message": None,
                        "model_used": m_name,
                        "tokens": {"prompt_tokens": p_tokens, "response_tokens": c_tokens, "total_tokens": t_tokens}
                    }
            except Exception as e:
                logger.warning(f"Error processing audio with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "transcription": "",
            "success": False,
            "fallback_message": "Não consegui compreender o áudio com clareza. Você poderia enviar sua mensagem por escrito ou gravar um novo áudio?",
            "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
        }

    async def process_image_message(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        context_prompt: Optional[str] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not client or not image_bytes or len(image_bytes) < 50:
            return {
                "analysis": "",
                "success": False,
                "fallback_message": "Não foi possível visualizar a imagem com nitidez. Por favor, envie uma foto mais nítida ou informe os dados por texto.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        from google.genai import types

        prompt = context_prompt or (
            "Analise esta imagem enviada pelo cliente no WhatsApp da empresa Servweld (equipamentos e serviços de solda).\n"
            "- Se for um comprovante de pagamento / PIX / nota fiscal: extraia o valor, favorecido, data e status da transação.\n"
            "- Se for uma foto de máquina, tocha, cabo, peça ou equipamento de solda: descreva o modelo visível e identifique se há defeito aparente, código de erro no display ou desgaste visível.\n"
            "- Se for uma foto de placa de identificação técnica: extraia a voltagem, amperagem, número de série e modelo."
        )

        part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type or "image/jpeg"
        )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=[part, prompt]
                )
                text_out = response.text.strip() if response and response.text else ""
                usage = getattr(response, "usage_metadata", None)
                p_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
                c_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
                t_tokens = getattr(usage, "total_token_count", 0) if usage else 0

                if text_out:
                    return {
                        "analysis": text_out,
                        "success": True,
                        "fallback_message": None,
                        "model_used": m_name,
                        "tokens": {"prompt_tokens": p_tokens, "response_tokens": c_tokens, "total_tokens": t_tokens}
                    }
            except Exception as e:
                logger.warning(f"Error processing image with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "analysis": "",
            "success": False,
            "fallback_message": "Não foi possível visualizar a imagem com nitidez. Por favor, envie uma foto mais nítida ou informe os dados por texto.",
            "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
        }

    async def process_document_message(
        self,
        doc_bytes: bytes,
        mime_type: str = "application/pdf",
        context_prompt: Optional[str] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not client or not doc_bytes or len(doc_bytes) < 30:
            return {
                "extracted_content": "",
                "success": False,
                "fallback_message": "Não foi possível extrair o conteúdo deste documento PDF. Por favor, reenvie o arquivo ou nos informe os dados por texto.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        from google.genai import types

        prompt = context_prompt or (
            "Leia e analise o documento PDF em anexo enviado pelo cliente. "
            "Extraia os principais dados relevantes (número do pedido/fatura/proposta, itens solicitados, valores, especificações técnicas de solda e prazos) de forma clara e estruturada."
        )

        part = types.Part.from_bytes(
            data=doc_bytes,
            mime_type=mime_type or "application/pdf"
        )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=[part, prompt]
                )
                text_out = response.text.strip() if response and response.text else ""
                usage = getattr(response, "usage_metadata", None)
                p_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
                c_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
                t_tokens = getattr(usage, "total_token_count", 0) if usage else 0

                if text_out:
                    return {
                        "extracted_content": text_out,
                        "success": True,
                        "fallback_message": None,
                        "model_used": m_name,
                        "tokens": {"prompt_tokens": p_tokens, "response_tokens": c_tokens, "total_tokens": t_tokens}
                    }
            except Exception as e:
                logger.warning(f"Error processing document with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "extracted_content": "",
            "success": False,
            "fallback_message": "Não foi possível extrair o conteúdo deste documento PDF. Por favor, reenvie o arquivo ou nos informe os dados por texto.",
            "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
        }

    async def generate_onboarding_summary(
        self,
        customer_name: str,
        protocol_number: str,
        department_name: str,
        messages_history: List[Dict[str, str]],
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        """
        Generates the structured 'Resumo Onde Parou' system onboarding card (Seção 2).
        Synthesizes customer intent, what was already handled by the AI, and the immediate next recommended action.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not messages_history:
            return (
                f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                f"👤 *Cliente:* {customer_name}\n"
                f"🔢 *Protocolo:* {protocol_number}\n"
                f"🏢 *Departamento:* {department_name}\n"
                f"🎯 *Motivo do Contato:* Novo chamado iniciado pelo cliente.\n"
                f"📍 *Onde Parou:* Início do atendimento.\n"
                f"👉 *Próxima Ação Sugerida:* Enviar saudação inicial e verificar a necessidade do cliente."
            )

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

        prompt = (
            f"Você é o assistente de IA responsável pelo Onboarding do Atendente Humano da empresa Servweld.\n"
            f"Analise a conversa real abaixo entre o cliente e a IA no setor '{department_name}' (Protocolo: {protocol_number}).\n\n"
            "Gere um resumo estruturado no seguinte formato exato:\n"
            f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
            f"👤 *Cliente:* {customer_name}\n"
            f"🔢 *Protocolo:* {protocol_number}\n"
            f"🏢 *Departamento:* {department_name}\n"
            "🎯 *Motivo do Contato:* <resumo em 1 frase factual sobre o que o cliente quer>\n"
            "📍 *Onde Parou:* <o que a IA/cliente já falaram antes de passar para o humano>\n"
            "👉 *Próxima Ação Sugerida:* <orientação prática e direta para o atendente continuar o atendimento sem repetir perguntas já respondidas>\n\n"
            "DIRETRIZES ESTRITAS DE FACTUALIDADE E ANTI-ALUCINAÇÃO:\n"
            f"1. NOME DO CLIENTE: No campo 'Cliente', use EXATAMENTE '{customer_name}'. É PROIBIDO inventar títulos profissionais (Eng., Dr., etc.) ou sobrenomes que não constem expressamente na identificação.\n"
            "2. BASE EXCLUSIVAMENTE FACTUAL: Use apenas o que foi dito nas mensagens reais. É proibido inventar valores, modelos de equipamentos, marcas ou problemas técnicos adicionais.\n"
            "3. Seja direto, profissional e objetivo.\n\n"
            f"HISTÓRICO REAL DA CONVERSA:\n" + "\n".join(messages_text)
        )

        if not client:
            return (
                f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                f"👤 *Cliente:* {customer_name}\n"
                f"🔢 *Protocolo:* {protocol_number}\n"
                f"🏢 *Departamento:* {department_name}\n"
                f"🎯 *Motivo do Contato:* Atendimento transferido para equipe humana.\n"
                f"📍 *Onde Parou:* Transferência solicitada.\n"
                f"👉 *Próxima Ação Sugerida:* Verifique a última mensagem do cliente e dê continuidade."
            )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.1-flash-lite", "gemini-3.6-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=prompt
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Error generating onboarding summary with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return (
            f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
            f"👤 *Cliente:* {customer_name}\n"
            f"🔢 *Protocolo:* {protocol_number}\n"
            f"🏢 *Departamento:* {department_name}\n"
            f"🎯 *Motivo do Contato:* Atendimento transferido para operador.\n"
            f"📍 *Onde Parou:* Transferência efetuada.\n"
            f"👉 *Próxima Ação Sugerida:* Analise o histórico e responda o cliente."
        )

    async def generate_suggested_reply(
        self,
        customer_name: str,
        department_name: str,
        messages_history: List[Dict[str, str]],
        memory_summary: Optional[str] = None,
        rag_context: Optional[str] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        """
        Generates a professional, polite, and helpful draft response suggestion for the human attendant to review and edit before sending (Seção 2 - Botão 'Consultar IA').
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

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

        rag_prompt = f"\nINFORMAÇÕES DA BASE DE CONHECIMENTO DA EMPRESA (RAG):\n{rag_context}\n" if rag_context else ""
        memory_prompt = f"\nRESUMO CONTEXTUAL ANTERIOR DO CLIENTE:\n{memory_summary}\n" if memory_summary else ""

        prompt = (
            "Você é um consultor assistente de atendimento da empresa Servweld (Equipamentos de Solda, Corte, Assistência Técnica e Locação).\n"
            f"O atendente humano do setor '{department_name}' solicitou uma SUGESTÃO DE RESPOSTA para enviar ao cliente '{customer_name}'.\n\n"
            f"{memory_prompt}"
            f"{rag_prompt}"
            "DIRETRIZES DA RESPOSTA:\n"
            "1. Escreva uma mensagem pronta para envio, redigida em primeira pessoa (como se você fosse o atendente humano da Servweld).\n"
            "2. Seja extremamente educado, claro, acolhedor, profissional e direto ao ponto.\n"
            "3. Não use introduções explicativas como 'Aqui está uma sugestão:' ou 'Você pode dizer:'. Retorne APENAS o texto exato da resposta a ser colocada no chat.\n"
            "4. Dê continuidade imediata ao diálogo, respondendo à última dúvida ou solicitação do cliente com base no histórico real.\n"
            "5. Se for necessária uma informação técnica que você não tem certeza, sugira pedir educadamente a informação necessária ao cliente.\n\n"
            f"HISTÓRICO DA CONVERSA:\n" + "\n".join(messages_text)
        )

        if not client:
            return f"Olá {customer_name}, boa tarde! Como posso te ajudar hoje?"

        models_to_try = [primary_model]
        for candidate in ["gemini-3.1-flash-lite", "gemini-3.6-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=prompt
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Error generating suggested reply with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return f"Olá {customer_name}! Recebi sua mensagem e já estou verificando o seu caso para te ajudar."

    async def summarize_conversation_for_transfer(
        self,
        customer_name: str,
        messages_history: List[Dict[str, str]],
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"

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

        models_to_try = [primary_model]
        if "gemini-2.5-flash" not in models_to_try:
            models_to_try.append("gemini-2.5-flash")

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=full_prompt
                )
                return response.text.strip() or "Resumo não gerado devido ao formato de saída da IA."
            except Exception as e:
                logger.warning(f"Error generating transfer summary with '{m_name}': {e}")
                await asyncio.sleep(0.5)

        return (
            f"• 🎯 **Objetivo Principal**: Transferência de atendimento de {customer_name}.\n"
            f"• 📝 **Histórico**: Conversa transferida com histórico disponível.\n"
            f"• ⚡ **Próximo Passo**: Analise as mensagens anteriores."
        )

gemini_service = GeminiService()
