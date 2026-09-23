import asyncio
import logging
import os
import re
import uuid
import base64
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx
from sqlalchemy import select, and_

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import (
    WhatsAppNumber, Contact, Conversation, Message, 
    MessageSender, MessageType, ConversationStatus, WhatsAppGroup
)
from app.services.lid_resolver_service import resolve_and_bind_contact, download_and_cache_avatar_locally
from app.services.whatsapp_sync_service import whatsapp_sync_service, parse_quoted_context
from app.api.websockets import manager as ws_manager

logger = logging.getLogger("whatsapp_reconciliation")

class WhatsAppReconciliationService:
    def __init__(self):
        self.default_base_url = settings.EVOLUTION_API_URL.rstrip('/')
        self.default_api_key = settings.EVOLUTION_API_KEY
        self._is_running = False
        self._reconciling_instances = set()

    async def _get_active_base_url(self) -> str:
        """
        Determines the active base_url for Evolution API.
        Tests primary EVOLUTION_API_URL; if unreachable, falls back to public OCI URL.
        """
        urls_to_try = [self.default_base_url]
        if "localhost" in self.default_base_url:
            urls_to_try.append(self.default_base_url.replace("localhost", "127.0.0.1"))
        fallback_url = "http://ominichannel.duckdns.org:8080"
        if fallback_url not in urls_to_try:
            urls_to_try.append(fallback_url)

        headers = {
            "apikey": self.default_api_key,
            "Content-Type": "application/json"
        }

        for u in urls_to_try:
            clean_u = u.rstrip('/')
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.get(f"{clean_u}/instance/fetchInstances", headers=headers)
                    if r.status_code in [200, 401, 403]:
                        return clean_u
            except Exception:
                continue

        return self.default_base_url

    def _parse_ts(self, ts_raw: Any) -> datetime:
        if not ts_raw:
            return datetime.utcnow()
        try:
            ts_int = int(ts_raw)
            if ts_int > 1e11:
                ts_int = ts_int / 1000.0
            return datetime.utcfromtimestamp(ts_int)
        except Exception:
            return datetime.utcnow()

    async def sync_contacts_agenda(self, client: httpx.AsyncClient, base_url: str, headers: dict, instance_name: str, tenant_id: int) -> dict:
        """
        Scans /chat/findContacts and updates or creates Contact records in the database with the official
        name saved in the phone's address book (Google Contacts/Agenda), prioritizing saved name over pushName.
        """
        try:
            res = await client.post(f"{base_url}/chat/findContacts/{instance_name}", headers=headers, json={})
            if res.status_code != 200:
                return {"created": 0, "updated": 0}
            contacts_list = res.json()
            if not isinstance(contacts_list, list):
                return {"created": 0, "updated": 0}

            created_count = 0
            updated_count = 0
            # Raw WhatsApp CDN URLs (pps.whatsapp.net) are signed and expire after a while -
            # storing them directly leaves the avatar broken once the signature lapses. Collect
            # (contact_id, remote_url) pairs here and download+localize them to /uploads/avatars/
            # after commit (need real ids, which only exist post-flush/commit).
            pending_avatar_downloads: List[tuple] = []
            async with AsyncSessionLocal() as db:
                db_contacts_res = await db.execute(select(Contact).where(Contact.tenant_id == tenant_id))
                db_contacts = {c.telefone: c for c in db_contacts_res.scalars().all() if c.telefone}

                for ct in contacts_list:
                    if not isinstance(ct, dict):
                        continue
                    remote_jid = ct.get("remoteJid") or ""
                    if not remote_jid or "@g.us" in remote_jid:
                        continue

                    # Prioritize official address book name over pushName
                    saved_name = ct.get("name") or ct.get("verifiedName")
                    push_name = ct.get("pushName")
                    pic_url = ct.get("profilePicUrl")

                    clean_phone = remote_jid.split("@")[0].split(":")[0]
                    clean_phone = "".join(filter(str.isdigit, clean_phone))

                    target_name = (saved_name or "").strip() or (push_name or "").strip()
                    if not clean_phone or len(clean_phone) < 8:
                        continue

                    # Find matching contact in DB
                    c_obj = db_contacts.get(clean_phone)
                    if not c_obj and len(clean_phone) >= 8:
                        for p, obj in db_contacts.items():
                            if p and len(p) >= 8 and (clean_phone.endswith(p[-8:]) or p.endswith(clean_phone[-8:])):
                                c_obj = obj
                                break

                    if c_obj:
                        locked = (c_obj.dados_adicionais or {}).get("custom_name_locked", False)
                        has_changed = False
                        # Never let a synced name overwrite one that already looks real (has
                        # letters) — only replace clearly weak placeholders (missing, equal to
                        # the phone number, "Contato ..." fallback, or no letters at all e.g.
                        # a formatted phone used as the name). Otherwise a good business name
                        # like "Adalberto Gas Particular" gets silently downgraded to whatever
                        # short pushName the customer set for themselves on WhatsApp.
                        current_name = (c_obj.nome or "").strip()
                        current_is_weak = (
                            not current_name or
                            current_name == c_obj.telefone or
                            current_name.startswith("Contato ") or
                            not re.search(r'[A-Za-zÀ-ÿ]', current_name)
                        )
                        if not locked and current_is_weak:
                            if saved_name and c_obj.nome != saved_name:
                                c_obj.nome = saved_name
                                has_changed = True
                            elif target_name and c_obj.nome != target_name:
                                c_obj.nome = target_name
                                has_changed = True
                        if pic_url and not c_obj.foto_perfil_url:
                            pending_avatar_downloads.append((c_obj.id, pic_url))
                            has_changed = True

                        if has_changed:
                            updated_count += 1
                    else:
                        # Create brand new contact imported directly from WhatsApp / phone agenda
                        new_c = Contact(
                            tenant_id=tenant_id,
                            telefone=clean_phone,
                            nome=target_name or clean_phone,
                            dados_adicionais={"origin": "phone_agenda", "instance": instance_name}
                        )
                        db.add(new_c)
                        if pic_url:
                            await db.flush()
                            pending_avatar_downloads.append((new_c.id, pic_url))
                        db_contacts[clean_phone] = new_c
                        created_count += 1

                if created_count > 0 or updated_count > 0:
                    await db.commit()
                    logger.info(f"[AGENDA SYNC] Instância '{instance_name}': {created_count} criados, {updated_count} atualizados.")

            for c_id, pic_url in pending_avatar_downloads:
                asyncio.create_task(download_and_cache_avatar_locally(c_id, pic_url))

            return {"created": created_count, "updated": updated_count}
        except Exception as e:
            logger.debug(f"[AGENDA SYNC] Erro ao sincronizar contatos de {instance_name}: {e}")
            return {"created": 0, "updated": 0}

    async def sync_all_contacts_agenda(self, tenant_id: Optional[int] = None) -> dict:
        """
        Pulls phonebook contacts across all active WhatsApp numbers for the given tenant (or all tenants).
        """
        base_url = await self._get_active_base_url()
        headers = {
            "apikey": self.default_api_key,
            "Content-Type": "application/json"
        }
        total_created = 0
        total_updated = 0

        async with AsyncSessionLocal() as db:
            stmt = select(WhatsAppNumber).where(WhatsAppNumber.status == True)
            if tenant_id:
                stmt = stmt.where(WhatsAppNumber.tenant_id == tenant_id)
            wns = (await db.execute(stmt)).scalars().all()

        async with httpx.AsyncClient(timeout=30.0) as client:
            for wn in wns:
                if wn.instancia_evolution_api:
                    res = await self.sync_contacts_agenda(
                        client=client,
                        base_url=base_url,
                        headers=headers,
                        instance_name=wn.instancia_evolution_api,
                        tenant_id=wn.tenant_id
                    )
                    total_created += res.get("created", 0)
                    total_updated += res.get("updated", 0)

        return {"created": total_created, "updated": total_updated}

    async def reconcile_instance(
        self,
        instance_name: str,
        whatsapp_number_id: int,
        tenant_id: int,
        dept_name: str,
        limit_chats: int = 60,
        limit_msgs: int = 50
    ) -> int:
        """
        Executes a complete sweep of an instance:
        1. Synchronizes contacts address book names.
        2. Scans recent chats (/chat/findChats) to restore missing chats & chronological timestamps.
        3. Imports any missing messages and call cards.
        """
        if instance_name in self._reconciling_instances:
            logger.debug(f"[RECONCILE] Instância {instance_name} já em reconciliação. Ignorando.")
            return 0

        self._reconciling_instances.add(instance_name)
        total_synced = 0

        try:
            base_url = await self._get_active_base_url()
            headers = {
                "apikey": self.default_api_key,
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=25.0) as client:
                # 1. Sync phonebook contact names
                await self.sync_contacts_agenda(client, base_url, headers, instance_name, tenant_id)

                # 2. Sweep active chats list (/chat/findChats)
                try:
                    c_res = await client.post(f"{base_url}/chat/findChats/{instance_name}", headers=headers, json={})
                    if c_res.status_code == 200:
                        raw_chats = c_res.json()
                        if isinstance(raw_chats, list) and raw_chats:
                            # Process top chats
                            for chat_item in raw_chats[:limit_chats]:
                                if not isinstance(chat_item, dict):
                                    continue
                                r_jid = chat_item.get("remoteJid") or ""
                                if not r_jid or "status@broadcast" in r_jid:
                                    continue

                                p_name = chat_item.get("pushName") or chat_item.get("name") or "Cliente"
                                last_msg = chat_item.get("lastMessage") or {}
                                last_key = last_msg.get("key", {}) if isinstance(last_msg, dict) else {}
                                last_msg_id = last_key.get("id")

                                # Check timestamp
                                chat_ts_raw = (
                                    last_msg.get("messageTimestamp")
                                    if isinstance(last_msg, dict) and last_msg.get("messageTimestamp")
                                    else chat_item.get("updatedAt")
                                )
                                chat_dt = datetime.utcnow()
                                if chat_ts_raw:
                                    if isinstance(chat_ts_raw, str) and ("T" in chat_ts_raw or "-" in chat_ts_raw):
                                        try:
                                            chat_dt = datetime.fromisoformat(chat_ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                                        except Exception:
                                            chat_dt = datetime.utcnow()
                                    else:
                                        chat_dt = self._parse_ts(chat_ts_raw)

                                # Resolve contact and conversation
                                async with AsyncSessionLocal() as db:
                                    contact = await resolve_and_bind_contact(
                                        session=db,
                                        tenant_id=tenant_id,
                                        raw_jid=r_jid,
                                        push_name=p_name
                                    )

                                    conv_stmt = select(Conversation).where(
                                        Conversation.tenant_id == tenant_id,
                                        Conversation.contact_id == contact.id,
                                        Conversation.whatsapp_number_id == whatsapp_number_id
                                    ).order_by(Conversation.ultima_interacao_em.desc())
                                    conv = (await db.execute(conv_stmt)).scalars().first()

                                    if not conv:
                                        conv = Conversation(
                                            tenant_id=tenant_id,
                                            whatsapp_number_id=whatsapp_number_id,
                                            contact_id=contact.id,
                                            status=ConversationStatus.COM_HUMANO,
                                            protocol_number=None,
                                            dados_adicionais={"is_migrated": True},
                                            criado_em=chat_dt,
                                            ultima_interacao_em=chat_dt
                                        )
                                        db.add(conv)
                                        await db.flush()
                                        logger.info(f"[RECONCILE CHAT] Criada conversa ausente #{conv.id} para '{contact.nome}' ({contact.telefone})")

                                    # If last message is missing in DB, fetch recent messages for this chat
                                    missing_last = False
                                    if last_msg_id:
                                        m_exists = (await db.execute(select(Message.id).where(Message.whatsapp_msg_id == last_msg_id))).scalars().first()
                                        if not m_exists:
                                            missing_last = True

                                    # Update ultima_interacao_em if chat_dt is newer
                                    if conv.ultima_interacao_em is None or chat_dt > conv.ultima_interacao_em:
                                        conv.ultima_interacao_em = chat_dt

                                    await db.commit()

                                # If last message was missing, fetch chat's recent messages
                                if missing_last:
                                    try:
                                        chat_msgs_res = await client.post(
                                            f"{base_url}/chat/findMessages/{instance_name}",
                                            headers=headers,
                                            json={"where": {"key": {"remoteJid": r_jid}}, "limit": 15}
                                        )
                                        if chat_msgs_res.status_code == 200:
                                            m_records = chat_msgs_res.json().get("messages", {}).get("records", []) if isinstance(chat_msgs_res.json(), dict) else []
                                            for rm in m_records:
                                                rk = rm.get("key", {})
                                                rm_id = rk.get("id")
                                                if not rm_id:
                                                    continue
                                                async with AsyncSessionLocal() as db_m:
                                                    if (await db_m.execute(select(Message.id).where(Message.whatsapp_msg_id == rm_id))).scalars().first():
                                                        continue
                                                    r_from_me = rk.get("fromMe", False)
                                                    r_text, r_tipo = whatsapp_sync_service._parse_message_content(rm)
                                                    if not r_text:
                                                        continue
                                                    r_dt = self._parse_ts(rm.get("messageTimestamp"))
                                                    r_extra = {}
                                                    rm_payload_safe = rm.get("message") or {}
                                                    rm_doc_wrapper = rm_payload_safe.get("documentWithCaptionMessage") or {}
                                                    r_doc = (rm_payload_safe.get("documentMessage") or
                                                             (rm_doc_wrapper.get("message") or {}).get("documentMessage") or {})
                                                    if r_doc:
                                                        fn = r_doc.get("fileName") or r_doc.get("title")
                                                        if fn:
                                                            r_extra["original_filename"] = fn
                                                            r_extra["file_name"] = fn

                                                    n_msg = Message(
                                                        conversation_id=conv.id,
                                                        remetente=MessageSender.ATENDENTE if r_from_me else MessageSender.CLIENTE,
                                                        conteudo=r_text,
                                                        tipo=r_tipo,
                                                        status="read",
                                                        whatsapp_msg_id=rm_id,
                                                        dados_adicionais=r_extra if r_extra else None,
                                                        timestamp=r_dt
                                                    )
                                                    db_m.add(n_msg)
                                                    await db_m.commit()
                                                    total_synced += 1
                                    except Exception:
                                        pass
                except Exception as chats_err:
                    logger.debug(f"[RECONCILE] Erro ao varrer chats de {instance_name}: {chats_err}")

                # 3. Global recent messages fallback (/chat/findMessages)
                try:
                    msgs_res = await client.post(
                        f"{base_url}/chat/findMessages/{instance_name}",
                        headers=headers,
                        json={"limit": limit_msgs}
                    )
                    if msgs_res.status_code == 200:
                        records = msgs_res.json().get("messages", {}).get("records", []) if isinstance(msgs_res.json(), dict) else []
                        for m in records:
                            k = m.get("key", {})
                            msg_id = k.get("id")
                            if not msg_id:
                                continue
                            remote_jid = k.get("remoteJid", "")
                            if not remote_jid or "status@broadcast" in remote_jid:
                                continue
                            remote_jid_alt = k.get("remoteJidAlt") or m.get("remoteJidAlt") or ""
                            if "@s.whatsapp.net" in str(remote_jid_alt):
                                remote_jid = remote_jid_alt

                            async with AsyncSessionLocal() as db:
                                exists = (await db.execute(select(Message.id).where(Message.whatsapp_msg_id == msg_id))).scalars().first()
                                if exists:
                                    continue

                                from_me = k.get("fromMe", False)
                                push_name = m.get("pushName") or "Cliente"
                                contact = await resolve_and_bind_contact(
                                    session=db,
                                    tenant_id=tenant_id,
                                    raw_jid=remote_jid,
                                    push_name=push_name,
                                    remote_jid_alt=remote_jid_alt
                                )

                                c_stmt = select(Conversation).where(
                                    Conversation.tenant_id == tenant_id,
                                    Conversation.contact_id == contact.id,
                                    Conversation.whatsapp_number_id == whatsapp_number_id
                                ).order_by(Conversation.ultima_interacao_em.desc())
                                conv = (await db.execute(c_stmt)).scalars().first()

                                text_content, msg_type = whatsapp_sync_service._parse_message_content(m)
                                if not text_content:
                                    continue

                                msg_dt = self._parse_ts(m.get("messageTimestamp"))

                                if not conv:
                                    conv = Conversation(
                                        tenant_id=tenant_id,
                                        whatsapp_number_id=whatsapp_number_id,
                                        contact_id=contact.id,
                                        status=ConversationStatus.COM_HUMANO,
                                        protocol_number=None,
                                        dados_adicionais={"is_migrated": True},
                                        criado_em=msg_dt,
                                        ultima_interacao_em=msg_dt
                                    )
                                    db.add(conv)
                                    await db.flush()

                                quote_data = parse_quoted_context(m, from_me=from_me, contact_name=contact.nome)
                                extra_dict = {}
                                if quote_data:
                                    extra_dict["quoted_message"] = quote_data
                                m_payload_safe = m.get("message") or {}
                                m_doc_wrapper = m_payload_safe.get("documentWithCaptionMessage") or {}
                                m_doc = (m_payload_safe.get("documentMessage") or
                                         (m_doc_wrapper.get("message") or {}).get("documentMessage") or {})
                                if m_doc:
                                    fn = m_doc.get("fileName") or m_doc.get("title")
                                    if fn:
                                        extra_dict["original_filename"] = fn
                                        extra_dict["file_name"] = fn

                                new_msg = Message(
                                    conversation_id=conv.id,
                                    remetente=MessageSender.ATENDENTE if from_me else MessageSender.CLIENTE,
                                    conteudo=text_content,
                                    tipo=msg_type,
                                    status="read",
                                    whatsapp_msg_id=msg_id,
                                    dados_adicionais=extra_dict if extra_dict else None,
                                    timestamp=msg_dt
                                )
                                db.add(new_msg)

                                if conv.ultima_interacao_em is None or msg_dt > conv.ultima_interacao_em:
                                    conv.ultima_interacao_em = msg_dt

                                await db.commit()
                                total_synced += 1
                                logger.info(f"[RECONCILE MSG] Mensagem #{new_msg.id} recuperada para conv #{conv.id} ({contact.nome}): {text_content[:40]}")
                except Exception as msgs_err:
                    logger.debug(f"[RECONCILE] Erro ao varrer mensagens globais de {instance_name}: {msgs_err}")

            # Notify department clients to refresh chronological order
            if total_synced > 0:
                try:
                    await ws_manager.broadcast_to_department(
                        tenant_id=tenant_id,
                        whatsapp_number_id=whatsapp_number_id,
                        message_data={"type": "CONVERSATIONS_RECONCILED", "synced_count": total_synced}
                    )
                except Exception:
                    pass

            return total_synced
        except Exception as err:
            logger.error(f"[RECONCILE FATAL] Falha na reconciliação de {instance_name}: {err}", exc_info=True)
            return total_synced
        finally:
            self._reconciling_instances.discard(instance_name)

    async def reconcile_by_instance_name(self, instance_name: str) -> int:
        """Helper to run reconciliation for a specific instance by name."""
        try:
            async with AsyncSessionLocal() as db:
                stmt = select(WhatsAppNumber).where(
                    WhatsAppNumber.instancia_evolution_api == instance_name,
                    WhatsAppNumber.status == True
                )
                wn = (await db.execute(stmt)).scalars().first()
                if not wn:
                    return 0
                return await self.reconcile_instance(
                    instance_name=wn.instancia_evolution_api,
                    whatsapp_number_id=wn.id,
                    tenant_id=wn.tenant_id,
                    dept_name=wn.nome_departamento or "Geral"
                )
        except Exception as e:
            logger.error(f"Erro em reconcile_by_instance_name({instance_name}): {e}")
            return 0

    async def reconcile_all_instances(self, limit_chats: int = 60, limit_msgs: int = 50):
        """Runs reconciliation across all active WhatsApp numbers in database.

        `limit_chats`/`limit_msgs` afinam o peso da varredura - a varredura de emergência
        disparada pelo vigia (ver main.py) usa valores bem menores que o padrão daqui: numa
        queda real o mais importante é ser rápido e pegar o que é mais recente/relevante, não
        varrer exaustivamente - confirmado em produção em 23/09/2026 que a versão pesada podia
        levar vários minutos e competir por recursos com o uso normal do sistema.
        """
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
                        dept_name=wn.nome_departamento or "Geral",
                        limit_chats=limit_chats,
                        limit_msgs=limit_msgs
                    )
        except Exception as e:
            logger.debug(f"[RECONCILE] Error during reconcile_all_instances: {e}")

whatsapp_reconciliation_service = WhatsAppReconciliationService()

async def start_whatsapp_reconciliation_loop(interval_seconds: int = 60):
    logger.info(f"🔄 WhatsApp Continuous Reconciliation Watchdog started ({interval_seconds}s interval).")
    await asyncio.sleep(15)  # Brief pause after boot
    while True:
        try:
            await whatsapp_reconciliation_service.reconcile_all_instances()
        except asyncio.CancelledError:
            break
        except Exception as err:
            logger.error(f"[RECONCILE LOOP] Unexpected error: {err}")
        await asyncio.sleep(interval_seconds)
