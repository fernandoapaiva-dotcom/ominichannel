import asyncio
import logging
import httpx
from sqlalchemy import select, update, delete

from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, Message, WhatsAppNumber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup_lids")

async def run_cleanup():
    logger.info("=== INICIANDO LIMPEZA E RESOLUÇÃO DE CONTATOS E CONVERSAS LID ===")
    base_url = "http://ominichannel.duckdns.org:8080"
    headers = {"apikey": "omini_master_key_123"}

    # 1. Fetch address book from all open instances
    address_book = {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            wn_res = await client.get(f"{base_url}/instance/fetchInstances", headers=headers)
            if wn_res.status_code == 200:
                for inst in wn_res.json():
                    name = inst.get("name")
                    if name and inst.get("connectionStatus") == "open":
                        try:
                            r = await client.post(f"{base_url}/chat/findContacts/{name}", headers=headers, json={})
                            if r.status_code == 200 and isinstance(r.json(), list):
                                for c in r.json():
                                    jid = c.get("remoteJid", "")
                                    if "@s.whatsapp.net" in jid:
                                        p = jid.split("@")[0].split(":")[0]
                                        c_name = c.get("pushName") or c.get("name") or c.get("verifiedName")
                                        c_pic = c.get("profilePicUrl")
                                        if p and (c_name or c_pic):
                                            address_book[p] = {"name": c_name, "pic": c_pic}
                                logger.info(f"Agenda de '{name}': {len(address_book)} contatos recuperados.")
                        except Exception as err:
                            logger.warning(f"Erro ao carregar contatos de {name}: {err}")
        except Exception as e:
            logger.error(f"Erro ao buscar instâncias: {e}")

    # 2. Iterate through database contacts and fix LIDs or generic 'Cliente WhatsApp' names
    async with AsyncSessionLocal() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()
        fixed_count = 0
        deleted_duplicates = 0

        for c in contacts:
            phone = str(c.telefone).strip()
            is_lid = len(phone) >= 14 and not phone.startswith("55") and not phone.startswith("120363") and "@g.us" not in phone and "-" not in phone

            # If contact is a LID, try resolving to canonical 55 phone number
            real_phone = phone
            if is_lid:
                # Query canonical phone from Evolution API
                try:
                    async with httpx.AsyncClient(timeout=6.0) as client:
                        r_lid = await client.post(
                            f"{base_url}/chat/whatsappNumbers/instancia_financeiro",
                            headers=headers,
                            json={"numbers": [phone]}
                        )
                        if r_lid.status_code == 200 and isinstance(r_lid.json(), list):
                            for item in r_lid.json():
                                if item.get("exists") and item.get("jid"):
                                    real_phone = item.get("jid").split("@")[0]
                                    break
                except Exception as lid_err:
                    logger.debug(f"Error resolving LID {phone}: {lid_err}")

            if real_phone != phone and not real_phone.startswith("1438") and not real_phone.startswith("226") and not real_phone.startswith("198"):
                # Check if real contact already exists in DB
                dup_stmt = select(Contact).where(
                    Contact.tenant_id == c.tenant_id,
                    Contact.telefone == real_phone,
                    Contact.id != c.id
                )
                dup_c = (await session.execute(dup_stmt)).scalars().first()
                if dup_c:
                    # Reassign all conversations from LID contact (c) to real contact (dup_c)
                    await session.execute(
                        update(Conversation)
                        .where(Conversation.contact_id == c.id)
                        .values(contact_id=dup_c.id)
                    )
                    await session.delete(c)
                    deleted_duplicates += 1
                    logger.info(f"Merged LID contact {c.id} ({phone}) into existing real contact {dup_c.id} ({real_phone})")
                    continue
                else:
                    c.telefone = real_phone
                    phone = real_phone
                    fixed_count += 1

            # Update contact name & avatar if matched in address_book
            ab_info = address_book.get(phone)
            if ab_info:
                if ab_info.get("name") and (c.nome in [None, "", phone, "Cliente WhatsApp", "WhatsApp", "WhatsApp Business"] or c.nome.isdigit()):
                    c.nome = ab_info["name"]
                    fixed_count += 1
                if ab_info.get("pic") and not c.foto_perfil_url:
                    c.foto_perfil_url = ab_info["pic"]
                    fixed_count += 1

        await session.commit()
        logger.info(f"=== LIMPEZA CONCLUÍDA: {fixed_count} contatos atualizados, {deleted_duplicates} contatos duplicados limpos. ===")

if __name__ == "__main__":
    asyncio.run(run_cleanup())
