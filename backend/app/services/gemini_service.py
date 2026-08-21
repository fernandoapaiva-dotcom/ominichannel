import logging
import json
import re
import asyncio
from typing import Dict, Any, List, Optional
from google import genai
from app.core.config import settings

logger = logging.getLogger("gemini_service")

# =========================================================================
# CENTRALIZED CUSTOMER NAME SANITIZATION & ANTI-HALLUCINATION DIRECTIVES
# =========================================================================

def sanitize_customer_name(name: Optional[str]) -> str:
    """
    Centralized anti-hallucination sanitizer for customer names across the entire system.
    Strips hallucinated prefixes (Eng., Dr., Sr., Prof., Adv., etc.), quotes, extra symbols,
    and returns a clean, factual customer name (or 'Cliente' if missing/empty).
    """
    if not name or not isinstance(name, str):
        return "Cliente"
    
    clean = name.strip()
    if not clean or clean.lower() in ["none", "null", "undefined", "cliente", "contato", "usuário", "usuario"]:
        return "Cliente"

    # Strip surrounding quotes or parentheses
    clean = re.sub(r'^[\s"\'`\(\[\{]+|[\s"\'`\)\]\}]+$', '', clean).strip()

    # Regex to remove hallucinated professional/honorific titles at the beginning of the name
    title_pattern = r'^(?:(?:eng(?:enheiro|enheira|º|ª)?\.?)|(?:dr(?:a|ª|º)?\.?)|(?:doutor(?:a)?\.?)|(?:sr(?:a|ª)?\.?)|(?:senhor(?:a)?\.?)|(?:prof(?:essor|essora)?\.?)|(?:adv(?:ogado|ogada)?\.?))\s+'
    clean = re.sub(title_pattern, '', clean, flags=re.IGNORECASE).strip()

    if not clean or len(clean) < 2:
        return "Cliente"

    # If the contact is an internal device/branch name (e.g., "Servweld Assistência Técnica", "Servsolda Locação"), return "Cliente"
    internal_keywords = [
        "servweld", "servsolda", "assistência técnica", "assistencia tecnica",
        "locação e corte", "locacao e corte", "financeiro servweld", "vendas e e-commerce"
    ]
    if any(k in clean.lower() for k in internal_keywords):
        return "Cliente"

    return clean

def is_bot_or_menu_message(text: str) -> bool:
    """
    Detects if the incoming message is an automated IVR/URA menu, bot, or other company's automated system
    to avoid infinite loops between AIs.
    """
    if not text or not isinstance(text, str):
        return False
    lower = text.lower()
    patterns = [
        r'digite\s+\d+',
        r'escolha\s+(?:uma\s+)?(?:das\s+)?opç(?:ão|ões)',
        r'menu\s+principal',
        r'autoatendimento',
        r'assistente\s+virtual',
        r'sou\s+a\s+(?:ia|robô|assistente|inteligência)',
        r'atendimento\s+eletr[oô]nico',
        r'n[aã]o\s+responda\s+a\s+est[ea]\s+mensagem',
        r'\[\s*\d+\s*\]\s*[-–—:]\s*\w+',
        r'1\s*[-–—:]\s*\w+.*\n.*2\s*[-–—:]\s*\w+',
        r'protocolo\s+de\s+atendimento\s*:\s*\d{4,}',
        r'para\s+(?:falar|solicitar|consultar).*\s+digite',
        r'hor[aá]rio\s+de\s+atendimento.*das\s+\d+h\s+às\s+\d+h',
        r'selecione\s+uma\s+das\s+opções',
        r'opção\s+\d+:'
    ]
    for p in patterns:
        if re.search(p, lower):
            return True
    return False

CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE = (
    "=== REGRA MANDATÓRIA CENTRAL: NOME DO CLIENTE & ANTI-ALUCINAÇÃO ===\n"
    "1. NUNCA invente, deduza ou adicione títulos profissionais, honoríficos ou acadêmicos (tais como 'Eng.', 'Dr.', 'Engenheiro', 'Doutor', 'Sr.', 'Sra.', 'Prof.', 'Advogado', etc.).\n"
    "2. NUNCA invente sobrenomes, cargos ou apelidos que não tenham sido expressamente declarados pelo próprio cliente.\n"
    "3. Se o cliente apenas informou um primeiro nome (ex: 'Marcos'), use ESTRITAMENTE E APENAS 'Marcos'. É ESTRITAMENTE PROIBIDO inventar 'Eng. Marcos', 'Sr. Marcos' ou 'Marcos Roberto'.\n"
    "4. Se o nome não foi informado ou for genérico ('Cliente'), trate o usuário cordialmente como 'Cliente' sem inventar nenhum nome próprio.\n"
    "===================================================================\n"
)

RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE = (
    "=== REGRA MANDATÓRIA CENTRAL: PREÇOS, PRODUTOS & ANTI-ALUCINAÇÃO DE VALORES ===\n"
    "1. PREÇOS E CONDIÇÕES SÓ COM FONTE REAL: Você SOMENTE pode informar valores em R$, preços de venda, locação ou condições comerciais se constarem EXPRESSAMENTE na 'BASE DE CONHECIMENTO RAG' fornecida.\n"
    "2. PROIBIÇÃO ABSOLUTA DE ESTIMAR OU INVENTAR PREÇOS: Se o cliente perguntar o valor de um item, serviço ou máquina e o preço NÃO estiver na Base RAG, É ESTRITAMENTE PROIBIDO inventar, supor ou estimar um número!\n"
    "3. COMPORTAMENTO QUANDO O PREÇO NÃO CONSTA NO RAG: Responda gentilmente que no momento você não tem o valor exato cadastrado e que vai confirmar a cotação atualizada diretamente com a equipe do setor, oferecendo encaminhar ou verificar com um especialista.\n"
    "=================================================================================\n"
)


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
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"
        clean_name = sanitize_customer_name(customer_name)

        dept_descriptions_text = "\n".join([
            f"• SETOR: '{d.get('nome_departamento') or d.get('nome')}' (ID: {d.get('id')}):\n  {d.get('descricao_roteamento') or d.get('descricao')}"
            for d in departments
        ])

        system_instruction = (
            "Você é o Especialista de Triagem e Roteamento de Atendimento da empresa Servweld (Equipamentos de Solda, Corte, Assistência e Locação).\n"
            "Sua única função é classificar a real necessidade do cliente e determinar com máxima precisão o departamento correto.\n\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
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
            "     * Defina: target_department_id = null, target_department_name = 'NENHUM', needs_transfer = false, requires_clarification = true, confidence = 0.0 a 0.3.\n"
            "5. REGRA MANDATÓRIA DE PERMANÊNCIA NO SETOR ATUAL (PROIBIÇÃO DE TRANSFERÊNCIAS INDEVIDAS):\n"
            "   - NUNCA use o nome do contato cadastrado na agenda (ex: se o contato contiver 'Assistência Técnica' ou 'Vendas' no nome) para decidir o setor! O setor depende 100% da mensagem do cliente.\n"
            f"   - Se o cliente perguntar por um atendente/colaborador específico (ex: 'Consigo falar com o Fernando?', 'Quero falar com um humano', 'Me passa para um atendente', 'Pode me atender?'), ISSO NUNCA É MOTIVO DE TRANSFERÊNCIA DE SETOR!\n"
            f"   - O atendimento DEVE PERMANECER NO SETOR ATUAL ('{current_department_name}')!\n"
            "     * Defina: needs_transfer = false, target_department_id = null, target_department_name = 'NENHUM', confidence = 0.0.\n"
            "   - SOMENTE transfira se a mensagem do cliente contiver expressamente palavras-chave e intenção técnica/comercial clara de OUTRO setor diferente do atual.\n\n"
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
            f"Cliente: '{clean_name}'\n"
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
                "confidence": 0.5,
                "reason": "Cliente Gemini não inicializado",
                "customer_intent_summary": "Triagem padrão de atendimento"
            }

        models_to_try = [primary_model]
        for candidate in ["gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=full_prompt
                )
                if response and response.text:
                    clean_text = response.text.strip()
                    if "```json" in clean_text:
                        clean_text = clean_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_text:
                        clean_text = clean_text.split("```")[1].split("```")[0].strip()
                    
                    data = json.loads(clean_text)
                    return {
                        "target_department_id": data.get("target_department_id"),
                        "target_department_name": data.get("target_department_name") or current_department_name,
                        "needs_transfer": bool(data.get("needs_transfer", False)),
                        "requires_clarification": bool(data.get("requires_clarification", False)),
                        "confidence": float(data.get("confidence", 0.8)),
                        "reason": str(data.get("reason", "Avaliação de intenção concluída")),
                        "customer_intent_summary": str(data.get("customer_intent_summary", "Atendimento geral"))
                    }
            except Exception as e:
                logger.warning(f"Error evaluating department routing with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "target_department_id": None,
            "target_department_name": current_department_name,
            "needs_transfer": False,
            "requires_clarification": False,
            "confidence": 0.5,
            "reason": "Fallback após falha de classificação",
            "customer_intent_summary": "Atendimento padrão"
        }

    async def generate_rag_response(
        self,
        customer_name: str,
        department_name: str,
        user_message: str,
        rag_context: str,
        conversation_history: List[Dict[str, str]],
        tenant_prompt: Optional[str] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"
        clean_name = sanitize_customer_name(customer_name)

        messages_text = []
        for msg in conversation_history[-4:]:
            role = "Cliente" if msg["remetente"] == "cliente" else "Atendente/IA"
            messages_text.append(f"{role}: {msg['conteudo']}")

        system_instruction = (
            f"Você é a IA de Atendimento da empresa Servweld (Setor: {department_name}).\n"
            f"Atenda o cliente '{clean_name}' com extrema cordialidade e precisão técnica.\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{tenant_prompt or 'Resolva dúvidas com base estritamente no contexto da base de conhecimento da empresa.'}\n\n"
            f"BASE DE CONHECIMENTO RAG:\n{rag_context}"
        )

        full_prompt = (
            f"{system_instruction}\n\n"
            f"Histórico Recente:\n" + "\n".join(messages_text) + "\n\n"
            f"Mensagem Atual do Cliente: {user_message}\n\n"
            "Responda de forma clara, natural e prestativa:"
        )

        if not client:
            return f"Olá {clean_name}! Como posso te ajudar hoje?"

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
                return response.text.strip()
            except Exception as e:
                logger.warning(f"Error generating RAG response with '{m_name}': {e}")
                await asyncio.sleep(0.5)

        return f"Olá {clean_name}! Em que posso te ajudar hoje?"

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
        protocol_number: Optional[str] = None,
        should_announce_protocol: bool = False,
        is_technician_or_admin: bool = False,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"
        clean_name = sanitize_customer_name(customer_name)

        dept_desc_prompt = ""
        if department_descriptions:
            dept_desc_prompt = "\nFRONTEIRAS DOS DEPARTAMENTOS (SEÇÃO 0):\n" + "\n".join([
                f"- '{k}': {v}" for k, v in department_descriptions.items()
            ]) + "\n"

        dept_list_str = ", ".join(available_departments) if available_departments else department_name

        proto_prompt = ""
        if protocol_number:
            if should_announce_protocol:
                proto_prompt = f"PROTOCOLO OFICIAL DESTE ATENDIMENTO: #{protocol_number}\n- REGRA OBRIGATÓRIA: Como é a abertura deste atendimento, mencione o protocolo formal logo no início da mensagem (ex: '📋 Protocolo: #{protocol_number}').\n\n"
            else:
                proto_prompt = f"PROTOCOLO OFICIAL DESTE ATENDIMENTO: #{protocol_number}\n\n"

        if is_technician_or_admin:
            tech_directive = (
                "\n"
                "=========================================================================================\n"
                f"🛡️ MODO COPILOTO TÉCNICO INTERNO / ENGENHARIA DE BANCADA ATIVADO (USUÁRIO: {clean_name})\n"
                "=========================================================================================\n"
                "- Você está conversando com um TÉCNICO AUTORIZADO DA SERVWELD OU ADMINISTRADOR DO SISTEMA.\n"
                "- SEU PAPEL: Atue como Engenheiro Eletrônico Especialista e Copiloto Técnico de Bancada.\n"
                "- LIBERAÇÃO COMPLETA DE DIAGNÓSTICO E REPARO: Ajude o técnico em todos os procedimentos de bancada, testes de circuito, leitura de diagramas e esquemas elétricos, medição de componentes (IGBTs, MOSFETs, pontes retificadoras, osciladores PWM, transformadores, sensores Hall, shunts, circuitos snubber), calibração e análise de falhas.\n"
                "- USO DA BASE RAG E MANUAIS: Extraia da base de conhecimento RAG todos os manuais técnicos, diagramas esquemáticos, pinagens, tensões de gate e testes passo a passo para orientar o técnico de forma precisa e aprofundada.\n"
                "- Responda com linguagem técnica profissional (eletrônica de potência, circuitos de controle, formas de onda, pontos de teste).\n"
                "=========================================================================================\n"
            )
        else:
            tech_directive = (
                "\n"
                "=========================================================================================\n"
                "🔒 REGRA ESTRITA DE PROTEÇÃO DE NEGÓCIO E SEGURANÇA - ATENDIMENTO A CLIENTE EXTERNO\n"
                "=========================================================================================\n"
                "- Você está atendendo um CLIENTE COMUM / EXTERNO da Servweld.\n"
                "- PROIBIÇÃO ABSOLUTA DE INSTRUÇÕES DE REPARO/CONSERTO: NUNCA ensine o cliente a abrir máquinas, consertar placas, medir circuitos eletrônicos internos ou trocar peças por conta própria. Isso traz risco severo de acidentes elétricos graves e elimina a demanda de serviços da assistência técnica da loja.\n"
                "- PROCEDIMENTO PERMITIDO COM O CLIENTE:\n"
                "  1. Se o cliente relatar um código de erro ou defeito (ex: LED de sobreaquecimento aceso, código E01/E02, máquina desarmando disjuntor): Você pode apenas explicar brevemente o significado geral do erro em alto nível (ex: 'O código E01 indica uma proteção ativada por sobreaquecimento ou anomalia no circuito de potência').\n"
                "  2. CONVITE PARA ASSISTÊNCIA TÉCNICA: Convide e oriente o cliente a trazer ou enviar a máquina para o laboratório especializado da Servweld, onde nossos técnicos qualificados farão o teste e orçamento com garantia e peças originais.\n"
                "  3. Forneça o endereço da loja e horários de recebimento de equipamentos.\n"
                "=========================================================================================\n"
            )

        system_instruction = (
            f"Você é a IA Concierge de atendimento da empresa Servweld.\n"
            f"Setor atual do atendimento: '{department_name}'. Setores ativos na empresa: [{dept_list_str}].\n"
            f"{dept_desc_prompt}"
            f"{proto_prompt}"
            f"{tech_directive}"
            f"Atenda o interlocutor '{clean_name}' com extrema polidez, fluidez, objetividade e empatia.\n\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE}\n"
            "DIRETRIZES FUNDAMENTAIS DE CONVERSAÇÃO E FLUXO CONSTITUÍDO (COMEÇO, MEIO E FIM):\n"
            "1. SEM MENUS ROBÓTICOS OU NUMÉRICOS: Proibido 'Digite 1 para X, 2 para Y'. Dialogue de forma 100% natural.\n"
            "2. ANÁLISE DE HISTÓRICO ANTERIOR E REABERTURA EM ATÉ 5 DIAS (OBRIGATÓRIO NA RESPOSTA):\n"
            "   - Verifique o 'HISTÓRICO ANTERIOR/MEMÓRIA RESUMIDA DA CONVERSA' fornecido abaixo.\n"
            "   - SE HOUVER HISTÓRICO ANTERIOR RECENTE E A MENSAGEM DO CLIENTE FOR APENAS UMA SAUDAÇÃO VAGA (ex: 'Oi', 'Olá', 'Bom dia', 'Tudo bem?'):\n"
            "     * SUA RESPOSTA AO CLIENTE DEVE OBRIGATORIAMENTE CITAR O ASSUNTO ANTERIOR E FAZER A PERGUNTA DE RETOMADA!\n"
            f"     * Formato obrigatório: 'Olá, {clean_name}! Tudo bem? Vi que conversamos recentemente sobre [resumo do assunto tratado antes]. Você gostaria de continuar esse assunto ou precisa de ajuda com uma nova solicitação?'\n"
            "     * NUNCA envie apenas uma saudação vazia se houver histórico anterior recente!\n"
            "   - CONTINUIDADE DIRETA: Se o cliente já indicar continuidade explícita daquele assunto, reconheça imediatamente sem pedir para repetir.\n"
            "   - NOVO ASSUNTO: Se o cliente indicar um novo tema, faça a recepção do novo assunto normalmente.\n"
            "3. FORA DO ESCOPO: Se o cliente fizer perguntas totalmente desconexas com a empresa (ex: 'Vocês vendem pizza?'), esclareça gentilmente os serviços e produtos que a Servweld atende (equipamentos de solda, corte, assistência, locação e financeiro).\n"
            "4. REGRAS DE SETOR & PROIBIÇÃO DE TRANSFERÊNCIAS INDEVIDAS:\n"
            f"   - Se o cliente pedir para falar com um atendente humano, vendedor ou colaborador específico (ex: 'Consigo falar com o Fernando?', 'Quero falar com atendente', 'Pode me atender?'):\n"
            f"     * O ATENDIMENTO DEVE PERMANECER NO SETOR ATUAL ('{department_name}')!\n"
            "     * DEFINA 'TRANSFERIR_SETOR: NAO'.\n"
            f"     * Tente adiantar as informações antes de transferir ('Com certeza! Para eu já adiantar o seu atendimento com a nossa equipe de {department_name}, você poderia me informar o que você precisa ou qual máquina tem interesse?').\n"
            "   - NUNCA transfira de setor com base no nome salvo na agenda do cliente!\n"
            "   - SOMENTE defina 'TRANSFERIR_SETOR: <NomeDoSetor>' se a mensagem do cliente contiver expressamente palavras-chave e intenção clara de OUTRO setor (ex: problema em máquina alugada -> Locação; comprar produtos novos -> Vendas; dúvida de boleto -> Financeiro).\n"
            "   - SE VOCÊ FOR TRANSFERIR DE SETOR: Você DEVE OBRIGATORIAMENTE informar o cliente no texto da resposta ('Com certeza! Estou transferindo seu atendimento para a nossa equipe de [NomeDoSetor], que é o setor responsável por...')!\n"
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
            "   - Se o cliente ainda não informou o nome (nome está como 'Cliente' ou número), dê as boas-vindas e pergunte gentilmente o nome dele para um atendimento personalizado.\n"
            "13. DETECÇÃO DE BOT / URA / MENU AUTOMÁTICO DE OUTRA EMPRESA (ANTI-LOOP ETERNO):\n"
            "   - Se a mensagem recebida for um MENU AUTOMÁTICO, URA, BOT, AUTOATENDIMENTO ou IA de outra empresa (ex: 'Digite 1 para Suporte', 'Escolha uma opção', 'Menu principal', 'Sou a assistente virtual', etc.):\n"
            "     * DEFINA 'RESPOSTA: [SILENCIAR_IA]'\n"
            "     * DEFINA 'ESCALAR_HUMANO: SIM'\n"
            "     * NUNCA responda a outro robô para evitar um loop eterno de mensagens redundantes!\n\n"
            f"{tenant_prompt or 'Resolva dúvidas com base no contexto fornecido.'}\n\n"
            f"HISTÓRICO ANTERIOR/MEMÓRIA RESUMIDA DA CONVERSA:\n{memory_summary or 'Nenhum histórico anterior.'}\n\n"
            f"BASE DE CONHECIMENTO RAG:\n{rag_context or 'Nenhum documento específico encontrado.'}"
        )

        # Early check for Bot / URA / Menu of another company
        if is_bot_or_menu_message(user_message):
            logger.info(f"[ANTI-LOOP BOT] Mensagem identificada como menu/bot de outra empresa: '{user_message[:60]}...'. Silenciando IA.")
            return {
                "resposta": "",
                "escalar_humano": True,
                "is_bot_or_menu": True,
                "transferir_setor": None,
                "nova_memoria": "Mensagem recebida é um menu/bot automático de outra empresa. IA silenciada para evitar loop.",
                "finalizar_conversa": False,
                "enviar_localizacao": False
            }

        messages_text = []
        for msg in conversation_history[-6:]:
            role = "Cliente" if msg["remetente"] == "cliente" else "Atendente/IA"
            messages_text.append(f"{role}: {msg['conteudo']}")
        
        full_prompt = (
            f"{system_instruction}\n\n"
            f"Diálogo Recente:\n" + "\n".join(messages_text) + "\n\n"
            f"Mensagem Atual do Cliente: {user_message}\n\n"
            "Responda no seguinte formato exato:\n"
            "RESPOSTA: <mensagem em português natural para o cliente>\n"
            "ESCALAR_HUMANO: <SIM ou NAO>\n"
            "TRANSFERIR_SETOR: <NomeDoNovoSetor ou NAO>\n"
            "NOVA_MEMORIA: <resumo factual dos fatos relevantes>\n"
            "FINALIZAR_CONVERSA: <SIM ou NAO>\n"
            "ENVIAR_LOCALIZACAO: <SIM ou NAO>"
        )

        default_res = {
            "resposta": f"Olá, {clean_name}! Como posso te ajudar hoje?",
            "escalar_humano": False,
            "transferir_setor": None,
            "nova_memoria": memory_summary or "",
            "finalizar_conversa": False,
            "enviar_localizacao": False
        }

        if not client:
            return default_res

        models_to_try = [primary_model] if primary_model in ["gemini-3.1-flash-lite", "gemini-3.6-flash"] else ["gemini-3.1-flash-lite", "gemini-3.6-flash"]
        for candidate in ["gemini-3.6-flash", "gemini-3.1-flash-lite"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            for attempt in range(2):
                try:
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=m_name,
                        contents=full_prompt
                    )
                    if response and response.text:
                        break
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str and attempt == 0:
                        logger.warning(f"Rate limit 429 on {m_name}, retrying in 1.5s...")
                        await asyncio.sleep(1.5)
                        continue
                    logger.warning(f"Error calling Gemini with model '{m_name}': {e}")
                    response = None
                    break
            
            if response and response.text:
                text = response.text.strip()
                lines = text.split("\n")
                
                resposta = ""
                escalar_humano = False
                transferir_setor = None
                nova_memoria = memory_summary or ""
                finalizar_conversa = False
                enviar_localizacao = False

                current_field = None
                resposta_lines = []
                memoria_lines = []

                for line in lines:
                    if line.startswith("RESPOSTA:"):
                        current_field = "RESPOSTA"
                        resposta_lines.append(line.replace("RESPOSTA:", "").strip())
                    elif line.startswith("ESCALAR_HUMANO:"):
                        current_field = "ESCALAR_HUMANO"
                        val = line.replace("ESCALAR_HUMANO:", "").strip().upper()
                        escalar_humano = "SIM" in val or "TRUE" in val
                    elif line.startswith("TRANSFERIR_SETOR:"):
                        current_field = "TRANSFERIR_SETOR"
                        val = line.replace("TRANSFERIR_SETOR:", "").strip()
                        if val.upper() not in ["NAO", "NÃO", "NONE", "FALSE", ""]:
                            transferir_setor = val
                    elif line.startswith("NOVA_MEMORIA:"):
                        current_field = "NOVA_MEMORIA"
                        memoria_lines.append(line.replace("NOVA_MEMORIA:", "").strip())
                    elif line.startswith("FINALIZAR_CONVERSA:"):
                        current_field = "FINALIZAR_CONVERSA"
                        val = line.replace("FINALIZAR_CONVERSA:", "").strip().upper()
                        finalizar_conversa = "SIM" in val or "TRUE" in val
                    elif line.startswith("ENVIAR_LOCALIZACAO:"):
                        current_field = "ENVIAR_LOCALIZACAO"
                        val = line.replace("ENVIAR_LOCALIZACAO:", "").strip().upper()
                        enviar_localizacao = "SIM" in val or "TRUE" in val
                    else:
                        if current_field == "RESPOSTA":
                            resposta_lines.append(line)
                        elif current_field == "NOVA_MEMORIA":
                            memoria_lines.append(line)

                resposta = "\n".join(resposta_lines).strip()
                nova_memoria = "\n".join(memoria_lines).strip()

                if not resposta:
                    resposta = text

                return {
                    "resposta": resposta,
                    "escalar_humano": False if is_technician_or_admin else escalar_humano,
                    "transferir_setor": None if is_technician_or_admin else transferir_setor,
                    "nova_memoria": nova_memoria,
                    "finalizar_conversa": finalizar_conversa,
                    "enviar_localizacao": enviar_localizacao
                }

        return default_res

    # =========================================================================
    # MULTIMODAL MEDIA PROCESSING METHODS
    # =========================================================================

    async def process_audio_message(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not client or not audio_bytes:
            return {
                "transcription": "",
                "success": False,
                "fallback_message": "Não foi possível transcrever o áudio recebido. Por favor, envie uma mensagem de texto ou tente gravar novamente.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        audio_prompt = (
            "Transcreva com extrema precisão o áudio em português brasileiro a seguir.\n"
            "Retorne APENAS o texto exato falado, sem introduções, aspas ou comentários adicionais.\n"
            "Se o áudio estiver completamente inaudível, mudo ou irreconhecível, retorne exatamente: [AUDIO_INAUDIVEL]"
        )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=[
                        audio_prompt,
                        genai.types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
                    ]
                )
                if response and response.text:
                    transcription = response.text.strip()
                    if "[AUDIO_INAUDIVEL]" in transcription or not transcription:
                        return {
                            "transcription": "",
                            "success": False,
                            "fallback_message": "Não consegui compreender o seu áudio devido ao ruído ou volume baixo. Poderia enviar novamente ou escrever por texto?",
                            "tokens": {
                                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                                "response_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                            }
                        }

                    return {
                        "transcription": transcription,
                        "success": True,
                        "tokens": {
                            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                            "response_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                        },
                        "model_used": m_name
                    }
            except Exception as e:
                logger.warning(f"Error processing audio with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "transcription": "",
            "success": False,
            "fallback_message": "Não consegui processar o áudio enviado. Por favor, digite sua mensagem por texto para que possamos te ajudar.",
            "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
        }

    async def process_image_message(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        task_type: str = "general",
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not client or not image_bytes:
            return {
                "description": "",
                "extracted_text": "",
                "success": False,
                "fallback_message": "Não foi possível analisar a imagem enviada. Por favor, envie uma nova foto mais nítida ou detalhe por mensagem de texto.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        if task_type == "defect_inspection":
            image_prompt = (
                "Você é um técnico especialista em equipamentos de solda e corte da empresa Servweld.\n"
                "Analise detalhadamente a foto do equipamento ou peça enviada pelo cliente.\n"
                "Identifique:\n"
                "1. O tipo de equipamento, componente ou peça visível (tocha, cabo, bocal, máquina, etc.).\n"
                "2. Quaisquer defeitos visíveis, danos, rompimentos, queimaduras, desgaste ou anomalias.\n"
                "3. Um diagnóstico técnico inicial claro em 2 a 3 frases com a recomendação prática.\n"
                "Se a imagem estiver totalmente ilegível, escura, corrompida ou não for de equipamento/ferramenta, retorne: [IMAGEM_ILEGIVEL]"
            )
        else:
            image_prompt = (
                "Você é um assistente de OCR e visão computacional da empresa Servweld.\n"
                "Analise a imagem enviada (comprovante de pagamento, nota fiscal, documento ou texto).\n"
                "Extraia com precisão todas as informações textuais relevantes (valor em R$, pagador, recebedor, data, ID de transação Pix ou dados da nota).\n"
                "Resuma de forma clara e factual os dados encontrados.\n"
                "Se a imagem estiver completamente ilegível, borrada ou sem texto identificável, retorne: [IMAGEM_ILEGIVEL]"
            )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=[
                        image_prompt,
                        genai.types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                    ]
                )
                if response and response.text:
                    analysis_text = response.text.strip()
                    if "[IMAGEM_ILEGIVEL]" in analysis_text or not analysis_text:
                        return {
                            "description": "",
                            "extracted_text": "",
                            "success": False,
                            "fallback_message": "A foto enviada está um pouco ilegível ou escura. Poderia nos enviar uma nova imagem mais nítida e iluminada?",
                            "tokens": {
                                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                                "response_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                            }
                        }

                    return {
                        "description": analysis_text,
                        "extracted_text": analysis_text,
                        "success": True,
                        "tokens": {
                            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                            "response_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                        },
                        "model_used": m_name
                    }
            except Exception as e:
                logger.warning(f"Error processing image with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "description": "",
            "extracted_text": "",
            "success": False,
            "fallback_message": "Não foi possível carregar a imagem. Por favor, reenvie a foto ou digite as informações.",
            "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
        }

    async def process_document_message(
        self,
        pdf_bytes: bytes,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        if not client or not pdf_bytes:
            return {
                "extracted_content": "",
                "success": False,
                "fallback_message": "Não foi possível ler o documento PDF enviado. Por favor, envie novamente ou nos informe os dados por texto.",
                "tokens": {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0}
            }

        doc_prompt = (
            "Você é o assistente de análise de documentos da empresa Servweld.\n"
            "Leia com atenção o documento PDF em anexo (Ordem de Serviço, Nota Fiscal, Contrato ou Relatório Técnico).\n"
            "Extraia e resuma de forma estruturada:\n"
            "- Tipo de documento\n"
            "- Número de identificação/OS/NF\n"
            "- Partes envolvidas (cliente, prestador)\n"
            "- Descrição dos serviços, produtos ou equipamentos citados\n"
            "- Valores e prazos informados (se houver)\n"
            "Se o documento for inválido, corrompido ou ilegível, retorne exatamente: [PDF_CORROMPIDO]"
        )

        models_to_try = [primary_model]
        for candidate in ["gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]:
            if candidate not in models_to_try:
                models_to_try.append(candidate)

        for m_name in models_to_try:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=m_name,
                    contents=[
                        doc_prompt,
                        genai.types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                    ]
                )
                if response and response.text:
                    extracted = response.text.strip()
                    if "[PDF_CORROMPIDO]" in extracted or not extracted:
                        return {
                            "extracted_content": "",
                            "success": False,
                            "fallback_message": "O arquivo PDF enviado parece estar corrompido ou ilegível. Por favor, tente enviar novamente o arquivo ou tire uma foto dele.",
                            "tokens": {
                                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                                "response_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                            }
                        }

                    return {
                        "extracted_content": extracted,
                        "success": True,
                        "tokens": {
                            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                            "response_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0)
                        },
                        "model_used": m_name
                    }
            except Exception as e:
                logger.warning(f"Error processing PDF document with '{m_name}': {e}")
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
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"
        clean_name = sanitize_customer_name(customer_name)

        if not messages_history:
            return (
                f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                f"👤 *Cliente:* {clean_name}\n"
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
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            "Gere um resumo estruturado no seguinte formato exato:\n"
            f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
            f"👤 *Cliente:* {clean_name}\n"
            f"🔢 *Protocolo:* {protocol_number}\n"
            f"🏢 *Departamento:* {department_name}\n"
            "🎯 *Motivo do Contato:* <resumo em 1 frase factual sobre o que o cliente quer>\n"
            "📍 *Onde Parou:* <o que a IA/cliente já falaram antes de passar para o humano>\n"
            "👉 *Próxima Ação Sugerida:* <orientação prática e direta para o atendente continuar o atendimento sem repetir perguntas já respondidas>\n\n"
            "DIRETRIZES ESTRITAS DE FACTUALIDADE:\n"
            f"1. NOME DO CLIENTE: No campo 'Cliente', use EXATAMENTE '{clean_name}'. É PROIBIDO inventar títulos profissionais (Eng., Dr., etc.) ou sobrenomes que não constem expressamente na identificação.\n"
            "2. BASE EXCLUSIVAMENTE FACTUAL: Use apenas o que foi dito nas mensagens reais. É proibido inventar valores, modelos de equipamentos, marcas ou problemas técnicos adicionais.\n"
            "3. Seja direto, profissional e objetivo.\n\n"
            f"HISTÓRICO REAL DA CONVERSA:\n" + "\n".join(messages_text)
        )

        if not client:
            return (
                f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                f"👤 *Cliente:* {clean_name}\n"
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
            f"👤 *Cliente:* {clean_name}\n"
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
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"
        clean_name = sanitize_customer_name(customer_name)

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
            f"O atendente humano do setor '{department_name}' solicitou uma SUGESTÃO DE RESPOSTA para enviar ao cliente '{clean_name}'.\n\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{memory_prompt}"
            f"{rag_prompt}"
            "DIRETRIZES DA RESPOSTA:\n"
            "1. Escreva uma mensagem pronta para envio, redigida em primeira pessoa (como se você fosse o atendente humano da Servweld).\n"
            "2. Seja extremamente educado, claro, acolhedor, profissional e direto ao ponto.\n"
            "3. Não use introduções explicativas como 'Aqui está uma sugestão:' ou 'Você pode dizer:'. Retorne APENAS o texto exato da resposta a ser colocada no chat.\n"
            "4. Dê continuidade imediata ao diálogo, respondendo à última dúvida ou solicitação do cliente com base no histórico real.\n"
            "5. Se for necessária uma informação técnica ou valor que não conste na base, sugira verificar com o setor responsável em vez de inventar números.\n\n"
            f"HISTÓRICO DA CONVERSA:\n" + "\n".join(messages_text)
        )

        if not client:
            return f"Olá {clean_name}, boa tarde! Como posso te ajudar hoje?"

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

        return f"Olá {clean_name}! Recebi sua mensagem e já estou verificando o seu caso para te ajudar."

    async def summarize_conversation_for_transfer(
        self,
        customer_name: str,
        messages_history: List[Dict[str, str]],
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-2.5-flash"
        clean_name = sanitize_customer_name(customer_name)

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
            f"Sua tarefa é analisar a conversa real com o cliente '{clean_name}' abaixo e gerar um RESUMO EXECUTIVO verdadeiro para o próximo atendente.\n\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
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
                f"• 🎯 **Objetivo Principal**: Transferência de atendimento de {clean_name}.\n"
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
            f"• 🎯 **Objetivo Principal**: Transferência de atendimento de {clean_name}.\n"
            f"• 📝 **Histórico**: Conversa transferida com histórico disponível.\n"
            f"• ⚡ **Próximo Passo**: Analise as mensagens anteriores."
        )


gemini_service = GeminiService()
