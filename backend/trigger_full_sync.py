import asyncio
import logging
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import WhatsAppNumber
from app.services.settings_service import settings_service
from app.services.whatsapp_sync_service import whatsapp_sync_service

logging.basicConfig(level=logging.INFO)
logger = logger = logging.getLogger("trigger_full_sync")

async def sync_all():
    logger.info("=== DISPARANDO SINCRONIZAÇÃO EM MASSA DE TODAS AS INSTÂNCIAS ===")
    async with AsyncSessionLocal() as db:
        stmt = select(WhatsAppNumber).where(WhatsAppNumber.status == True)
        res = await db.execute(stmt)
        numbers = res.scalars().all()

        for wn in numbers:
            if wn.instancia_evolution_api and (wn.provider_type or "evolution") != "meta":
                decrypted = await settings_service.get_tenant_decrypted_settings(db, wn.tenant_id)
                logger.info(f"🔄 Disparando varredura para '{wn.nome_departamento}' ({wn.instancia_evolution_api})...")
                
                res_sync = await whatsapp_sync_service.sync_instance_history(
                    tenant_id=wn.tenant_id,
                    whatsapp_number_id=wn.id,
                    instance_name=wn.instancia_evolution_api,
                    custom_base_url=decrypted.get("evolution_api_url"),
                    custom_api_key=decrypted.get("evolution_api_key")
                )
                logger.info(f"✅ Resultado para '{wn.instancia_evolution_api}': {res_sync}")

if __name__ == "__main__":
    asyncio.run(sync_all())
