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
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.websockets import manager as ws_manager
from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import OsBoardOrder, OsBoardEvent, User, UserRole, WhatsAppNumber
from app.api.v1.os_handler_ingest import verify_os_handler_key, TIPO_OS_LABEL

logger = logging.getLogger("os_board")
router = APIRouter(prefix="/os-board", tags=["Quadro de Técnicos"])

EVENTO_FINALIZADA = 7

# Colunas do quadro, na ordem do fluxo da O.S. Cada coluna agrupa códigos de CODTIPOEVENTOOS do Softsystem.
# "aprovado"/"nao_aprovado" e "descarte" também recebem eventos gravados pelo PRÓPRIO backend (ver
# record_board_event), não só pelo vigia - respectivamente quando o cliente responde no WhatsApp, e
# quando o prazo de 90 dias de "Aguardando retirada" se esgota (ver os_board_followup_service).
EVENTO_APROVADO = 15
EVENTO_NAO_APROVADO = 16
EVENTO_DESCARTE = 14
EVENTO_ORCAMENTO_ENVIADO = 3
EVENTO_RETIRADA = 6
BOARD_STAGES: List[Dict[str, Any]] = [
    {"key": "entrada", "label": "Entrada", "codes": [1]},
    {"key": "avaliacao", "label": "Avaliação", "codes": [2]},
    {"key": "orcamento", "label": "Orçamento enviado", "codes": [EVENTO_ORCAMENTO_ENVIADO]},
    {"key": "aprovado", "label": "Aprovado", "codes": [EVENTO_APROVADO]},
    {"key": "nao_aprovado", "label": "Não aprovado", "codes": [EVENTO_NAO_APROVADO]},
    {"key": "execucao", "label": "Execução", "codes": [4]},
    {"key": "peca", "label": "Aguardando peça", "codes": [8]},
    {"key": "retirada", "label": "Aguardando retirada", "codes": [EVENTO_RETIRADA]},
    {"key": "sem_reparo", "label": "Sem reparo", "codes": [11, 12, 13]},
    {"key": "descarte", "label": "Desmanche e Descarte", "codes": [EVENTO_DESCARTE]},
]
EVENT_LABELS = {
    1: "Entrada", 2: "Avaliação", 3: "Orçamento enviado", 4: "Execução", 6: "Aguardando retirada",
    7: "Finalizada", 8: "Aguardando peça", 11: "Sem conserto", 12: "Não autorizada", 13: "Sem defeito",
    14: "Desmontado/Sucateado", 15: "Orçamento aprovado", 16: "Orçamento não aprovado",
}
_CODE_TO_STAGE = {code: st["key"] for st in BOARD_STAGES for code in st["codes"]}
NO_TECH_LABEL = "SEM TÉCNICO"
RETIRADA_PRAZO_DIAS = 90
EMPRESA_LABEL_PT = {"servweld": "Servweld", "centrooeste": "Centro-Oeste"}


def titleCase_pt(s: str) -> str:
    return s.lower().title() if s else s


def now_brt() -> datetime:
    """
    'Agora' no horário de Brasília, sem fuso (naive) - para comparar com os horários que vêm do
    Softsystem (relógio do computador da loja, sempre Brasília). O servidor roda em UTC, então
    datetime.now() do processo NÃO é Brasília - teria de ser convertido, e datetime.utcnow() já é
    UTC por definição, então só falta subtrair as 3 horas (mesma convenção usada em
    calendar_reminder_service.py para o mesmo motivo).
    """
    return datetime.utcnow() - timedelta(hours=3)


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
    telefone: Optional[str] = None
    contato_nome: Optional[str] = None
    valor_total: Optional[float] = None
    forma_pagamento: Optional[str] = None


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
        if o.telefone:
            row.telefone = _clean(o.telefone, 20)
        if o.contato_nome:
            row.contato_nome = _clean(o.contato_nome, 120)
        row.valor_total = o.valor_total
        row.forma_pagamento = _clean(o.forma_pagamento, 60)
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
            novo_evento, novo_quando = latest[k]
            if novo_evento != row.situacao_evento:
                row.last_nudge_at = None  # etapa mudou - a contagem de 2 em 2 dias da cobrança recomeça
            row.situacao_evento, row.ultimo_evento_em = novo_evento, novo_quando
        row.finalizada_em = finalizada.get(k)
    await db.commit()

    # Avisa os painéis abertos (o quadro se atualiza sozinho). Em carga grande não vale avisar lote a lote.
    if len(touched) <= 100:
        try:
            await ws_manager.broadcast_to_tenant(tenant_id, {"type": "OS_BOARD_UPDATE", "empresa": empresa})
        except Exception as err:
            logger.debug(f"[OS BOARD] broadcast falhou: {err}")
    return {"status": "ok", "orders": len(payload.orders), "events": new_events}


