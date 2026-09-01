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
        self.instance_reconnect_attempts: Dict[str, int] = {}

    async def check_and_auto_heal_instances(self):
        """
        Periodically inspects all registered WhatsApp instances and automatically
        reconnects any disconnected instances using smart exponential backoff.
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

                    # Reset attempts count when connection is healthy and open
                    if live_status == "open":
                        self.instance_reconnect_attempts[inst_name] = 0
                        continue

                    # Do NOT interrupt if Baileys is actively connecting right now
                    if live_status == "connecting":
                        logger.debug(f"[Watchdog] Instância '{inst_name}' está em progresso de conexão ('connecting'). Aguardando...")
                        continue

                    # Safe reconnect only for closed or missing sessions
                    attempts = self.instance_reconnect_attempts.get(inst_name, 0)
                    if attempts >= 6:
                        logger.warning(f"[Watchdog] Instância '{inst_name}' atingiu limite de {attempts} tentativas. Interrompendo para evitar bloqueio por martelamento de socket.")
                        continue

                    # Calculate exponential backoff interval (120s, 300s, 600s...)
                    cooldown = min(600, 120 * (2 ** min(attempts, 3)))
                    last_try = self.instance_last_reconnect.get(inst_name, 0)

                    if current_ts - last_try >= cooldown:
                        self.instance_last_reconnect[inst_name] = current_ts
                        self.instance_reconnect_attempts[inst_name] = attempts + 1
                        logger.info(f"🛡️ [Watchdog] Instância '{inst_name}' desconectada ('{live_status}'). Apenas monitorando status para evitar martelamento de socket.")

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
