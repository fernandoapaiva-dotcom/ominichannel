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
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, WhatsAppNumber
from app.services.evolution_service import evolution_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_stale_avatars")

DRY_RUN = "--dry-run" in sys.argv


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

    # This VM occasionally hits severe hypervisor-level CPU steal (a known Always-Free-tier
    # OCI limitation, unrelated to this script) where even a LOCAL call to Evolution API can
    # blow past its 3s timeout. A low concurrency + a couple of retries with backoff turns
    # those transient timeouts into eventual successes instead of permanent false "no photo"
    # results, without adding meaningful extra load of our own.
    sem = asyncio.Semaphore(2)
    success = 0
    failed = 0
    RETRIES = 3

    async def process(c_id, tel, nome):
        nonlocal success, failed
        async with sem:
            instance_name = instance_by_contact.get(c_id) or fallback_instance
            for attempt in range(RETRIES):
                try:
                    async with AsyncSessionLocal() as db:
                        c_obj = await db.get(Contact, c_id)
                        before = c_obj.foto_perfil_url if c_obj else None
                    await evolution_service.fetch_and_update_contact_avatar(
                        contact_id=c_id, instance_name=instance_name, phone=tel
                    )
                    async with AsyncSessionLocal() as db:
                        c_obj = await db.get(Contact, c_id)
                        after = c_obj.foto_perfil_url if c_obj else None
                    if after and after != before and after.startswith("/uploads/avatars/"):
                        success += 1
                        logger.info(f"  OK  #{c_id} {nome} -> {after}")
                        break
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                    failed += 1
                    logger.info(f"  SEM FOTO  #{c_id} {nome} (privacidade/instancia offline/numero invalido, apos {RETRIES} tentativas)")
                except Exception as e:
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                    failed += 1
                    logger.warning(f"  ERRO #{c_id} {nome}: {e}")

    await asyncio.gather(*[process(c_id, tel, nome) for c_id, tel, nome in stale_contacts])

    logger.info(f"Concluído. Sucesso: {success} | Sem foto/erro: {failed} | Total: {len(stale_contacts)}")


if __name__ == "__main__":
    asyncio.run(main())
