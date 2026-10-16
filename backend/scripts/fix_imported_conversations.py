"""
Arruma as conversas que a sincronização de histórico criou antes da correção de 13/10/2026 -
ficavam com o horário da importação (todas no topo da lista, como se tivessem acabado de chegar)
e com status "HUMANO" (lotando a fila de atendimento).

Só mexe em conversa que:
  - foi criada pela importação (dados_adicionais.is_migrated) nos últimos DIAS_ATRAS dias,
  - não tem protocolo e está com status com_humano,
  - não teve nenhuma mensagem nova depois de criada (ninguém atendeu nem o cliente escreveu).
Nessas: horário = última mensagem de verdade, e se ela tiver mais de 24h, status = encerrada.

Uso:
    cd backend && source venv/bin/activate
    python -m scripts.fix_imported_conversations           # só mostra o que faria
    python -m scripts.fix_imported_conversations --aplicar # grava
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.models.models import Conversation, Message, ConversationStatus
from app.services.whatsapp_sync_service import IMPORT_OPEN_WINDOW_HOURS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("fix_imported_conversations")

DIAS_ATRAS = 3


async def main(aplicar: bool):
    agora = datetime.utcnow()
    corte_aberta = agora - timedelta(hours=IMPORT_OPEN_WINDOW_HOURS)
    ajustadas = encerradas = puladas = 0

    async with AsyncSessionLocal() as db:
        convs = (await db.execute(select(Conversation).where(
            Conversation.criado_em >= agora - timedelta(days=DIAS_ATRAS),
            Conversation.protocol_number.is_(None),
            Conversation.status == ConversationStatus.COM_HUMANO,
        ))).scalars().all()

        for conv in convs:
            if not (conv.dados_adicionais or {}).get("is_migrated"):
                continue

            # Mensagem nova depois da criação = alguém mexeu nela de verdade, não é só importação.
            # (1 min de folga: a importação grava as mensagens logo depois de criar a conversa.)
            mexida = (await db.execute(select(func.count(Message.id)).where(
                Message.conversation_id == conv.id,
                Message.timestamp > conv.criado_em + timedelta(minutes=1),
            ))).scalar()
            if mexida:
                puladas += 1
                continue

            ultima = (await db.execute(select(func.max(Message.timestamp)).where(
                Message.conversation_id == conv.id,
            ))).scalar()
            if ultima:
                conv.ultima_interacao_em = ultima
            fechar = not ultima or ultima < corte_aberta
            if fechar:
                conv.status = ConversationStatus.ENCERRADA
                encerradas += 1
            ajustadas += 1
            logger.info(f"Conversa #{conv.id}: horário -> {ultima}{' | encerrada' if fechar else ''}")

        if aplicar:
            await db.commit()
        else:
            await db.rollback()

    logger.info(
        f"{'APLICADO' if aplicar else 'SIMULAÇÃO (nada gravado, rode com --aplicar)'}: "
        f"{ajustadas} conversas ajustadas, {encerradas} encerradas, {puladas} puladas (tiveram movimento depois da importação)."
    )


if __name__ == "__main__":
    asyncio.run(main(aplicar="--aplicar" in sys.argv))
