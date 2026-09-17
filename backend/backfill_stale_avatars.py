"""
Correção retroativa em massa: contatos cuja foto_perfil_url ainda aponta direto para um
link assinado da CDN do WhatsApp (pps.whatsapp.net) ao invés de um arquivo local baixado
em /uploads/avatars/. Esses links são assinados e expiram sozinhos depois de um tempo -
uma vez expirado, o contato fica travado pra sempre com uma URL morta (a foto some no
sistema mesmo continuando visível no WhatsApp), porque o loop automático de correção só
tentava rebaixar essa MESMA URL velha e nunca pedia uma nova ao Evolution API. Esse bug foi
corrigido em evolution_service.py; este script aplica a correção retroativamente para quem
já ficou preso nesse estado.

Uso:
    python backfill_stale_avatars.py            # aplica as correções
    python backfill_stale_avatars.py --dry-run   # só reporta o que seria feito
"""
import asyncio
import sys
import logging
import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, WhatsAppNumber
from app.services.lid_resolver_service import download_and_cache_avatar_locally

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_stale_avatars")

DRY_RUN = "--dry-run" in sys.argv

BASE_URL = settings.EVOLUTION_API_URL.rstrip("/")
HEADERS = {"apikey": settings.EVOLUTION_API_KEY, "Content-Type": "application/json"}
# This VM is going through a sustained hypervisor-level CPU steal spike (a known Always-Free
# OCI limitation, unrelated to this script). evolution_service's normal 3s timeout is tuned
# for live, latency-sensitive request paths and kept failing here even fully sequential with
# no concurrency at all - re-testing "failed" contacts individually right after always got
# the real photo back. So this backfill talks to Evolution API directly with a much more
# patient timeout instead of going through evolution_service's tight one.
PATIENT_TIMEOUT = httpx.Timeout(20.0)


async def patient_fetch_profile_picture_url(client: httpx.AsyncClient, instance_name: str, number: str, all_instances: list) -> "str | None":
    clean_num = number.split("@")[0].replace("+", "").replace("-", "").replace(" ", "").strip()
    tried = [instance_name] if instance_name else []
    for inst in tried + [i for i in all_instances if i and i != instance_name]:
        try:
            resp = await client.post(
                f"{BASE_URL}/chat/fetchProfilePictureUrl/{inst}",
                headers=HEADERS, json={"number": clean_num}, timeout=PATIENT_TIMEOUT
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                pic = data.get("profilePictureUrl") or data.get("picture") or data.get("url")
                if pic and isinstance(pic, str) and pic.startswith("http"):
                    return pic
        except Exception as e:
            logger.debug(f"    tentativa em {inst} falhou: {e}")
    return None


async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Contact.id, Contact.telefone, Contact.nome)
            .where(
                Contact.foto_perfil_url.like("http%"),
                Contact.foto_perfil_url.notlike("/uploads/avatars/%"),
            )
        )
        stale_contacts = res.all()

        # Pick a fallback instance name just to seed fetch_profile_picture_url - it
        # already falls back to every other connected instance on its own.
        wn_res = await db.execute(select(WhatsAppNumber.instancia_evolution_api).limit(1))
        fallback_instance = wn_res.scalar_one_or_none() or ""

        # Prefer each contact's own most recent instance when we have one
        conv_res = await db.execute(
            select(Conversation.contact_id, WhatsAppNumber.instancia_evolution_api)
            .join(WhatsAppNumber, Conversation.whatsapp_number_id == WhatsAppNumber.id)
            .order_by(Conversation.ultima_interacao_em.desc())
        )
        instance_by_contact = {}
        for contact_id, inst in conv_res.all():
            if contact_id not in instance_by_contact and inst:
                instance_by_contact[contact_id] = inst

    logger.info(f"Contatos com avatar remoto (possivelmente expirado): {len(stale_contacts)}")
    if DRY_RUN:
        for c_id, tel, nome in stale_contacts[:30]:
            logger.info(f"  [DRY-RUN] #{c_id} {nome} ({tel})")
        logger.info("Dry-run: nenhuma alteração feita.")
        return

    success = 0
    failed = 0
    processed = 0

    async with httpx.AsyncClient() as client:
        try:
            inst_resp = await client.get(f"{BASE_URL}/instance/fetchInstances", headers=HEADERS, timeout=PATIENT_TIMEOUT)
            all_instances = [
                i.get("name") for i in inst_resp.json()
                if isinstance(i, dict) and i.get("connectionStatus") == "open"
            ] if inst_resp.status_code == 200 else []
        except Exception:
            all_instances = []
        logger.info(f"Instancias conectadas: {all_instances}")

        for c_id, tel, nome in stale_contacts:
            instance_name = instance_by_contact.get(c_id) or fallback_instance
            pic_url = await patient_fetch_profile_picture_url(client, instance_name, tel, all_instances)

            if pic_url:
                local_pic = await download_and_cache_avatar_locally(c_id, pic_url)
                if local_pic:
                    success += 1
                    logger.info(f"  OK  #{c_id} {nome} -> {local_pic}")
                else:
                    failed += 1
                    logger.info(f"  ERRO AO BAIXAR  #{c_id} {nome} (achou a URL mas nao conseguiu salvar)")
            else:
                failed += 1
                logger.info(f"  SEM FOTO  #{c_id} {nome} (privacidade ou instancia indisponivel)")

            processed += 1
            if processed % 50 == 0:
                logger.info(f"  ... progresso: {processed}/{len(stale_contacts)} (sucesso={success}, sem_foto={failed})")
            await asyncio.sleep(0.3)

    logger.info(f"Concluído. Sucesso: {success} | Sem foto/erro: {failed} | Total: {len(stale_contacts)}")


if __name__ == "__main__":
    asyncio.run(main())
