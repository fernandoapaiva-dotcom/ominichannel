import asyncio
import logging
import os
import base64
import subprocess
import tempfile
from typing import Dict, Any, Optional, List
import httpx
from app.core.config import settings
from app.services.lid_resolver_service import download_and_cache_avatar_locally, resolve_lid_info

logger = logging.getLogger("evolution_service")

def convert_to_ogg_opus(input_path: str) -> str:
    """
    Converts any input audio/video file (webm, mp4, wav, mp3) into a true WhatsApp-compliant
    Ogg Opus voice note with exact duration headers using ffmpeg.
    Returns path to converted .ogg file if successful, or original path if conversion fails.
    """
    try:
        out_fd, out_path = tempfile.mkstemp(suffix=".ogg")
        os.close(out_fd)

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:a", "libopus",
            "-b:a", "32k",
            "-ar", "48000",
            "-ac", "1",
            "-application", "voip",
            out_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
    except Exception as e:
        logger.error(f"ffmpeg conversion error: {e}")
    return input_path


import random
import time

class EvolutionService:
    def __init__(self):
        self.default_base_url = settings.EVOLUTION_API_URL.rstrip('/')
        self.default_api_key = settings.EVOLUTION_API_KEY
        self.qr_code_cache: Dict[str, str] = {}
        self._http_client: Optional[httpx.AsyncClient] = None
        self._contact_locks: Dict[str, asyncio.Lock] = {}
        self._last_send_time: Dict[str, float] = {}

    def _get_contact_lock(self, key: str) -> asyncio.Lock:
        if key not in self._contact_locks:
            self._contact_locks[key] = asyncio.Lock()
        return self._contact_locks[key]

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
                    "CALL",
                    "PRESENCE_UPDATE"
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

    async def send_presence(
        self,
        instance_name: str,
        number: str,
        presence: str = "composing",
        delay: int = 0,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Emits WhatsApp Web WebSocket presence stanza ('composing' or 'recording') to WhatsApp servers.
        This is REQUIRED by Meta anti-spam filters before sending any message.
        """
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/chat/sendPresence/{instance_name}"
        clean_number = self._format_target_number(number)
        payload = {
            "number": clean_number,
            "presence": presence,
            "delay": delay
        }
        client = self.get_client()
        try:
            res = await client.post(url, json=payload, headers=headers, timeout=5.0)
            return res.json() if res.content else {}
        except Exception as e:
            logger.debug(f"[ANTI-BAN] sendPresence ({presence}) to {clean_number} failed/timed out: {e}")
            return {}

    async def _apply_anti_ban_pacing_and_presence(
        self,
        instance_name: str,
        number: str,
        text: str = "",
        presence_type: str = "composing",
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ):
        """
        Enforces 100% Anti-Ban safeguards:
        1. Rate-limiting / inter-message spacing (cooldown gap between consecutive messages).
        2. 'composing' or 'recording' presence stanza sent to WhatsApp Web.
        3. Dynamic human typing delay (simulates typing proportional to text length + jitter).
        """
        clean_number = self._format_target_number(number)
        lock_key = f"{instance_name}:{clean_number}"
        lock = self._get_contact_lock(lock_key)

        async with lock:
            # 1. Enforce minimum inter-message gap (cooldown gap of 2.2s - 3.8s)
            now = time.time()
            last_time = self._last_send_time.get(lock_key, 0.0)
            elapsed = now - last_time
            min_gap = random.uniform(2.2, 3.8)
            if elapsed < min_gap:
                wait_time = min_gap - elapsed
                logger.info(f"[ANTI-BAN] Throttling message to {clean_number} (waiting {wait_time:.2f}s gap)")
                await asyncio.sleep(wait_time)

            # 2. Calculate dynamic human typing / recording delay
            if presence_type == "recording":
                typing_delay_sec = random.uniform(2.5, 4.2)
            elif presence_type == "composing":
                char_count = len(text or "")
                raw_delay = 1.6 + (char_count * 0.035) + random.uniform(0.3, 1.1)
                typing_delay_sec = max(1.8, min(6.5, raw_delay))
            else:
                typing_delay_sec = 1.5

            delay_ms = int(typing_delay_sec * 1000)

            # 3. Emit presence status (composing / recording) to WhatsApp servers
            await self.send_presence(
                instance_name=instance_name,
                number=clean_number,
                presence=presence_type,
                delay=delay_ms,
                custom_base_url=custom_base_url,
                custom_api_key=custom_api_key
            )

            # 4. Hold execution for the duration of the typing/recording simulation
            logger.info(f"[ANTI-BAN] Simulating human {presence_type} state for {clean_number} ({typing_delay_sec:.2f}s delay)")
            await asyncio.sleep(typing_delay_sec)

            # Update last send time timestamp
            self._last_send_time[lock_key] = time.time()

    def _add_micro_jitter(self, text: str) -> str:
        """
        Appends non-visible zero-width space characters (\u200b) to prevent
        Meta's automated spam hash filter from matching duplicate automated text templates.
        """
        if not text:
            return text
        jitter_count = random.randint(1, 3)
        zero_spaces = "\u200b" * jitter_count
        return f"{text}{zero_spaces}"

    async def send_text_message(
        self,
        instance_name: str,
        number: str,
        text: str,
        mentioned: Optional[List[str]] = None,
        quoted: Optional[Dict[str, Any]] = None,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        # 1. Apply 100% Anti-Ban safeguards: presence simulation, human delay, and rate limiting
        await self._apply_anti_ban_pacing_and_presence(
            instance_name=instance_name,
            number=number,
            text=text,
            presence_type="composing",
            custom_base_url=custom_base_url,
            custom_api_key=custom_api_key
        )

        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendText/{instance_name}"
        clean_number = self._format_target_number(number)
        safe_text = self._add_micro_jitter(text)

        payload: Dict[str, Any] = {
            "number": clean_number,
            "text": safe_text
        }
        if mentioned:
            payload["mentioned"] = mentioned
        if quoted:
            payload["quoted"] = quoted
        client = self.get_client()
        try:
            response = await client.post(url, json=payload, headers=headers)
            res_data = response.json() if response.content else {}

            # (Auto-restart automático de socket desativado para prevenir martelamento de conexão na Meta)

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

            # (Failover a instâncias cruzadas removido para prevenir envio não autorizado e proteger linhas contra banimento)

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
        Safe alternative for interactive buttons:
        Converts legacy Protobuf buttons (which trigger Meta anti-bot bans) into native WhatsApp Polls (sendPoll).
        Native Polls are 100% official, safe, and native on WhatsApp Web & Mobile.
        """
        logger.info(f"[ANTI-BAN] Converting legacy button request for {number} to safe Native WhatsApp Poll...")
        question = f"{title}\n{description}".strip()
        if len(question) > 255:
            question = question[:250] + "..."

        options = []
        for btn in buttons:
            btn_text = ""
            if isinstance(btn, dict):
                btn_text = btn.get("displayText") or btn.get("buttonText", {}).get("displayText") or btn.get("id", "")
            elif isinstance(btn, str):
                btn_text = btn
            if btn_text:
                options.append(str(btn_text))

        if not options:
            options = ["Sim, aceitar", "Não, recusar"]

        return await self.send_poll_message(
            instance_name=instance_name,
            number=number,
            question=question,
            options=options,
            selectable_count=1,
            custom_base_url=custom_base_url,
            custom_api_key=custom_api_key
        )

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
        # 1. Apply Anti-Ban pacing & presence ("composing")
        await self._apply_anti_ban_pacing_and_presence(
            instance_name=instance_name,
            number=number,
            text=question,
            presence_type="composing",
            custom_base_url=custom_base_url,
            custom_api_key=custom_api_key
        )

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
                        res_data = response.json() if response.text else {}
                        res_data["success"] = True
                        return res_data
                    else:
                        logger.warning(f"Evolution edit_message returned {response.status_code} for {url}: {response.text[:200]}")
                except Exception as e:
                    logger.warning(f"Error trying to edit message via {url}: {e}")

        return {"success": False, "message": "Failed to update message on WhatsApp API"}

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
        # 1. Apply Anti-Ban pacing & presence ("composing")
        await self._apply_anti_ban_pacing_and_presence(
            instance_name=instance_name,
            number=number,
            text=name or address or "Localização",
            presence_type="composing",
            custom_base_url=custom_base_url,
            custom_api_key=custom_api_key
        )

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
        NOTE: Evolution API 2.3.7 accepts public HTTPS URL or pure base64 (no "data:" prefix).
        It REJECTS "data:audio/ogg;base64,..." format.
        """
        # 1. Apply Anti-Ban pacing & presence ("recording")
        await self._apply_anti_ban_pacing_and_presence(
            instance_name=instance_name,
            number=number,
            text="",
            presence_type="recording",
            custom_base_url=custom_base_url,
            custom_api_key=custom_api_key
        )

        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/message/sendWhatsAppAudio/{instance_name}"
        clean_number = self._format_target_number(number)

        audio_payload = audio_media

        if audio_payload.startswith("/uploads/"):
            # Use the public HTTPS URL so Evolution API can fetch and process it directly
            fname = os.path.basename(audio_payload)
            lpath = os.path.join("uploads", fname)
            # If file is not already ogg, convert it first
            if os.path.exists(lpath) and not fname.endswith(".ogg"):
                ogg_path = convert_to_ogg_opus(lpath)
                if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
                    import shutil
                    ogg_fname = os.path.basename(ogg_path)
                    dest = os.path.join("uploads", ogg_fname)
                    shutil.move(ogg_path, dest)
                    fname = ogg_fname
            audio_payload = f"https://ominichannel.duckdns.org/uploads/{fname}"
            logger.info(f"[AUDIO] Sending via public URL: {audio_payload}")

        elif audio_payload.startswith("data:") and ";base64," in audio_payload:
            # Strip the data: prefix — Evolution API only accepts pure base64, not data URIs
            raw_b64 = audio_payload.split(";base64,")[1]
            try:
                raw_bytes = base64.b64decode(raw_b64)
                in_fd, in_path = tempfile.mkstemp(suffix=".webm")
                os.write(in_fd, raw_bytes)
                os.close(in_fd)

                ogg_path = convert_to_ogg_opus(in_path)
                if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
                    with open(ogg_path, "rb") as f:
                        raw_b64 = base64.b64encode(f.read()).decode("utf-8")
                    if ogg_path != in_path:
                        os.remove(ogg_path)
                if os.path.exists(in_path):
                    os.remove(in_path)
            except Exception as conv_err:
                logger.error(f"Error converting base64 audio with ffmpeg: {conv_err}")
            # Pass pure base64 without data: prefix
            audio_payload = raw_b64
            logger.info(f"[AUDIO] Sending via pure base64 ({len(audio_payload)} chars)")

        elif not audio_payload.startswith("http"):
            # Already pure base64 — use as-is
            logger.info(f"[AUDIO] Sending via pure base64 ({len(audio_payload)} chars)")

        payload = {
            "number": clean_number,
            "audio": audio_payload,
            "mimetype": "audio/ogg",
            "ptt": True,
            "delay": 1200,
            "encoding": True
        }
        client = self.get_client()
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=20.0)
            res_data = response.json() if response.content else {}
            logger.info(f"[AUDIO] sendWhatsAppAudio response: {response.status_code} | {str(res_data)[:300]}")
            if response.status_code < 400 or res_data.get("key") or res_data.get("id"):
                res_data["success"] = True
                return res_data

            # Failover to sendMedia if sendWhatsAppAudio rejected request
            logger.warning(f"sendWhatsAppAudio returned {response.status_code}, falling back to sendMedia...")
            fallback_url = f"{base_url}/message/sendMedia/{instance_name}"
            fallback_payload = {
                "number": clean_number,
                "mediatype": "audio",
                "mediaType": "audio",
                "mimetype": "audio/ogg",
                "media": audio_payload,
                "fileName": "voice_note.ogg",
                "ptt": True
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

        # 1. Apply Anti-Ban pacing & presence ("composing")
        await self._apply_anti_ban_pacing_and_presence(
            instance_name=instance_name,
            number=number,
            text=caption or file_name or "Mídia",
            presence_type="composing",
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

            # (Auto-restart automático de socket desativado para prevenir martelamento de conexão na Meta)

            if response.status_code == 400 and "@g.us" not in str(clean_number) and "@lid" not in str(clean_number):
                alt_number = await self.resolve_canonical_jid(instance_name, str(number), custom_base_url, custom_api_key)
                if alt_number and alt_number != clean_number:
                    retry_payload = {**payload, "number": self._format_target_number(alt_number)}
                    retry_res = await client.post(url, json=retry_payload, headers=headers)
                    if retry_res.status_code < 400:
                        retry_data = retry_res.json()
                        retry_data["success"] = True
                        return retry_data

            # (Failover a instâncias cruzadas removido para prevenir envio não autorizado e proteger linhas contra banimento)

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
        async with httpx.AsyncClient(timeout=6.0) as client:
            try:
                res = await client.post(url, json=payload, headers=headers, timeout=6.0)
                if res.status_code in (200, 201):
                    data = res.json()
                    return data.get("base64")
                else:
                    # If from_me failed, try the inverse
                    key_obj["fromMe"] = not from_me
                    res2 = await client.post(url, json=payload, headers=headers, timeout=6.0)
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
        clean_num = number.split("@")[0].replace("+", "").replace("-", "").replace(" ", "").strip()
        nums_to_try = [clean_num]
        if len(clean_num) == 12 and clean_num.startswith("55"):
            nums_to_try.append(f"{clean_num[:4]}9{clean_num[4:]}")
        elif len(clean_num) == 13 and clean_num.startswith("55"):
            nums_to_try.append(f"{clean_num[:4]}{clean_num[5:]}")

        async with httpx.AsyncClient(timeout=6.0) as client:
            for num_variant in nums_to_try:
                payload = {"number": num_variant}
                # 1. Try provided instance first
                if instance_name:
                    url = f"{base_url}/chat/fetchProfilePictureUrl/{instance_name}"
                    try:
                        response = await client.post(url, headers=headers, json=payload)
                        if response.status_code in [200, 201]:
                            data = response.json()
                            pic = data.get("profilePictureUrl") or data.get("picture") or data.get("url")
                            if pic and isinstance(pic, str) and pic.startswith("http"):
                                return pic
                    except Exception as e:
                        logger.debug(f"Failed to fetch profile picture on {instance_name} for {num_variant}: {e}")

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
                                    if pic and isinstance(pic, str) and pic.startswith("http"):
                                        return pic
                            except Exception:
                                continue
                except Exception as e:
                    logger.warning(f"Error checking connected instances for profile pic: {e}")
        return None

    async def fetch_and_update_contact_avatar(
        self,
        contact_id: int,
        instance_name: str,
        phone: str
    ):
        """
        Fetches official WhatsApp avatar URL for contact, downloads locally, and saves to DB.
        """
        if not phone or not instance_name:
            return
        try:
            pic_url = await self.fetch_profile_picture_url(instance_name=instance_name, number=phone)
            if pic_url:
                from app.core.database import AsyncSessionLocal
                from app.models.models import Contact
                from app.services.lid_resolver_service import download_and_cache_avatar_locally
                from app.core.websocket import manager

                local_avatar = await download_and_cache_avatar_locally(contact_id, pic_url)
                final_pic = local_avatar or pic_url

                async with AsyncSessionLocal() as session:
                    c_obj = await session.get(Contact, contact_id)
                    if c_obj and c_obj.foto_perfil_url != final_pic:
                        c_obj.foto_perfil_url = final_pic
                        tenant_id = c_obj.tenant_id
                        await session.commit()
                        logger.info(f"AVATAR: Foto salva com sucesso para o contato #{contact_id}: {final_pic}")
                        # Broadcast update to clients
                        try:
                            await manager.broadcast_to_tenant(tenant_id, {
                                "type": "CONTACT_UPDATED",
                                "contact_id": contact_id,
                                "foto_perfil_url": final_pic
                            })
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"Error updating contact avatar for contact {contact_id}: {e}")

    async def resolve_and_update_contact_phone(
        self,
        contact_id: int,
        instance_name: str,
        lid_phone: str
    ):
        """
        Resolves a 15-digit LID privacy number to the real 55xx phone number and updates DB.
        """
        if not lid_phone or not instance_name:
            return
        try:
            real_phone = await self.resolve_canonical_jid(instance_name=instance_name, number=lid_phone)
            if real_phone and real_phone.startswith("55") and len(real_phone) in [12, 13]:
                from app.core.database import AsyncSessionLocal
                from app.models.models import Contact
                async with AsyncSessionLocal() as session:
                    c_obj = await session.get(Contact, contact_id)
                    if c_obj and c_obj.telefone != real_phone:
                        logger.info(f"LID RESOLUTION: Resolvido contato #{contact_id} de LID '{lid_phone}' para telefone real '{real_phone}'")
                        c_obj.telefone = real_phone
                        await session.commit()
        except Exception as e:
            logger.debug(f"Error resolving LID for contact {contact_id}: {e}")

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
                    res = await client.get(f"{base_url}/group/fetchAllGroups/{instance_name}?getParticipants=false", headers=headers)
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
                                g_res = await client.get(f"{base_url}/group/fetchAllGroups/{inst}?getParticipants=false", headers=headers)
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

                            # C. Check if Contact is an unresolved raw LID
                            if len(clean_num) >= 14 and not clean_num.startswith("55") and not clean_num.startswith("120363"):
                                lid_res = await resolve_lid_info(clean_num)
                                if lid_res.get("real_phone") or lid_res.get("name") or lid_res.get("profile_pic"):
                                    cached_p = None
                                    if lid_res.get("profile_pic"):
                                        cached_p = await download_and_cache_avatar_locally(c_id, lid_res["profile_pic"])
                                    updates.append({
                                        "id": c_id,
                                        "telefone": lid_res.get("real_phone") or c_tel,
                                        "nome": lid_res.get("name") or c_nome,
                                        "foto_perfil_url": cached_p or lid_res.get("profile_pic") or c_pic
                                    })
                                    continue

                            # D. If contact has remote/expiring avatar URL (pps.whatsapp.net), cache it locally
                            if c_pic and c_pic.startswith("http") and not c_pic.startswith("/uploads/avatars/"):
                                cached = await download_and_cache_avatar_locally(c_id, c_pic)
                                if cached:
                                    updates.append({"id": c_id, "telefone": c_tel, "nome": c_nome, "foto_perfil_url": cached})
                                    continue

                            # E. Fetch Profile Picture if missing (max 5 per cycle to keep server ultra fast)
                            if not c_pic and pic_fetches < 5:
                                pic_fetches += 1
                                for inst in instances:
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
                                                cached = await download_and_cache_avatar_locally(c_id, pic)
                                                updates.append({"id": c_id, "telefone": c_tel, "nome": c_nome, "foto_perfil_url": cached or pic})
                                                break
                                    except Exception:
                                        continue

                        if updates:
                            async with AsyncSessionLocal() as db:
                                for u in updates:
                                    c_obj = await db.get(Contact, u["id"])
                                    if c_obj:
                                        if u.get("telefone") and u["telefone"] != c_obj.telefone:
                                            c_obj.telefone = u["telefone"]
                                        if u.get("nome") and u["nome"] != c_obj.nome:
                                            c_obj.nome = u["nome"]
                                        if u.get("foto_perfil_url") and u["foto_perfil_url"] != c_obj.foto_perfil_url:
                                            c_obj.foto_perfil_url = u["foto_perfil_url"]
                                await db.commit()
        except Exception as e:
            logger.debug(f"Profile picture and group sync loop error: {e}")

        await asyncio.sleep(interval_seconds)

