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
from app.models.models import Contact, Conversation
from app.services.backup_service import create_db_snapshot
from app.services.lid_resolver_service import resolve_lid_info

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


def is_valid_candidate_name(nome: str) -> bool:
    """Some WhatsApp pushNames are just punctuation/emoji (e.g. '.', '🙏') — those would be
    a downgrade versus even the raw phone digits, so require at least 2 real letters."""
    if not nome:
        return False
    letters_only = re.sub(r"[^A-Za-zÀ-ÿ]", "", nome)
    return len(letters_only) >= 2


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


async def batch_resolve_lids(lid_phones):
    """Resolves LIDs to real phone/name/pic using the same three-tier fallback
    (direct Postgres -> docker exec psql -> Evolution HTTP findMessages) already
    proven live against production for the group-mentions fix. Run with bounded
    concurrency since the slower HTTP fallback tier can be hit for unresolved LIDs."""
    lid_map = {}
    if not lid_phones:
        return lid_map

    # Kept low on purpose: resolve_lid_info's Postgres pool only allows 5 concurrent
    # connections, and its fallback tier shells out to `docker exec psql` per LID - on
    # this box (954MB RAM, throttled CPU) running 15 of those at once starved the pool
    # and blew past the fallback's 2.5s timeout for almost every LID, which is why a
    # previous run here only resolved 12 of 773 despite most of them having real data
    # available (confirmed by resolving the same LIDs one at a time - 5/5 succeeded).
    sem = asyncio.Semaphore(4)

    async def _resolve_one(lid):
        async with sem:
            try:
                info = await resolve_lid_info(lid)
                if info.get("real_phone") or info.get("name") or info.get("profile_pic"):
                    lid_map[lid] = info
            except Exception as e:
                logger.debug(f"Erro ao resolver LID {lid}: {e}")

    total = len(lid_phones)
    for i in range(0, total, 200):
        chunk = lid_phones[i:i + 200]
        await asyncio.gather(*[_resolve_one(lid) for lid in chunk])
        logger.info(f"Progresso da resolução de LIDs: {min(i + 200, total)}/{total}")

    resolved_phones = sum(1 for v in lid_map.values() if v.get("real_phone"))
    logger.info(f"Resolvidos: {resolved_phones} números reais e {len(lid_map)} registros com algum dado (nome/foto/telefone) de {total} LIDs.")
    return lid_map


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
        lid_map = await batch_resolve_lids(lid_phones)

        merged_count = 0
        phone_fixed_count = 0
        name_fixed_count = 0
        pic_fixed_count = 0

        for c in contacts:
            if is_locked(c):
                continue

            phone = str(c.telefone).strip()
            lid_info = lid_map.get(phone) if is_lid_phone(phone) else None

            if lid_info and lid_info.get("real_phone") and lid_info["real_phone"].startswith("55"):
                real_phone = lid_info["real_phone"]
                if real_phone != phone:
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
                best_name = (ab_info.get("name") if ab_info else None) or (lid_info.get("name") if lid_info else None)
                if best_name and best_name != c.nome and is_valid_candidate_name(best_name):
                    logger.info(f"[NOME] contato {c.id} ({phone}): '{c.nome}' -> '{best_name}'")
                    if not dry_run:
                        c.nome = best_name
                    name_fixed_count += 1

            ab_info = address_book.get(phone)
            best_pic = (ab_info.get("pic") if ab_info else None) or (lid_info.get("profile_pic") if lid_info else None)
            if best_pic and not c.foto_perfil_url:
                if not dry_run:
                    c.foto_perfil_url = best_pic
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
