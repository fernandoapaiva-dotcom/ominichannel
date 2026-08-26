import asyncio
import logging
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Tenant, Conversation, Message, MessageSender, MessageType, WhatsAppNumber
from app.services.evolution_service import evolution_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("automation_service")

DEFAULT_AUTOMATION_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "os_handler": {
        "enabled": True,
        "trigger_on_attendant": True,
        "trigger_on_customer": True,
        "keywords": ["posto autorizado", "status:", "aberto a os", "ordem de servico", "servsolda", "servweld"],
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
            ]
        }
    },
    "custom_rules": [
        {
            "id": "rule_pix",
            "name": "Chave Pix e Pagamento",
            "enabled": True,
            "trigger_on": "both",
            "keywords": ["qual o pix", "chave pix", "como pagar", "dados bancarios", "pix da loja"],
            "reply_text": "📌 *Dados Oficiais para Pagamento via Pix:*\nChave: contato@servweld.com.br\nFavorecido: SERVWELD / SERVSOLDA\n\nPor favor, envie o comprovante nesta conversa para confirmação."
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
        
        if keywords and not any(k in norm_text for k in keywords):
            return None

        status = None
        if "status: orcamento" in norm_text or "status:orcamento" in norm_text or ("orcamento" in norm_text and ("aberto a os" in norm_text or "posto autorizado" in norm_text)):
            status = "orcamento"
        elif "garantia de loja" in norm_text or "garantia loja" in norm_text:
            status = "garantia_loja"
        elif "garantia de fabrica" in norm_text or "garantia fabrica" in norm_text:
            status = "garantia_fabrica"

        if not status:
            return None

        diag_prices: Dict[str, Any] = os_cfg.get("diagnostic_prices", {})
        templates = os_cfg.get("templates", {})
        template_msgs = templates.get(status, [])
        if not template_msgs:
            return None

        detected_equip = "Equipamento"
        valor_diagnostico = 100

        if status == "orcamento":
            sorted_equips = sorted(diag_prices.keys(), key=lambda x: len(x), reverse=True)
            matched_equip = None
            for eq in sorted_equips:
                norm_eq = normalize_text(eq)
                if norm_eq in norm_text:
                    matched_equip = eq
                    break
            
            if matched_equip:
                detected_equip = matched_equip.title()
                valor_diagnostico = diag_prices[matched_equip]
            else:
                detected_equip = "Equipamento"
                valor_diagnostico = 100

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

        return status, formatted_messages

    @staticmethod
    def match_custom_rules(
        text: str,
        config: Dict[str, Any],
        from_me: bool
    ) -> Optional[List[str]]:
        rules = config.get("custom_rules", [])
        norm_text = normalize_text(text)

        for r in rules:
            if not r.get("enabled", True):
                continue
            
            trigger_on = r.get("trigger_on", "both")
            if trigger_on == "attendant" and not from_me:
                continue
            if trigger_on == "customer" and from_me:
                continue

            keywords = [normalize_text(k) for k in r.get("keywords", []) if k]
            if any(k in norm_text for k in keywords):
                reply = r.get("reply_text")
                if reply:
                    return [reply]
        return None

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

                if os_match:
                    _, messages_to_send = os_match
                    logger.info(f"⚡ [AUTOMAÇÃO OS] Disparando {len(messages_to_send)} mensagens automáticas para {recipient_phone} ({contact_name})")
                else:
                    # 2. Try Custom Rules
                    custom_match = cls.match_custom_rules(message_text, config, from_me)
                    if custom_match:
                        messages_to_send = custom_match
                        logger.info(f"⚡ [AUTOMAÇÃO REGRA] Disparando resposta padrão para {recipient_phone} ({contact_name})")

                if not messages_to_send:
                    return

                delay_ms = config.get("os_handler", {}).get("typing_delay_ms", 2000)
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
