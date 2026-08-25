import asyncio
import logging
from typing import Dict, Any, List
import httpx
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import WhatsAppNumber
from app.services.evolution_service import evolution_service
from app.api.websockets import ws_manager

logger = logging.getLogger("whatsapp_watchdog")

class WhatsAppWatchdogService:
    def __init__(self):
        self.is_running = False
        self.instance_last_reconnect: Dict[str, float] = {}

    async def check_and_auto_heal_instances(self):
        """
        Periodically inspects all registered WhatsApp instances and automatically
        reconnects any disconnected or closed instances without requiring manual intervention.
        """
        try:
            async with AsyncSessionLocal() as session:
                # 1. Fetch active registered WhatsApp numbers from DB
                stmt = select(WhatsAppNumber).where(WhatsAppNumber.status == True)
                res = await session.execute(stmt)
                registered_numbers = res.scalars().all()

                if not registered_numbers:
                    return

                # 2. Query live state from Evolution API
                base_url, headers = evolution_service._get_headers_and_url()
                live_instances = {}
                async with httpx.AsyncClient(timeout=8.0) as client:
                    try:
                        r = await client.get(f"{base_url}/instance/fetchInstances", headers=headers)
                        if r.status_code == 200 and isinstance(r.json(), list):
                            for inst in r.json():
                                name = inst.get("name")
                                if name:
                                    live_instances[name] = inst.get("connectionStatus")
                    except Exception as ping_err:
                        logger.warning(f"Watchdog não conseguiu consultar fetchInstances na Evolution API: {ping_err}")
                        return

                import time
                current_ts = time.time()

                # 3. Check each registered instance and heal if disconnected
                for wn in registered_numbers:
                    inst_name = wn.instancia_evolution_api
                    if not inst_name:
                        continue

                    live_status = live_instances.get(inst_name)

                    # If not connected (close, connecting, or missing)
                    if live_status != "open":
                        last_try = self.instance_last_reconnect.get(inst_name, 0)
                        # Throttle reconnection attempts to once every 45 seconds per instance
                        if current_ts - last_try >= 45:
                            self.instance_last_reconnect[inst_name] = current_ts
                            logger.info(f"🔄 [Watchdog] Detectada instância '{inst_name}' com status '{live_status}'. Tentando reconexão automática...")
                            
                            try:
                                async with httpx.AsyncClient(timeout=10.0) as client:
                                    conn_res = await client.get(
                                        f"{base_url}/instance/connect/{inst_name}",
                                        headers=headers
                                    )
                                    logger.info(f"🔄 [Watchdog] Tentativa de reconexão de '{inst_name}' enviada (HTTP {conn_res.status_code}).")
                            except Exception as rec_err:
                                logger.error(f"Erro ao tentar reconectar '{inst_name}': {rec_err}")

        except Exception as e:
            logger.error(f"Erro no ciclo do WhatsApp Watchdog: {e}")

    async def run_loop(self, interval_seconds: int = 45):
        """Infinite loop that monitors instances in background."""
        self.is_running = True
        logger.info(f"🛡️ WhatsApp Auto-Heal Watchdog iniciado (Varredura a cada {interval_seconds}s).")
        while self.is_running:
            try:
                await self.check_and_auto_heal_instances()
            except Exception as e:
                logger.error(f"Erro não tratado no loop do Watchdog: {e}")
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self.is_running = False

whatsapp_watchdog = WhatsAppWatchdogService()

async def start_whatsapp_watchdog_loop(interval_seconds: int = 45):
    await whatsapp_watchdog.run_loop(interval_seconds=interval_seconds)
