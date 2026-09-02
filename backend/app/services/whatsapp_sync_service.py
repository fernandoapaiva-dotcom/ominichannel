import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, Message, WhatsAppNumber, MessageSender, MessageType, ConversationStatus, WhatsAppGroup
from app.api.websockets import manager as ws_manager
from app.services.lid_resolver_service import resolve_lid_info, download_and_cache_avatar_locally, resolve_and_bind_contact

logger = logging.getLogger("whatsapp_sync_service")

class WhatsAppSyncService:
    def __init__(self):
        self.default_base_url = settings.EVOLUTION_API_URL.rstrip('/')
        self.default_api_key = settings.EVOLUTION_API_KEY
        self.syncing_instances = set()
        self.sync_progress: Dict[str, Dict[str, Any]] = {}

    def _get_headers_and_url(self, custom_base_url: Optional[str] = None, custom_api_key: Optional[str] = None):
        base_url = (custom_base_url or self.default_base_url).rstrip('/')
        if "localhost" in base_url:
            base_url = base_url.replace("localhost", "127.0.0.1")
        api_key = custom_api_key or self.default_api_key
        headers = {
            "apikey": api_key,
            "Content-Type": "application/json"
        }
        return base_url, headers

    def _clean_phone_from_jid(self, jid: str) -> str:
        if not jid:
            return ""
        clean = jid.split('@')[0]
        clean = clean.split(':')[0]
        return clean

    def _parse_message_content(self, msg_obj: Dict[str, Any]) -> tuple[str, MessageType]:
        msg_payload = msg_obj.get("message") or {}
        msg_type_str = msg_obj.get("messageType", "conversation")

        if "conversation" in msg_payload:
            return msg_payload["conversation"], MessageType.TEXTO

        if "extendedTextMessage" in msg_payload:
            text = msg_payload["extendedTextMessage"].get("text", "")
            return text, MessageType.TEXTO

        if "imageMessage" in msg_payload:
            caption = msg_payload["imageMessage"].get("caption", "")
            url = msg_payload["imageMessage"].get("url", "")
            return f"{url}|{caption}" if (url and caption) else (url or caption or "[Imagem]"), MessageType.IMAGEM

        if "audioMessage" in msg_payload:
            url = msg_payload["audioMessage"].get("url", "")
            return url or "[Áudio]", MessageType.AUDIO

        if "videoMessage" in msg_payload:
            caption = msg_payload["videoMessage"].get("caption", "")
            url = msg_payload["videoMessage"].get("url", "")
            return f"{url}|{caption}" if (url and caption) else (url or caption or "[Vídeo]"), MessageType.VIDEO

        if "documentMessage" in msg_payload or "documentWithCaptionMessage" in msg_payload:
            doc = msg_payload.get("documentMessage") or msg_payload.get("documentWithCaptionMessage", {}).get("message", {}).get("documentMessage", {})
            title = doc.get("title") or doc.get("fileName") or "[Documento]"
            url = doc.get("url", "")
            return f"{url}|{title}" if url else title, MessageType.ARQUIVO

        if "stickerMessage" in msg_payload:
            url = msg_payload["stickerMessage"].get("url", "")
            return url or "[Figurinha]", MessageType.IMAGEM

        if "contactMessage" in msg_payload:
            c_msg = msg_payload["contactMessage"]
            vcard = c_msg.get("vcard") or ""
            name = c_msg.get("displayName") or ""
            if not name:
                import re
                fn = re.search(r"FN:(.+)", vcard)
                name = fn.group(1).strip() if fn else "Contato"
            phone = ""
            if "waid=" in vcard:
                try:
                    phone = vcard.split("waid=")[1].split(":")[0].split("\n")[0].strip()
                except Exception:
                    pass
            if not phone and "TEL" in vcard:
                import re
                tel = re.findall(r"TEL[^:]*:(.+)", vcard)
                if tel:
                    phone = tel[0].strip()
            return f"[CONTATO]|{name}|{phone}|{vcard}", MessageType.TEXTO

        if "contactsArrayMessage" in msg_payload:
            c_arr = msg_payload.get("contactsArrayMessage", {}).get("contacts", [])
            items = []
            for c in c_arr:
                vcard = c.get("vcard") or ""
                name = c.get("displayName") or "Contato"
                phone = ""
                if "waid=" in vcard:
                    try:
                        phone = vcard.split("waid=")[1].split(":")[0].split("\n")[0].strip()
                    except Exception:
                        pass
                if not phone and "TEL" in vcard:
                    import re
                    tel = re.findall(r"TEL[^:]*:(.+)", vcard)
                    if tel:
                        phone = tel[0].strip()
                items.append(f"{name}:{phone}")
            return f"[CONTATOS_MULTIPLOS]|" + ";".join(items), MessageType.TEXTO

        return f"[{msg_type_str}]", MessageType.TEXTO

    def get_tenant_progress(self, tenant_id: int) -> List[Dict[str, Any]]:
        prefix = f"{tenant_id}_"
        return [prog for k, prog in self.sync_progress.items() if k.startswith(prefix)]

    async def _emit_progress(self, tenant_id: int, progress_data: Dict[str, Any]):
        key = f"{tenant_id}_{progress_data['instance']}"
        self.sync_progress[key] = progress_data
        try:
            await ws_manager.broadcast_to_tenant(tenant_id, {
                "type": "whatsapp_sync_progress",
                "data": progress_data
            })
        except Exception as e:
            logger.debug(f"Error broadcasting sync progress via websocket: {e}")

    async def sync_instance_history(
        self,
        tenant_id: int,
        whatsapp_number_id: int,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None,
        limit_chats: int = 5000,
        limit_msgs: int = 500
    ) -> Dict[str, Any]:
        """
        Scans connected instance address book, chats & message history, automatically importing
        true contact names from phone agenda and deduplicating into database with live progress tracking.
        """
        if instance_name in self.syncing_instances:
            logger.info(f"Sync already running for instance '{instance_name}'. Skipping duplicate trigger.")
            return {"success": True, "message": "Sincronização já em andamento."}

        self.syncing_instances.add(instance_name)
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)

        stats = {
            "instance": instance_name,
            "whatsapp_number_id": whatsapp_number_id,
            "status": "running",
            "total_chats": 0,
            "processed_chats": 0,
            "contacts_synced": 0,
            "conversations_synced": 0,
            "messages_synced": 0,
            "percentage": 0,
            "current_contact": "Iniciando varredura da agenda de contatos...",
            "started_at": datetime.utcnow().isoformat(),
            "errors": []
        }

        await self._emit_progress(tenant_id, stats)

        try:
            logger.info(f"=== INICIANDO SINCRONIZAÇÃO AUTOMÁTICA DE HISTÓRICO: {instance_name} (Tenant {tenant_id}) ===")
            async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=35.0) as client:
                
                # 0. Fetch and Sync all WhatsApp Groups (/group/fetchAllGroups/{instance_name})
                try:
                    stats["current_contact"] = "Sincronizando grupos do WhatsApp..."
                    await self._emit_progress(tenant_id, stats)
                    g_res = await client.get(f"/group/fetchAllGroups/{instance_name}?getParticipants=false")
                    if g_res.status_code == 200:
                        raw_groups = g_res.json()
                        if isinstance(raw_groups, dict):
                            raw_groups = raw_groups.get("groups") or raw_groups.get("records") or raw_groups.get("data") or []
                        if isinstance(raw_groups, list):
                            async with AsyncSessionLocal() as g_session:
                                g_count = 0
                                for g_item in raw_groups:
                                    if not isinstance(g_item, dict):
                                        continue
                                    g_jid = g_item.get("id") or g_item.get("remoteJid") or g_item.get("jid") or ""
                                    g_subject = g_item.get("subject") or g_item.get("name") or "Grupo do WhatsApp"
                                    if not g_jid or "@g.us" not in str(g_jid):
                                        continue

                                    g_stmt = select(WhatsAppGroup).where(
                                        WhatsAppGroup.tenant_id == tenant_id,
                                        WhatsAppGroup.group_jid == g_jid
                                    )
                                    g_obj = (await g_session.execute(g_stmt)).scalars().first()
                                    if not g_obj:
                                        g_obj = WhatsAppGroup(
                                            tenant_id=tenant_id,
                                            group_jid=g_jid,
                                            nome=g_subject,
                                            owner_phone=str(g_item.get("owner") or ""),
                                            participantes=g_item.get("participants") or [],
                                            timestamp_criacao=datetime.utcnow()
                                        )
                                        g_session.add(g_obj)
                                    else:
                                        g_obj.nome = g_subject
                                        if g_item.get("participants"):
                                            g_obj.participantes = g_item.get("participants")

                                    gc_stmt = select(Contact).where(
                                        Contact.tenant_id == tenant_id,
                                        Contact.telefone == g_jid
                                    )
                                    gc_obj = (await g_session.execute(gc_stmt)).scalars().first()
                                    if not gc_obj:
                                        gc_obj = Contact(
                                            tenant_id=tenant_id,
                                            telefone=g_jid,
                                            nome=g_subject,
                                            dados_adicionais={"is_group": True}
                                        )
                                        g_session.add(gc_obj)
                                    else:
                                        gc_obj.nome = g_subject

                                    g_count += 1
                                await g_session.commit()
                                logger.info(f"[{instance_name}] Sincronizados {g_count} grupos do WhatsApp no banco de dados.")
                except Exception as g_err:
                    logger.warning(f"[{instance_name}] Erro ao buscar grupos: {g_err}")

                # 1. First fetch Phone Address Book Contacts (/chat/findContacts)
                address_book_map: Dict[str, Dict[str, Any]] = {}
                try:
                    contacts_res = await client.post(f"/chat/findContacts/{instance_name}", json={})
                    if contacts_res.status_code in [401, 403] and headers.get("apikey") != self.default_api_key:
                        headers["apikey"] = self.default_api_key
                        client.headers["apikey"] = self.default_api_key
                        contacts_res = await client.post(f"/chat/findContacts/{instance_name}", json={})

                    if contacts_res.status_code == 200:
                        raw_contacts = contacts_res.json()
                        if isinstance(raw_contacts, list):
                            for c in raw_contacts:
                                jid = c.get("remoteJid", "")
                                p = self._clean_phone_from_jid(jid)
                                name = c.get("pushName") or c.get("name") or c.get("verifiedName")
                                pic = c.get("profilePicUrl")
                                if "@lid" in jid or (len(p) >= 14 and not p.startswith("55") and not p.startswith("120363")):
                                    lid_res = await resolve_lid_info(p)
                                    if lid_res.get("real_phone"):
                                        p = lid_res["real_phone"]
                                    if lid_res.get("name") and (not name or name in [p, "Cliente WhatsApp"]):
                                        name = lid_res["name"]
                                    if lid_res.get("profile_pic") and not pic:
                                        pic = lid_res["profile_pic"]

                                if p and name and name != p and "@g.us" not in jid:
                                    address_book_map[p] = {
                                        "name": name,
                                        "profile_pic": pic
                                    }
                            logger.info(f"[{instance_name}] {len(address_book_map)} contatos com nome recuperados da agenda do WhatsApp.")
                except Exception as ab_err:
                    logger.warning(f"Erro ao buscar agenda de contatos: {ab_err}")

                # 2. Fetch chats from Evolution API
                chats_res = await client.post(f"/chat/findChats/{instance_name}", json={})
                if chats_res.status_code in [401, 403] and headers.get("apikey") != self.default_api_key:
                    headers["apikey"] = self.default_api_key
                    client.headers["apikey"] = self.default_api_key
                    chats_res = await client.post(f"/chat/findChats/{instance_name}", json={})

                if chats_res.status_code != 200:
                    err_msg = f"Instância {instance_name} não respondeu (HTTP {chats_res.status_code}). Verifique se o QR Code está conectado."
                    logger.warning(err_msg)
                    stats["status"] = "error"
                    stats["errors"].append(err_msg)
                    await self._emit_progress(tenant_id, stats)
                    return {"success": False, "stats": stats, "error": err_msg}

                chats_list = chats_res.json()
                if not isinstance(chats_list, list):
                    chats_list = []

                total_chats = min(len(chats_list), limit_chats)
                stats["total_chats"] = total_chats
                logger.info(f"[{instance_name}] {len(chats_list)} chats encontrados na sessão do WhatsApp.")

                if total_chats == 0:
                    stats["status"] = "completed"
                    stats["percentage"] = 100
                    stats["current_contact"] = "Nenhum chat encontrado na instância."
                    await self._emit_progress(tenant_id, stats)
                    return {"success": True, "stats": stats}

                async with AsyncSessionLocal() as session:
                    # Pre-sync all address book contacts into DB
                    for phone, ab_info in address_book_map.items():
                        c_stmt = select(Contact).where(
                            Contact.tenant_id == tenant_id,
                            Contact.telefone == phone
                        )
                        c_res = await session.execute(c_stmt)
                        c_obj = c_res.scalars().first()
                        if not c_obj:
                            c_obj = Contact(
                                tenant_id=tenant_id,
                                telefone=phone,
                                nome=ab_info["name"],
                                foto_perfil_url=ab_info["profile_pic"]
                            )
                            session.add(c_obj)
                            await session.flush()
                            stats["contacts_synced"] += 1
                        else:
                            if c_obj.nome != ab_info["name"]:
                                c_obj.nome = ab_info["name"]
                            if ab_info["profile_pic"] and not c_obj.foto_perfil_url:
                                c_obj.foto_perfil_url = ab_info["profile_pic"]

                        if ab_info.get("profile_pic") and not (c_obj.foto_perfil_url or "").startswith("/uploads/avatars/"):
                            cached_pic = await download_and_cache_avatar_locally(c_obj.id, ab_info["profile_pic"])
                            if cached_pic:
                                c_obj.foto_perfil_url = cached_pic
                    await session.commit()

                    # Process chats batch by batch
                    for idx, chat in enumerate(chats_list[:total_chats]):
                        jid = chat.get("remoteJid", "")
                        if not jid or "status@broadcast" in jid:
                            stats["processed_chats"] = idx + 1
                            stats["percentage"] = round(((idx + 1) / total_chats) * 100, 1)
                            continue

                        phone = self._clean_phone_from_jid(jid)
                        if not phone:
                            stats["processed_chats"] = idx + 1
                            stats["percentage"] = round(((idx + 1) / total_chats) * 100, 1)
                            continue

                        # Prefer address book name over raw chat name or fallback to chat name / phone
                        ab_entry = address_book_map.get(phone)
                        name = (
                            ab_entry["name"] if ab_entry
                            else chat.get("pushName") or chat.get("name") or chat.get("verifiedName") or phone
                        )
                        profile_pic = (ab_entry.get("profile_pic") if ab_entry else None) or chat.get("profilePicUrl")

                        stats["current_contact"] = f"{name} ({phone})"
                        stats["processed_chats"] = idx + 1
                        stats["percentage"] = round(((idx + 1) / total_chats) * 100, 1)

                        if idx % 3 == 0 or idx == total_chats - 1:
                            await self._emit_progress(tenant_id, stats)

                        # 1. Fetch messages for this chat via HTTP (outside DB transaction)
                        records = []
                        try:
                            msgs_payload = {
                                "where": {
                                    "key": {
                                        "remoteJid": jid
                                    }
                                },
                                "limit": limit_msgs
                            }
                            msgs_res = await client.post(f"/chat/findMessages/{instance_name}", json=msgs_payload)
                            if msgs_res.status_code == 200:
                                msgs_json = msgs_res.json()
                                records = (
                                    msgs_json.get("messages", {}).get("records", [])
                                    if isinstance(msgs_json, dict) and "messages" in msgs_json
                                    else msgs_json.get("records", []) if isinstance(msgs_json, dict)
                                    else msgs_json if isinstance(msgs_json, list)
                                    else []
                                )

                                # If chat is a LID, resolve to true phone number via remoteJidAlt
                                if "@lid" in jid or (len(phone) >= 14 and not phone.startswith("55") and not phone.startswith("120363")):
                                    for m_item in records:
                                        k_obj = m_item.get("key", {})
                                        alt_jid = k_obj.get("remoteJidAlt") or m_item.get("remoteJidAlt") or ""
                                        if "@s.whatsapp.net" in alt_jid:
                                            resolved_phone = self._clean_phone_from_jid(alt_jid)
                                            if resolved_phone:
                                                phone = resolved_phone
                                                if m_item.get("pushName") and (name == phone or not name or name == jid):
                                                    name = m_item["pushName"]
                                                break

                        except Exception as chat_err:
                            logger.warning(f"Erro ao buscar mensagens do chat {jid}: {chat_err}")

                        # 2. Open short-lived DB transaction with retry to save Contact, Conv and Messages
                        for attempt in range(5):
                            try:
                                async with AsyncSessionLocal() as session:
                                    # 2. Get or create clean definitive Contact with LID resolution and permanent local avatar cache
                                    contact = await resolve_and_bind_contact(
                                        session=session,
                                        tenant_id=tenant_id,
                                        raw_jid=jid,
                                        push_name=name,
                                        profile_pic_url=profile_pic
                                    )
                                    stats["contacts_synced"] += 1

                                    # Get or create Conversation
                                    conv_stmt = select(Conversation).where(
                                        Conversation.tenant_id == tenant_id,
                                        Conversation.contact_id == contact.id,
                                        Conversation.whatsapp_number_id == whatsapp_number_id
                                    )
                                    conv_res = await session.execute(conv_stmt)
                                    conv = conv_res.scalars().first()

                                    if not conv:
                                        conv = Conversation(
                                            tenant_id=tenant_id,
                                            whatsapp_number_id=whatsapp_number_id,
                                            contact_id=contact.id,
                                            status=ConversationStatus.COM_HUMANO,
                                            protocol_number=None,
                                            dados_adicionais={"is_migrated": True, "migrated_from_whatsapp": True},
                                            criado_em=datetime.utcnow(),
                                            ultima_interacao_em=datetime.utcnow()
                                        )
                                        session.add(conv)
                                        await session.flush()
                                        stats["conversations_synced"] += 1

                                    # Insert messages
                                    latest_msg_dt = None
                                    for m_obj in records:
                                        key_obj = m_obj.get("key", {})
                                        msg_wa_id = key_obj.get("id")
                                        if not msg_wa_id:
                                            continue

                                        from_me = key_obj.get("fromMe", False)
                                        remetente = MessageSender.ATENDENTE if from_me else MessageSender.CLIENTE
                                        content_text, msg_type = self._parse_message_content(m_obj)

                                        ts_raw = m_obj.get("messageTimestamp")
                                        msg_dt = datetime.utcnow()
                                        if ts_raw:
                                            try:
                                                ts_int = int(ts_raw)
                                                if ts_int > 1e11:
                                                    ts_int = ts_int / 1000.0
                                                msg_dt = datetime.fromtimestamp(ts_int)
                                            except Exception:
                                                pass

                                        if latest_msg_dt is None or msg_dt > latest_msg_dt:
                                            latest_msg_dt = msg_dt

                                        existing_msg_stmt = select(Message.id).where(
                                            Message.conversation_id == conv.id,
                                            Message.whatsapp_msg_id == msg_wa_id
                                        )
                                        existing_res = await session.execute(existing_msg_stmt)
                                        if existing_res.scalars().first():
                                            continue

                                        db_msg = Message(
                                            conversation_id=conv.id,
                                            remetente=remetente,
                                            conteudo=content_text,
                                            tipo=msg_type,
                                            status="delivered",
                                            whatsapp_msg_id=msg_wa_id,
                                            timestamp=msg_dt
                                        )
                                        session.add(db_msg)
                                        stats["messages_synced"] += 1

                                    if latest_msg_dt and (not conv.ultima_interacao_em or latest_msg_dt > conv.ultima_interacao_em):
                                        conv.ultima_interacao_em = latest_msg_dt

                                    await session.commit()
                                break
                            except Exception as db_err:
                                if "locked" in str(db_err).lower() and attempt < 4:
                                    await asyncio.sleep(0.3 * (attempt + 1))
                                    continue
                                logger.warning(f"Erro ao salvar dados do chat {jid}: {db_err}")
                                break

                    stats["status"] = "completed"
                    stats["percentage"] = 100
                    stats["current_contact"] = "Sincronização concluída com sucesso!"
                    await self._emit_progress(tenant_id, stats)
                    logger.info(f"=== SINCRONIZAÇÃO CONCLUÍDA [{instance_name}]: {stats['contacts_synced']} contatos, {stats['conversations_synced']} conversas, {stats['messages_synced']} mensagens. ===")

            return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Erro fatal na sincronização de histórico da instância {instance_name}: {e}", exc_info=True)
            stats["status"] = "error"
            stats["errors"].append(str(e))
            await self._emit_progress(tenant_id, stats)
            return {"success": False, "stats": stats, "error": str(e)}
        finally:
            self.syncing_instances.discard(instance_name)

    def trigger_background_sync(
        self,
        tenant_id: int,
        whatsapp_number_id: int,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ):
        """Spawns an asynchronous background task to sync instance history non-blockingly."""
        asyncio.create_task(
            self.sync_instance_history(
                tenant_id=tenant_id,
                whatsapp_number_id=whatsapp_number_id,
                instance_name=instance_name,
                custom_base_url=custom_base_url,
                custom_api_key=custom_api_key
            )
        )

whatsapp_sync_service = WhatsAppSyncService()
