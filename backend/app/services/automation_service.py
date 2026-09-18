import asyncio
import logging
import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Tenant, Conversation, Message, MessageSender, MessageType, WhatsAppNumber
from app.services.evolution_service import evolution_service
from app.services.gemini_service import gemini_service
from app.services.settings_service import settings_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("automation_service")

DEFAULT_AUTOMATION_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "os_handler": {
        "enabled": True,
        "trigger_on_attendant": True,
        "trigger_on_customer": True,
        "keywords": ["posto autorizado", "status:", "aberto a os", "ordem de servico", "servsolda", "servweld"],
        "match_mode": "any",
        "typing_delay_ms": 2000,
        "diagnostic_prices": {
            "alimentador de arame": 150,
            "filtro de ar": 60,
            "maçarico de corte": 50,
            "mig": 200,
            "cnc": 400,
            "retificador": 200,
            "teste": 60,
            "transformador de solda": 90,
            "carregador de bateria": 80,
            "ignitor": 80,
            "maçarico de solda": 50,
            "tig": 200,
            "painel de secagem": 200,
            "talha elétrica": 250,
            "tocha de solda": 50,
            "unidade de refrigeração": 100,
            "compressor de ar": 250,
            "inversor": 100,
            "plasma": 200,
            "repuxadeira": 150,
            "regulador": 50,
            "tartaruga": 150,
            "tocha de corte": 50
        },
        "templates": {
            "orcamento": [
                "Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊",
                "💰 *Diagnóstico Técnico:* Caso o orçamento *NÃO SEJA APROVADO*, será cobrada uma taxa de *R$ {valor_diagnostico}*. Esse valor poderá ser abatido se o serviço for autorizado posteriormente.",
                "⏳ *Validade do Orçamento:* 15 dias.\n🔧 *Garantia:* 90 dias para serviços e peças trocadas.\n📦 *Peças do cliente:* garantia somente da mão de obra.\n⚠️ Após 90 dias da liberação para retirada, o equipamento poderá ser considerado abandonado e sucateado conforme nossas condições gerais."
            ],
            "garantia_loja": [
                "Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊",
                "🔧 *Garantia de Loja:* 90 dias contados a partir do serviço anterior.\nCobre vícios de mão de obra e peças trocadas.\n📦 *Peças do cliente:* garantia apenas de mão de obra.",
                "⚠️ Após 90 dias da liberação para retirada, o equipamento pode ser considerado abandonado e sucateado."
            ],
            "garantia_fabrica": [
                "Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊",
                "🏭 *Garantia de Fábrica:* Não há cobrança de diagnóstico ou orçamento. Todos os custos são arcados pela fabricante.",
                "⚠️ Após 90 dias da liberação para retirada, o equipamento pode ser considerado abandonado e sucateado."
            ],
            "locacao": [
                "Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊",
                "🔑 *Locação de Equipamento:* a devolução deve ocorrer na data combinada. Avarias, peças faltantes ou atraso na devolução podem gerar cobrança adicional, conforme as Condições Gerais informadas na sua Ordem de Serviço.",
                "📦 *Caução/Depósito:* condicionado à devolução do equipamento em perfeito estado de funcionamento."
            ]
        },
        # Pergunta de confirmação enviada ANTES do PDF completo da O.S. - o cliente precisa
        # responder (texto livre, interpretado por IA) confirmando que leu a condição mais
        # importante daquele tipo de O.S. antes de receber o arquivo. Editável na mesma tela
        # de Automações.
        "confirmation_prompts": {
            "orcamento": "⚠️ *Muito importante:* caso o orçamento *NÃO seja aprovado*, será cobrada a taxa de diagnóstico informada acima (R$ {valor_diagnostico}). Responda *SIM* confirmando que leu essa condição para eu te enviar o PDF completo da sua Ordem de Serviço.",
            "garantia_loja": "⚠️ Após 90 dias da liberação para retirada, o equipamento pode ser considerado abandonado e sucateado, conforme as Condições Gerais de Serviço. Responda *SIM* confirmando que leu essa condição para eu te enviar o PDF completo da sua Ordem de Serviço.",
            "garantia_fabrica": "⚠️ Após 90 dias da liberação para retirada, o equipamento pode ser considerado abandonado e sucateado, conforme as Condições Gerais de Serviço. Responda *SIM* confirmando que leu essa condição para eu te enviar o PDF completo da sua Ordem de Serviço.",
            "locacao": "⚠️ Avarias, peças faltantes ou atraso na devolução podem gerar cobrança adicional sobre a caução. Responda *SIM* confirmando que leu essa condição para eu te enviar o PDF completo da sua Ordem de Serviço."
        }
    },
    # Avisos de progresso disparados quando o técnico muda o "Tipo de Evento" da O.S. no
    # Softsystem (aba Eventos). ENTRADA e "ORC ENV/ AGUARD APROVACAO" já são cobertos pelos
    # fluxos de cima (natureza + aprovação) - aqui ficam os demais estágios do ciclo de vida.
    # Chave = código do tipo de evento no Softsystem (CODTIPOEVENTOOS), editável na tela de
    # Automações. {nome_cliente} é o único placeholder suportado aqui.
    "eventos_os": {
        "enabled": True,
        "templates": {
            "2": "🔍 Olá, {nome_cliente}! Seu equipamento está em *avaliação técnica* no momento.",
            "4": "🔧 Olá, {nome_cliente}! Seu equipamento entrou em *execução/reparo*.",
            "6": "✅ Ótima notícia, {nome_cliente}! Seu equipamento já está pronto e *disponível para retirada*.",
            "7": "🏁 Olá, {nome_cliente}! Seu atendimento foi *finalizado*. Agradecemos a confiança em nossos serviços!",
            "8": "📦 Olá, {nome_cliente}! Estamos *aguardando a chegada de uma peça* necessária para o reparo do seu equipamento. Assim que chegar, damos continuidade.",
            "11": "⚠️ Olá, {nome_cliente}! Identificamos que o seu equipamento *não possui conserto viável*. Em breve entraremos em contato com mais detalhes.",
            "12": "ℹ️ Olá, {nome_cliente}! O reparo do seu equipamento *não foi autorizado*, conforme combinado.",
            "13": "✅ Olá, {nome_cliente}! Não identificamos nenhum defeito no seu equipamento durante a avaliação.",
            "14": "⚠️ Olá, {nome_cliente}! Conforme as Condições Gerais e o prazo já decorrido, o seu equipamento foi *desmontado/sucateado*."
        }
    },
    "custom_rules": [
        {
            "id": "rule_pix",
            "name": "Chave Pix e Pagamento",
            "enabled": True,
            "trigger_on": "both",
            "match_mode": "any",
            "keywords": ["qual o pix", "chave pix", "como pagar", "dados bancarios", "pix da loja"],
            "reply_type": "single",
            "reply_text": "📌 *Dados Oficiais para Pagamento via Pix:*\nChave: contato@servweld.com.br\nFavorecido: SERVWELD / SERVSOLDA\n\nPor favor, envie o comprovante nesta conversa para confirmação.",
            "reply_sequence": [],
            "typing_delay_ms": 2000
        }
    ],
    "ai_fallback_intent": True
}

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("utf-8")

