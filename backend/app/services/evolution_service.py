import asyncio
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
        self._http_client: Optional[httpx.AsyncClient] = None

    def get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=30, max_connections=60),
                timeout=httpx.Timeout(15.0, connect=3.0)
            )
        return self._http_client

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
                "url": f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/evolution",
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

    def _format_target_number(self, number: str) -> str:
        raw_num = str(number).strip()
        if "@" in raw_num:
            return raw_num
        digits = "".join(filter(str.isdigit, raw_num))
        if raw_num.startswith("120363") or len(digits) > 15:
            return f"{digits}@g.us"
        if len(digits) >= 14 and not digits.startswith("55"):
            return f"{digits}@lid"
        return digits

    async def resolve_canonical_jid(self, instance_name: str, number: str, custom_base_url: Optional[str] = None, custom_api_key: Optional[str] = None) -> str:
        """
        Resolves the exact registered WhatsApp JID for Brazilian phone numbers (handling the 8 vs 9 digit variation).
        """
        raw_num = str(number).strip()
        if "@" in raw_num or raw_num.startswith("120363"):
            return raw_num
        digits = "".join(filter(str.isdigit, raw_num))
        if not digits:
            return raw_num
        if not digits.startswith("55") and len(digits) in [10, 11]:
            digits = f"55{digits}"

        # If Brazilian phone number (12 or 13 digits starting with 55)
        if digits.startswith("55") and len(digits) in [12, 13]:
            variants = [digits]
            if len(digits) == 13:
                variants.append(digits[:4] + digits[5:])
            elif len(digits) == 12:
                variants.append(digits[:4] + "9" + digits[4:])

            base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
            async with httpx.AsyncClient(timeout=6.0) as client:
                try:
                    r = await client.post(
                        f"{base_url}/chat/whatsappNumbers/{instance_name}",
                        headers=headers,
                        json={"numbers": variants}
                    )
                    if r.status_code == 200 and isinstance(r.json(), list):
                        for item in r.json():
                            if item.get("exists") and item.get("jid"):
                                return item.get("jid").split("@")[0]
                except Exception as e:
                    logger.debug(f"Error resolving canonical JID for {number}: {e}")

        return digits

    async def send_text_message(
        self,
        instance_name: str,
        number: str,
        text: str,
        mentioned: Optional[List[str]] = None,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendText/{instance_name}"
        clean_number = self._format_target_number(number)

        payload: Dict[str, Any] = {
            "number": clean_number,
            "text": text
        }
        if mentioned:
            payload["mentioned"] = mentioned
        client = self.get_client()
        try:
            response = await client.post(url, json=payload, headers=headers)
            res_data = response.json() if response.content else {}

            # Auto-retry on Connection Closed (stale socket)
            if response.status_code >= 500 or "connection closed" in str(res_data).lower():
                logger.warning(f"Instance {instance_name} socket stale/closed. Attempting auto-restart and retry...")
                try:
                    await client.post(f"{base_url}/instance/restart/{instance_name}", headers=headers)
                    await asyncio.sleep(1.0)
                    retry_sock_res = await client.post(url, json=payload, headers=headers)
                    if retry_sock_res.status_code < 400:
                        retry_sock_data = retry_sock_res.json()
                        retry_sock_data["success"] = True
                        return retry_sock_data
                except Exception as rest_err:
                    logger.warning(f"Error during auto-restart for {instance_name}: {rest_err}")

            # Retry with canonical JID (8 vs 9 digits) if WhatsApp rejected the initial number (400)
            if response.status_code == 400 and "@g.us" not in str(clean_number) and "@lid" not in str(clean_number):
                alt_number = await self.resolve_canonical_jid(instance_name, str(number), custom_base_url, custom_api_key)
                if alt_number and alt_number != clean_number:
                    retry_payload = {**payload, "number": self._format_target_number(alt_number)}
                    retry_res = await client.post(url, json=retry_payload, headers=headers)
                    if retry_res.status_code < 400:
                        retry_data = retry_res.json()
                        retry_data["success"] = True
                        return retry_data

            # Failover to default instance if current instance returned 404 Not Found
            if response.status_code == 404 and instance_name != "instancia_vendas":
                logger.warning(f"Instance '{instance_name}' returned 404 Not Found. Failing over to 'instancia_vendas'...")
                fb_url = f"{base_url}/message/sendText/instancia_vendas"
                fb_res = await client.post(fb_url, json=payload, headers=headers)
                if fb_res.status_code < 400:
                    fb_data = fb_res.json()
                    fb_data["success"] = True
                    return fb_data

            if response.status_code >= 400:
                err_msg = res_data.get("message") or res_data.get("response", {}).get("message") if isinstance(res_data.get("response"), dict) else res_data.get("message")
                if not err_msg and "connection closed" in str(res_data).lower():
                    err_msg = "A conexão do WhatsApp oscilou. Tentando reconectar..."
                return {"success": False, "error": err_msg or f"HTTP {response.status_code}"}
            res_data["success"] = True
            return res_data
        except Exception as e:
            logger.error(f"Error sending text message to {number} via instance {instance_name}: {e}")
            return {"success": False, "error": str(e)}

    async def send_button_message(
        self,
        instance_name: str,
        number: str,
        title: str,
        description: str,
        footer: str,
        buttons: List[Dict[str, Any]],
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends an interactive button message via Evolution API v2.
        Endpoint: POST /message/sendButtons/{instance_name}
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendButtons/{instance_name}"
        clean_number = await self.resolve_canonical_jid(instance_name, number, custom_base_url, custom_api_key)
        payload = {
            "number": clean_number,
            "title": title,
            "description": description,
            "footer": footer,
            "buttons": buttons
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                res_data = response.json() if response.content else {}
                if response.status_code < 400:
                    res_data["success"] = True
                    return res_data
                
                # Fallback to plain text message if buttons fail
                logger.warning(f"sendButtons returned {response.status_code}, falling back to sendText")
                full_text = f"*{title}*\n\n{description}\n\n_{footer}_"
                return await self.send_text_message(instance_name, number, full_text)
            except Exception as e:
                logger.error(f"Error sending buttons to {number} via instance {instance_name}: {e}")
                full_text = f"*{title}*\n\n{description}\n\n_{footer}_"
                return await self.send_text_message(instance_name, number, full_text)

    async def send_poll_message(
        self,
        instance_name: str,
        number: str,
        question: str,
        options: List[str],
        selectable_count: int = 1,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends an interactive one-click Poll button message via Evolution API v2.
        Endpoint: POST /message/sendPoll/{instance_name}
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendPoll/{instance_name}"
        clean_number = await self.resolve_canonical_jid(instance_name, number, custom_base_url, custom_api_key)
        
        # WhatsApp requires at least 2 options for polls
        safe_options = list(options)
        if len(safe_options) < 2:
            safe_options.append("❌ Recusar" if "Confirmar" in safe_options[0] else "⏳ Em Andamento")

        payload = {
            "number": clean_number,
            "name": question,
            "selectableCount": selectable_count,
            "values": safe_options
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                res_data = response.json() if response.content else {}
                if response.status_code < 400:
                    res_data["success"] = True
                    return res_data
                logger.warning(f"sendPoll returned {response.status_code}: {res_data}")
                return {"success": False, "error": str(res_data)}
            except Exception as e:
                logger.error(f"Error sending poll to {number} via instance {instance_name}: {e}")
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
        clean_number = self._format_target_number(number)
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
                if response.status_code == 400 and "@lid" not in clean_number and "@g.us" not in clean_number:
                    digits = "".join(filter(str.isdigit, clean_number))
                    lid_payload = {**payload, "number": f"{digits}@lid"}
                    retry_res = await client.post(url, json=lid_payload, headers=headers, timeout=15.0)
                    if retry_res.status_code < 400:
                        retry_data = retry_res.json()
                        retry_data["success"] = True
                        return retry_data

                if response.status_code >= 400:
                    return {"success": False, "error": res_data.get("message") or f"HTTP {response.status_code}"}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending native location message to {number} via instance {instance_name}: {e}")
                return {"success": False, "error": str(e)}

    async def send_whatsapp_audio(
        self,
        instance_name: str,
        number: str,
        audio_media: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends a native WhatsApp Voice Note (PTT / Push-To-Talk audio) with waveform icon via Evolution API v2.
        Endpoint: POST /message/sendWhatsAppAudio/{instance_name}
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendWhatsAppAudio/{instance_name}"
        clean_number = self._format_target_number(number)

        audio_payload = audio_media
        detected_mime = "audio/ogg"
        fname_ext = "ogg"

        if audio_payload.startswith("/uploads/"):
            fname = os.path.basename(audio_payload)
            l_lower = fname.lower()
            if l_lower.endswith(".webm"):
                detected_mime = "audio/webm"
                fname_ext = "webm"
            elif l_lower.endswith(".mp3"):
                detected_mime = "audio/mp3"
                fname_ext = "mp3"
            elif l_lower.endswith(".mp4") or l_lower.endswith(".m4a"):
                detected_mime = "audio/mp4"
                fname_ext = "m4a"
            elif l_lower.endswith(".wav"):
                detected_mime = "audio/wav"
                fname_ext = "wav"
            else:
                detected_mime = "audio/ogg"
                fname_ext = "ogg"

            lpath = os.path.join("uploads", fname)
            if os.path.exists(lpath):
                with open(lpath, "rb") as f:
                    raw_b64 = base64.b64encode(f.read()).decode("utf-8")
                    audio_payload = f"data:{detected_mime};base64,{raw_b64}"
        elif not audio_payload.startswith("data:") and not audio_payload.startswith("http"):
            audio_payload = f"data:{detected_mime};base64,{audio_payload}"

        payload = {
            "number": clean_number,
            "audio": audio_payload,
            "mimetype": detected_mime,
            "delay": 1200,
            "encoding": True
        }
        client = self.get_client()
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=20.0)
            res_data = response.json() if response.content else {}
            if response.status_code < 400 or res_data.get("key") or res_data.get("id"):
                res_data["success"] = True
                return res_data

            # Failover to sendMedia audio if sendWhatsAppAudio endpoint rejected request
            logger.warning(f"sendWhatsAppAudio returned {response.status_code}, falling back to sendMedia...")
            fallback_url = f"{base_url}/message/sendMedia/{instance_name}"
            raw_media = audio_payload.split(";base64,")[1] if ";base64," in audio_payload else audio_payload
            fallback_payload = {
                "number": clean_number,
                "mediatype": "audio",
                "mediaType": "audio",
                "mimetype": detected_mime,
                "media": raw_media,
                "fileName": f"voice_note.{fname_ext}"
            }
            fb_res = await client.post(fallback_url, json=fallback_payload, headers=headers, timeout=20.0)
            fb_data = fb_res.json() if fb_res.content else {}
            if fb_res.status_code < 400 or fb_data.get("key") or fb_data.get("id"):
                fb_data["success"] = True
                return fb_data

            return {"success": False, "error": fb_data.get("message") or f"HTTP {fb_res.status_code}"}
        except Exception as e:
            logger.error(f"Error sending WhatsApp PTT audio to {number} via instance {instance_name}: {e}")
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
        if media_type == "audio" or (mimetype and mimetype.startswith("audio/")):
            return await self.send_whatsapp_audio(
                instance_name=instance_name,
                number=number,
                audio_media=media,
                custom_base_url=custom_base_url,
                custom_api_key=custom_api_key
            )

        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendMedia/{instance_name}"
        clean_number = self._format_target_number(number)

        media_payload = media
        if media_payload.startswith("data:") and ";base64," in media_payload:
            media_payload = media_payload.split(";base64,")[1]

        payload = {
            "number": clean_number,
            "mediatype": media_type,
            "mediaType": media_type,
            "mimetype": mimetype,
            "media": media_payload,
            "fileName": file_name or "arquivo",
            "caption": caption
        }
        client = self.get_client()
        try:
            response = await client.post(url, json=payload, headers=headers)
            res_data = response.json() if response.content else {}

            # Auto-retry on Connection Closed (stale socket)
            if response.status_code >= 500 or "connection closed" in str(res_data).lower():
                logger.warning(f"Instance {instance_name} socket stale/closed for media. Attempting auto-restart and retry...")
                try:
                    await client.post(f"{base_url}/instance/restart/{instance_name}", headers=headers)
                    await asyncio.sleep(1.0)
                    retry_sock_res = await client.post(url, json=payload, headers=headers)
                    if retry_sock_res.status_code < 400:
                        retry_sock_data = retry_sock_res.json()
                        retry_sock_data["success"] = True
                        return retry_sock_data
                except Exception as rest_err:
                    logger.warning(f"Error during auto-restart for {instance_name}: {rest_err}")

            if response.status_code == 400 and "@g.us" not in str(clean_number) and "@lid" not in str(clean_number):
                alt_number = await self.resolve_canonical_jid(instance_name, str(number), custom_base_url, custom_api_key)
                if alt_number and alt_number != clean_number:
                    retry_payload = {**payload, "number": self._format_target_number(alt_number)}
                    retry_res = await client.post(url, json=retry_payload, headers=headers)
                    if retry_res.status_code < 400:
                        retry_data = retry_res.json()
                        retry_data["success"] = True
                        return retry_data

            # Failover to default instance if current instance returned 404 Not Found
            if response.status_code == 404 and instance_name != "instancia_vendas":
                logger.warning(f"Instance '{instance_name}' returned 404 Not Found for media. Failing over to 'instancia_vendas'...")
                fb_url = f"{base_url}/message/sendMedia/instancia_vendas"
                fb_res = await client.post(fb_url, json=payload, headers=headers)
                if fb_res.status_code < 400:
                    fb_data = fb_res.json()
                    fb_data["success"] = True
                    return fb_data

            if response.status_code >= 400:
                err_msg = res_data.get("message") or res_data.get("response", {}).get("message") if isinstance(res_data.get("response"), dict) else res_data.get("message")
                return {"success": False, "error": err_msg or f"HTTP {response.status_code}"}
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
        clean_number = self._format_target_number(number)
        payload = {
            "number": clean_number,
            "sticker": sticker_media
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                res_data = response.json()
                if response.status_code == 400 and "@lid" not in clean_number and "@g.us" not in clean_number:
                    digits = "".join(filter(str.isdigit, clean_number))
                    lid_payload = {**payload, "number": f"{digits}@lid"}
                    retry_res = await client.post(url, json=lid_payload, headers=headers, timeout=30.0)
                    if retry_res.status_code < 400:
                        retry_data = retry_res.json()
                        retry_data["success"] = True
                        return retry_data

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
        custom_api_key: Optional[str] = None,
        full_message: Optional[Dict] = None
    ) -> Optional[str]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/chat/getBase64FromMediaMessage/{instance_name}"
        key_obj: Dict[str, Any] = {
            "id": message_id,
            "fromMe": from_me
        }
        if remote_jid:
            key_obj["remoteJid"] = remote_jid

        msg_payload = dict(full_message) if full_message else {}
        msg_payload["key"] = key_obj

        payload = {
            "message": msg_payload,
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

    async def mark_message_as_read(
        self,
        instance_name: str,
        message_id: str,
        remote_jid: str,
        from_me: bool = False,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> bool:
        """Marks a WhatsApp message (and all prior) as read via Evolution API."""
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/chat/markMessageAsRead/{instance_name}"
        payload = {
            "readMessages": [
                {
                    "remoteJid": remote_jid,
                    "fromMe": from_me,
                    "id": message_id
                }
            ]
        }
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(url, json=payload, headers=headers, timeout=10.0)
                if res.status_code in (200, 201):
                    logger.info(f"[MARK_READ] Marked msg {message_id} as read on WhatsApp via {instance_name}")
                    return True
                else:
                    logger.warning(f"[MARK_READ] Failed to mark read, status {res.status_code}: {res.text[:200]}")
                    return False
            except Exception as e:
                logger.error(f"[MARK_READ] Error marking message as read via instance {instance_name}: {e}")
                return False

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
                        webhook_url = f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/v1/webhooks/evolution"
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

                        # Fetch contacts quickly
                        contacts_to_check = []
                        async with AsyncSessionLocal() as db:
                            c_res = await db.execute(select(Contact.id, Contact.telefone, Contact.nome, Contact.foto_perfil_url))
                            contacts_data = c_res.all()

                        updates = []
                        pic_fetches = 0

                        for c_id, c_tel, c_nome, c_pic in contacts_data:
                            raw_tel = c_tel.split("@")[0] if "@" in str(c_tel) else str(c_tel)
                            clean_num = raw_tel.replace("+", "").replace(" ", "").strip()
                            clean_digits = "".join(filter(str.isdigit, raw_tel))

                            # A. Check if Contact is a WhatsApp Group
                            if raw_tel in group_map or clean_num in group_map or f"{raw_tel}@g.us" in group_map or clean_digits in group_map:
                                g_info = group_map.get(raw_tel) or group_map.get(clean_num) or group_map.get(f"{raw_tel}@g.us") or group_map.get(clean_digits)
                                if g_info and g_info.get("subject"):
                                    new_name = g_info["subject"] if c_nome != g_info["subject"] else None
                                    new_pic = g_info["pictureUrl"] if g_info.get("pictureUrl") and c_pic != g_info["pictureUrl"] else None
                                    if new_name or new_pic:
                                        updates.append({"id": c_id, "nome": new_name or c_nome, "foto_perfil_url": new_pic or c_pic})
                                continue

                            # B. Check if Contact is an internal WhatsApp LID
                            if clean_num in lid_map:
                                real_phone = lid_map[clean_num]
                                matching = next((x for x in contacts_data if x[1] == real_phone), None)
                                if matching:
                                    target_name = f"{matching[2]} (Comunidade)"
                                    target_pic = matching[3] if not c_pic else c_pic
                                    if c_nome != target_name or (target_pic and c_pic != target_pic):
                                        updates.append({"id": c_id, "nome": target_name, "foto_perfil_url": target_pic})
                                continue

                            # C. Fetch Profile Picture if missing (max 3 per cycle to keep server ultra fast)
                            if not c_pic and pic_fetches < 3:
                                pic_fetches += 1
                                for inst in instances[:2]:
                                    try:
                                        res = await client.post(
                                            f"{base_url}/chat/fetchProfilePictureUrl/{inst}",
                                            headers=headers,
                                            json={"number": clean_num},
                                            timeout=3.0
                                        )
                                        if res.status_code in [200, 201]:
                                            pic = res.json().get("profilePictureUrl")
                                            if pic:
                                                updates.append({"id": c_id, "nome": c_nome, "foto_perfil_url": pic})
                                                break
                                    except Exception:
                                        continue

                        if updates:
                            async with AsyncSessionLocal() as db:
                                for u in updates:
                                    c_obj = await db.get(Contact, u["id"])
                                    if c_obj:
                                        c_obj.nome = u["nome"]
                                        c_obj.foto_perfil_url = u["foto_perfil_url"]
                                await db.commit()
        except Exception as e:
            logger.debug(f"Profile picture and group sync loop error: {e}")

        await asyncio.sleep(interval_seconds)

