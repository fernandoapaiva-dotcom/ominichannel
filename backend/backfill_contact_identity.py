"""
Correção retroativa em massa: contatos com número no formato LID (interno da Evolution
API, ao invés do telefone real) e/ou nome "fraco" (sem letras, ou igual ao próprio
número) são resolvidos para o padrão pedido: nome fiel (da agenda salva no WhatsApp ou
extraído das próprias interações) e número real de telefone, sempre que possível.

Não sobrescreve nomes já "bons" (com letras) nem contatos com dados_adicionais.custom_name_locked.

Uso:
    python backfill_contact_identity.py            # aplica as correções
    python backfill_contact_identity.py --dry-run   # só reporta o que seria feito
"""
import asyncio
import re
import sys
import logging
import httpx
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, Message
from app.services.backup_service import create_db_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_contact_identity")

BASE_URL = "http://ominichannel.duckdns.org:8080"
HEADERS = {"apikey": "omini_master_key_123"}

GENERIC_NAMES = {"", "cliente", "cliente whatsapp", "whatsapp", "whatsapp business"}


def has_letter(s: str) -> bool:
    return bool(re.search(r"[A-Za-zÀ-ÿ]", s or ""))


def is_weak_name(nome: str, telefone: str) -> bool:
    n = (nome or "").strip()
    if not n:
        return True
    if n == telefone:
        return True
    if n.lower() in GENERIC_NAMES:
        return True
    if not has_letter(n):
        return True
    return False


def is_lid_phone(phone: str) -> bool:
    phone = str(phone).strip()
    return (
        len(phone) >= 14
        and not phone.startswith("55")
        and not phone.startswith("120363")
        and "@g.us" not in phone
        and "-" not in phone
    )


def is_locked(contact: Contact) -> bool:
    return bool((contact.dados_adicionais or {}).get("custom_name_locked"))


async def fetch_open_instances(client: httpx.AsyncClient):
    try:
        r = await client.get(f"{BASE_URL}/instance/fetchInstances", headers=HEADERS)
        if r.status_code == 200:
            return [i.get("name") for i in r.json() if i.get("name") and i.get("connectionStatus") == "open"]
    except Exception as e:
        logger.error(f"Erro ao buscar instâncias: {e}")
    return []


async def build_address_book(instances):
    address_book = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for iname in instances:
            try:
                res = await client.post(f"{BASE_URL}/chat/findContacts/{iname}", headers=HEADERS, json={})
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
                logger.warning(f"Erro ao buscar contatos de {iname}: {e}")
    logger.info(f"Agenda combinada: {len(address_book)} contatos com nome/foto reais.")
    return address_book


async def batch_resolve_lids(instances, lid_phones):
    lid_map = {}
    if not instances or not lid_phones:
        return lid_map
    instance = instances[0]
    async with httpx.AsyncClient(timeout=25.0) as client:
        chunk_size = 50
        for i in range(0, len(lid_phones), chunk_size):
            chunk = lid_phones[i:i + chunk_size]
            try:
                r_num = await client.post(
                    f"{BASE_URL}/chat/whatsappNumbers/{instance}",
                    headers=HEADERS,
                    json={"numbers": chunk},
                )
                if r_num.status_code == 200 and isinstance(r_num.json(), list):
                    for item in r_num.json():
                        if item.get("exists") and item.get("jid"):
                            orig = item.get("number") or item.get("id")
                            j = item.get("jid")
                            if "@s.whatsapp.net" in j:
                                real_p = j.split("@")[0].split(":")[0]
                                if orig and real_p.startswith("55"):
                                    lid_map[str(orig).strip()] = real_p
            except Exception as e:
                logger.warning(f"Erro no lote de resolução de LIDs ({i}-{i+chunk_size}): {e}")
    logger.info(f"Resolvidos {len(lid_map)}/{len(lid_phones)} LIDs para número real via Evolution API.")
    return lid_map