def get_greeting() -> str:
    # Brazil Time (UTC-3)
    br_hour = (datetime.utcnow() - timedelta(hours=3)).hour
    if 5 <= br_hour < 12:
        return "Bom dia"
    elif 12 <= br_hour < 18:
        return "Boa tarde"
    else:
        return "Boa noite"

class AutomationService:

    @staticmethod
    async def get_tenant_automations(db: AsyncSession, tenant_id: int) -> Dict[str, Any]:
        stmt = select(Tenant.config_geral).where(Tenant.id == tenant_id)
        res = await db.execute(stmt)
        cfg = res.scalar_one_or_none() or {}
        automations = cfg.get("automations")
        if not automations:
            return DEFAULT_AUTOMATION_CONFIG
        return automations

    @staticmethod
    async def save_tenant_automations(db: AsyncSession, tenant_id: int, automations_data: Dict[str, Any]) -> Dict[str, Any]:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        res = await db.execute(stmt)
        tenant = res.scalar_one_or_none()
        if not tenant:
            raise ValueError("Tenant não encontrado")

        cfg = dict(tenant.config_geral or {})
        cfg["automations"] = automations_data
        tenant.config_geral = cfg
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(tenant, "config_geral")
        await db.commit()
        return automations_data

    @staticmethod
    def match_os_handler(
        text: str,
        config: Dict[str, Any],
        from_me: bool,
        client_name: str
    ) -> Optional[Tuple[str, List[str]]]:
        os_cfg = config.get("os_handler", {})
        if not os_cfg.get("enabled", True):
            return None

        trigger_attendant = os_cfg.get("trigger_on_attendant", True)
        trigger_customer = os_cfg.get("trigger_on_customer", True)

        if from_me and not trigger_attendant:
            return None
        if not from_me and not trigger_customer:
            return None

        norm_text = normalize_text(text)
        keywords = [normalize_text(k) for k in os_cfg.get("keywords", []) if k]
        match_mode = os_cfg.get("match_mode", "any")

        if keywords:
            if match_mode == "all":
                # Must contain ALL keywords
                if not all(k in norm_text for k in keywords):
                    return None
            else:
                # Must contain AT LEAST ONE keyword
                if not any(k in norm_text for k in keywords):
                    return None

        status = None
        if "status: orcamento" in norm_text or "status:orcamento" in norm_text or ("orcamento" in norm_text and ("aberto a os" in norm_text or "posto autorizado" in norm_text or "os " in norm_text)):
            status = "orcamento"
        elif "garantia de loja" in norm_text or "garantia loja" in norm_text:
            status = "garantia_loja"
        elif "garantia de fabrica" in norm_text or "garantia fabrica" in norm_text:
            status = "garantia_fabrica"
        elif "status: locacao" in norm_text or "status:locacao" in norm_text or "locacao" in norm_text:
            status = "locacao"

        if not status:
            return None

        diag_prices: Dict[str, Any] = os_cfg.get("diagnostic_prices", {})
        detected_equip, valor_diagnostico = ("Equipamento", 100)
        if status == "orcamento":
            detected_equip, valor_diagnostico = AutomationService.resolve_diagnostic_price(norm_text, diag_prices)

        formatted_messages = AutomationService.format_os_templates(
            status, config, client_name, detected_equip, valor_diagnostico
        )
        if not formatted_messages:
            return None

        return status, formatted_messages

    @staticmethod
    def resolve_diagnostic_price(text: str, diag_prices: Dict[str, Any]) -> Tuple[str, int]:
        """
        Finds the best-matching equipment name (from the diagnostic_prices table) mentioned
        anywhere in `text` (already normalized or raw - normalize_text is idempotent-safe to
        re-run), longest name first so e.g. "tocha de corte" wins over "tocha de solda" when
        only one is actually present. Falls back to a generic R$100 default when nothing matches
        (equipment not yet cataloged) rather than skipping the message entirely.
        """
        norm_text = normalize_text(text)
        sorted_equips = sorted(diag_prices.keys(), key=lambda x: len(x), reverse=True)
        for eq in sorted_equips:
            if normalize_text(eq) in norm_text:
                return eq.title(), diag_prices[eq]

        # Fuzzy fallback: the equipment field on the real O.S. PDF had a typo
        # ("TRASNFORMADOR" instead of "TRANSFORMADOR") that a plain substring scan can't
        # catch. difflib is stdlib (no new dependency) and a 0.75 cutoff is strict enough to
        # avoid false positives on a long free-text message (the chat-triggered call site).
        import difflib
        norm_equips = {normalize_text(eq): eq for eq in diag_prices.keys()}
        close = difflib.get_close_matches(norm_text, list(norm_equips.keys()), n=1, cutoff=0.75)
        if close:
            eq = norm_equips[close[0]]
            return eq.title(), diag_prices[eq]

        return "Equipamento", 100

    @staticmethod
    def format_os_templates(
        status: str,
        config: Dict[str, Any],
        client_name: str,
        detected_equip: str = "Equipamento",
        valor_diagnostico: int = 100
    ) -> List[str]:
        """
        Pure template-formatting step, shared by the chat-message-triggered match_os_handler()
        AND the PDF-ingestion flow (which resolves equip/valor itself from the O.S. PDF instead
        of scanning a chat message's text).
        """
        os_cfg = config.get("os_handler", {})
        templates = os_cfg.get("templates", {})
        template_msgs = templates.get(status, [])
        if not template_msgs:
            return []

        saudacao = get_greeting()
        nome_display = client_name or "Cliente"

        formatted_messages = []
        for tmpl in template_msgs:
            msg_str = (
                tmpl
                .replace("{nome_cliente}", nome_display)
                .replace("{saudacao}", saudacao)
                .replace("{valor_diagnostico}", str(valor_diagnostico))
                .replace("{equipamento}", detected_equip)
            )
            formatted_messages.append(msg_str)

        return formatted_messages

    @staticmethod
    def format_confirmation_prompt(
        status: str,
        config: Dict[str, Any],
        valor_diagnostico: int = 100
    ) -> Optional[str]:
        """The 'please confirm you read this' gate message sent before the O.S. PDF itself."""
        os_cfg = config.get("os_handler", {})
        prompts = os_cfg.get("confirmation_prompts", {})
        prompt = prompts.get(status)
        if not prompt:
            return None
        return prompt.replace("{valor_diagnostico}", str(valor_diagnostico))

    @staticmethod
    def format_evento_message(
        cod_tipo_evento: int,
        config: Dict[str, Any],
        client_name: str
    ) -> Optional[str]:
        """
        Progress-update message for a Softsystem O.S. event (aba Eventos) other than ENTRADA
        or ORC ENV/AGUARD APROVACAO, which are handled by the natureza/approval flows above.
        Returns None if this event type has no configured message (e.g. disabled, or a code
        not in the map) - caller should simply not send anything in that case.
        """
        ev_cfg = config.get("eventos_os", {})
        if not ev_cfg.get("enabled", True):
            return None
        templates = ev_cfg.get("templates", {})
        tmpl = templates.get(str(cod_tipo_evento))
        if not tmpl:
            return None
        return tmpl.replace("{nome_cliente}", client_name or "Cliente")

    @staticmethod
    def match_custom_rules(
        text: str,
        config: Dict[str, Any],
        from_me: bool,
        client_name: str = "Cliente"
    ) -> Optional[List[str]]:
        rules = config.get("custom_rules", [])
        norm_text = normalize_text(text)
        saudacao = get_greeting()

        for r in rules:
            if not r.get("enabled", True):
                continue
            
            trigger_on = r.get("trigger_on", "both")
            if trigger_on == "attendant" and not from_me:
                continue
            if trigger_on == "customer" and from_me:
                continue

            keywords = [normalize_text(k) for k in r.get("keywords", []) if k]
            match_mode = r.get("match_mode", "any")

            matched = False
            if keywords:
                if match_mode == "all":
                    matched = all(k in norm_text for k in keywords)
                else:
                    matched = any(k in norm_text for k in keywords)

            if matched:
                # Check if it's a sequence or single reply
                seq = r.get("reply_sequence")
                if isinstance(seq, list) and len(seq) > 0:
                    formatted_seq = []
                    for s in seq:
                        msg_str = (
                            s
                            .replace("{nome_cliente}", client_name)
                            .replace("{saudacao}", saudacao)
                        )
                        formatted_seq.append(msg_str)
                    return formatted_seq
                
                reply = r.get("reply_text")
                if reply:
                    formatted = (
                        reply
                        .replace("{nome_cliente}", client_name)
                        .replace("{saudacao}", saudacao)
                    )
                    return [formatted]

        return None

    @staticmethod
    def classify_yes_no_reply(text: str) -> str:
        """
        Simple keyword-based yes/no classifier for confirmation gates (e.g. "confirme que leu
        as condições para receber o PDF"). Deliberately keyword-based rather than calling an
        LLM - matches this module's own established pattern (all of match_os_handler/
        match_custom_rules already work this way), and doesn't depend on a tenant having a
        Gemini API key configured. Returns "CONFIRMA", "NEGA" or "AMBIGUA".
        """
        norm = normalize_text(text)
        yes_words = ["sim", "confirmo", "confirmado", "concordo", "aceito", "certo", "correto", "isso", "pode", "ok", "okay", "de acordo", "afirmativo"]
        no_words = ["nao", "recuso", "negativo", "cancela", "cancelar", "nunca"]
        has_yes = any(w in norm for w in yes_words)
        has_no = any(w in norm for w in no_words)
        if has_yes and not has_no:
            return "CONFIRMA"
        if has_no and not has_yes:
            return "NEGA"
        return "AMBIGUA"

    @classmethod
    async def chat_ai_rule_copilot(
        cls,
        db: AsyncSession,
        tenant_id: int,
        conversation_history: List[Dict[str, str]],
        user_message: str
    ) -> Dict[str, Any]:
        """
        Interactive AI Copilot that converses with the user in Portuguese,
        gathers required requirements, asks clarifying questions, and outputs a complete JSON automation rule.
        """
        decrypted = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
        api_key = decrypted.get("gemini_api_key")
        model_name = decrypted.get("gemini_model_name") or "gemini-2.5-flash"

        if not api_key:
            return {
                "reply": "⚠️ Nenhuma chave de API do Google Gemini configurada. Por favor, configure a chave na aba 'Integrações & Segurança' para usar o Copilot.",
                "proposed_rule": None
            }

        client = gemini_service.get_client_for_key(api_key)

        current_automations = await cls.get_tenant_automations(db, tenant_id)

        system_instruction = (
            "Você é o 'Copilot de Automações & Gatilhos Inteligentes' do sistema Omnichannel SERVWELD / SERVSOLDA.\n\n"
            "Seu objetivo é conversar de forma amigável, clara e prestativa com o proprietário/atendente, coletando os detalhes da automação desejada.\n\n"
            "COMO AGIR:\n"
            "1. Ouça a necessidade do usuário (ex: aviso de garantia, regras de orçamento, cobrança de taxa, respostas a dúvidas frequentes, recados padrão de entrega, etc.).\n"
            "2. Se faltarem informações importantes (ex: quem dispara — atendente ou cliente?, quais palavras-chave?, tempo de digitação?, balão único ou sequência?), faça perguntas pontuais e objetivas de forma cordial.\n"
            "3. Quando você tiver informações suficientes para criar ou refinar o gatilho, apresente uma explicação clara em texto e, NO FINAL DA RESPOSTA, inclua OBRIGATORIAMENTE um bloco formatado com ```json_rule ... ``` contendo a regra estruturada pronta para ser aplicada no sistema.\n\n"
            "FORMATO DO BLOCO json_rule:\n"
            "```json_rule\n"
            "{\n"
            f'  "id": "rule_{int(datetime.utcnow().timestamp())}",\n'
            '  "name": "Título Descritivo e Claro do Gatilho",\n'
            '  "enabled": true,\n'
            '  "trigger_on": "both",\n'
            '  "match_mode": "any",\n'
            '  "keywords": ["palavra1", "palavra2", "expressao completa"],\n'
            '  "reply_type": "sequence",\n'
            '  "reply_text": "Texto completo principal com emojis e quebras de linha...",\n'
            '  "reply_sequence": [\n'
            '    "Balão 1: Olá, {nome_cliente}! 👋 {saudacao}, tudo bem?",\n'
            '    "Balão 2: Informamos que seu equipamento..."\n'
            '  ],\n'
            '  "typing_delay_ms": 2000\n'
            '}\n'
            "```\n\n"
            "Tags dinâmicas suportadas que você pode usar nas mensagens: {nome_cliente}, {saudacao}.\n"
            "Seja proativo sugerindo boas práticas de atendimento no WhatsApp!"
        )

        formatted_contents = []
        for turn in conversation_history:
            role = "user" if turn.get("sender") == "user" else "model"
            formatted_contents.append({"role": role, "parts": [{"text": turn.get("text", "")}]})

        formatted_contents.append({"role": "user", "parts": [{"text": user_message}]})

        try:
            res = client.models.generate_content(
                model=model_name,
                contents=formatted_contents,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.4
                }
            )

            reply_text = res.text or "Desculpe, não consegui processar a resposta."

            # Check if json_rule is present in response
            proposed_rule = None
            json_match = re.search(r'```json_rule\s*(\{[\s\S]*?\})\s*```', reply_text)
            if json_match:
                try:
                    proposed_rule = json.loads(json_match.group(1))
                except Exception as ex:
                    logger.warning(f"Failed to parse json_rule from Copilot: {ex}")

            # Strip the raw json_rule block from the text display for clean readability if needed, or leave it intact
            clean_reply = reply_text.replace(json_match.group(0), '').strip() if json_match else reply_text

            return {
                "reply": clean_reply,
                "proposed_rule": proposed_rule
            }

        except Exception as err:
            logger.error(f"Error in chat_ai_rule_copilot: {err}", exc_info=True)
            return {
                "reply": f"❌ Erro ao consultar a IA Copilot: {str(err)}",
                "proposed_rule": None
            }

    @classmethod
    async def process_and_dispatch_automation(
        cls,
        tenant_id: int,
        conversation_id: int,
        message_text: str,
        from_me: bool,
        contact_name: str,
        instance_name: Optional[str],
        recipient_phone: str
    ):
        if not message_text or not recipient_phone or not instance_name:
            return

        try:
            from app.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                config = await cls.get_tenant_automations(db, tenant_id)
                if not config.get("enabled", True):
                    return

                # 1. Try OS Handler Match
                os_match = cls.match_os_handler(message_text, config, from_me, contact_name)
                messages_to_send: List[str] = []
                delay_ms = config.get("os_handler", {}).get("typing_delay_ms", 2000)

                if os_match:
                    _, messages_to_send = os_match
                    logger.info(f"⚡ [AUTOMAÇÃO OS] Disparando {len(messages_to_send)} mensagens automáticas para {recipient_phone} ({contact_name})")
                else:
                    # 2. Try Custom Rules
                    custom_match = cls.match_custom_rules(message_text, config, from_me, contact_name)
                    if custom_match:
                        messages_to_send = custom_match
                        logger.info(f"⚡ [AUTOMAÇÃO REGRA] Disparando {len(messages_to_send)} resposta(s) padrão para {recipient_phone} ({contact_name})")

                if not messages_to_send:
                    return

                delay_sec = max(0.5, float(delay_ms) / 1000.0)

                for msg_content in messages_to_send:
                    # A. Send typing presence
                    try:
                        await evolution_service.send_presence(
                            instance_name=instance_name,
                            number=recipient_phone,
                            presence="composing"
                        )
                    except Exception as e:
                        logger.debug(f"Presence typing warning: {e}")

                    # B. Wait typing delay
                    await asyncio.sleep(delay_sec)

                    # C. Send WhatsApp text
                    send_res = await evolution_service.send_text_message(
                        instance_name=instance_name,
                        number=recipient_phone,
                        text=msg_content
                    )

                    # D. Save to DB
                    saved_msg = Message(
                        conversation_id=conversation_id,
                        remetente=MessageSender.SISTEMA,
                        conteudo=msg_content,
                        tipo=MessageType.TEXTO,
                        status="sent",
                        whatsapp_msg_id=send_res.get("id") if isinstance(send_res, dict) else None,
                        timestamp=datetime.utcnow()
                    )
                    db.add(saved_msg)

                    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
                    conv_res = await db.execute(conv_stmt)
                    conv = conv_res.scalar_one_or_none()
                    if conv:
                        conv.ultima_interacao_em = datetime.utcnow()

                    await db.commit()
                    await db.refresh(saved_msg)

                    # E. Realtime WebSocket Broadcast to Attendants Dashboard
                    await ws_manager.broadcast_to_department(
                        tenant_id=tenant_id,
                        whatsapp_number_id=conv.whatsapp_number_id if conv else None,
                        message_data={
                            "type": "NEW_MESSAGE",
                            "conversation_id": conversation_id,
                            "id": saved_msg.id,
                            "remetente": MessageSender.SISTEMA.value,
                            "conteudo": msg_content,
                            "status": "sent",
                            "timestamp": str(saved_msg.timestamp),
                            "agent_name": "Automação OS"
                        }
                    )

                logger.info(f"✅ [AUTOMAÇÃO CONCLUÍDA] Sequência de mensagens enviada com sucesso para #{conversation_id}")

        except Exception as err:
            logger.error(f"❌ Erro na execução da automação em segundo plano: {err}", exc_info=True)


automation_service = AutomationService()
