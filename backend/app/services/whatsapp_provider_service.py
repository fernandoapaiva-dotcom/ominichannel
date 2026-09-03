import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import httpx

from app.models.models import WhatsAppNumber
from app.core.security import decrypt_data
from app.services.evolution_service import evolution_service

logger = logging.getLogger("whatsapp_provider_service")

class WhatsAppProviderInterface(ABC):
    @abstractmethod
    async def send_text_message(self, number: str, text: str, mentioned: Optional[list] = None) -> Dict[str, Any]:
        """Sends text message to a specific phone number."""
        pass

    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """Gets provider connection status or QR code."""
        pass

class EvolutionProvider(WhatsAppProviderInterface):
    def __init__(self, instance_name: Optional[str]):
        self.instance_name = instance_name or ""

    async def send_text_message(self, number: str, text: str, mentioned: Optional[list] = None, quoted: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.instance_name:
            return {"success": False, "error": "Nome da instância na Evolution API não configurado."}
        return await evolution_service.send_text_message(
            instance_name=self.instance_name,
            number=number,
            text=text,
            mentioned=mentioned,
            quoted=quoted
        )

    async def get_status(self) -> Dict[str, Any]:
        if not self.instance_name:
            return {"success": False, "error": "Instância não configurada"}
        return await evolution_service.get_qr_code(self.instance_name)

class MetaCloudProvider(WhatsAppProviderInterface):
    """
    WhatsApp Official API (Meta Cloud API v20.0) Provider Implementation.
    """
    def __init__(self, phone_number_id: Optional[str], waba_id: Optional[str], access_token_encrypted: Optional[str]):
        self.phone_number_id = phone_number_id or ""
        self.waba_id = waba_id or ""
        self.access_token = decrypt_data(access_token_encrypted) if access_token_encrypted else ""

    async def send_text_message(self, number: str, text: str) -> Dict[str, Any]:
        if not self.phone_number_id or not self.access_token:
            return {
                "success": False,
                "error": "Credenciais da Meta Cloud API (Phone Number ID / Access Token) não configuradas."
            }

        clean_number = "".join(filter(str.isdigit, number))
        url = f"https://graph.facebook.com/v20.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text
            }
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=15.0)
                res_data = response.json()
                if response.status_code >= 400:
                    err_msg = res_data.get("error", {}).get("message") or f"Meta HTTP {response.status_code}"
                    return {"success": False, "error": err_msg}
                res_data["success"] = True
                return res_data
            except Exception as e:
                logger.error(f"Error sending Meta Cloud API message to {number}: {e}")
                return {"success": False, "error": str(e)}

    async def get_status(self) -> Dict[str, Any]:
        if not self.phone_number_id or not self.access_token:
            return {"success": False, "error": "Credenciais da Meta API incompletas"}
        return {"success": True, "provider": "meta", "status": "CONNECTED", "phone_number_id": self.phone_number_id}

class WhatsAppProviderFactory:
    @staticmethod
    def get_provider(number_record: WhatsAppNumber) -> WhatsAppProviderInterface:
        provider_type = getattr(number_record, "provider_type", "evolution") or "evolution"
        if provider_type == "meta":
            return MetaCloudProvider(
                phone_number_id=number_record.meta_phone_number_id,
                waba_id=number_record.meta_waba_id,
                access_token_encrypted=number_record.meta_access_token_encrypted
            )
        else:
            return EvolutionProvider(instance_name=number_record.instancia_evolution_api)
