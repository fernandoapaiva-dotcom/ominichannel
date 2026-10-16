"""
Interação interna na O.S. (técnico <-> escritório), estilo "Interagir na Ordem de Serviço" do
Telecontrol - pedido do usuário em 14/10/2026. Ver OsInteraction (models.py) pro significado de
cada tipo. Usado pelos dois lados com o mesmo formato: quadro administrativo (os_board.py,
autor_tipo="admin") e Portal do Técnico (technician_portal.py, autor_tipo="tecnico").
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import OsBoardOrder, OsInteraction

logger = logging.getLogger("os_interaction")

TIPOS_VALIDOS = {"observacao", "pendencia", "resolucao"}


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() + "Z" if dt else None


def _serialize(i: OsInteraction) -> Dict[str, Any]:
    return {
        "id": i.id, "tipo": i.tipo, "mensagem": i.mensagem, "autor": i.autor, "autor_tipo": i.autor_tipo,
        "criado_em": _iso(i.criado_em), "lido_em": _iso(i.lido_em), "lido_por": i.lido_por,
        "resolved_at": _iso(i.resolved_at), "resolved_by": i.resolved_by,
    }


async def _get_order(db: AsyncSession, tenant_id: int, codos: int) -> OsBoardOrder:
    order = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
    ))).scalars().first()
    if not order:
        raise ValueError(f"O.S. #{codos} não encontrada no quadro")
    return order


async def list_interactions(db: AsyncSession, tenant_id: int, codos: int, viewer_tipo: str, viewer_nome: str) -> List[Dict[str, Any]]:
    """Histórico completo da O.S. (mais antiga primeiro). Abrir = ler: marca como lidas as
    mensagens do OUTRO lado que ainda não tinham sido lidas (leitura confirmada)."""
    order = await _get_order(db, tenant_id, codos)
    rows = (await db.execute(select(OsInteraction).where(
        OsInteraction.tenant_id == tenant_id, OsInteraction.empresa == order.empresa,
        OsInteraction.loja == order.loja, OsInteraction.codos == codos,
    ).order_by(OsInteraction.criado_em.asc(), OsInteraction.id.asc()))).scalars().all()

    now = datetime.utcnow()
    changed = False
    for r in rows:
        if r.autor_tipo != viewer_tipo and r.lido_em is None:
            r.lido_em = now
            r.lido_por = viewer_nome
            changed = True
    if changed:
        await db.commit()
    return [_serialize(r) for r in rows]


async def create_interaction(db: AsyncSession, tenant_id: int, codos: int, tipo: str, mensagem: str, autor: str, autor_tipo: str) -> Dict[str, Any]:
    if tipo not in TIPOS_VALIDOS:
        raise ValueError("Tipo de interação inválido")
    mensagem = (mensagem or "").strip()
    if tipo == "resolucao" and not mensagem:
        mensagem = "Pendência resolvida."
    if not mensagem:
        raise ValueError("Mensagem não pode ser vazia")

    order = await _get_order(db, tenant_id, codos)
    now = datetime.utcnow()
    row = OsInteraction(
        tenant_id=tenant_id, empresa=order.empresa, loja=order.loja, codos=codos,
        tipo=tipo, mensagem=mensagem, autor=autor, autor_tipo=autor_tipo, criado_em=now,
    )
    db.add(row)

    if tipo == "resolucao":
        abertas = (await db.execute(select(OsInteraction).where(
            OsInteraction.tenant_id == tenant_id, OsInteraction.empresa == order.empresa,
            OsInteraction.loja == order.loja, OsInteraction.codos == codos,
            OsInteraction.tipo == "pendencia", OsInteraction.resolved_at.is_(None),
        ))).scalars().all()
        if not abertas:
            raise ValueError("Não há pendência aberta nesta O.S.")
        for p in abertas:
            p.resolved_at = now
            p.resolved_by = autor

    await db.commit()
    await db.refresh(row)
    return _serialize(row)


async def open_pendencias_by_order(db: AsyncSession, tenant_id: int) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """Pendência aberta mais recente de cada O.S. do tenant - alimenta o alerta (!) nos cartões
    do quadro. Uma consulta só pro quadro inteiro (são poucas linhas abertas por vez)."""
    rows = (await db.execute(select(OsInteraction).where(
        OsInteraction.tenant_id == tenant_id, OsInteraction.tipo == "pendencia",
        OsInteraction.resolved_at.is_(None),
    ).order_by(OsInteraction.criado_em.asc()))).scalars().all()
    result: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in rows:
        # ordem crescente: a última gravada por O.S. é a mais recente
        result[(r.empresa, r.codos)] = {"mensagem": r.mensagem, "autor": r.autor, "criado_em": _iso(r.criado_em)}
    return result
