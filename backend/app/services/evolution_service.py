import logging
from typing import Dict, Any, Optional
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
                    "CONNECTION_UPDATE"
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
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/instance/connect/{instance_name}"
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
        clean_number = "".join(filter(str.isdigit, number))
        if len(clean_number) == 12 and clean_number.startswith("55") and clean_number[4] != "9":
            clean_number = clean_number[:4] + "9" + clean_number[4:]
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
        clean_number = "".join(filter(str.isdigit, number))
        if len(clean_number) == 12 and clean_number.startswith("55") and clean_number[4] != "9":
            clean_number = clean_number[:4] + "9" + clean_number[4:]

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

    async def get_media_base64(
        self,
        instance_name: str,
        message_id: str,
        custom_base_url: Optional[str] = None,
        custom_api_key: Optional[str] = None
    ) -> Optional[str]:
        base_url, headers = self._get_headers_and_url(custom_base_url, custom_api_key)
        url = f"{base_url}/chat/getBase64FromMediaMessage/{instance_name}"
        payload = {
            "message": {
                "key": {
                    "id": message_id
                }
            },
            "convertToMp4": False
        }
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(url, json=payload, headers=headers, timeout=15.0)
                if res.status_code in (200, 201):
                    data = res.json()
                    return data.get("base64")
            except Exception as e:
                logger.error(f"Error fetching media base64 for msg {message_id}: {e}")
        return None

evolution_service = EvolutionService()