async def extract_name_from_messages(session, contact_id) -> str:
    convs = (await session.execute(select(Conversation).where(Conversation.contact_id == contact_id))).scalars().all()
    for conv in convs:
        msgs = (await session.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
        for m in msgs:
            text = m.conteudo or ""
            m_name = re.search(r"Ol[aá],\s*([^!\n]+)!", text)
            if m_name:
                cand = m_name.group(1).strip()
                if cand and not cand.isdigit() and not cand.startswith("55") and cand.lower() not in GENERIC_NAMES:
                    return cand
    return None


async def run(dry_run: bool):
    if not dry_run:
        snapshot = create_db_snapshot()
        if snapshot:
            logger.info(f"Backup de segurança criado antes da correção em massa: {snapshot}")
        else:
            logger.warning("Não foi possível criar backup de segurança — abortando por segurança.")
            return
    else:
        logger.info("=== MODO DRY-RUN: nenhuma alteração será salva ===")

    async with httpx.AsyncClient(timeout=15.0) as client:
        instances = await fetch_open_instances(client)
    logger.info(f"Instâncias abertas: {instances}")

    address_book = await build_address_book(instances)

    async with AsyncSessionLocal() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()
        logger.info(f"Total de contatos no tenant/base: {len(contacts)}")

        lid_contacts = [c for c in contacts if is_lid_phone(str(c.telefone))]
        lid_phones = list({str(c.telefone).strip() for c in lid_contacts})
        lid_map = await batch_resolve_lids(instances, lid_phones)

        merged_count = 0
        phone_fixed_count = 0
        name_fixed_count = 0
        pic_fixed_count = 0

        for c in contacts:
            if is_locked(c):
                continue

            phone = str(c.telefone).strip()

            if is_lid_phone(phone):
                real_phone = lid_map.get(phone)
                if real_phone and real_phone != phone:
                    existing = (await session.execute(select(Contact).where(
                        Contact.tenant_id == c.tenant_id,
                        Contact.telefone == real_phone,
                        Contact.id != c.id,
                    ))).scalars().first()

                    if existing:
                        logger.info(f"[MERGE] contato {c.id} ({phone}) -> contato {existing.id} ({real_phone})")
                        if not dry_run:
                            await session.execute(
                                update(Conversation).where(Conversation.contact_id == c.id).values(contact_id=existing.id)
                            )
                            await session.delete(c)
                        merged_count += 1
                        continue
                    else:
                        logger.info(f"[NÚMERO] contato {c.id}: {phone} -> {real_phone}")
                        if not dry_run:
                            c.telefone = real_phone
                        phone = real_phone
                        phone_fixed_count += 1

            if is_weak_name(c.nome, phone):
                ab_info = address_book.get(phone)
                best_name = ab_info.get("name") if ab_info else None
                if not best_name:
                    best_name = await extract_name_from_messages(session, c.id)
                if best_name and best_name != c.nome:
                    logger.info(f"[NOME] contato {c.id} ({phone}): '{c.nome}' -> '{best_name}'")
                    if not dry_run:
                        c.nome = best_name
                    name_fixed_count += 1

            ab_info = address_book.get(phone)
            if ab_info and ab_info.get("pic") and not c.foto_perfil_url:
                if not dry_run:
                    c.foto_perfil_url = ab_info["pic"]
                pic_fixed_count += 1

        if not dry_run:
            await session.commit()

        logger.info(
            f"=== {'SIMULAÇÃO' if dry_run else 'CONCLUÍDO'}: "
            f"{merged_count} contatos LID mesclados em contatos reais, "
            f"{phone_fixed_count} números corrigidos, "
            f"{name_fixed_count} nomes corrigidos, "
            f"{pic_fixed_count} fotos de perfil adicionadas ==="
        )


if __name__ == "__main__":
    asyncio.run(run(dry_run="--dry-run" in sys.argv))
