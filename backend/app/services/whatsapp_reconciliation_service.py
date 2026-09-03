import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List
import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import (
    WhatsAppNumber, Contact, Conversation, Message, 
    MessageSender, MessageType, ConversationStatus
)
from app.services.lid_resolver_service import resolve_and_bind_contact
from app.services.whatsapp_sync_service import whatsapp_sync_service
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("whatsapp_reconciliation")

class WhatsAppReconciliationService:
    def __init__(self):
        self.default_base_url = settings.EVOLUTION_API_URL.rstrip('/')
        self.default_api_key = settings.EVOLUTION_API_KEY
        self._is_running = False

    def _get_headers_and_url(self):
        base_url = self.default_base_url
        if "localhost" in base_url:
            base_url = base_url.replace("localhost", "127.0.0.1")
        headers = {
            "apikey": self.default_api_key,
            "Content-Type": "application/json"
        }
        return base_url, headers

    async def reconcile_instance(self, instance_name: str, whatsapp_number_id: int, tenant_id: int, dept_name: str, limit: int = 50) -> int:
        base_url, headers = self._get_headers_and_url()
        url = f"{base_url}/chat/findMessages/{instance_name}"
        payload = {"limit": limit}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code != 200:
                    return 0
                records = res.json().get("messages", {}).get("records", [])
                if not records:
                    return 0
        except Exception as e:
            logger.debug(f"[RECONCILE] Error fetching messages for {instance_name}: {e}")
            return 0

        # Sort chronologically (oldest to newest)
        def get_ts(m):
            ts = m.get("messageTimestamp") or 0
            try:
                return int(ts)
            except Exception:
                return 0
        records.sort(key=get_ts)

        synced_count = 0
        for m in records:
            k = m.get("key", {})
            msg_id = k.get("id")
            if not msg_id:
                continue

            remote_jid = k.get("remoteJid", "")
            if not remote_jid or "status@broadcast" in remote_jid:
                continue

            try:
                async with AsyncSessionLocal() as db:
                    # 1. Fast check if message already exists
                    stmt = select(Message.id).where(Message.whatsapp_msg_id == msg_id)
                    exists = (await db.execute(stmt)).scalars().first()
                    if exists:
                        continue

                    # 2. Extract message info
                    from_me = k.get("fromMe", False)
                    push_name = m.get("pushName") or "Cliente"

                    # 3. Resolve contact (handles LIDs, phone numbers, avatars)
                    contact = await resolve_and_bind_contact(
                        session=db,
                        tenant_id=tenant_id,
                        raw_jid=remote_jid,
                        push_name=push_name
                    )

                    # 4. Strict instance isolation: find or create conversation for THIS whatsapp_number_id
                    c_stmt = (
                        select(Conversation)
                        .where(
                            Conversation.tenant_id == tenant_id,
                            Conversation.contact_id == contact.id,
                            Conversation.whatsapp_number_id == whatsapp_number_id
                        )
                        .order_by(Conversation.ultima_interacao_em.desc())
                    )
                    conv = (await db.execute(c_stmt)).scalars().first()

                    # 5. Parse content
                    text_content, msg_type = whatsapp_sync_service._parse_message_content(m)
                    if not text_content:
                        continue

                    # 6. Parse timestamp
                    ts_raw = m.get("messageTimestamp")
                    msg_dt = datetime.utcnow()
                    if ts_raw:
                        try:
                            ts_int = int(ts_raw)
                            if ts_int > 1e11:
                                ts_int = ts_int / 1000.0
                            msg_dt = datetime.utcfromtimestamp(ts_int)
                        except Exception:
                            pass

                    if not conv:
                        conv = Conversation(
                            tenant_id=tenant_id,
                            whatsapp_number_id=whatsapp_number_id,
                            contact_id=contact.id,
                            status=ConversationStatus.COM_HUMANO,
                            protocol_number=None,
                            dados_adicionais={"is_migrated": True, "migrated_from_whatsapp": True},
                            criado_em=msg_dt,
                            ultima_interacao_em=msg_dt
                        )
                        db.add(conv)
                        await db.flush()

                    # 7. Add message
                    remetente = MessageSender.ATENDENTE if from_me else MessageSender.CLIENTE
                    new_msg = Message(
                        conversation_id=conv.id,
                        remetente=remetente,
                        conteudo=text_content,
                        tipo=msg_type,
                        status="read",
                        whatsapp_msg_id=msg_id,
                        timestamp=msg_dt
                    )
                    db.add(new_msg)

                    if conv.ultima_interacao_em is None or msg_dt > conv.ultima_interacao_em:
                        conv.ultima_interacao_em = msg_dt

                    await db.commit()
                    synced_count += 1
                    logger.info(f"[RECONCILE] Recovered missing message #{new_msg.id} for conv #{conv.id} ({contact.nome} - {dept_name}): {text_content[:40]}")

                    # 8. Broadcast to frontend agents so chat reflects it immediately
                    try:
                        await ws_manager.broadcast_to_department(
                            tenant_id=tenant_id,
                            whatsapp_number_id=whatsapp_number_id,
                            message_data={
                                "type": "NEW_MESSAGE",
                                "conversation_id": conv.id,
                                "remetente": remetente.value,
                                "conteudo": text_content,
                                "timestamp": msg_dt.isoformat() + "Z",
                                "contact_name": contact.nome,
                                "contact_phone": contact.telefone,
                                "department": dept_name
                            }
                        )
                    except Exception:
                        pass
            except Exception as loop_err:
                logger.debug(f"[RECONCILE] Error saving message {msg_id}: {loop_err}")
                continue

        return synced_count

    async def reconcile_all_instances(self):
        try:
            async with AsyncSessionLocal() as db:
                stmt = select(WhatsAppNumber).where(WhatsAppNumber.status == True)
                numbers = (await db.execute(stmt)).scalars().all()

            for wn in numbers:
                if wn.instancia_evolution_api:
                    await self.reconcile_instance(
                        instance_name=wn.instancia_evolution_api,
                        whatsapp_number_id=wn.id,
                        tenant_id=wn.tenant_id,
                        dept_name=wn.nome_departamento or "Geral"
                    )
        except Exception as e:
            logger.debug(f"[RECONCILE] Error during reconcile_all_instances: {e}")

whatsapp_reconciliation_service = WhatsAppReconciliationService()

async def start_whatsapp_reconciliation_loop(interval_seconds: int = 30):
    logger.info(f"🔄 WhatsApp Continuous Reconciliation Watchdog started ({interval_seconds}s interval).")
    await asyncio.sleep(10) # Brief pause after boot
    while True:
        try:
            await whatsapp_reconciliation_service.reconcile_all_instances()
        except asyncio.CancelledError:
            break
        except Exception as err:
            logger.error(f"[RECONCILE LOOP] Unexpected error: {err}")
        await asyncio.sleep(interval_seconds)
