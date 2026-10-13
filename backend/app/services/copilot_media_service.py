"""
Mídia do Copiloto Técnico (áudio, foto e vídeo que o técnico manda da bancada) - 13/10/2026.

Pedido do usuário: "um botão de áudio pra ele mandar áudio e a IA transcrever o que ele falou, e envio
de multimídia pra IA analisar com o técnico e dar sugestões do que ele pode fazer na hora da
manutenção". O arquivo fica guardado no servidor (pasta uploads/copilot) e só é servido pro próprio
técnico, dentro do Copiloto (GET /technician-portal/copilot/media/{id}), nunca como link público.

A tabela fica aqui (e não em models.py) de propósito: é de uso só do Copiloto e é criada sozinha no
boot (create_all) por estar registrada no mesmo Base.
"""
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import AsyncSessionLocal, Base

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "copilot"))

# Limites por tipo (o nginx aceita até 100 MB por envio)
MAX_BYTES = {"audio": 15 * 1024 * 1024, "imagem": 15 * 1024 * 1024, "video": 60 * 1024 * 1024}

EXTENSOES = {
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/ogg": ".ogg", "audio/aac": ".aac", "audio/flac": ".flac", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic", "image/heif": ".heif",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "video/3gpp": ".3gp", "video/mpeg": ".mpeg",
}


class CopilotMessageMedia(Base):
    __tablename__ = "copilot_message_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(Integer, index=True)
    tipo: Mapped[str] = mapped_column(String(10))  # 'audio' | 'imagem' | 'video'
    mimetype: Mapped[str] = mapped_column(String(80))
    caminho: Mapped[str] = mapped_column(String(500))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def tipo_da_midia(mimetype: str) -> Optional[str]:
    m = (mimetype or "").split(";")[0].strip().lower()
    if m.startswith("audio/"):
        return "audio"
    if m.startswith("image/"):
        return "imagem"
    if m.startswith("video/"):
        return "video"
    return None


async def salvar(message_id: int, tipo: str, mimetype: str, dados: bytes) -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    mime = (mimetype or "").split(";")[0].strip().lower()
    caminho = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{EXTENSOES.get(mime, '.bin')}")
    with open(caminho, "wb") as f:
        f.write(dados)
    async with AsyncSessionLocal() as db:
        db.add(CopilotMessageMedia(message_id=message_id, tipo=tipo, mimetype=mime, caminho=caminho))
        await db.commit()
    return caminho


async def tipos_por_mensagem(message_ids: List[int]) -> Dict[int, str]:
    if not message_ids:
        return {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(CopilotMessageMedia.message_id, CopilotMessageMedia.tipo)
                                 .where(CopilotMessageMedia.message_id.in_(message_ids)))).all()
    return {mid: tipo for mid, tipo in rows}


async def da_mensagem(message_id: int) -> Optional[CopilotMessageMedia]:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(CopilotMessageMedia).where(CopilotMessageMedia.message_id == message_id)
                                 .limit(1))).scalars().first()