async def record_board_event(db: AsyncSession, tenant_id: int, codos: int, cod_evento: int, when: Optional[datetime] = None) -> bool:
    """
    Grava, DIRETO do backend (sem passar pelo vigia/Softsystem), um evento que o próprio sistema decidiu:
    aprovação/recusa do orçamento respondida no WhatsApp (webhooks.py) e descarte automático por prazo
    vencido (os_board_followup_service). Atualiza o espelho na hora, em vez de esperar alguém lançar o
    mesmo evento no Softsystem depois - é só o card do quadro mudando de coluna; não escreve nada real
    no Softsystem. Localiza a O.S. por tenant+codos (pode achar mais de uma linha só em teoria, se algum
    dia um código de O.S. colidir entre as duas empresas). Não faz nada se a O.S. não estiver no espelho.
    """
    when = when or now_brt()
    rows = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
    ))).scalars().all()
    if not rows:
        return False
    for row in rows:
        exists = (await db.execute(select(OsBoardEvent.id).where(
            OsBoardEvent.tenant_id == tenant_id, OsBoardEvent.empresa == row.empresa, OsBoardEvent.loja == row.loja,
            OsBoardEvent.codos == codos, OsBoardEvent.cod_evento == cod_evento, OsBoardEvent.data == when
        ))).scalar_one_or_none()
        if not exists:
            db.add(OsBoardEvent(tenant_id=tenant_id, empresa=row.empresa, loja=row.loja, codos=codos, cod_evento=cod_evento, data=when))
        if cod_evento != row.situacao_evento:
            row.last_nudge_at = None
        row.situacao_evento = cod_evento
        row.ultimo_evento_em = when
        if cod_evento == EVENTO_FINALIZADA:
            row.finalizada_em = when
        row.atualizado_em = datetime.utcnow()
    await db.commit()
    try:
        await ws_manager.broadcast_to_tenant(tenant_id, {"type": "OS_BOARD_UPDATE", "empresa": rows[0].empresa})
    except Exception as err:
        logger.debug(f"[OS BOARD] broadcast falhou: {err}")
    return True


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
        "cod_tipo_os": order.cod_tipo_os,
        "tipo_os": TIPO_OS_LABEL.get(order.cod_tipo_os, None),
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
    cards_per_cell: int = Query(6, ge=1, le=120),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Quadro geral: uma linha por técnico, uma coluna por estágio. Aberto a todos os usuários."""
    now = now_brt()
    since_open = now - timedelta(days=days_open)

    stmt = select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == current_user.tenant_id,
        *_empresa_filter(empresa),
        OsBoardOrder.paga.is_(False),
        OsBoardOrder.venda_codigo.is_(None),
        or_(OsBoardOrder.situacao_evento.is_(None), OsBoardOrder.situacao_evento != EVENTO_FINALIZADA),
        # "atividade recente" também conta uma O.S. antiga que foi reaberta/editada no Softsystem agora
        # (o vigia só re-sincroniza o que muda - ver DATAALTERACAO em sync_board_empresa) - salvar de novo
        # uma O.S. de mais de 3 meses faz ela reaparecer no quadro, mesmo com entrada/evento antigos.
        or_(
            OsBoardOrder.ultimo_evento_em >= since_open,
            OsBoardOrder.data_entrada >= since_open,
            OsBoardOrder.atualizado_em >= since_open,
        )
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


@router.get("/cell")
async def get_board_cell(
    tecnico: str = Query(..., description="Nome do técnico como está no Softsystem, ou 'SEM TÉCNICO'"),
    stage: str = Query(..., description="Chave do estágio (ver GET /board -> stages[].key)"),
    empresa: Optional[str] = None,
    days_open: int = Query(120, ge=1, le=1500, description="Mesmo filtro de atividade recente do quadro geral"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lista completa de uma célula do quadro (técnico x estágio) - abre com o botão '+N O.S.' do cartão."""
    stage_def = next((s for s in BOARD_STAGES if s["key"] == stage), None)
    if not stage_def:
        raise HTTPException(status_code=422, detail="Estágio inválido")
    tech = tecnico.strip().upper()
    tech_filter = [OsBoardOrder.tecnico.is_(None)] if tech == NO_TECH_LABEL else [OsBoardOrder.tecnico == tech]

    situacao_condition = OsBoardOrder.situacao_evento.in_(stage_def["codes"])
    if 1 in stage_def["codes"]:  # "Entrada": situacao_evento ainda nulo (nenhum evento chegou) também conta
        situacao_condition = or_(situacao_condition, OsBoardOrder.situacao_evento.is_(None))

    now = now_brt()
    since_open = now - timedelta(days=days_open)
    orders = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == current_user.tenant_id, *_empresa_filter(empresa), *tech_filter,
        situacao_condition, OsBoardOrder.paga.is_(False), OsBoardOrder.venda_codigo.is_(None),
        or_(
            OsBoardOrder.ultimo_evento_em >= since_open,
            OsBoardOrder.data_entrada >= since_open,
            OsBoardOrder.atualizado_em >= since_open,
        ),
    ).order_by(OsBoardOrder.data_entrada.desc()))).scalars().all()

    return {"tecnico": tech, "stage": stage, "label": stage_def["label"], "cards": [_card(o, now) for o in orders]}


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
    end_dt = end or now_brt()
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
        efetivada = _efetivada(o)
        is_open = o.situacao_evento != EVENTO_FINALIZADA and not efetivada
        entered = in_period(o.data_entrada)
        # "finalizada" = tem o evento oficial (finalizada_em) OU já está efetivada (paga/venda
        # vinculada) mas o Softsystem nunca lançou o evento 7 pra essa O.S. - achado em produção em
        # 24/09/2026 (O.S. #1729: só tinha o evento ENTRADA, mas já tinha "Ver Venda #6041" e
        # Status Finalizada). Sem uma data própria de "quando foi efetivada" vinda do Softsystem,
        # usa a data de entrada como referência nesse segundo caso - melhor que nunca aparecer em
        # lugar nenhum do relatório (nem aberta, nem finalizada).
        efetivada_sem_evento = efetivada and not o.finalizada_em
        finished = in_period(o.finalizada_em) or (efetivada_sem_evento and entered)
        worked = any(in_period(e.data) for e in evs) or entered
        if is_open:
            summary["abertas_agora"] += 1
        summary["entradas_no_periodo"] += 1 if entered else 0
        summary["finalizadas_no_periodo"] += 1 if finished else 0
        summary["trabalhou_no_periodo"] += 1 if worked else 0
        summary["efetivadas_no_periodo"] += 1 if (efetivada and worked) else 0

        include = {
            # "entrada" é usado como lista de pendência ("o que ainda falta olhar"), não histórico -
            # uma O.S. que entrou no período mas já foi finalizada/efetivada (Venda vinculada/paga)
            # não deve continuar aparecendo aqui, mesmo que o único evento registrado seja ENTRADA.
            "trabalhou": worked, "entrada": entered and is_open, "finalizadas": finished,
            # "efetivadas" batendo com o mesmo critério period-bound do resumo (efetivadas_no_periodo)
            # acima - antes mostrava TODAS as O.S. efetivadas do técnico, sem respeitar o período
            # escolhido, o que fazia a lista não bater com o número do resumo.
            "abertas": is_open, "efetivadas": efetivada and worked, "todas": True,
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
            "tipo_os": TIPO_OS_LABEL.get(o.cod_tipo_os, None),
            "situacao": EVENT_LABELS.get(o.situacao_evento or 0, "—"),
            "stage": _stage_of(o),
            "finalizada_em": _iso(o.finalizada_em),
            "aberta": is_open,
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


# Estágios do relatório: os mesmos do quadro + Finalizada (que o quadro ao vivo esconde, mas o
# relatório precisa mostrar, já que "finalizadas" é um dos números pedidos).
REPORT_STAGE_LABELS: Dict[str, str] = {**{s["key"]: s["label"] for s in BOARD_STAGES}, "finalizada": "Finalizada"}


@router.get("/report.pdf")
async def get_report_pdf(
    tecnico: Optional[str] = Query(None, description="Nome do técnico, ou vazio/'todos' para todos"),
    evento: Optional[str] = Query(None, description="Chave do estágio (ver stages[].key), ou vazio/'todos' para todos"),
    empresa: Optional[str] = None,
    start: Optional[datetime] = Query(None, description="Entrada a partir de (vazio = sem início)"),
    end: Optional[datetime] = Query(None, description="Entrada até (vazio = até hoje)"),
    status: str = Query("todas", description="todas | abertas | finalizadas | efetivadas"),
    incluir_lista: bool = Query(True, description="Inclui a lista detalhada de O.S. no fim do PDF (só no modo completo)"),
    modo: str = Query("completo", description="completo (KPIs/financeiro/ranking) | lista (só a lista de O.S., pra entregar pro técnico)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Relatório em PDF: produtividade por técnico/evento, financeiro e forma de pagamento (modo completo),
    ou só a lista de O.S. do filtro, sem os números de gestão - pra imprimir/entregar pro técnico como
    lista de tarefas (modo lista). O modo completo (números financeiros/ranking) continua só pra
    administradores; a lista simples (sem nada financeiro) qualquer atendente pode gerar."""
    modo_norm = "lista" if (modo or "").strip().lower() == "lista" else "completo"
    if modo_norm == "completo" and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Somente administradores podem emitir o relatório completo")

    from app.services.os_board_report_service import build_os_report_pdf

    tech = (tecnico or "").strip().upper()
    ev = (evento or "").strip().lower()
    if ev and ev != "todos" and ev not in REPORT_STAGE_LABELS:
        raise HTTPException(status_code=422, detail="Estágio inválido")

    now = now_brt()
    end_dt = end or now
    start_dt = start  # sem piso por padrão: o relatório é sobre um universo de O.S., não só "recentes"

    filters = [OsBoardOrder.tenant_id == current_user.tenant_id, *_empresa_filter(empresa)]
    if tech and tech != "TODOS":
        filters.append(OsBoardOrder.tecnico.is_(None) if tech == NO_TECH_LABEL else or_(OsBoardOrder.tecnico == tech, OsBoardOrder.tecnico2 == tech))
    if start_dt:
        filters.append(OsBoardOrder.data_entrada >= start_dt)
    filters.append(OsBoardOrder.data_entrada <= end_dt)

    rows = (await db.execute(select(OsBoardOrder).where(*filters).order_by(OsBoardOrder.data_entrada.desc()))).scalars().all()

    # Decisão do orçamento na HISTÓRIA da O.S. (chegou a ser aprovada/recusada em algum momento), separado
    # do estágio ATUAL - uma O.S. aprovada e já finalizada não deve sumir da taxa de aprovação.
    codos_list = sorted({o.codos for o in rows})
    decisao_por_codos: Dict[int, str] = {}
    for i in range(0, len(codos_list), 500):
        chunk = codos_list[i:i + 500]
        ev_rows = (await db.execute(select(OsBoardEvent.codos, OsBoardEvent.cod_evento).where(
            OsBoardEvent.tenant_id == current_user.tenant_id, OsBoardEvent.codos.in_(chunk),
            OsBoardEvent.cod_evento.in_([EVENTO_APROVADO, EVENTO_NAO_APROVADO])
        ).order_by(OsBoardEvent.data.asc()))).all()
        for codos_, cod in ev_rows:
            decisao_por_codos[codos_] = "aprovado" if cod == EVENTO_APROVADO else "nao_aprovado"

    def row_stage(o: OsBoardOrder) -> str:
        if o.situacao_evento == EVENTO_FINALIZADA:
            return "finalizada"
        return _CODE_TO_STAGE.get(o.situacao_evento or 1, "entrada")

    report_rows = []
    for o in rows:
        stage = row_stage(o)
        if ev and ev != "todos" and stage != ev:
            continue
        is_open = o.situacao_evento != EVENTO_FINALIZADA and not _efetivada(o)
        if status == "abertas" and not is_open:
            continue
        if status == "finalizadas" and stage != "finalizada":
            continue
        if status == "efetivadas" and not _efetivada(o):
            continue
        report_rows.append({
            "codos": o.codos, "empresa": o.empresa, "cliente": o.cliente, "equipamento": o.equipamento,
            "tecnico_label": o.tecnico or NO_TECH_LABEL, "tecnico2_label": o.tecnico2 or None,
            "cod_tipo_os": o.cod_tipo_os, "tipo_os": TIPO_OS_LABEL.get(o.cod_tipo_os, None),
            "stage": stage, "situacao": EVENT_LABELS.get(o.situacao_evento or 0, "Entrada"),
            "data_entrada": o.data_entrada, "finalizada_em": o.finalizada_em,
            "aberta": is_open, "efetivada_motivo": _efetivada_motivo(o),
            "valor_total": o.valor_total, "forma_pagamento": o.forma_pagamento,
            "decisao": decisao_por_codos.get(o.codos),
        })

    if not report_rows:
        raise HTTPException(status_code=404, detail="Nenhuma O.S. encontrada para esses filtros")

    filtros_txt = {
        "Empresa": EMPRESA_LABEL_PT.get(empresa, "Todas") if empresa else "Todas",
        "Técnico": titleCase_pt(tech) if tech and tech != "TODOS" else "Todos",
        "Evento": REPORT_STAGE_LABELS.get(ev, "Todos") if ev and ev != "todos" else "Todos",
        "Status": {"todas": "Todas", "abertas": "Em aberto", "finalizadas": "Finalizadas", "efetivadas": "Efetivadas"}.get(status, status),
        "Período": f"{start_dt.strftime('%d/%m/%Y') if start_dt else 'início'} a {end_dt.strftime('%d/%m/%Y')}",
    }

    pdf_bytes = build_os_report_pdf(
        orders=report_rows, stage_labels=REPORT_STAGE_LABELS, event_labels=EVENT_LABELS,
        filtros=filtros_txt, gerado_em=now, incluir_lista=incluir_lista, modo=modo_norm,
    )
    prefixo = "lista-os" if modo_norm == "lista" else "relatorio-quadro-tecnicos"
    filename = f"{prefixo}-{now.strftime('%Y%m%d-%H%M')}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )
