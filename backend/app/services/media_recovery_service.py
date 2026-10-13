"""
Recuperação de mídia (foto/áudio/vídeo/arquivo) que chegou pelo WhatsApp mas não foi baixada.

Achado em 13/10/2026: o contrato em PDF da Andressa Lima (conversa #5000, 09/10) aparecia como
"Arquivo indisponível (link do WhatsApp expirou)" no sistema, mas abria normal no WhatsApp. Na
chegada, a busca do arquivo na Evolution API tinha limite de 8s e o PDF (~10MB) levou mais que isso;
o sistema guardou só o link .enc temporário do WhatsApp e nunca mais tentou. Depois que esse link
expira, o clique pra abrir também usava 8s, estourava de novo, e o endpoint concluía "expirou" e
bloqueava por 24h. Testado no mesmo dia: com tempo suficiente a Evolution recupera o arquivo mesmo
com o link expirado (pede pro celular reenviar a mídia) - 23s pra esse PDF.

Duas portas de entrada, mesmo código (recover_message_media):
  - sob demanda: conversations.get_message_media (clique pra abrir/baixar), com tempo de sobra;
  - automática: start_media_recovery_loop, pra mídia que falhou na chegada nos últimos
    LOOKBACK_DAYS - poucas por rodada, com intervalo crescente entre tentativas. Mídia mais antiga
    (ex: as ~4.700 que vieram da importação de histórico de mai-ago/2026 sem arquivo) NÃO entra aqui
    de propósito: pedir milhares de reenvios de mídia antiga de uma vez ao WhatsApp é pesado e foge
    do padrão de uso normal - essas são recuperadas uma a uma, quando alguém clica.
"""
import asyncio
import base64
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, Message, MessageSender, MessageType

logger = logging.getLogger("media_recovery")

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads"))
WHATSAPP_CDN_PREFIX = "https://mmg.whatsapp.net"

CHECK_INTERVAL_SECONDS = 300
LOOKBACK_DAYS = 14
MAX_PER_CYCLE = 5
BACKGROUND_TIMEOUT_SECONDS = 120.0
# Espera antes da tentativa N+1 (a primeira roda já na próxima rodada); depois da última, desiste.
RETRY_BACKOFF_MINUTES = [10, 30, 120, 360, 1440]


def _original_filename(msg: Message) -> Optional[str]:
    raw = msg.conteudo or ""
    extra = msg.dados_adicionais if isinstance(msg.dados_adicionais, dict) else {}
    name = extra.get("original_filename") or extra.get("file_name")
    if not name and "|" in raw:
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        if len(parts) >= 2:
            candidate = parts[1]
            if "." in candidate and len(candidate.split(".")[-1]) <= 6:
                name = candidate
    return name


