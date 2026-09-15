"""
Consolidates WhatsApp GROUP chats that ended up split across multiple Contact and/or
Conversation records - e.g. the same group JID once saved as "120363...@g.us" and once
as "120363..." (no suffix), or the same group tracked separately under two different
department WhatsApp numbers. Real WhatsApp shows one thread per group; this made ours
show the same group's history fragmented across several "duplicate" chats.

Rule (as agreed): the conversation with the most messages becomes the keeper. Every other
conversation for the same group has its messages moved into the keeper (skipping anything
whose whatsapp_msg_id is already there) and is then deleted. Duplicate contacts collapse
into the one with a real (lettered) name, or the lowest id if none has one.

Usage:
    python merge_duplicate_groups.py            # apply
    python merge_duplicate_groups.py --dry-run  # simulate only
"""
import asyncio
import re
import sys
import logging
from collections import defaultdict
from sqlalchemy import select, update, func

from app.core.database import AsyncSessionLocal
from app.models.models import Contact, Conversation, Message
from app.services.backup_service import create_db_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("merge_duplicate_groups")


def normalize_group_key(telefone: str) -> str:
    t = (telefone or "").strip()
    is_group = "@g.us" in t or t.startswith("120363") or bool(re.match(r"^\d{6,}-\d+", t))
    if not is_group:
        return ""
    return t.replace("@g.us", "").strip()


def has_letter(s: str) -> bool:
    return bool(re.search(r"[A-Za-zÀ-ÿ]", s or ""))


async def run(dry_run: bool):
    if not dry_run:
        snapshot = create_db_snapshot()
        if snapshot:
            logger.info(f"Backup de segurança criado: {snapshot}")
        else:
            logger.warning("Não foi possível criar backup de segurança — abortando por segurança.")
            return
    else:
        logger.info("=== MODO DRY-RUN: nenhuma alteração será salva ===")

    async with AsyncSessionLocal() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()

        groups_by_key: dict[str, list[Contact]] = defaultdict(list)
        for c in contacts:
            key = normalize_group_key(c.telefone)
            if key:
                groups_by_key[key].append(c)

        contacts_merged = 0
        conversations_merged = 0
        messages_moved = 0
        messages_deduped = 0

        for key, dup_contacts in groups_by_key.items():
            # Gather every conversation belonging to any of these contacts, with a live message count
            all_convs = []
            for c in dup_contacts:
                convs = (await session.execute(select(Conversation).where(Conversation.contact_id == c.id))).scalars().all()
                for conv in convs:
                    cnt = (await session.execute(
                        select(func.count()).select_from(Message).where(Message.conversation_id == conv.id)
                    )).scalar() or 0
                    all_convs.append((conv, cnt, c))

            if len(dup_contacts) <= 1 and len(all_convs) <= 1:
                continue  # nothing to merge for this group

            if not all_convs:
                # Just duplicate empty contacts, no conversations at all - still worth collapsing
                if len(dup_contacts) > 1:
                    best = sorted(dup_contacts, key=lambda c: (not has_letter(c.nome), c.id))[0]
                    for c in dup_contacts:
                        if c.id != best.id:
                            logger.info(f"[GRUPO {key}] contato vazio duplicado {c.id} ('{c.nome}') removido (mantendo {best.id})")
                            if not dry_run:
                                await session.delete(c)
                            contacts_merged += 1
                continue

            all_convs.sort(key=lambda x: x[1], reverse=True)
            keeper_conv, keeper_count, keeper_contact = all_convs[0]

            logger.info(
                f"[GRUPO {key}] '{keeper_contact.nome}' - mantendo conversa #{keeper_conv.id} "
                f"({keeper_count} msgs, depto {keeper_conv.whatsapp_number_id}) como principal"
            )

            existing_wa_ids = set()
            if all_convs[1:]:
                keeper_msgs = (await session.execute(
                    select(Message.whatsapp_msg_id).where(Message.conversation_id == keeper_conv.id)
                )).scalars().all()
                existing_wa_ids = {w for w in keeper_msgs if w}

            for conv, cnt, c in all_convs[1:]:
                msgs = (await session.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
                moved_here = 0
                deduped_here = 0
                for m in msgs:
                    if m.whatsapp_msg_id and m.whatsapp_msg_id in existing_wa_ids:
                        deduped_here += 1
                        if not dry_run:
                            await session.delete(m)
                    else:
                        moved_here += 1
                        if not dry_run:
                            m.conversation_id = keeper_conv.id
                        if m.whatsapp_msg_id:
                            existing_wa_ids.add(m.whatsapp_msg_id)

                logger.info(
                    f"[GRUPO {key}] conversa #{conv.id} (depto {conv.whatsapp_number_id}): "
                    f"{moved_here} mensagens movidas, {deduped_here} duplicadas descartadas -> apagando conversa vazia"
                )
                messages_moved += moved_here
                messages_deduped += deduped_here
                conversations_merged += 1
                if not dry_run:
                    await session.delete(conv)

            # Collapse duplicate contacts: prefer one with a real (lettered) name
            best_contact = sorted(dup_contacts, key=lambda c: (not has_letter(c.nome), c.id))[0]
            if keeper_conv.contact_id != best_contact.id and not dry_run:
                keeper_conv.contact_id = best_contact.id

            for c in dup_contacts:
                if c.id != best_contact.id:
                    remaining = (await session.execute(
                        select(func.count()).select_from(Conversation).where(Conversation.contact_id == c.id)
                    )).scalar() or 0
                    if remaining == 0:
                        logger.info(f"[GRUPO {key}] contato duplicado {c.id} ('{c.nome}') removido (mantendo {best_contact.id} '{best_contact.nome}')")
                        if not dry_run:
                            await session.delete(c)
                        contacts_merged += 1

        if not dry_run:
            await session.commit()

        logger.info(
            f"=== {'SIMULAÇÃO' if dry_run else 'CONCLUÍDO'}: "
            f"{contacts_merged} contatos duplicados removidos, "
            f"{conversations_merged} conversas fragmentadas consolidadas, "
            f"{messages_moved} mensagens movidas para a conversa principal, "
            f"{messages_deduped} mensagens duplicadas descartadas ==="
        )


if __name__ == "__main__":
    asyncio.run(run(dry_run="--dry-run" in sys.argv))
