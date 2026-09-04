import asyncio
import re
import logging
import httpx
from sqlalchemy import select, update, delete

from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fix_618_lids")

async def fix_all():
    base_url = "http://ominichannel.duckdns.org:8080"
    headers = {"apikey": "omini_master_key_123"}

    # 1. Fetch full address book map from all open instances
    address_book = {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(f"{base_url}/instance/fetchInstances", headers=headers)
            if r.status_code == 200:
                for inst in r.json():
                    iname = inst.get("name")
                    if iname and inst.get("connectionStatus") == "open":
                        try:
                            res = await client.post(f"{base_url}/chat/findContacts/{iname}", headers=headers, json={})
                            if res.status_code == 200 and isinstance(res.json(), list):
                                for c in res.json():
                                    jid = c.get("remoteJid", "")
                                    if "@s.whatsapp.net" in jid:
                                        p = jid.split("@")[0].split(":")[0]
                                        nm = c.get("pushName") or c.get("name") or c.get("verifiedName")
                                        pic = c.get("profilePicUrl")
                                        if p and (nm or pic):
                                            address_book[p] = {"name": nm, "pic": pic}
                        except Exception as e:
                            logger.warning(f"Error fetching address book for {iname}: {e}")
        except Exception as e:
            logger.error(f"Error fetching instances: {e}")

    logger.info(f"Loaded {len(address_book)} address book contacts.")

    # 2. Iterate and fix all LID contacts
    async with AsyncSessionLocal() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()
        lids = [c for c in contacts if len(str(c.telefone)) >= 14 and not str(c.telefone).startswith("55") and not str(c.telefone).startswith("120363") and "@g.us" not in str(c.telefone) and "-" not in str(c.telefone)]
        
        logger.info(f"Found {len(lids)} LID contacts to process...")
        merged_count = 0
        updated_count = 0

        async with httpx.AsyncClient(timeout=8.0) as client:
            for idx, c in enumerate(lids):
                lid_phone = str(c.telefone).strip()
                real_phone = lid_phone
                extracted_name = None

                # Search messages for phone number or name in protocol message
                convs = (await session.execute(select(Conversation).where(Conversation.contact_id == c.id))).scalars().all()
                for conv in convs:
                    msgs = (await session.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
                    for m in msgs:
                        text = m.conteudo or ""
                        # Match 'Olá, 55...'
                        m_phone = re.search(r"Ol[aá],\s*(55\d{10,11})", text)
                        if m_phone:
                            real_phone = m_phone.group(1)
                            break
                        # Match 'Olá, [Nome]!'
                        m_name = re.search(r"Ol[aá],\s*([^!\n]+)!", text)
                        if m_name and not extracted_name:
                            cand = m_name.group(1).strip()
                            if cand and not cand.isdigit() and not cand.startswith("55") and cand not in ["Cliente", "Cliente WhatsApp"]:
                                extracted_name = cand

                # If real_phone not extracted from text, query Evolution API whatsappNumbers
                if real_phone == lid_phone:
                    for inst_name in ["instancia_financeiro", "instancia_vendas"]:
                        try:
                            r_num = await client.post(
                                f"{base_url}/chat/whatsappNumbers/{inst_name}",
                                headers=headers,
                                json={"numbers": [lid_phone]}
                            )
                            if r_num.status_code == 200 and isinstance(r_num.json(), list):
                                for item in r_num.json():
                                    if item.get("exists") and item.get("jid"):
                                        j = item.get("jid")
                                        if "@s.whatsapp.net" in j:
                                            real_phone = j.split("@")[0].split(":")[0]
                                            break
                                if real_phone != lid_phone:
                                    break
                        except Exception:
                            pass

                # If real_phone was resolved to a canonical 55 phone
                if real_phone != lid_phone and real_phone.startswith("55"):
                    # Check if real contact already exists
                    existing_c = (await session.execute(select(Contact).where(
                        Contact.tenant_id == c.tenant_id,
                        Contact.telefone == real_phone,
                        Contact.id != c.id
                    ))).scalars().first()

                    if existing_c:
                        await session.execute(
                            update(Conversation)
                            .where(Conversation.contact_id == c.id)
                            .values(contact_id=existing_c.id)
                        )
                        await session.delete(c)
                        merged_count += 1
                        continue
                    else:
                        c.telefone = real_phone
                        updated_count += 1

                # Update contact name & picture
                cur_phone = str(c.telefone).strip()
                ab_info = address_book.get(cur_phone)
                best_name = (ab_info.get("name") if ab_info else None) or extracted_name
                best_pic = (ab_info.get("pic") if ab_info else None)

                if best_name and (c.nome in [None, "", cur_phone, "Cliente WhatsApp", "WhatsApp"] or c.nome.isdigit()):
                    c.nome = best_name
                    updated_count += 1

                if best_pic and not c.foto_perfil_url:
                    c.foto_perfil_url = best_pic
                    updated_count += 1

                if idx % 50 == 0:
                    await session.commit()
                    logger.info(f"Processed {idx}/{len(lids)} LIDs... Merged: {merged_count}, Updated: {updated_count}")

        await session.commit()
        logger.info(f"=== SUCESSO: {merged_count} LIDs mesclados, {updated_count} contatos atualizados ===")

if __name__ == "__main__":
    asyncio.run(fix_all())
