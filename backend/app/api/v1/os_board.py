"""
Quadro de técnicos (dashboard das O.S. do Softsystem).

O banco do Softsystem só é alcançável de dentro da loja, então quem alimenta este quadro é o vigia
(tools/os_db_watcher): ele envia o resumo de cada O.S. (técnico, cliente, equipamento, data de entrada)
e a linha do tempo de eventos para POST /os-board/sync - só leitura no Softsystem, nada é escrito lá.
O painel lê daqui: GET /os-board/board (quadro geral, todos os usuários) e GET /os-board/technician
(detalhe e auditoria por técnico, só administradores).

Regras combinadas com a loja:
  - "Finalizada" = o evento FINALIZADA (código 7). Todo o resto está "em aberto".
  - O quadro (e o modo TV) mostra só o que está em aberto: as finalizadas ficam para auditoria (detalhe por técnico).
  - O.S. com condição de pagamento preenchida OU com uma venda gerada ("Ver Venda N" na tela da O.S., campo
    CODORCAMENTO) no Softsystem (já efetivadas/devolvidas ao cliente) não entram no quadro - ficam só na auditoria.
  - Um quadro só para as duas empresas (Servweld e Centro-Oeste), com filtro por empresa.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.websockets import manager as ws_manager
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import OsBoardOrder, OsBoardEvent, User, UserRole, WhatsAppNumber
from app.api.v1.os_handler_ingest import verify_os_handler_key

logger = logging.getLogger("os_board")
router = APIRouter(prefix="/os-board", tags=["Quadro de Técnicos"])

EVENTO_FINALIZADA = 7

# Colunas do quadro, na ordem do fluxo da O.S. Cada coluna agrupa códigos de CODTIPOEVENTOOS do Softsystem.
BOARD_STAGES: List[Dict[str, Any]] = [
    {"key": "entrada", "label": "Entrada", "codes": [1]},
    {"key": "avaliacao", "label": "Avaliação", "codes": [2]},
    {"key": "orcamento", "label": "Orçamento enviado", "codes": [3]},
    {"key": "aprovado", "label": "Aprovado", "codes": [15]},
    {"key": "execucao", "label": "Execução", "codes": [4]},
    {"key": "peca", "label": "Aguardando peça", "codes": [8]},
    {"key": "retirada", "label": "Aguardando retirada", "codes": [6]},
    {"key": "sem_reparo", "label": "Sem reparo", "codes": [11, 12, 13, 14, 16]},
]
EVENT_LABELS = {
    1: "Entrada", 2: "Avaliação", 3: "Orçamento enviado", 4: "Execução", 6: "Aguardando retirada",
    7: "Finalizada", 8: "Aguardando peça", 11: "Sem conserto", 12: "Não autorizada", 13: "Sem defeito",
    14: "Desmontado/Sucateado", 15: "Orçamento aprovado", 16: "Orçamento não aprovado",
}
_CODE_TO_STAGE = {code: st["key"] for st in BOARD_STAGES for code in st["codes"]}
NO_TECH_LABEL = "SEM TÉCNICO"


# ---------------------------------------------------------------- ingestão (vigia da loja)

class BoardOrderIn(BaseModel):
    loja: int = 1
    codos: int
    cnpj: Optional[str] = None
    cliente: Optional[str] = None
    tecnico: Optional[str] = None
    tecnico2: Optional[str] = None
    data_entrada: Optional[datetime] = None
    cod_tipo_os: Optional[int] = None
    equipamento: Optional[str] = None
    paga: bool = False
    venda_codigo: Optional[int] = None


class BoardEventIn(BaseModel):
    loja: int = 1
    codos: int
    cod_evento: int
    data: datetime


class BoardSyncIn(BaseModel):
    empresa: str
    orders: List[BoardOrderIn] = []
    events: List[BoardEventIn] = []


async def _tenant_id_for_board(db: AsyncSession) -> int:
    wn = (await db.execute(
        select(WhatsAppNumber).where(WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID)
    )).scalar_one_or_none()
    if not wn:
        raise HTTPException(status_code=500, detail="Instância de Assistência Técnica não configurada no servidor")
    return wn.tenant_id


def _clean(text: Optional[str], limit: int) -> Optional[str]:
    text = (text or "").strip()
    return text[:limit] if text else None


@router.post("/sync", dependencies=[Depends(verify_os_handler_key)])
async def sync_board(payload: BoardSyncIn, db: AsyncSession = Depends(get_db)):
    """Recebe um lote de O.S. e de eventos (idempotente: reenviar o mesmo lote não duplica nada)."""
    if payload.empresa not in ("servweld", "centrooeste"):
        raise HTTPException(status_code=422, detail="empresa inválida")
    tenant_id = await _tenant_id_for_board(db)
    empresa = payload.empresa

    touched = {(o.loja, o.codos) for o in payload.orders} | {(e.loja, e.codos) for e in payload.events}
    if not touched:
        return {"status": "ok", "orders": 0, "events": 0}
    codos_list = sorted({c for _, c in touched})

    # ---- O.S. existentes deste lote
    existing_orders: Dict[tuple, OsBoardOrder] = {}
    for i in range(0, len(codos_list), 500):
        chunk = codos_list[i:i + 500]
        rows = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.empresa == empresa, OsBoardOrder.codos.in_(chunk)
        ))).scalars().all()
        for r in rows:
            existing_orders[(r.loja, r.codos)] = r

    now = datetime.utcnow()
    for o in payload.orders:
        row = existing_orders.get((o.loja, o.codos))
        if row is None:
            row = OsBoardOrder(tenant_id=tenant_id, empresa=empresa, loja=o.loja, codos=o.codos)
            db.add(row)
            existing_orders[(o.loja, o.codos)] = row
        row.cnpj = _clean(o.cnpj, 20)
        row.cliente = _clean(o.cliente, 255)
        row.tecnico = (_clean(o.tecnico, 80) or "").upper() or None
        row.tecnico2 = (_clean(o.tecnico2, 80) or "").upper() or None
        row.data_entrada = o.data_entrada
        row.cod_tipo_os = o.cod_tipo_os
        row.equipamento = _clean(o.equipamento, 255)
        row.paga = bool(o.paga)
        row.venda_codigo = o.venda_codigo
        row.atualizado_em = now

    # ---- eventos (só insere os que ainda não existem)
    existing_events = set()
    for i in range(0, len(codos_list), 500):
        chunk = codos_list[i:i + 500]
        rows = (await db.execute(select(
            OsBoardEvent.loja, OsBoardEvent.codos, OsBoardEvent.cod_evento, OsBoardEvent.data
        ).where(
            OsBoardEvent.tenant_id == tenant_id, OsBoardEvent.empresa == empresa, OsBoardEvent.codos.in_(chunk)
        ))).all()
        existing_events.update((r[0], r[1], r[2], r[3]) for r in rows)
    new_events = 0
    for e in payload.events:
        key = (e.loja, e.codos, e.cod_evento, e.data)
        if key in existing_events:
            continue
        existing_events.add(key)
        db.add(OsBoardEvent(tenant_id=tenant_id, empresa=empresa, loja=e.loja, codos=e.codos, cod_evento=e.cod_evento, data=e.data))
        new_events += 1
    await db.flush()

    # ---- recalcula a situação (último evento) de cada O.S. tocada
    latest: Dict[tuple, tuple] = {}
    finalizada: Dict[tuple, datetime] = {}
    for i in range(0, len(codos_list), 500):
        chunk = codos_list[i:i + 500]
        rows = (await db.execute(select(
            OsBoardEvent.loja, OsBoardEvent.codos, OsBoardEvent.cod_evento, OsBoardEvent.data
        ).where(
            OsBoardEvent.tenant_id == tenant_id, OsBoardEvent.empresa == empresa, OsBoardEvent.codos.in_(chunk)
        ))).all()
        for loja, codos, cod, data in rows:
            k = (loja, codos)
            if k not in latest or data >= latest[k][1]:
                latest[k] = (cod, data)
            if cod == EVENTO_FINALIZADA and (k not in finalizada or data > finalizada[k]):
                finalizada[k] = data
    for k, row in existing_orders.items():
        if k in latest:
            row.situacao_evento, row.ultimo_evento_em = latest[k]
        row.finalizada_em = finalizada.get(k)
    await db.commit()

    # Avisa os painéis abertos (o quadro se atualiza sozinho). Em carga grande não vale avisar lote a lote.
    if len(touched) <= 100:
        try:
            await ws_manager.broadcast_to_tenant(tenant_id, {"type": "OS_BOARD_UPDATE", "empresa": empresa})
        except Exception as err:
            logger.debug(f"[OS BOARD] broadcast falhou: {err}")
    return {"status": "ok", "orders": len(payload.orders), "events": new_events}


# ---------------------------------------------------------------- leitura (painel)

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _stage_of(order: OsBoardOrder) -> str:
    if order.situacao_evento == EVENTO_FINALIZADA:
        return "finalizada"
    return _CODE_TO_STAGE.get(order.situacao_evento or 1, "entrada")


def _efetivada(order: OsBoardOrder) -> bool:
    return bool(order.paga or order.venda_codigo)


def _efetivada_motivo(order: OsBoardOrder) -> Optional[str]:
    if order.venda_codigo:
        return f"Venda #{order.venda_codigo}"
    if order.paga:
        return "Pagamento já lançado"
    return None


def _card(order: OsBoardOrder, now: datetime) -> Dict[str, Any]:
    ref = order.ultimo_evento_em or order.data_entrada
    return {
        "codos": order.codos,
        "empresa": order.empresa,
        "cliente": order.cliente,
        "equipamento": order.equipamento,
        "tecnico2": order.tecnico2,
        "data_entrada": _iso(order.data_entrada),
        "ultimo_evento_em": _iso(order.ultimo_evento_em),
        "dias_no_estagio": max(0, (now - ref).days) if ref else None,
        "dias_desde_entrada": max(0, (now - order.data_entrada).days) if order.data_entrada else None,
    }


def _empresa_filter(empresa: Optional[str]):
    return [OsBoardOrder.empresa == empresa] if empresa in ("servweld", "centrooeste") else []


@router.get("/board")
async def get_board(
    empresa: Optional[str] = Query(None, description="servweld | centrooeste | (vazio = as duas)"),
    days_open: int = Query(120, ge=1, le=1500, description="O.S. em aberto com atividade nos últimos N dias"),
    cards_per_cell: int = Query(6, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Quadro geral: uma linha por técnico, uma coluna por estágio. Aberto a todos os usuários."""
    now = datetime.now()  # os horários do Softsystem são de Brasília (relógio da máquina)
    since_open = now - timedelta(days=days_open)

    stmt = select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == current_user.tenant_id,
        *_empresa_filter(empresa),
        OsBoardOrder.paga.is_(False),
        OsBoardOrder.venda_codigo.is_(None),
        or_(OsBoardOrder.situacao_evento.is_(None), OsBoardOrder.situacao_evento != EVENTO_FINALIZADA),
        or_(OsBoardOrder.ultimo_evento_em >= since_open, OsBoardOrder.data_entrada >= since_open)
    ).order_by(OsBoardOrder.data_entrada.desc())
    orders = (await db.execute(stmt)).scalars().all()

    rows: Dict[str, Dict[str, Any]] = {}
    totals = {st["key"]: 0 for st in BOARD_STAGES}
    for o in orders:
        name = o.tecnico or NO_TECH_LABEL
        row = rows.setdefault(name, {
            "name": name,
            "total_open": 0,
            "cells": {st["key"]: {"count": 0, "cards": []} for st in BOARD_STAGES},
        })
        stage = _stage_of(o)
        cell = row["cells"][stage]
        cell["count"] += 1
        totals[stage] += 1
        row["total_open"] += 1
        if len(cell["cards"]) < cards_per_cell:
            cell["cards"].append(_card(o, now))

    technicians = sorted(rows.values(), key=lambda r: (r["name"] == NO_TECH_LABEL, -r["total_open"], r["name"]))
    return {
        "stages": [{"key": s["key"], "label": s["label"]} for s in BOARD_STAGES],
        "technicians": technicians,
        "totals": totals,
        "total_open": sum(totals.values()),
        "generated_at": now.isoformat(),
    }


@router.get("/technician")
async def get_technician_detail(
    name: str = Query(..., description="Nome do técnico como está no Softsystem (ex.: JUNIOR)"),
    empresa: Optional[str] = None,
    start: Optional[datetime] = Query(None, description="Início do período"),
    end: Optional[datetime] = Query(None, description="Fim do período"),
    status: str = Query("trabalhou", description="trabalhou | entrada | finalizadas | abertas | efetivadas | todas"),
    limit: int = Query(300, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Detalhe e auditoria de um técnico (só administradores): O.S. dele no período, com a linha do tempo."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Somente administradores podem ver o detalhe por técnico")
    tech = name.strip().upper()
    end_dt = end or datetime.now()
    start_dt = start or (end_dt - timedelta(days=30))

    tech_filter = (
        [OsBoardOrder.tecnico.is_(None)] if tech == NO_TECH_LABEL
        else [or_(OsBoardOrder.tecnico == tech, OsBoardOrder.tecnico2 == tech)]
    )
    orders = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == current_user.tenant_id, *_empresa_filter(empresa), *tech_filter
    ))).scalars().all()
    if not orders:
        return {"name": tech, "summary": {"abertas_agora": 0, "entradas_no_periodo": 0, "finalizadas_no_periodo": 0,
                                          "trabalhou_no_periodo": 0, "efetivadas_no_periodo": 0}, "orders": [], "truncated": False}

    # eventos de todas as O.S. do técnico (para a linha do tempo e para "trabalhou no período")
    keys = {(o.empresa, o.loja, o.codos) for o in orders}
    codos_all = sorted({o.codos for o in orders})
    events_by_order: Dict[tuple, List[OsBoardEvent]] = {}
    for i in range(0, len(codos_all), 500):
        chunk = codos_all[i:i + 500]
        evs = (await db.execute(select(OsBoardEvent).where(
            OsBoardEvent.tenant_id == current_user.tenant_id, OsBoardEvent.codos.in_(chunk)
        ).order_by(OsBoardEvent.data.asc()))).scalars().all()
        for ev in evs:
            k = (ev.empresa, ev.loja, ev.codos)
            if k in keys:
                events_by_order.setdefault(k, []).append(ev)

    def in_period(dt: Optional[datetime]) -> bool:
        return bool(dt and start_dt <= dt <= end_dt)

    summary = {"abertas_agora": 0, "entradas_no_periodo": 0, "finalizadas_no_periodo": 0, "trabalhou_no_periodo": 0, "efetivadas_no_periodo": 0}
    result = []
    for o in orders:
        evs = events_by_order.get((o.empresa, o.loja, o.codos), [])
        is_open = o.situacao_evento != EVENTO_FINALIZADA and not _efetivada(o)
        entered = in_period(o.data_entrada)
        finished = in_period(o.finalizada_em)
        worked = any(in_period(e.data) for e in evs) or entered
        if is_open:
            summary["abertas_agora"] += 1
        summary["entradas_no_periodo"] += 1 if entered else 0
        summary["finalizadas_no_periodo"] += 1 if finished else 0
        summary["trabalhou_no_periodo"] += 1 if worked else 0
        summary["efetivadas_no_periodo"] += 1 if (_efetivada(o) and worked) else 0

        include = {
            "trabalhou": worked, "entrada": entered, "finalizadas": finished,
            "abertas": is_open and not _efetivada(o), "efetivadas": _efetivada(o), "todas": True,
        }.get(status, worked)
        if not include:
            continue
        result.append({
            "codos": o.codos,
            "empresa": o.empresa,
            "cliente": o.cliente,
            "equipamento": o.equipamento,
            "tecnico": o.tecnico,
            "tecnico2": o.tecnico2,
            "data_entrada": _iso(o.data_entrada),
            "situacao": EVENT_LABELS.get(o.situacao_evento or 0, "—"),
            "stage": _stage_of(o),
            "finalizada_em": _iso(o.finalizada_em),
            "aberta": is_open and not _efetivada(o),
            "paga": bool(o.paga),
            "venda_codigo": o.venda_codigo,
            "efetivada_motivo": _efetivada_motivo(o),
            "timeline": [{"evento": EVENT_LABELS.get(e.cod_evento, str(e.cod_evento)), "cod": e.cod_evento, "data": _iso(e.data)} for e in evs],
        })

    result.sort(key=lambda r: r["data_entrada"] or "", reverse=True)
    truncated = len(result) > limit
    return {"name": tech, "start": _iso(start_dt), "end": _iso(end_dt), "summary": summary, "orders": result[:limit], "truncated": truncated}


@router.get("/technicians")
async def list_technicians(
    empresa: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Nomes de técnicos que aparecem nas O.S. (para os filtros)."""
    rows = (await db.execute(
        select(OsBoardOrder.tecnico).where(OsBoardOrder.tenant_id == current_user.tenant_id, *_empresa_filter(empresa)).distinct()
    )).all()
    return sorted({r[0] for r in rows if r[0]})
