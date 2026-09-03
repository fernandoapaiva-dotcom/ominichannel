import logging
import json
import re
import asyncio
from datetime import datetime, timezone
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

STRICT_CONTEXT_AND_ANTI_HALLUCINATION_DIRECTIVE = (
    "=== REGRA MANDATÓRIA CENTRAL: CONTEXTO ESTATUTÁRIO & ANTI-ALUCINAÇÃO ===\n"
    "1. USO EXCLUSIVO DAS INFORMAÇÕES DO CONTEXTO: Você SÓ pode usar informações que estiverem explicitamente no CONTEXTO abaixo (nome do cliente, telefone, protocolo, histórico, RAG).\n"
    "2. SE UM DADO NÃO ESTIVER NO CONTEXTO, NUNCA INVENTE: Diga 'não tenho esse dado' ou simplesmente não mencione o campo. NUNCA invente nomes, telefones, protocolos ou situações hipotéticas.\n"
    "3. NUNCA AFIRME TER CONVERSADO ANTES COM O CLIENTE A MENOS QUE EXISTA HISTÓRICO EXPLÍCITO no CONTEXTO com timestamp anterior. Se o histórico do cliente estiver vazio ou 'nenhum', trate SEMPRE como primeiro contato.\n"
    "4. NOME DO CLIENTE: Se o nome estiver como '(vazio - não usar)', NUNCA use nem invente nomes ou títulos (Eng., Dr., Sr.). Dê as boas-vindas e pergunte gentilmente o nome dele para personalizar o atendimento.\n"
    "=========================================================================\n"
)

def format_clean_client_context(
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    protocol_number: Optional[str] = None,
    memory_summary: Optional[str] = None
) -> str:
    """
    Estrutura o contexto do cliente de forma limpa e explícita antes de enviar ao modelo:
    CONTEXTO_CLIENTE:
    nome: (vazio - não usar)
    telefone: 556199842757
    protocolo_atual: #20260824-0005
    historico_anterior: nenhum
    """
    clean_name = sanitize_customer_name(customer_name)
    has_real_name = bool(customer_name and clean_name not in ["Cliente", ""])
    name_str = clean_name if has_real_name else "(vazio - não usar)"
    
    clean_digits = "".join(filter(str.isdigit, str(customer_phone or "")))
    phone_str = clean_digits if clean_digits else "(não informado)"
    
    proto_clean = str(protocol_number or "").strip()
    if proto_clean and proto_clean not in ["None", "S/N", ""]:
        proto_str = proto_clean if proto_clean.startswith("#") else f"#{proto_clean}"
    else:
        proto_str = "(nenhum)"
    
    clean_mem = (memory_summary or "").strip()
    if not clean_mem or clean_mem.lower() in ["nenhum histórico anterior.", "nenhum", "none", "vazio", "sem histórico"]:
        hist_str = "nenhum"
    else:
        hist_str = clean_mem

    return (
        "CONTEXTO_CLIENTE:\n"
        f"nome: {name_str}\n"
        f"telefone: {phone_str}\n"
        f"protocolo_atual: {proto_str}\n"
        f"historico_anterior: {hist_str}"
    )

RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE = (
    "=== REGRA MANDATÓRIA CENTRAL: PREÇOS, PRODUTOS & ANTI-ALUCINAÇÃO DE VALORES ===\n"
    "1. PREÇOS E CONDIÇÕES SÓ COM FONTE REAL: Você SOMENTE pode informar valores em R$, preços de venda, locação ou condições comerciais se constarem EXPRESSAMENTE na 'BASE DE CONHECIMENTO RAG' fornecida.\n"
    "2. PROIBIÇÃO ABSOLUTA DE ESTIMAR OU INVENTAR PREÇOS: Se o cliente perguntar o valor de um item, serviço ou máquina e o preço NÃO estiver na Base RAG, É ESTRITAMENTE PROIBIDO inventar, supor ou estimar um número!\n"
    "3. COMPORTAMENTO QUANDO O PREÇO NÃO CONSTA NO RAG: Responda gentilmente que no momento você não tem o valor exato cadastrado e que vai confirmar a cotação atualizada diretamente com a equipe do setor, oferecendo encaminhar ou verificar com um especialista.\n"
    "=================================================================================\n"
)