async def recover_message_media(db, msg: Message, timeout: float) -> Tuple[Optional[str], Optional[str]]:
    """Busca a mídia da mensagem na Evolution API, grava em /uploads e troca o conteudo da mensagem
    pelo caminho local. Devolve (caminho_do_arquivo, nome_pra_download) ou (None, None) se falhou.
    `msg` precisa vir com conversation.whatsapp_number e conversation.contact carregados."""
    from app.services.evolution_service import evolution_service

    if not (msg.whatsapp_msg_id and msg.conversation and msg.conversation.whatsapp_number):
        return None, None
    conv = msg.conversation
    inst_name = conv.whatsapp_number.instancia_evolution_api or "instancia_financeiro"
    remote_jid = conv.contact.telefone if conv.contact else None
    if remote_jid and not remote_jid.endswith("@s.whatsapp.net") and not remote_jid.endswith("@g.us"):
        remote_jid = f"{remote_jid}@g.us" if ("120363" in remote_jid or len(remote_jid) > 15) else f"{remote_jid}@s.whatsapp.net"
    from_me = (msg.remetente == MessageSender.ATENDENTE.value or msg.remetente == "atendente" or msg.remetente == "ia")

    try:
        b64_data = await evolution_service.get_media_base64(
            instance_name=inst_name,
            message_id=msg.whatsapp_msg_id,
            from_me=from_me,
            remote_jid=remote_jid,
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"Error fetching base64 on {inst_name}: {e}")
        b64_data = None
    if not b64_data:
        return None, None

    ext = ".png"
    if msg.tipo == MessageType.VIDEO or msg.tipo == "video":
        ext = ".mp4"
    elif msg.tipo == MessageType.AUDIO or msg.tipo == "audio":
        ext = ".ogg"
    elif msg.tipo == MessageType.ARQUIVO or msg.tipo == "arquivo":
        ext = ".pdf"
    elif msg.tipo == MessageType.IMAGEM or msg.tipo == "imagem":
        ext = ".jpeg"

    raw = msg.conteudo or ""
    orig_filename = _original_filename(msg)
    try:
        raw_bytes = base64.b64decode(b64_data.split(",")[1] if "," in b64_data else b64_data)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        fname = f"{uuid.uuid4().hex}{ext}"
        fpath = os.path.join(UPLOAD_DIR, fname)
        with open(fpath, "wb") as f:
            f.write(raw_bytes)

        caption = ""
        if "|" in raw:
            parts = [p.strip() for p in raw.split("|") if p.strip()]
            if len(parts) >= 3:
                orig_filename = orig_filename or parts[1]
                caption = "|".join(parts[2:])
            elif len(parts) == 2:
                if not orig_filename and "." in parts[1] and len(parts[1].split(".")[-1]) <= 6:
                    orig_filename = parts[1]
                elif parts[1] != orig_filename:
                    caption = parts[1]

        if orig_filename and (msg.tipo in (MessageType.ARQUIVO, "arquivo") or orig_filename != fname):
            new_conteudo = f"/uploads/{fname}|{orig_filename}|{caption}" if caption else f"/uploads/{fname}|{orig_filename}"
        elif caption:
            new_conteudo = f"/uploads/{fname}|{caption}"
        else:
            new_conteudo = f"/uploads/{fname}"

        msg.conteudo = new_conteudo
        extra = dict(msg.dados_adicionais or {})
        if orig_filename:
            extra["original_filename"] = orig_filename
            extra["file_name"] = orig_filename
        for k in ("media_unavailable_since", "media_retry_count", "media_retry_next_at"):
            extra.pop(k, None)
        msg.dados_adicionais = extra
        flag_modified(msg, "dados_adicionais")
        await db.commit()
        return fpath, (orig_filename or fname)
    except Exception as e:
        logger.error(f"Error caching media base64: {e}")
        return None, None


async def _process_once() -> int:
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        candidates = (await db.execute(
            select(Message)
            .options(
                selectinload(Message.conversation).selectinload(Conversation.whatsapp_number),
                selectinload(Message.conversation).selectinload(Conversation.contact),
            )
            .where(
                Message.conteudo.like(f"{WHATSAPP_CDN_PREFIX}%"),
                Message.whatsapp_msg_id.isnot(None),
                Message.timestamp >= now - timedelta(days=LOOKBACK_DAYS),
            )
            .order_by(Message.id.desc())
        )).scalars().all()

        recovered = 0
        tried = 0
        for msg in candidates:
            if tried >= MAX_PER_CYCLE:
                break
            extra = dict(msg.dados_adicionais or {})
            count = int(extra.get("media_retry_count") or 0)
            if count > len(RETRY_BACKOFF_MINUTES):
                continue
            next_at = extra.get("media_retry_next_at")
            if next_at and datetime.fromisoformat(next_at) > now:
                continue
            tried += 1
            fpath, _ = await recover_message_media(db, msg, timeout=BACKGROUND_TIMEOUT_SECONDS)
            if fpath:
                recovered += 1
                logger.info(f"[MEDIA RECOVERY] Mensagem #{msg.id} (conversa #{msg.conversation_id}): mídia recuperada.")
            else:
                extra = dict(msg.dados_adicionais or {})
                extra["media_retry_count"] = count + 1
                if count < len(RETRY_BACKOFF_MINUTES):
                    extra["media_retry_next_at"] = (now + timedelta(minutes=RETRY_BACKOFF_MINUTES[count])).isoformat()
                msg.dados_adicionais = extra
                flag_modified(msg, "dados_adicionais")
                await db.commit()
                logger.warning(f"[MEDIA RECOVERY] Mensagem #{msg.id}: tentativa {count + 1} falhou.")
        return recovered


async def start_media_recovery_loop():
    logger.info(f"[MEDIA RECOVERY] Recuperação automática de mídia iniciada (a cada {CHECK_INTERVAL_SECONDS}s, últimos {LOOKBACK_DAYS} dias).")
    await asyncio.sleep(90)  # deixa o boot terminar antes da primeira rodada
    while True:
        try:
            n = await _process_once()
            if n:
                logger.info(f"[MEDIA RECOVERY] {n} mídia(s) recuperada(s) nesta rodada.")
        except Exception as e:
            logger.error(f"[MEDIA RECOVERY] Erro na rodada: {e}", exc_info=True)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
