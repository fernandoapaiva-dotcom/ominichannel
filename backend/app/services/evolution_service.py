import logging
from typing import Dict, Any, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger("evolution_service")

class EvolutionService:
    def __init__(self):
        self.default_base_url = settings.EVOLUTION_API_URL.rstrip('/')
        self.default_api_key = settings.EVOLUTION_API_KEY

    def _get_headers_and_url(self, custom_base_url: Optional[str] = None, custom_api_key: Optional[str] = None):
        base_url = (custom_base_url or self.default_base_url).rstrip('/')
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
                elif response.status_code in [401, 403]:
                    return {"success": False, "error": "Chave Master (apikey) inválida ou não autorizada."}
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
            "integration": "WHATSAPP-BAILEYS"
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                return response.json()
            except Exception as e:
                logger.error(f"Error creating Evolution API v2 instance {instance_name}: {e}")
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
                return response.json()
            except Exception as e:
                logger.error(f"Error fetching QR code for instance {instance_name}: {e}")
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

evolution_service = EvolutionService()