def validate_and_sanitize_ai_response(
    raw_ai_message: str,
    had_null_name: bool,
    had_empty_history: bool,
    store_name: str = "Servweld"
) -> str:
    """
    Camada de validação pós-resposta (Backend Anti-Hallucination Guard):
    1. Se nome_cliente do contexto era null/desconhecido, confere se mensagem_cliente
       contém algum nome próprio alucinado ou saudações com apelidos/títulos estranhos.
       Se sim, substitui por saudação neutra ("Olá! Seja bem-vindo(a) à {store_name}.").
    2. Se historico_anterior estava vazio, confere se mensagem_cliente contém expressões
       de histórico inventado ("conversamos antes", "vi que você", "recentemente", "no nosso último contato").
       Se sim, limpa essas expressões e garante atendimento de primeiro contato.
    """
    if not raw_ai_message or not isinstance(raw_ai_message, str):
        return f"Olá! Seja bem-vindo(a) à {store_name}. Como posso ajudar?"

    text = raw_ai_message.strip()

    # Checagem 1: Nome alucinado quando nome_cliente era null/não informado
    if had_null_name:
        hallucinated_name_patterns = [
            r'^(?:ol[áa]|bom\s+dia|boa\s+tarde|boa\s+noite)[,\s]+(?:eng(?:enheiro)?\.?|dr(?:a)?\.?|sr(?:a)?\.?|contato\s+\d+|cliente|[a-z0-9_\.\-]{3,}(?:\s+[a-z0-9_\.\-]+){0,4})[!\.,\s]+'
        ]
        for pat in hallucinated_name_patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                text = re.sub(pat, f"Olá! Seja bem-vindo(a) à {store_name}. ", text, count=1, flags=re.IGNORECASE).strip()
                break

    # Checagem 2: Expressões de histórico inventado quando historico_anterior era vazio
    if had_empty_history:
        fake_history_patterns = [
            r'(?:vi\s+que\s+conversamos\s+recentemente[^\.\?!]*[\.\?!])',
            r'(?:conforme\s+conversamos\s+anteriormente[^\.\?!]*[\.\?!])',
            r'(?:como\s+falamos\s+no\s+nosso\s+[úu]ltimo\s+contato[^\.\?!]*[\.\?!])',
            r'(?:em\s+continuidade\s+ao\s+nosso\s+atendimento\s+anterior[^\.\?!]*[\.\?!])',
            r'(?:dando\s+sequ[êe]ncia\s+ao\s+que\s+falamos[^\.\?!]*[\.\?!])',
            r'(?:conforme\s+nos\s+falamos\s+antes[^\.\?!]*[\.\?!])',
            r'(?:vi\s+que\s+voc[êe]\s+já\s+havia\s+entrado\s+em\s+contato[^\.\?!]*[\.\?!])'
        ]
        for pat in fake_history_patterns:
            text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

        if not text or len(text) < 8:
            text = f"Olá! Seja bem-vindo(a) à {store_name}. Como posso ajudar?"

    return text


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
        customer_name: Optional[str],
        department_name: str,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        memory_summary: Optional[str] = None,
        rag_context: Optional[str] = None,
        tenant_prompt: Optional[str] = None,
        available_departments: Optional[List[str]] = None,
        available_attendants: Optional[List[str]] = None,
        department_descriptions: Optional[Dict[str, str]] = None,
        protocol_number: Optional[str] = None,
        should_announce_protocol: bool = False,
        is_technician_or_admin: bool = False,
        customer_phone: Optional[str] = None,
        opened_at_str: Optional[str] = None,
        store_name: str = "Servweld",
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"

        clean_name = sanitize_customer_name(customer_name)
        has_real_name = bool(customer_name and clean_name not in ["Cliente", ""])
        had_null_name = not has_real_name
        nome_cliente_val = clean_name if has_real_name else "null"

        clean_digits = "".join(filter(str.isdigit, str(customer_phone or "")))
        telefone_val = clean_digits if clean_digits else "não informado"
        protocolo_val = str(protocol_number).strip() if (protocol_number and str(protocol_number) not in ["None", "S/N", ""]) else "não gerado"
        if protocolo_val != "não gerado" and not protocolo_val.startswith("#"):
            protocolo_val = f"#{protocolo_val}"

        # Histórico anterior formatado com timestamps/ordem
        had_empty_history = True
        formatted_history_list = []
        if conversation_history:
            for m in conversation_history:
                r_raw = str(m.get("remetente", "")).lower()
                remetente = "Cliente" if r_raw == "cliente" else "Atendente/IA"
                conteudo = str(m.get("conteudo", "")).strip()
                ts = m.get("timestamp") or ""
                if conteudo:
                    had_empty_history = False
                    if ts:
                        formatted_history_list.append(f"[{ts}] {remetente}: {conteudo}")
                    else:
                        formatted_history_list.append(f"{remetente}: {conteudo}")

        if memory_summary and memory_summary.strip() and memory_summary.strip().lower() not in ["nenhum histórico anterior.", "nenhum", "none", "vazio"]:
            had_empty_history = False
            formatted_history_list.insert(0, f"[MEMÓRIA ANTERIOR]: {memory_summary.strip()}")

        if formatted_history_list:
            historico_anterior_str = "\n".join(formatted_history_list[-10:])
        else:
            historico_anterior_str = "(nenhum — este é o primeiro contato do cliente)"

        agentes_str = ", ".join(available_attendants) if available_attendants else "Equipe de Atendimento do Setor (disponível)"

        dept_desc_prompt = ""
        if department_descriptions:
            dept_desc_prompt = "\nFRONTEIRAS DOS DEPARTAMENTOS:\n" + "\n".join([
                f"- '{k}': {v}" for k, v in department_descriptions.items()
            ]) + "\n"

        tech_directive = ""
        if is_technician_or_admin:
            tech_directive = (
                "=========================================================================================\n"
                "🛡️ MODO COPILOTO TÉCNICO INTERNO / ENGENHARIA DE BANCADA (INTERLOCUTOR É TÉCNICO AUTORIZADO / ADMIN):\n"
                "- O interlocutor é um TÉCNICO / ENGENHEIRO DA LOJA SERVWEELD trabalhando na bancada de manutenção!\n"
                "- FORNEÇA AJUDA TÉCNICA APROFUNDADA, DIAGNÓSTICOS DE DEFEITOS, ROTEIROS DE TESTE E DADOS DE MANUAIS / DIAGRAMAS ELETRÔNICOS.\n"
                "- Auxilie em: medições com multímetro (tensão, diodo, continuidade), interpretação de códigos de erro (ex: falhas de barramento DC, erro 11, IGBTs, resistores de gate, fontes auxiliares +15V/-15V/+5V, sensores Hall, relés de pré-carga, optoacopladores).\n"
                "- Identifique pinagens de conectores (ex: J18, J19), estado de chicotes e oriente o passo a passo seguro para o conserto do equipamento.\n"
                "- Seja um Orientador Técnico Master experiente, técnico e prático de bancada.\n"
                "=========================================================================================\n"
            )
        else:
            tech_directive = (
                "=========================================================================================\n"
                "🛡️ MODO ATENDIMENTO AO CLIENTE EXTERNO (NÃO É TÉCNICO INTERNO):\n"
                "- Você está atendendo um CLIENTE COMUM / EXTERNO da Servweld.\n"
                "- PROIBIÇÃO ABSOLUTA DE INSTRUÇÕES DE REPARO/CONSERTO: NUNCA ensine o cliente a abrir máquinas, consertar placas, medir circuitos eletrônicos internos ou trocar peças por conta própria. Isso traz risco severo de acidentes elétricos graves e elimina a demanda de serviços da assistência técnica da loja.\n"
                "- PROCEDIMENTO PERMITIDO COM O CLIENTE:\n"
                "  1. Se o cliente relatar um código de erro ou defeito (ex: LED de sobreaquecimento aceso, código E01/E02, máquina desarmando disjuntor): Você pode apenas explicar brevemente o significado geral do erro em alto nível (ex: 'O código E01 indica uma proteção ativada por sobreaquecimento ou anomalia no circuito de potência').\n"
                "  2. CONVITE PARA ASSISTÊNCIA TÉCNICA: Convide e oriente o cliente a trazer ou enviar a máquina para o laboratório especializado da Servweld, onde nossos técnicos qualificados farão o teste e orçamento com garantia e peças originais.\n"
                "  3. Forneça o endereço da loja e horários de recebimento de equipamentos.\n"
                "=========================================================================================\n"
            )

        system_instruction = (
            f"Você é a IA Concierge da {store_name} (Servweld / Servsolda), responsável pelo primeiro atendimento acolhedor, rápido e resolutivo via WhatsApp no departamento de {department_name}.\n\n"
            "# DIRETRIZES FUNDAMENTAIS DE ATENDIMENTO:\n\n"
            "1. RECEPÇÃO E PROTOCOLO:\n"
            "   - Cumprimente o cliente com simpatia e profissionalismo.\n"
            f"   - {'Atenção: Este é o primeiro contato. O sistema já anexa o número do protocolo automaticamente no topo, portanto NÃO repita o número do protocolo no corpo da mensagem.' if should_announce_protocol else 'O protocolo já foi aberto anteriormente nesta conversa. NUNCA mencione número de protocolo nem reinicie saudações de boas-vindas.'}\n\n"
            "2. LOCALIZAÇÃO E ENDEREÇO:\n"
            "   - Se o cliente perguntar sobre onde fica a loja, endereço, localização, como chegar, rota, mapa ou GPS, responda acolhedoramente com o endereço completo e avise que o mapa interativo para abrir no GPS (Google Maps / Waze) está logo abaixo:\n"
            "     📍 Endereço: SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, CEP: 71215-226\n"
            "     🗺️ Google Maps: https://maps.google.com/?q=-15.820418,-47.956467\n"
            "   - Defina \"enviar_localizacao\": true no JSON.\n\n"
            "3. HORÁRIO DE ATENDIMENTO E FUNCIONAMENTO:\n"
            "   - Se o cliente perguntar sobre horários de funcionamento, que horas abre ou fecha, informe com clareza:\n"
            "     ⏰ Segunda a Sexta-feira das 08h00 às 18h00 (Não abrimos aos sábados, domingos e feriados).\n\n"
            "4. DIRECIONAMENTO E TRIAGEM DE SETORES:\n"
            "   - Entenda a necessidade do cliente e faça o direcionamento correto:\n"
            "     • Assistência Técnica: Conserto e manutenção de máquinas de solda, tochas, placas eletrônicas, orçamentos e serviços de bancada.\n"
            "     • Vendas: Compra de novas máquinas de solda, tochas, consumíveis (bicos, bocais, difusores), arames, eletrodos, reguladores e EPIs.\n"
            "     • Locação: Aluguel de máquinas e equipamentos de solda.\n"
            "     • Financeiro: Boletos, faturamento, notas fiscais, comprovantes, dados de pagamento e chave PIX.\n"
            "     • Atendimento Geral: Informações institucionais, recepção e dúvidas gerais.\n"
            "   - Pergunte ou confirme educadamente com o cliente para transferi-lo à equipe especialista do setor responsável.\n\n"
            "5. DÚVIDAS GERAIS E RESPOSTAS OBJETIVAS:\n"
            "   - Responda as dúvidas básicas do cliente com clareza, cortesia e agilidade, sem rodeios.\n\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{dept_desc_prompt}"
            f"{tech_directive}\n"
            "# FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO)\n\n"
            "Responda SEMPRE como JSON estruturado:\n"
            "{\n"
            "  \"mensagem_cliente\": \"texto que será enviado ao cliente no WhatsApp\",\n"
            "  \"temperatura\": \"baixa | media | alta\",\n"
            "  \"transferir_humano\": true | false,\n"
            "  \"motivo_transferencia\": null,\n"
            "  \"atendente_preferencial\": null,\n"
            "  \"transferir_setor\": null,\n"
            "  \"enviar_localizacao\": false,\n"
            "  \"enviar_pix\": false,\n"
            "  \"dados_extraidos\": {\n"
            "    \"nome_cliente\": null,\n"
            "    \"resumo_necessidade\": \"resumo do que o cliente precisa\"\n"
            "  }\n"
              "}\n"
        )

        contexto_atendimento = (
            "CONTEXTO_ATENDIMENTO:\n"
            f"empresa: {store_name} (Servweld / Servsolda)\n"
            f"departamento_atual: {department_name}\n"
            f"protocolo_atual: {protocolo_val}\n"
            f"nome_cliente: {nome_cliente_val}\n"
            f"telefone: {telefone_val}\n"
            f"data_abertura: {opened_at_str or datetime.utcnow().strftime('%d/%m/%Y %H:%M')}\n"
            "endereco_oficial: SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, CEP: 71215-226\n"
            "google_maps_link: https://maps.google.com/?q=-15.820418,-47.956467\n"
            "horario_funcionamento: Segunda a Sexta-feira das 08h00 às 18h00 (Fechado aos sábados, domingos e feriados)\n\n"
            f"historico_anterior:\n{historico_anterior_str}\n\n"
            f"agentes_disponiveis_no_departamento:\n{agentes_str}\n\n"
            f"BASE_DE_CONHECIMENTO_RAG:\n{rag_context or 'Nenhum documento específico encontrado.'}\n\n"
            f"mensagem_atual_do_cliente: \"{user_message}\""
        )

        full_prompt = f"{system_instruction}\n\n{contexto_atendimento}"

        # Early check for Bot / URA / Menu of another company
        if is_bot_or_menu_message(user_message):
            logger.info(f"[ANTI-LOOP BOT] Mensagem identificada como menu/bot de outra empresa: '{user_message[:60]}...'. Silenciando IA.")
            return {
                "resposta": "",
                "temperatura": "baixa",
                "escalar_humano": True,
                "is_bot_or_menu": True,
                "atendente_preferencial": None,
                "transferir_setor": None,
                "nova_memoria": "Mensagem recebida é um menu/bot automático de outra empresa. IA silenciada para evitar loop.",
                "finalizar_conversa": False,
                "enviar_localizacao": False
            }

        if had_empty_history:
            fallback_text = f"Olá! Seja bem-vindo(a) à {store_name}. Como posso ajudar?"
        else:
            fallback_text = "Olá! Já recebi suas informações e estou encaminhando para nossa equipe especialista dar continuidade ao seu atendimento. Um momento, por favor!"

        default_res = {
            "resposta": fallback_text,
            "temperatura": "baixa",
            "escalar_humano": not had_empty_history,
            "atendente_preferencial": None,
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
                
                # Try parsing JSON first
                parsed_json = None
                try:
                    # Strip markdown code blocks if wrapped
                    clean_json_str = text
                    if clean_json_str.startswith("```"):
                        clean_json_str = re.sub(r'^```(?:json)?\s*', '', clean_json_str)
                        clean_json_str = re.sub(r'\s*```$', '', clean_json_str)
                    clean_json_str = clean_json_str.strip()
                    parsed_json = json.loads(clean_json_str)
                except Exception:
                    pass

                resposta = ""
                temperatura = "baixa"
                escalar_humano = False
                atendente_preferencial = None
                transferir_setor = None
                enviar_localizacao = False
                enviar_pix = False
                nova_memoria = memory_summary or ""

                if isinstance(parsed_json, dict):
                    resposta = str(parsed_json.get("mensagem_cliente") or parsed_json.get("resposta") or "").strip()
                    temperatura = str(parsed_json.get("temperatura") or "baixa").lower()
                    escalar_humano = bool(parsed_json.get("transferir_humano") or parsed_json.get("escalar_humano") or temperatura == "alta")
                    atendente_preferencial = parsed_json.get("atendente_preferencial") or None
                    transferir_setor = parsed_json.get("transferir_setor") or None
                    enviar_localizacao = bool(parsed_json.get("enviar_localizacao"))
                    enviar_pix = bool(parsed_json.get("enviar_pix"))
                    
                    dados_ext = parsed_json.get("dados_extraidos") or {}
                    if isinstance(dados_ext, dict):
                        extracted_name = dados_ext.get("nome_cliente")
                        resumo_nec = dados_ext.get("resumo_necessidade") or ""
                        if resumo_nec:
                            nova_memoria = f"Necessidade do Cliente: {resumo_nec}"
                else:
                    # Fallback key-value line parser
                    lines = text.split("\n")
                    resposta_lines = []
                    current_field = None
                    for line in lines:
                        if line.startswith("RESPOSTA:") or line.startswith("mensagem_cliente:"):
                            current_field = "RESPOSTA"
                            resposta_lines.append(line.split(":", 1)[1].strip())
                        elif line.startswith("ESCALAR_HUMANO:") or line.startswith("transferir_humano:"):
                            current_field = "ESCALAR_HUMANO"
                            val = line.split(":", 1)[1].strip().upper()
                            escalar_humano = "SIM" in val or "TRUE" in val
                        elif line.startswith("ATENDENTE_PREFERENCIAL:"):
                            current_field = "ATENDENTE_PREFERENCIAL"
                            val = line.split(":", 1)[1].strip()
                            if val.upper() not in ["NAO", "NÃO", "NONE", "NULL", "FALSE", ""]:
                                atendente_preferencial = val
                        elif line.startswith("TRANSFERIR_SETOR:"):
                            current_field = "TRANSFERIR_SETOR"
                            val = line.split(":", 1)[1].strip()
                            if val.upper() not in ["NAO", "NÃO", "NONE", "NULL", "FALSE", ""]:
                                transferir_setor = val
                        elif line.startswith("ENVIAR_LOCALIZACAO:"):
                            val = line.split(":", 1)[1].strip().upper()
                            enviar_localizacao = "SIM" in val or "TRUE" in val
                        elif line.startswith("ENVIAR_PIX:"):
                            val = line.split(":", 1)[1].strip().upper()
                            enviar_pix = "SIM" in val or "TRUE" in val
                        else:
                            if current_field == "RESPOSTA":
                                resposta_lines.append(line)
                    resposta = "\n".join(resposta_lines).strip()
                    if not resposta:
                        resposta = text

                # 🛡️ CAMADA DE VALIDAÇÃO PÓS-RESPOSTA (ANTI-HALLUCINATION POST-GUARD)
                sanitized_reply = validate_and_sanitize_ai_response(
                    raw_ai_message=resposta,
                    had_null_name=had_null_name,
                    had_empty_history=had_empty_history,
                    store_name=store_name
                )

                return {
                    "resposta": sanitized_reply,
                    "temperatura": temperatura,
                    "escalar_humano": False if is_technician_or_admin else (escalar_humano or bool(atendente_preferencial)),
                    "atendente_preferencial": atendente_preferencial,
                    "transferir_setor": None if is_technician_or_admin else transferir_setor,
                    "nova_memoria": nova_memoria,
                    "finalizar_conversa": False,
                    "enviar_localizacao": enviar_localizacao,
                    "enviar_pix": enviar_pix,
                    "contexto_enviado": contexto_atendimento
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
        has_real_name = bool(customer_name and clean_name not in ["Cliente", ""])
        display_name = clean_name if has_real_name else "Cliente (nome não informado)"

        if not messages_history:
            return (
                f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                f"👤 *Cliente:* {display_name}\n"
                f"🔢 *Protocolo:* {protocol_number}\n"
                f"🏢 *Departamento:* {department_name}\n"
                f"🎯 *Motivo do Contato:* Novo chamado iniciado pelo cliente.\n"
                f"⚙️ *Equipamento/Modelo:* Não informado pelo cliente\n"
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
            "# DIRETRIZES MANDATÓRIAS DE FACTUALIDADE E RASTREABILIDADE DE ORIGEM (TAREFA 2):\n"
            "1. FONTE EXCLUSIVA: Preencha cada campo usando APENAS o que o cliente escreveu literalmente.\n"
            "2. NÃO INFERIR DETALHES TÉCNICOS: Se marca, modelo ou detalhe técnico não foi digitado expressamente pelo cliente, defina 'origem': 'nao_informado' e 'valor': 'Não informado pelo cliente'. NUNCA infira nem complete com algo plausível, mesmo que a IA Concierge tenha sugerido esse detalhe na conversa.\n"
            "3. RASTREABILIDADE: Se um detalhe técnico ou defeito foi sugerido pela IA mas o cliente ainda não confirmou com todas as letras, defina 'origem': 'ia_sugeriu'. Se o próprio cliente digitou, defina 'origem': 'cliente'.\n"
            f"4. NOME DO CLIENTE: Use '{display_name}'. Proibido inventar títulos (Eng., Dr.) ou sobrenomes.\n\n"
            "Responda SEMPRE em JSON estruturado:\n"
            "{\n"
            "  \"motivo_contato\": {\"valor\": \"resumo curto da necessidade\", \"origem\": \"cliente | ia_sugeriu\"},\n"
            "  \"equipamento_modelo\": {\"valor\": \"nome do equipamento ou Não informado pelo cliente\", \"origem\": \"cliente | ia_sugeriu | nao_informado\"},\n"
            "  \"defeito\": {\"valor\": \"defeito relatado ou Não informado\", \"origem\": \"cliente | ia_sugeriu | nao_informado\"},\n"
            "  \"onde_parou\": \"o que a IA/cliente falaram por último\",\n"
            "  \"proxima_acao\": \"orientação prática e direta para o atendente continuar\"\n"
            "}\n\n"
            f"HISTÓRICO REAL DA CONVERSA:\n" + "\n".join(messages_text)
        )

        def format_field(field_obj: Dict[str, Any]) -> str:
            if not isinstance(field_obj, dict):
                return str(field_obj or "Não informado pelo cliente")
            val = str(field_obj.get("valor", "")).strip()
            orig = str(field_obj.get("origem", "")).strip().lower()
            if orig == "nao_informado" or not val or val.lower() in ["não informado", "nao informado", "não informado pelo cliente", "nenhum", "null"]:
                return "Não informado pelo cliente"
            if orig == "ia_sugeriu":
                return f"{val} ⚠️ (detalhe sugerido pela IA, não confirmado literalmente pelo cliente)"
            return val

        if not client:
            return (
                f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                f"👤 *Cliente:* {display_name}\n"
                f"🔢 *Protocolo:* {protocol_number}\n"
                f"🏢 *Departamento:* {department_name}\n"
                f"🎯 *Motivo do Contato:* Atendimento transferido para equipe humana.\n"
                f"⚙️ *Equipamento/Modelo:* Não informado pelo cliente\n"
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
                    raw_text = response.text.strip()
                    try:
                        clean_json_str = raw_text
                        if clean_json_str.startswith("```"):
                            clean_json_str = re.sub(r'^```(?:json)?\s*', '', clean_json_str)
                            clean_json_str = re.sub(r'\s*```$', '', clean_json_str)
                        clean_json_str = clean_json_str.strip()
                        parsed = json.loads(clean_json_str)
                        
                        motivo = format_field(parsed.get("motivo_contato", {}))
                        equipamento = format_field(parsed.get("equipamento_modelo", {}))
                        defeito = format_field(parsed.get("defeito", {}))
                        onde_parou = str(parsed.get("onde_parou", "Transferência para operador")).strip()
                        proxima_acao = str(parsed.get("proxima_acao", "Analisar histórico e responder o cliente")).strip()

                        return (
                            f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
                            f"👤 *Cliente:* {display_name}\n"
                            f"🔢 *Protocolo:* {protocol_number}\n"
                            f"🏢 *Departamento:* {department_name}\n"
                            f"🎯 *Motivo do Contato:* {motivo}\n"
                            f"⚙️ *Equipamento/Modelo:* {equipamento}\n"
                            f"🛠️ *Defeito Relatado:* {defeito}\n"
                            f"📍 *Onde Parou:* {onde_parou}\n"
                            f"👉 *Próxima Ação Sugerida:* {proxima_acao}"
                        )
                    except Exception:
                        # Fallback text if json decode fails
                        return raw_text
            except Exception as e:
                logger.warning(f"Error generating onboarding summary with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return (
            f"📋 *RESUMO DE ONBOARDING (ONDE PAROU)*\n"
            f"👤 *Cliente:* {display_name}\n"
            f"🔢 *Protocolo:* {protocol_number}\n"
            f"🏢 *Departamento:* {department_name}\n"
            f"🎯 *Motivo do Contato:* Atendimento transferido para operador.\n"
            f"⚙️ *Equipamento/Modelo:* Não informado pelo cliente\n"
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
        customer_phone: Optional[str] = None,
        protocol_number: Optional[str] = None,
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

        contexto_cliente_block = format_clean_client_context(
            customer_name=customer_name,
            customer_phone=customer_phone,
            protocol_number=protocol_number,
            memory_summary=memory_summary
        )

        rag_prompt = f"\nINFORMAÇÕES DA BASE DE CONHECIMENTO DA EMPRESA (RAG):\n{rag_context}\n" if rag_context else ""

        prompt = (
            "Você é um consultor assistente de atendimento da empresa Servweld (Equipamentos de Solda, Corte, Assistência Técnica e Locação).\n"
            f"O atendente humano do setor '{department_name}' solicitou uma SUGESTÃO DE RESPOSTA para enviar ao cliente.\n\n"
            f"{STRICT_CONTEXT_AND_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{contexto_cliente_block}\n"
            f"{rag_prompt}"
            "DIRETRIZES DA RESPOSTA:\n"
            "1. Escreva uma mensagem pronta para envio, redigida em primeira pessoa (como se você fosse o atendente humano da Servweld).\n"
            "2. Seja extremamente educado, claro, acolhedor, profissional e direto ao ponto.\n"
            "3. Não use introduções explicativas como 'Aqui está uma sugestão:' ou 'Você pode dizer:'. Retorne APENAS o texto exato da resposta a ser colocada no chat.\n"
            "4. Dê continuidade imediata ao diálogo, respondendo à última dúvida ou solicitação do cliente com base no histórico real.\n"
            "5. Se for necessária uma informação técnica ou valor que não conste na base, sugira verificar com o setor responsável em vez de inventar números.\n\n"
            f"HISTÓRICO DA CONVERSA:\n" + ("\n".join(messages_text) if messages_text else "nenhum")
        )

        if not client:
            return f"Olá! Como posso te ajudar hoje?"

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

        return f"Olá! Recebi sua mensagem e já estou verificando o seu caso para te ajudar."

    async def generate_copilot_consultation(
        self,
        attendant_name: str,
        customer_name: str,
        department_name: str,
        conversation_history: List[Dict[str, str]],
        copilot_chat_history: List[Dict[str, str]],
        user_question: str,
        rag_context: Optional[str] = None,
        memory_summary: Optional[str] = None,
        customer_phone: Optional[str] = None,
        protocol_number: Optional[str] = None,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Interactive Copilot AI for the human attendant:
        - Analyzes the full customer conversation history.
        - Uses department RAG knowledge base (manuals, prices, store procedures).
        - Answers the attendant's questions and provides ready-to-use message drafts.
        """
        client = self.get_client_for_key(tenant_gemini_api_key)
        primary_model = tenant_gemini_model_name or "gemini-3.1-flash-lite"
        clean_name = sanitize_customer_name(customer_name)

        customer_transcript = []
        for m in conversation_history:
            r_raw = str(m.get("remetente", "")).lower()
            if r_raw == "cliente":
                remetente = f"Cliente ({clean_name})"
            elif r_raw == "ia":
                remetente = "IA Concierge"
            elif r_raw == "sistema":
                remetente = "Sistema"
            else:
                remetente = f"Atendente ({attendant_name})"

            conteudo = str(m.get("conteudo", "")).strip()
            if conteudo:
                customer_transcript.append(f"[{remetente}]: {conteudo}")

        copilot_history_text = []
        for ch in (copilot_chat_history or []):
            role = "Atendente" if ch.get("role") == "user" else "Copiloto IA"
            copilot_history_text.append(f"{role}: {ch.get('content', '')}")

        contexto_cliente_block = format_clean_client_context(
            customer_name=customer_name,
            customer_phone=customer_phone,
            protocol_number=protocol_number,
            memory_summary=memory_summary
        )

        dados_oficiais_empresa = (
            "🏢 DADOS OFICIAIS DA EMPRESA (SERVWELD / SERVSOLDA):\n"
            "• Nome da Empresa: Servweld Equipamentos e Assistência Técnica / Servsolda\n"
            "• Endereço Oficial: SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, CEP: 71215-226\n"
            "• Link do Google Maps / GPS: https://maps.google.com/?q=-15.820418,-47.956467\n"
            "• Horário de Atendimento e Funcionamento: Segunda a Sexta-feira das 08h00 às 18h00 (Horário de Brasília). Fechado aos sábados, domingos e feriados.\n"
            "• Setores da Empresa:\n"
            "  - Assistência Técnica: Conserto, manutenção, revisão e testes em máquinas de solda MIG/TIG/MMA/Plasma, tochas, placas eletrônicas e orçamentos.\n"
            "  - Vendas: Máquinas novas, tochas, consumíveis (bicos, bocais, difusores, pinças, lentes), arames (MIG/MAG), varetas TIG, eletrodos, reguladores de gás e EPIs.\n"
            "  - Locação: Aluguel de máquinas de solda e equipamentos.\n"
            "  - Financeiro: Faturamento, boletos, notas fiscais e dados para pagamento via PIX.\n"
            "• DIRETRIZES PARA LOCALIZAÇÃO E MAPAS:\n"
            "  - NUNCA use links quebrados ou do Firebase Dynamic Links (como maps.app.goo.gl).\n"
            "  - Quando for solicitada mensagem com localização/endereço ou rota, elabore uma mensagem acolhedora e personalizada com o contexto do cliente (cumprimente com o nome do cliente, mencione as máquinas ou serviço a ser realizado), passe o endereço oficial, horários de atendimento, e informe ao cliente que o mapa interativo com GPS (para clicar e navegar no Google Maps / Waze) está logo abaixo.\n"
            "  - Se citar o link no texto, utilize sempre: https://maps.google.com/?q=-15.820418,-47.956467\n"
            "• REGRA MANDATÓRIA: NUNCA USE PLACEHOLDERS como '[INSERIR ENDEREÇO...]', '[INSERIR LINK...]' ou '[PREENCHER AQUI]'. Sempre insira diretamente o endereço real e dados oficiais acima!\n"
        )

        rag_block = f"\n📚 BASE DE CONHECIMENTO TÉCNICO & PROCEDIMENTOS DA EMPRESA (RAG):\n{rag_context}\n" if rag_context else ""
        copilot_block = f"\n💬 HISTÓRICO DE CONSULTA ENTRE VOCÊ E O ATENDENTE:\n" + "\n".join(copilot_history_text) + "\n" if copilot_history_text else ""

        system_instruction = (
            "Você é o COPILOTO IA ESPECIALISTA DA SERVWELD (Equipamentos de Solda, Corte, Assistência Técnica e Locação).\n"
            f"Você está prestando consultoria em tempo real diretamente para o ATENDENTE HUMANO ({attendant_name}) do setor '{department_name}'.\n\n"
            f"O atendente está em atendimento com o cliente '{clean_name}'.\n\n"
            f"{STRICT_CONTEXT_AND_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{CUSTOMER_NAME_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{RAG_PRICE_AND_PRODUCT_ANTI_HALLUCINATION_DIRECTIVE}\n"
            f"{dados_oficiais_empresa}\n"
            f"{contexto_cliente_block}\n"
            f"{rag_block}"
            "SUAS ATRIBUIÇÕES:\n"
            "1. Analise todo o histórico da conversa entre o cliente e a empresa.\n"
            "2. Oriente o atendente com clareza, objetividade técnica ou comercial, explicando causas de defeitos, diagnósticos, procedimentos, compatibilidade de peças ou estratégias de vendas.\n"
            "3. Quando a pergunta do atendente pedir uma sugestão de resposta para enviar ao cliente (ou quando for conveniente fornecer uma mensagem pronta), inclua uma mensagem pronta completa formatada entre as tags [SUGESTAO_RESPOSTA] e [/SUGESTAO_RESPOSTA]. NUNCA use placeholders — coloque o texto 100% pronto para envio imediato. O atendente poderá inserir essa sugestão no chat com 1 clique.\n"
            "4. Mantenha um tom profissional, prestativo e colaborativo de parceiro/mentor técnico.\n\n"
            f"📜 HISTÓRICO REAL DA CONVERSA COM O CLIENTE:\n" + ("\n".join(customer_transcript[-25:]) if customer_transcript else "Nenhuma mensagem anterior.") + "\n"
            f"{copilot_block}\n"
            f"PERGUNTA OU SOLICITAÇÃO DO ATENDENTE ({attendant_name}):\n{user_question}"
        )

        if not client:
            return {
                "answer": "Copiloto IA indisponível: Chave de API Gemini não configurada nas configurações do sistema.",
                "suggested_message": ""
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
                    contents=system_instruction
                )
                if response and response.text:
                    full_text = response.text.strip()
                    
                    # Extract suggested message if delimited
                    suggested_msg = ""
                    if "[SUGESTAO_RESPOSTA]" in full_text and "[/SUGESTAO_RESPOSTA]" in full_text:
                        parts = full_text.split("[SUGESTAO_RESPOSTA]")
                        clean_answer = parts[0].strip()
                        rest = parts[1].split("[/SUGESTAO_RESPOSTA]")
                        suggested_msg = rest[0].strip()
                        if len(rest) > 1 and rest[1].strip():
                            clean_answer += "\n\n" + rest[1].strip()
                    else:
                        clean_answer = full_text

                    return {
                        "answer": clean_answer,
                        "suggested_message": suggested_msg
                    }
            except Exception as e:
                logger.warning(f"Error in copilot consultation with '{m_name}': {e}")
                await asyncio.sleep(0.3)

        return {
            "answer": "Desculpe, ocorreu uma instabilidade momentânea ao processar sua consulta com o Copiloto IA. Por favor, tente novamente.",
            "suggested_message": ""
        }

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

    async def classify_store_info_intent(
        self,
        user_message: str,
        tenant_gemini_api_key: Optional[str] = None,
        tenant_gemini_model_name: Optional[str] = None
    ) -> str:
        """
        Classifies whether the user is asking for:
        1. STORE_LOCATION: Specifically asking where the company/store is located, store address, or location to visit.
           CRITICAL: If the customer is talking about their OWN location ("minha localização", "estou em Sobradinho",
           "vou mandar minha localização", "entregam no meu endereço"), this is NOT STORE_LOCATION -> return NONE.
        2. STORE_HOURS: Asking for the store opening/closing hours or days of operation.
        3. NONE: Any other question, product inquiry, technical issue, greetings, or customer talking about themselves.
        """
        if not user_message or not isinstance(user_message, str):
            return "NONE"

        clean_text = user_message.strip()
        if len(clean_text) < 3:
            return "NONE"

        clean_lower = clean_text.lower()

        # Fast heuristic: if user explicitly states it's their own location, rule out STORE_LOCATION immediately
        is_client_own_location = any(k in clean_lower for k in [
            "minha localiza", "minha rua", "meu bairro", "minha cidade", "minha casa",
            "meu endereço", "meu endereco", "estou em ", "estou no ", "estou na ",
            "sou de ", "moro em ", "aqui em ", "aqui no ", "aqui na ",
            "vou mandar minha", "vou te mandar minha", "vou enviar minha",
            "entregam na", "entregam no", "entregam em"
        ])
        if is_client_own_location and not any(k in clean_lower for k in ["onde fica a loja", "qual o endereço de vocês", "endereço da servweld"]):
            return "NONE"

        prompt = (
            "Você é um classificador de intenções extremamente preciso para uma empresa de equipamentos e assistência técnica.\n"
            "Analise a mensagem do cliente abaixo e determine se ele está pedindo uma informação institucional da EMPRESA.\n\n"
            f"MENSAGEM DO CLIENTE: \"{clean_text}\"\n\n"
            "CATEGORIAS POSSÍVEIS:\n"
            "- STORE_LOCATION: O cliente está pedindo o ENDEREÇO ou LOCALIZAÇÃO DA LOJA/EMPRESA (ex: 'Onde vocês ficam?', 'Qual o endereço da loja?', 'Me passa a localização de vocês?', 'Onde levo minha máquina?').\n"
            "  *ATENÇÃO MÁXIMA*: Se o cliente estiver falando da PRÓPRIA localização dele (ex: 'Moro em Sobradinho', 'Minha localização é tal', 'Estou no Guará', 'Vocês entregam aqui na minha cidade?'), NUNCA classifique como STORE_LOCATION! Nesses casos responda NONE.\n"
            "- STORE_HOURS: O cliente está perguntando o HORÁRIO DE FUNCIONAMENTO ou atendimento da loja (ex: 'Qual o horário de funcionamento?', 'Até que horas vocês atendem?', 'Que horas abre?', 'Abrem no sábado?').\n"
            "- NONE: O cliente está falando de outro assunto (produtos, máquinas, preços, defeitos, saudações, ou falando de si mesmo).\n\n"
            "Responda APENAS com uma das três palavras: STORE_LOCATION, STORE_HOURS ou NONE."
        )

        client = self.get_client_for_key(tenant_gemini_api_key)
        model_name = tenant_gemini_model_name or "gemini-2.5-flash"

        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt
            )
            raw_res = (response.text or "").strip().upper()
            if "STORE_LOCATION" in raw_res:
                return "STORE_LOCATION"
            elif "STORE_HOURS" in raw_res:
                return "STORE_HOURS"
            return "NONE"
        except Exception as e:
            logger.warning(f"Error classifying intent with Gemini: {e}")
            if not is_client_own_location and any(k in clean_lower for k in [
                "onde fica", "onde vocês ficam", "qual o endereço", "qual o endereco",
                "localização da loja", "localizacao da loja", "localização de vocês", "localizacao de vocês"
            ]):
                return "STORE_LOCATION"
            if any(k in clean_lower for k in [
                "horário de funcionamento", "horario de funcionamento", "horário de atendimento",
                "horario de atendimento", "que horas abre", "até que horas", "ate que horas"
            ]):
                return "STORE_HOURS"
            return "NONE"


gemini_service = GeminiService()
