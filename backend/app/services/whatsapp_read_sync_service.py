"""
Sincronização contínua de "lida" do sistema -> WhatsApp.

Pedido do usuário em 13/10/2026: "quando abre o whatsapp fixa x conversas com monte de chat, mas
eu já respondi ou visualizei no sistema, eu queria que fosse sincronizado". Até então o sistema só
avisava o WhatsApp UMA vez, na hora de abrir a conversa (conversations.trigger_whatsapp_mark_read),
e ficavam de fora:
  - conversa respondida sem abrir, ou respondida pela IA - nunca era avisada;
  - aviso que falhou com o WhatsApp desconectado ("Connection Closed" - 18 no log de 12/10) - perdido
    pra sempre, sem nova tentativa;
  - mensagem que o cliente mandou DEPOIS de a conversa ter sido aberta e respondida pelo sistema.

Agora, a cada SYNC_INTERVAL_SECONDS, toda conversa com mensagem de cliente recente que está "resolvida"
no sistema - última mensagem do cliente já marcada como lida (Message.status == "read") OU já
respondida depois dela por atendente/IA - e que ainda não foi avisada ao WhatsApp, é marcada como lida
lá também. O último aviso confirmado fica em Conversation.dados_adicionais["wa_read_synced_msg_pk"];
se falhar, a próxima rodada tenta de novo sozinha.

Fora de propósito:
  - Grupos (@g.us): marcar lida em grupo exige o participante de cada mensagem, que não guardamos.
  - Mensagem mais antiga que LOOKBACK_HOURS: não reprocessa o histórico inteiro no primeiro boot
    (seriam milhares de chamadas à Evolution API de uma vez).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, Message, WhatsAppNumber

logger = logging.getLogger("whatsapp_read_sync")

SYNC_INTERVAL_SECONDS = 180
LOOKBACK_HOURS = 72
MAX_CONVERSATIONS_PER_CYCLE = 40
PER_CALL_GAP_SECONDS = 1.0
MAX_IDS_PER_CALL = 20
_OUTGOING_SENDERS = ("atendente", "ia")
_DISCONNECTED_HINTS = ("connection closed", "not connected", "does not exist", "http 404")


async def _process_once() -> int:
    from app.api.v1.conversations import resolve_remote_jid
    from app.services.evolution_service import evolution_service
    from app.services.settings_service import settings_service

    cutoff = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)
    async with AsyncSessionLocal() as db:
        last_client = (
            select(Message.conversation_id.label("cid"), func.max(Message.id).label("mid"))
            .where(
                func.lower(Message.remetente) == "cliente",
                Message.whatsapp_msg_id.isnot(None),
                Message.timestamp >= cutoff,
            )
            .group_by(Message.conversation_id)
            .subquery()
        )
        last_out = (
            select(Message.conversation_id.label("cid"), func.max(Message.id).label("mid"))
            .where(func.lower(Message.remetente).in_(_OUTGOING_SENDERS), Message.timestamp >= cutoff)
            .group_by(Message.conversation_id)
            .subquery()
        )
        rows = (await db.execute(
            select(Message, last_out.c.mid)
            .join(last_client, Message.id == last_client.c.mid)
            .outerjoin(last_out, last_out.c.cid == last_client.c.cid)
        )).all()

        pending = []
        for msg, last_out_id in rows:
            resolved = (msg.status == "read") or (last_out_id is not None and last_out_id > msg.id)
            if resolved:
                pending.append(msg)
        if not pending:
            return 0

        convs = {
            c.id: c for c in (await db.execute(
                select(Conversation)
                .options(selectinload(Conversation.contact))
                .where(Conversation.id.in_([m.conversation_id for m in pending]))
            )).scalars().all()
        }
        pending = [
            m for m in pending
            if m.conversation_id in convs
            and int((convs[m.conversation_id].dados_adicionais or {}).get("wa_read_synced_msg_pk") or 0) < m.id
        ]
        pending.sort(key=lambda m: m.id, reverse=True)
        pending = pending[:MAX_CONVERSATIONS_PER_CYCLE]

        numbers = {
            n.id: n for n in (await db.execute(
                select(WhatsAppNumber).where(WhatsAppNumber.id.in_({convs[m.conversation_id].whatsapp_number_id for m in pending}))
            )).scalars().all()
        }
        tenant_settings = {}
        jobs = []
        for m in pending:
            conv = convs[m.conversation_id]
            wn = numbers.get(conv.whatsapp_number_id)
            remote_jid = resolve_remote_jid(conv)
            if not wn or not wn.instancia_evolution_api or not remote_jid or remote_jid.endswith("@g.us"):
                continue
            synced_pk = int((conv.dados_adicionais or {}).get("wa_read_synced_msg_pk") or 0)
            ids = (await db.execute(
                select(Message.whatsapp_msg_id)
                .where(
                    Message.conversation_id == conv.id,
                    func.lower(Message.remetente) == "cliente",
                    Message.whatsapp_msg_id.isnot(None),
                    Message.id > synced_pk,
                    Message.timestamp >= cutoff,
                )
                .order_by(Message.id.desc())
                .limit(MAX_IDS_PER_CALL)
            )).scalars().all()
            if conv.tenant_id not in tenant_settings:
                tenant_settings[conv.tenant_id] = await settings_service.get_tenant_decrypted_settings(db, conv.tenant_id)
            jobs.append((conv.id, m.id, wn.instancia_evolution_api, remote_jid, list(ids), tenant_settings[conv.tenant_id]))

    done = 0
    skip_instances = set()
    for conv_id, msg_pk, instance, remote_jid, ids, decrypted in jobs:
        if instance in skip_instances or not ids:
            continue
        ok, err = await evolution_service.mark_messages_as_read(
            instance_name=instance, remote_jid=remote_jid, message_ids=ids,
            custom_base_url=decrypted.get("evolution_api_url"),
            custom_api_key=decrypted.get("evolution_api_key"),
        )
        if ok:
            async with AsyncSessionLocal() as db:
                conv = await db.get(Conversation, conv_id)
                if conv:
                    extra = dict(conv.dados_adicionais or {})
                    extra["wa_read_synced_msg_pk"] = msg_pk
                    conv.dados_adicionais = extra
                    flag_modified(conv, "dados_adicionais")
                    await db.commit()
            done += 1
        else:
            if any(h in err.lower() for h in _DISCONNECTED_HINTS):
                skip_instances.add(instance)
                logger.warning(f"[READ SYNC] Instância '{instance}' indisponível ({err[:120]}) - tento de novo na próxima rodada.")
            else:
                logger.warning(f"[READ SYNC] Conversa #{conv_id}: falha ao marcar lida no WhatsApp ({err[:160]}).")
        await asyncio.sleep(PER_CALL_GAP_SECONDS)
    return done


async def start_whatsapp_read_sync_loop():
    logger.info(f"[READ SYNC] Sincronização de lidas sistema -> WhatsApp iniciada (a cada {SYNC_INTERVAL_SECONDS}s).")
    await asyncio.sleep(60)  # deixa o boot terminar antes da primeira rodada
    while True:
        try:
            n = await _process_once()
            if n:
                logger.info(f"[READ SYNC] {n} conversa(s) marcada(s) como lida(s) no WhatsApp.")
        except Exception as e:
            logger.error(f"[READ SYNC] Erro na rodada de sincronização: {e}", exc_info=True)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
