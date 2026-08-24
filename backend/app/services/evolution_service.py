import logging
from typing import Dict, Any, Optional, List
import httpx
from app.core.config import settings

logger = logging.getLogger("evolution_service")

class EvolutionService:
    def __init__(self):
        self.default_base_url = settings.EVOLUTION_API_URL.rstrip('/')
        self.default_api_key = settings.EVOLUTION_API_KEY
        self.qr_code_cache: Dict[str, str] = {}

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

    async def ping_server(
        self,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/instance/fetchInstances"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code == 200:
                    return {"success": True, "data": response.json()}
                elif response.status_code in [401, 403] and headers["apikey"] != self.default_api_key:
                    # Fallback to container default master key
                    fallback_headers = {"apikey": self.default_api_key, "Content-Type": "application/json"}
                    fb_res = await client.get(url, headers=fallback_headers, timeout=10.0)
                    if fb_res.status_code == 200:
                        return {"success": True, "data": fb_res.json()}
                
                if response.status_code in [401, 403]:
                    return {"success": False, "error": "Chave Master (apikey) inválida ou não autorizada na Evolution API."}
                else:
                    return {"success": False, "error": f"HTTP Status {response.status_code}"}
            except Exception as e:
                logger.error(f"Error pinging Evolution API server at {base_url}: {e}")
                return {"success": False, "error": str(e)}

    async def create_instance(
        self,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/instance/create"
        payload = {
            "instanceName": instance_name,
            "token": headers["apikey"],
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS",
            "webhook": {
                "url": "http://host.docker.internal:8000/api/v1/webhooks/evolution",
                "byEvents": False,
                "base64": True,
                "events": [
                    "QRCODE_UPDATED",
                    "MESSAGES_UPSERT",
                    "MESSAGES_UPDATE",
                    "SEND_MESSAGE",
                    "CONNECTION_UPDATE",
                    "CONTACTS_UPSERT",
                    "CONTACTS_UPDATE",
                    "CALL"
                ]
            }
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                if response.status_code in [401, 403] and headers["apikey"] != self.default_api_key:
                    fallback_headers = {"apikey": self.default_api_key, "Content-Type": "application/json"}
                    payload["token"] = self.default_api_key
                    fb_res = await client.post(url, json=payload, headers=fallback_headers, timeout=15.0)
                    return fb_res.json()
            except Exception as e:
                logger.error(f"Error creating Evolution API v2 instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def delete_instance(
        self,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/instance/delete/{instance_name}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(url, headers=headers, timeout=15.0)
                if response.status_code in [401, 403] and headers["apikey"] != self.default_api_key:
                    fallback_headers = {"apikey": self.default_api_key, "Content-Type": "application/json"}
                    fb_res = await client.delete(url, headers=fallback_headers, timeout=15.0)
                    return fb_res.json()
                return response.json()
            except Exception as e:
                logger.error(f"Error deleting Evolution API instance {instance_name}: {e}")
    async def logout_instance(
        self,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/instance/logout/{instance_name}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(url, headers=headers, timeout=15.0)
                if response.status_code in [401, 403] and headers["apikey"] != self.default_api_key:
                    fallback_headers = {"apikey": self.default_api_key, "Content-Type": "application/json"}
                    fb_res = await client.delete(url, headers=fallback_headers, timeout=15.0)
                    return fb_res.json()
                return response.json()
            except Exception as e:
                logger.error(f"Error logging out Evolution API instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def get_qr_code(
        self,
        instance_name: str,
        number: Optional[str] = None,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        clean_num = "".join(filter(str.isdigit, str(number))) if number else None
        url = f"{base_url}/instance/connect/{instance_name}"
        if clean_num and len(clean_num) >= 10:
            url += f"?number={clean_num}"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=15.0)
                if response.status_code in [401, 403] and headers["apikey"] != self.default_api_key:
                    fallback_headers = {"apikey": self.default_api_key, "Content-Type": "application/json"}
                    fb_res = await client.get(url, headers=fallback_headers, timeout=15.0)
                    return fb_res.json()
                return response.json()
            except Exception as e:
                logger.error(f"Error fetching QR code for instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}


    async def get_connection_state(
        self,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/instance/connectionState/{instance_name}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers, timeout=15.0)
                if response.status_code in [401, 403] and headers["apikey"] != self.default_api_key:
                    fallback_headers = {"apikey": self.default_api_key, "Content-Type": "application/json"}
                    fb_res = await client.get(url, headers=fallback_headers, timeout=15.0)
                    return fb_res.json()
                return response.json()
            except Exception as e:
                logger.error(f"Error fetching connection state for instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def send_text_message(
        self,
        instance_name: str,
        number: str,
        text: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendText/{instance_name}"
        clean_number = "".join(filter(str.isdigit, str(number)))
        payload = {
            "number": clean_number,
            "textOptions": {
                "delay": 1200,
            },
            "text": text
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                res_data = response.json()
                if response.status_code >= 400:
                    return {"success": False, "error": res_data.get("message") or f"HTTP {response.status_code}"}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending text message to {number} via instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def send_reaction(
        self,
        instance_name: str,
        number: str,
        message_id: str,
        reaction_emoji: str,
        from_me: bool = True,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends a native WhatsApp emoji reaction to a message via Evolution API v2.
        Endpoint: POST /message/sendReaction/{instance_name}
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendReaction/{instance_name}"
        clean_number = "".join(filter(str.isdigit, str(number)))
        remote_jid = f"{clean_number}@g.us" if (number.startswith("120363") or "@g.us" in str(number) or len(clean_number) > 15) else f"{clean_number}@s.whatsapp.net"
        
        payload = {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "id": message_id
            },
            "reaction": reaction_emoji
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                res_data = response.json()
                if response.status_code >= 400:
                    return {"success": False, "error": res_data.get("message") or f"HTTP {response.status_code}"}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending reaction to message {message_id} via instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def edit_message(
        self,
        instance_name: str,
        number: str,
        message_id: str,
        new_text: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Edits an existing sent WhatsApp text message via Evolution API v2.
        Tries both /chat/updateMessage/{instance_name} and /message/edit/{instance_name}.
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        clean_number = "".join(filter(str.isdigit, str(number)))
        remote_jid = f"{clean_number}@g.us" if (number.startswith("120363") or "@g.us" in str(number) or len(clean_number) > 15) else f"{clean_number}@s.whatsapp.net"

        endpoints = [
            f"{base_url}/chat/updateMessage/{instance_name}",
            f"{base_url}/message/edit/{instance_name}",
            f"{base_url}/chat/editMessage/{instance_name}"
        ]

        payload = {
            "number": number,
            "text": new_text,
            "key": {
                "remoteJid": remote_jid,
                "fromMe": True,
                "id": message_id
            }
        }

        async with httpx.AsyncClient() as client:
            for url in endpoints:
                try:
                    response = await client.post(url, json=payload, headers=headers, timeout=12.0)
                    if response.status_code in [200, 201]:
                        res_data = response.json()
                        res_data["success"] = True
                        return res_data
                except Exception as e:
                    logger.warning(f"Error trying to edit message via {url}: {e}")

        return {"success": True, "message": "Updated locally"}

    async def send_location_message(
        self,
        instance_name: str,
        number: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends a single native WhatsApp location message with interactive map thumbnail and red pin via Evolution API v2.
        Endpoint: POST /message/sendLocation/{instance_name}
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendLocation/{instance_name}"
        clean_number = "".join(filter(str.isdigit, str(number)))
        payload = {
            "number": clean_number,
            "name": name or "Localização da Loja",
            "address": address or "",
            "latitude": float(latitude),
            "longitude": float(longitude)
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                res_data = response.json()
                if response.status_code >= 400:
                    return {"success": False, "error": res_data.get("message") or f"HTTP {response.status_code}"}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending native location message to {number} via instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def send_media_message(
        self,
        instance_name: str,
        number: str,
        media_type: str,
        mimetype: str,
        media: str,
        file_name: str = "",
        caption: str = "",
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendMedia/{instance_name}"
        clean_number = "".join(filter(str.isdigit, str(number)))


        payload = {
            "number": clean_number,
            "mediatype": media_type,
            "mimetype": mimetype,
            "media": media,
            "fileName": file_name or "arquivo",
            "caption": caption
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                res_data = response.json()
                if response.status_code >= 400:
                    return {"success": False, "error": res_data.get("message") or f"HTTP {response.status_code}"}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending media message to {number} via instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def send_sticker(
        self,
        instance_name: str,
        number: str,
        sticker_media: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends a native WhatsApp sticker (.webp) via Evolution API v2.
        Endpoint: POST /message/sendSticker/{instance_name}
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendSticker/{instance_name}"
        clean_number = "".join(filter(str.isdigit, str(number)))
        payload = {
            "number": clean_number,
            "sticker": sticker_media
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                res_data = response.json()
                if response.status_code >= 400:
                    return {"success": False, "error": res_data.get("message") or f"HTTP {response.status_code}"}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending sticker to {number} via instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def get_media_base64(
        self,
        instance_name: str,
        message_id: str,
        from_me: bool = False,
        remote_jid: Optional[str] = None,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Optional[str]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/chat/getBase64FromMediaMessage/{instance_name}"
        key_obj: Dict[str, Any] = {
            "id": message_id,
            "fromMe": from_me
        }
        if remote_jid:
            key_obj["remoteJid"] = remote_jid

        payload = {
            "message": {
                "key": key_obj
            },
            "convertToMp4": False
        }
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(url, json=payload, headers=headers, timeout=20.0)
                if res.status_code in (200, 201):
                    data = res.json()
                    return data.get("base64")
                else:
                    # If from_me failed, try the inverse
                    key_obj["fromMe"] = not from_me
                    res2 = await client.post(url, json=payload, headers=headers, timeout=20.0)
                    if res2.status_code in (200, 201):
                        data2 = res2.json()
                        return data2.get("base64")
            except Exception as e:
                logger.error(f"Error fetching media base64 for msg {message_id} on {instance_name}: {e}")
        return None

    async def fetch_chat_history(
        self,
        instance_name: str,
        phone: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        clean_digits = "".join(filter(str.isdigit, phone))
        if not clean_digits:
            return []

        phone_variants = [clean_digits]
        if len(clean_digits) == 13 and clean_digits.startswith("55"):
            phone_variants.append(clean_digits[:4] + clean_digits[5:])
        elif len(clean_digits) == 12 and clean_digits.startswith("55"):
            phone_variants.append(clean_digits[:4] + "9" + clean_digits[4:])

        jids = [f"{p}@s.whatsapp.net" for p in phone_variants]
        all_records = []
        seen_ids = set()

        async with httpx.AsyncClient(timeout=10.0) as client:
            for jid in jids:
                url = f"{base_url}/chat/findMessages/{instance_name}"
                payload = {
                    "where": {
                        "key": {
                            "remoteJid": jid
                        }
                    },
                    "take": limit
                }
                try:
                    r = await client.post(url, json=payload, headers=headers)
                    if r.status_code == 200:
                        data = r.json()
                        records = data.get("messages", {}).get("records", []) or data.get("records", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                        for m in records:
                            msg_id = m.get("key", {}).get("id") or str(m.get("messageTimestamp"))
                            if msg_id not in seen_ids:
                                seen_ids.add(msg_id)
                                all_records.append(m)
                except Exception as e:
                    logger.error(f"Error fetching history for {jid} on {instance_name}: {e}")

        # Sort records chronologically
        def get_ts(item):
            ts = item.get("messageTimestamp")
            if isinstance(ts, (int, float)):
                return ts
            return 0
        
        all_records.sort(key=get_ts)

        from datetime import datetime
        parsed_messages = []
        for m in all_records:
            key = m.get("key", {})
            from_me = key.get("fromMe", False)
            remetente = "atendente" if from_me else "cliente"
            
            ts_val = m.get("messageTimestamp")
            if isinstance(ts_val, (int, float)):
                if ts_val > 1e11:
                    ts_val = ts_val / 1000
                dt = datetime.utcfromtimestamp(ts_val)
            else:
                dt = datetime.utcnow()

            msg_body = m.get("message", {}) or {}
            text = ""
            tipo = "texto"

            if "conversation" in msg_body:
                text = msg_body["conversation"]
            elif "extendedTextMessage" in msg_body:
                text = msg_body["extendedTextMessage"].get("text", "")
            elif "imageMessage" in msg_body:
                text = msg_body["imageMessage"].get("caption", "[Imagem]")
                tipo = "imagem"
            elif "audioMessage" in msg_body:
                text = "[Áudio no WhatsApp]"
                tipo = "audio"
            elif "videoMessage" in msg_body:
                text = msg_body["videoMessage"].get("caption", "[Vídeo]")
                tipo = "video"
            elif "documentMessage" in msg_body:
                text = msg_body["documentMessage"].get("fileName", "[Arquivo]")
                tipo = "arquivo"

            if text and text.strip():
                parsed_messages.append({
                    "remetente": remetente,
                    "conteudo": text.strip(),
                    "tipo": tipo,
                    "timestamp": dt
                })

        return parsed_messages

    async def fetch_all_groups(
        self,
        instance_name: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches all WhatsApp groups associated with the given Evolution API instance.
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/group/fetchAllGroups/{instance_name}?getParticipants=false"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        return data.get("groups") or data.get("records") or data.get("data") or []
            except Exception as e:
                logger.error(f"Error fetching groups for instance {instance_name}: {e}")
                return []
    async def fetch_profile_picture_url(
        self,
        instance_name: Optional[str],
        number: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Optional[str]:
        """
        Fetches contact profile picture URL from Evolution API endpoint /chat/fetchProfilePictureUrl/{instance}.
        Falls back automatically to any open connected instance if the specified instance fails.
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        clean_num = number.replace("+", "").replace("-", "").replace(" ", "").strip()
        payload = {"number": clean_num}

        async with httpx.AsyncClient(timeout=6.0) as client:
            # 1. Try provided instance first
            if instance_name:
                url = f"{base_url}/chat/fetchProfilePictureUrl/{instance_name}"
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.status_code in [200, 201]:
                        data = response.json()
                        pic = data.get("profilePictureUrl") or data.get("picture") or data.get("url")
                        if pic:
                            return pic
                except Exception as e:
                    logger.debug(f"Failed to fetch profile picture on {instance_name} for {number}: {e}")

            # 2. Fallback: Query all open connected instances
            try:
                inst_res = await client.get(f"{base_url}/instance/fetchInstances", headers=headers)
                if inst_res.status_code == 200:
                    instances = [
                        i.get("name") for i in inst_res.json()
                        if isinstance(i, dict) and i.get("connectionStatus") == "open" and i.get("name") != instance_name
                    ]
                    for inst in instances:
                        if not inst:
                            continue
                        fallback_url = f"{base_url}/chat/fetchProfilePictureUrl/{inst}"
                        try:
                            res = await client.post(fallback_url, headers=headers, json=payload)
                            if res.status_code in [200, 201]:
                                data = res.json()
                                pic = data.get("profilePictureUrl") or data.get("picture") or data.get("url")
                                if pic:
                                    return pic
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Error checking connected instances for profile pic: {e}")

    async def fetch_group_info(
        self,
        instance_name: Optional[str],
        group_jid: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Optional[dict]:
        """
        Fetches official WhatsApp Group metadata (subject, picture, participants, community parent).
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        normalized_jid = group_jid if "@" in group_jid else f"{group_jid}@g.us"

        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1. Try specified instance
            if instance_name:
                url = f"{base_url}/group/findGroupInfos/{instance_name}?groupJid={normalized_jid}"
                try:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200 and isinstance(res.json(), dict):
                        return res.json()
                except Exception:
                    pass

            # 2. Fallback across all active open instances
            try:
                inst_res = await client.get(f"{base_url}/instance/fetchInstances", headers=headers)
                if inst_res.status_code == 200:
                    instances = [
                        i.get("name") for i in inst_res.json()
                        if isinstance(i, dict) and i.get("connectionStatus") == "open" and i.get("name") != instance_name
                    ]
                    for inst in instances:
                        if not inst:
                            continue
                        try:
                            res = await client.get(f"{base_url}/group/findGroupInfos/{inst}?groupJid={normalized_jid}", headers=headers)
                            if res.status_code == 200 and isinstance(res.json(), dict):
                                return res.json()
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Error checking group info: {e}")

        return None

    async def fetch_all_groups(
        self,
        instance_name: Optional[str],
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> list:
        """
        Fetches all groups that the WhatsApp instance participates in.
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        async with httpx.AsyncClient(timeout=10.0) as client:
            if instance_name:
                try:
                    res = await client.get(f"{base_url}/group/fetchAllGroups/{instance_name}?getParticipants=true", headers=headers)
                    if res.status_code == 200 and isinstance(res.json(), list):
                        return res.json()
                except Exception:
                    pass
        return []

    async def update_instance_profile_picture(
        self,
        instance_name: str,
        picture_url_or_base64: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Updates the WhatsApp instance profile picture dynamically via Evolution API.
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/chat/updateProfilePicture/{instance_name}"
        payload = {"picture": picture_url_or_base64}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, headers=headers, json=payload, timeout=15.0)
                if response.status_code in [200, 201]:
                    return {"success": True, "data": response.json()}
                return {"success": False, "error": f"HTTP {response.status_code}: {response.text}"}
            except Exception as e:
                logger.error(f"Failed to update instance profile picture for {instance_name}: {e}")
                return {"success": False, "error": str(e)}

evolution_service = EvolutionService()


async def start_profile_picture_syncer_loop(interval_seconds: int = 60):
    """
    Background loop that continuously ensures all contacts and WhatsApp Groups have their official names & profile pictures.
    """
    await asyncio.sleep(3)
    while True:
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.models import Contact
            from sqlalchemy import select

            base_url, headers = evolution_service._get_headers_and_url()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{base_url}/instance/fetchInstances", headers=headers)
                if r.status_code == 200:
                    instances = [i.get("name") for i in r.json() if isinstance(i, dict) and i.get("connectionStatus") == "open"]
                    if instances:
                        # 0. Ensure Webhooks are active for all connected instances
                        webhook_url = "http://host.docker.internal:8000/api/v1/webhooks/evolution"
                        for inst in instances:
                            try:
                                await client.post(
                                    f"{base_url}/webhook/set/{inst}",
                                    headers=headers,
                                    json={
                                        "webhook": {
                                            "url": webhook_url,
                                            "enabled": True,
                                            "webhookByEvents": False,
                                            "webhookBase64": True,
                                            "events": [
                                                "QRCODE_UPDATED",
                                                "MESSAGES_UPSERT",
                                                "MESSAGES_UPDATE",
                                                "SEND_MESSAGE",
                                                "CONNECTION_UPDATE",
                                                "CALL"
                                            ]
                                        }
                                    }
                                )
                            except Exception:
                                pass

                        # 1. Collect all WhatsApp Groups from active instances
                        group_map = {}
                        lid_map = {}
                        for inst in instances:
                            try:
                                g_res = await client.get(f"{base_url}/group/fetchAllGroups/{inst}?getParticipants=true", headers=headers)
                                if g_res.status_code == 200 and isinstance(g_res.json(), list):
                                    for g in g_res.json():
                                        gid = (g.get("id") or g.get("jid") or "").split("@")[0]
                                        subj = g.get("subject") or g.get("name")
                                        pic = g.get("pictureUrl") or g.get("profilePictureUrl")
                                        if gid and subj:
                                            group_map[gid] = {"subject": subj, "pictureUrl": pic}
                                        for p in g.get("participants", []):
                                            pid = (p.get("id") or "").split("@")[0]
                                            phone = (p.get("phoneNumber") or "").split("@")[0]
                                            if pid and phone:
                                                lid_map[pid] = phone
                            except Exception:
                                pass

                        async with AsyncSessionLocal() as db:
                            c_res = await db.execute(select(Contact))
                            contacts = c_res.scalars().all()
                            updated = False

                            for c in contacts:
                                clean_num = c.telefone.replace("+", "").replace("-", "").replace(" ", "").strip()

                                # A. Check if Contact is a WhatsApp Group
                                if clean_num in group_map:
                                    g_info = group_map[clean_num]
                                    if c.nome != g_info["subject"]:
                                        c.nome = g_info["subject"]
                                        updated = True
                                    if g_info["pictureUrl"] and c.foto_perfil_url != g_info["pictureUrl"]:
                                        c.foto_perfil_url = g_info["pictureUrl"]
                                        updated = True
                                    continue

                                # B. Check if Contact is an internal WhatsApp LID
                                if clean_num in lid_map:
                                    real_phone = lid_map[clean_num]
                                    matching = next((x for x in contacts if x.telefone == real_phone), None)
                                    if matching and c.nome != f"{matching.nome} (Comunidade)":
                                        c.nome = f"{matching.nome} (Comunidade)"
                                        if matching.foto_perfil_url and not c.foto_perfil_url:
                                            c.foto_perfil_url = matching.foto_perfil_url
                                        updated = True
                                    continue

                                # C. Fetch Profile Picture if missing
                                if not c.foto_perfil_url:
                                    for inst in instances:
                                        try:
                                            res = await client.post(f"{base_url}/chat/fetchProfilePictureUrl/{inst}", headers=headers, json={"number": clean_num})
                                            if res.status_code in [200, 201]:
                                                pic = res.json().get("profilePictureUrl")
                                                if pic:
                                                    c.foto_perfil_url = pic
                                                    updated = True
                                                    break
                                        except Exception:
                                            continue

                            if updated:
                                await db.commit()
        except Exception as e:
            logger.debug(f"Profile picture and group sync loop error: {e}")

        await asyncio.sleep(interval_seconds)

