"""
Relatório de avisos/cobranças de O.S. por WhatsApp (módulo Relatórios) - pedido do usuário em
14/10/2026: acompanhar o andamento das cobranças de "Aguardando aprovação" (orçamento enviado) e
"Aguardando retirada", no dia ou num período, por cliente, com o sucesso do envio.

Não depende dos fluxos de envio gravarem nada: index_new_messages() lê as mensagens do SISTEMA
já salvas no chat e reconhece, pelo texto, qual aviso é e de qual O.S. (todos os textos levam o
número da O.S.) - ver OsEnvioLog. Roda incremental a cada consulta do relatório, então o
histórico (desde 22/09/2026) e os envios novos entram sozinhos.

Se algum desses textos mudar (automation_service / os_board_followup_service /
os_handler_ingest / os_report_service), o padrão correspondente aqui precisa acompanhar.
"""
import asyncio
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Contact, Conversation, Message, MessageSender, OsBoardOrder, OsEnvioLog

logger = logging.getLogger("os_envio_report")

BRT_OFFSET = timedelta(hours=3)  # mensagens são gravadas em UTC; relatório é em horário de Brasília
RESPOSTA_JANELA = timedelta(hours=72)  # cliente "respondeu" se mandou mensagem até 3 dias depois

# (etapa, tipo, regex com o nº da O.S. no grupo 1)
_PADROES: List[Tuple[str, str, "re.Pattern"]] = [
    ("orcamento", "cobranca", re.compile(r"Só confirmando: você já pôde ver o orçamento da sua Ordem de Serviço \*#(\d+)\*")),
    ("retirada", "cobranca", re.compile(r"Seu equipamento \(O\.S\. \*#(\d+)\*\) já está pronto e à sua espera")),
    ("retirada", "descarte", re.compile(r"para retirada do equipamento da sua Ordem de Serviço \*#(\d+)\* se encerrou")),
    ("retirada", "envio", re.compile(r"O\.S\. #(\d+)\*?\)?[^\n]*?disponível para retirada|disponível para retirada[^\n]*?O\.S\. #(\d+)")),
]
# Envio do orçamento: a pergunta de aprovação não tem o nº da O.S. - ele vem da mensagem logo
# antes na mesma conversa (texto "Ordem de Serviço #N está pronto" ou o PDF "N - Cliente.pdf").
_PROMPT_APROVACAO = "a execução do serviço pelo valor informado no orçamento"
_ANTES_DO_PROMPT = [
    re.compile(r"Ordem de Serviço #(\d+) está pronto"),
    re.compile(r"\|(\d+) - [^|]*\.pdf$"),
]
_PROMPT_LOOKBACK = timedelta(minutes=15)

ETAPA_LABEL = {"orcamento": "Aguardando aprovação", "retirada": "Aguardando retirada"}
TIPO_LABEL = {"envio": "Envio", "cobranca": "Cobrança", "descarte": "Aviso de descarte"}
STATUS_LABEL = {"sent": "Enviada", "delivered": "Entregue", "read": "Lida", "failed": "Falhou", "failed_invalid_number": "Número inválido"}


def _classify(conteudo: str) -> Optional[Tuple[str, str, int]]:
    for etapa, tipo, pat in _PADROES:
        m = pat.search(conteudo or "")
        if m:
            num = next(g for g in m.groups() if g)
            return etapa, tipo, int(num)
    return None


# Duas consultas do relatório ao mesmo tempo indexavam as mesmas mensagens e a segunda batia na
# chave única (UNIQUE os_envio_logs.message_id) - erro 500 visto em produção em 15/10/2026. Uma
# indexação por vez resolve; o except abaixo é a rede de segurança.
_index_lock = asyncio.Lock()


async def index_new_messages(db: AsyncSession, tenant_id: int) -> int:
    """Lê as mensagens do sistema ainda não vistas e registra as que são avisos/cobranças de O.S."""
    async with _index_lock:
        try:
            return await _index_new_messages(db, tenant_id)
        except IntegrityError:
            await db.rollback()
            logger.info("[RELATORIO ENVIOS] Indexação concorrente detectada - mensagens já registradas, seguindo.")
            return 0


async def _index_new_messages(db: AsyncSession, tenant_id: int) -> int:
    ultimo = (await db.execute(select(func.max(OsEnvioLog.message_id)).where(
        OsEnvioLog.tenant_id == tenant_id
    ))).scalar() or 0
    rows = (await db.execute(
        select(Message.id, Message.conversation_id, Message.conteudo, Message.timestamp)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.tenant_id == tenant_id, Message.id > ultimo, Message.remetente == MessageSender.SISTEMA)
        .order_by(Message.id.asc())
    )).all()

    novos = 0
    for msg_id, conv_id, conteudo, ts in rows:
        achado = _classify(conteudo)
        if not achado and _PROMPT_APROVACAO in (conteudo or "") and "da O.S." not in (conteudo or ""):
            anteriores = (await db.execute(
                select(Message.conteudo).where(
                    Message.conversation_id == conv_id, Message.id < msg_id,
                    Message.remetente == MessageSender.SISTEMA, Message.timestamp >= ts - _PROMPT_LOOKBACK,
                ).order_by(Message.id.desc()).limit(4)
            )).scalars().all()
            for anterior in anteriores:
                m = next((p.search(anterior or "") for p in _ANTES_DO_PROMPT if p.search(anterior or "")), None)
                if m:
                    achado = ("orcamento", "envio", int(m.group(1)))
                    break
        if not achado:
            continue
        etapa, tipo, codos = achado
        db.add(OsEnvioLog(
            tenant_id=tenant_id, message_id=msg_id, conversation_id=conv_id,
            codos=codos, etapa=etapa, tipo=tipo, enviado_em=ts,
        ))
        novos += 1
    if novos:
        await db.commit()
        logger.info(f"[RELATORIO ENVIOS] {novos} aviso(s)/cobrança(s) de O.S. indexado(s).")
    return novos


def _digits(s: Optional[str]) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _resultado(etapa: str, o: Optional[OsBoardOrder]) -> str:
    """Onde a O.S. está AGORA, do ponto de vista daquela cobrança."""
    if not o:
        return "—"
    ev = o.situacao_evento
    if o.paga or o.venda_codigo or ev == 7:
        return "Retirado/finalizado" if etapa == "retirada" else "Aprovado (já finalizado)"
    if etapa == "orcamento":
        if ev in (15, 4, 8, 6):
            return "Aprovado"
        if ev in (16, 12):
            return "Recusado"
        if ev == 3:
            return "Aguardando resposta"
    else:
        if ev == 6:
            return "Aguardando retirada"
        if ev == 14:
            return "Desmanche/descarte"
    from app.api.v1.os_board import EVENT_LABELS
    return EVENT_LABELS.get(ev or 0, "—")


async def build_report(
    db: AsyncSession, tenant_id: int, inicio: Optional[date], fim: Optional[date],
    etapa: Optional[str] = None, cliente: Optional[str] = None, empresa: Optional[str] = None,
) -> Dict[str, Any]:
    await index_new_messages(db, tenant_id)

    q = select(OsEnvioLog).where(OsEnvioLog.tenant_id == tenant_id)
    if inicio:
        q = q.where(OsEnvioLog.enviado_em >= datetime.combine(inicio, datetime.min.time()) + BRT_OFFSET)
    if fim:
        q = q.where(OsEnvioLog.enviado_em < datetime.combine(fim + timedelta(days=1), datetime.min.time()) + BRT_OFFSET)
    if etapa in ETAPA_LABEL:
        q = q.where(OsEnvioLog.etapa == etapa)
    logs = (await db.execute(q.order_by(OsEnvioLog.enviado_em.asc()))).scalars().all()

    codos_set = {l.codos for l in logs}
    conv_ids = {l.conversation_id for l in logs}
    msg_ids = [l.message_id for l in logs]

    # status atual de cada mensagem (enviada/entregue/lida/falhou)
    status_by_msg: Dict[int, str] = {}
    for i in range(0, len(msg_ids), 500):
        for mid, st in (await db.execute(select(Message.id, Message.status).where(Message.id.in_(msg_ids[i:i + 500])))).all():
            status_by_msg[mid] = st or "sent"

    # telefone do contato de cada conversa (pra casar a O.S. certa quando o nº existe nas duas empresas)
    phone_by_conv: Dict[int, str] = {}
    if conv_ids:
        for cid, tel in (await db.execute(
            select(Conversation.id, Contact.telefone).join(Contact, Contact.id == Conversation.contact_id).where(Conversation.id.in_(conv_ids))
        )).all():
            phone_by_conv[cid] = _digits(tel)

    orders_by_codos: Dict[int, List[OsBoardOrder]] = defaultdict(list)
    if codos_set:
        for o in (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos.in_(codos_set)
        ))).scalars().all():
            orders_by_codos[o.codos].append(o)

    def order_for(l: OsEnvioLog) -> Optional[OsBoardOrder]:
        cands = orders_by_codos.get(l.codos) or []
        if len(cands) <= 1:
            return cands[0] if cands else None
        tel = phone_by_conv.get(l.conversation_id, "")
        return next((o for o in cands if tel and _digits(o.telefone) and (tel.endswith(_digits(o.telefone)[-8:]))), cands[0])

    # nº da cobrança (1ª, 2ª...) contando o histórico inteiro daquela O.S./etapa, não só o período
    seq: Dict[int, int] = {}
    if codos_set:
        hist = (await db.execute(select(OsEnvioLog.message_id, OsEnvioLog.codos, OsEnvioLog.etapa).where(
            OsEnvioLog.tenant_id == tenant_id, OsEnvioLog.codos.in_(codos_set), OsEnvioLog.tipo == "cobranca"
        ).order_by(OsEnvioLog.enviado_em.asc()))).all()
        cont: Dict[Tuple[int, str], int] = defaultdict(int)
        for mid, c, et in hist:
            cont[(c, et)] += 1
            seq[mid] = cont[(c, et)]

    # cliente respondeu (qualquer mensagem dele na conversa até 72h depois do envio)?
    respostas: Dict[int, List[datetime]] = defaultdict(list)
    if logs:
        lo = min(l.enviado_em for l in logs)
        hi = max(l.enviado_em for l in logs) + RESPOSTA_JANELA
        conv_list = list(conv_ids)
        for i in range(0, len(conv_list), 500):
            for cid, ts in (await db.execute(select(Message.conversation_id, Message.timestamp).where(
                Message.conversation_id.in_(conv_list[i:i + 500]), Message.remetente == MessageSender.CLIENTE,
                Message.timestamp > lo, Message.timestamp <= hi,
            ))).all():
                respostas[cid].append(ts)

    # a resposta conta pro envio mais recente antes dela: janela vai até o próximo envio na mesma conversa
    proximo_envio: Dict[int, datetime] = {}
    ultimo_por_conv: Dict[int, OsEnvioLog] = {}
    for l in logs:  # já em ordem crescente de enviado_em
        anterior = ultimo_por_conv.get(l.conversation_id)
        if anterior:
            proximo_envio[anterior.id] = l.enviado_em
        ultimo_por_conv[l.conversation_id] = l

    termo = (cliente or "").strip().lower()
    termo_dig = _digits(termo)
    rows: List[Dict[str, Any]] = []
    for l in logs:
        o = order_for(l)
        if empresa in ("servweld", "centrooeste") and (not o or o.empresa != empresa):
            continue
        nome_cliente = (o.cliente if o else None) or (o.contato_nome if o else None) or "—"
        if termo:
            alvo = " ".join(filter(None, [o.cliente if o else "", o.contato_nome if o else "", str(l.codos)])).lower()
            tel_ok = bool(termo_dig) and len(termo_dig) >= 4 and termo_dig in _digits(o.telefone if o else "")
            if termo not in alvo and not tel_ok and termo != str(l.codos):
                continue
        status = status_by_msg.get(l.message_id, "sent")
        fim_janela = min(l.enviado_em + RESPOSTA_JANELA, proximo_envio.get(l.id, l.enviado_em + RESPOSTA_JANELA))
        respondeu = not status.startswith("failed") and any(
            l.enviado_em < ts <= fim_janela for ts in respostas.get(l.conversation_id, [])
        )
        local = l.enviado_em - BRT_OFFSET
        rows.append({
            "id": l.id,
            "data": local.strftime("%Y-%m-%d"),
            "data_hora": local.isoformat(),
            "codos": l.codos,
            "empresa": o.empresa if o else None,
            "cliente": nome_cliente,
            "contato": o.contato_nome if o else None,
            "telefone": o.telefone if o else None,
            "tecnico": o.tecnico if o else None,
            "equipamento": o.equipamento if o else None,
            "valor_total": o.valor_total if o else None,
            "etapa": l.etapa,
            "etapa_label": ETAPA_LABEL[l.etapa],
            "tipo": l.tipo,
            "tipo_label": TIPO_LABEL.get(l.tipo, l.tipo),
            "tentativa": seq.get(l.message_id),
            "status": status,
            "status_label": STATUS_LABEL.get(status, status),
            "sucesso": not status.startswith("failed"),
            "respondeu": respondeu,
            "resultado": _resultado(l.etapa, o),
        })

    total = len(rows)
    falhas = sum(1 for r in rows if not r["sucesso"])
    resumo = {
        "total": total,
        "orcamento": sum(1 for r in rows if r["etapa"] == "orcamento"),
        "retirada": sum(1 for r in rows if r["etapa"] == "retirada"),
        "cobrancas": sum(1 for r in rows if r["tipo"] == "cobranca"),
        "envios": sum(1 for r in rows if r["tipo"] == "envio"),
        "sucesso": total - falhas,
        "falhas": falhas,
        "entregues": sum(1 for r in rows if r["status"] in ("delivered", "read")),
        "lidas": sum(1 for r in rows if r["status"] == "read"),
        "respondidas": sum(1 for r in rows if r["respondeu"]),
        "os_distintas": len({(r["empresa"], r["codos"]) for r in rows}),
        "clientes_distintos": len({r["cliente"] for r in rows}),
        # valor parado esperando o cliente aprovar (cada O.S. uma vez só)
        "valor_aguardando_aprovacao": round(sum(
            v for v in {(r["empresa"], r["codos"]): (r["valor_total"] or 0) for r in rows
                        if r["etapa"] == "orcamento" and r["resultado"] == "Aguardando resposta"}.values()
        ), 2),
    }

    por_cliente_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        c = por_cliente_map.setdefault(r["cliente"], {
            "cliente": r["cliente"], "contato": r["contato"], "telefone": r["telefone"], "os": set(),
            "orcamento_envios": 0, "orcamento_cobrancas": 0, "retirada_envios": 0, "retirada_cobrancas": 0,
            "descarte": 0, "falhas": 0, "respondidas": 0, "ultimo_envio": None,
        })
        c["os"].add(r["codos"])
        if r["tipo"] == "descarte":
            c["descarte"] += 1
        else:
            c[f"{r['etapa']}_{'cobrancas' if r['tipo'] == 'cobranca' else 'envios'}"] += 1
        c["falhas"] += 0 if r["sucesso"] else 1
        c["respondidas"] += 1 if r["respondeu"] else 0
        c["ultimo_envio"] = max(filter(None, [c["ultimo_envio"], r["data_hora"]]))
    por_cliente = sorted(
        ({**c, "os": sorted(c["os"]), "total": c["orcamento_envios"] + c["orcamento_cobrancas"] + c["retirada_envios"] + c["retirada_cobrancas"] + c["descarte"]}
         for c in por_cliente_map.values()),
        key=lambda c: (-c["total"], c["cliente"]),
    )

    cobertura = await build_coverage(db, tenant_id, etapa, cliente, empresa, inicio, fim)

    return {
        "cobertura": cobertura,
        "filtros": {"inicio": inicio.isoformat() if inicio else None, "fim": fim.isoformat() if fim else None,
                    "etapa": etapa, "cliente": cliente, "empresa": empresa},
        "resumo": resumo,
        "rows": list(reversed(rows)),  # mais recente primeiro
        "por_cliente": por_cliente,
    }


# --------------------------------------------------------------------------- conferência por status
# Pedido do usuário em 14/10/2026: "quantos no total tem no status e quantos o sistema enviou
# mensagem" + conferir se a tratativa está certa. Foto de AGORA das O.S. paradas esperando o
# cliente (mesmo critério da cobrança automática - os_board_followup_service._list_due_*), cruzada
# com os envios registrados desde que cada uma entrou no status.

ETAPA_EVENTO = {"orcamento": 3, "retirada": 6}

SITUACAO_ORDEM = ["atrasada", "falhou", "sem_telefone", "na_interno", "aguardando_1a", "em_dia"]
SITUACAO_LABEL = {
    "atrasada": "Atrasada",
    "falhou": "Última mensagem falhou",
    "sem_telefone": "Sem telefone - nunca é cobrada",
    "na_interno": "Orçamento interno (N/A) - não cobra",
    "aguardando_1a": "Aguardando 1ª cobrança",
    "em_dia": "Em dia",
}


def _dias_uteis_encerrados(desde: datetime, agora: datetime) -> int:
    """Quantos expedientes (dia útil, até as 18h) terminaram entre `desde` e `agora` - a cobrança só
    sai em dia útil 08h-18h, então só conta como atraso o expediente inteiro que passou sem envio."""
    from app.services.os_board_followup_service import _FERIADOS_NACIONAIS, BUSINESS_END_HOUR
    if desde >= agora:
        return 0
    n = 0
    dia = desde.date()
    while dia <= agora.date():
        util = dia.weekday() < 5 and dia.strftime("%Y-%m-%d") not in _FERIADOS_NACIONAIS
        fim_expediente = datetime.combine(dia, datetime.min.time()).replace(hour=BUSINESS_END_HOUR)
        # o dia em que venceu só conta se ainda sobrava expediente depois do vencimento
        if util and fim_expediente <= agora and desde < fim_expediente - timedelta(hours=1):
            n += 1
        dia += timedelta(days=1)
    return n


async def build_coverage(
    db: AsyncSession, tenant_id: int, etapa: Optional[str] = None, cliente: Optional[str] = None,
    empresa: Optional[str] = None, inicio: Optional[date] = None, fim: Optional[date] = None,
) -> Dict[str, Any]:
    from app.services.os_board_followup_service import _is_na_obs, _now_brt, NUDGE_INTERVAL_DAYS, RETIRADA_PRAZO_DIAS

    agora = _now_brt()
    etapas = [etapa] if etapa in ETAPA_EVENTO else list(ETAPA_EVENTO)
    orders = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == tenant_id,
        OsBoardOrder.situacao_evento.in_([ETAPA_EVENTO[e] for e in etapas]),
        OsBoardOrder.paga.is_(False), OsBoardOrder.venda_codigo.is_(None),
    ))).scalars().all()
    if empresa in ("servweld", "centrooeste"):
        orders = [o for o in orders if o.empresa == empresa]
    termo = (cliente or "").strip().lower()
    if termo:
        termo_dig = _digits(termo)
        orders = [o for o in orders if termo in " ".join(filter(None, [o.cliente, o.contato_nome, str(o.codos)])).lower()
                  or (len(termo_dig) >= 4 and termo_dig in _digits(o.telefone))]

    # envios (já em BRT) de cada O.S./etapa
    envios: Dict[Tuple[int, str], List[Tuple[datetime, int, str]]] = defaultdict(list)
    codos_set = {o.codos for o in orders}
    if codos_set:
        logs = (await db.execute(select(OsEnvioLog, Message.status).join(Message, Message.id == OsEnvioLog.message_id).where(
            OsEnvioLog.tenant_id == tenant_id, OsEnvioLog.codos.in_(codos_set)
        ).order_by(OsEnvioLog.enviado_em.asc()))).all()
        for l, st in logs:
            envios[(l.codos, l.etapa)].append((l.enviado_em - BRT_OFFSET, l.message_id, st or "sent"))

    ini_brt = datetime.combine(inicio, datetime.min.time()) if inicio else None
    fim_brt = datetime.combine(fim + timedelta(days=1), datetime.min.time()) if fim else None

    resumo = {e: {"etapa": e, "label": ETAPA_LABEL[e], "total": 0, "avisadas": 0, "no_periodo": 0, "sem_mensagem": 0,
                  "atrasadas": 0, "falhas": 0, "sem_telefone": 0, "na_interno": 0, "mensagens": 0} for e in etapas}
    itens: List[Dict[str, Any]] = []
    for o in orders:
        et = "orcamento" if o.situacao_evento == 3 else "retirada"
        entrou = o.ultimo_evento_em
        # só conta o que foi mandado DESTA vez no status (com 1h de folga: o aviso inicial às vezes sai
        # um pouco antes do horário do evento que o vigia registra)
        desde = (entrou - timedelta(hours=1)) if entrou else None
        meus = [e for e in envios.get((o.codos, et), []) if not desde or e[0] >= desde]
        ultimo = meus[-1] if meus else None
        no_periodo = [e for e in meus if (not ini_brt or e[0] >= ini_brt) and (not fim_brt or e[0] < fim_brt)]

        ultimo_toque = o.last_nudge_at or entrou
        proxima = (ultimo_toque + timedelta(days=NUDGE_INTERVAL_DAYS)) if ultimo_toque else None
        dias_restantes = (RETIRADA_PRAZO_DIAS - (agora - entrou).days) if (et == "retirada" and entrou) else None

        if not _digits(o.telefone):
            sit = "sem_telefone"
        elif et == "orcamento" and _is_na_obs(o.situacao_obs):
            sit = "na_interno"
        elif ultimo and ultimo[2].startswith("failed"):
            sit = "falhou"
        elif proxima and _dias_uteis_encerrados(proxima, agora) >= 1:
            sit = "atrasada"
        elif not meus:
            sit = "aguardando_1a"
        else:
            sit = "em_dia"

        r = resumo[et]
        r["total"] += 1
        r["avisadas"] += 1 if meus else 0
        r["no_periodo"] += 1 if no_periodo else 0
        r["sem_mensagem"] += 0 if meus else 1
        r["mensagens"] += len(meus)
        r["atrasadas"] += 1 if sit == "atrasada" else 0
        r["falhas"] += 1 if sit == "falhou" else 0
        r["sem_telefone"] += 1 if sit == "sem_telefone" else 0
        r["na_interno"] += 1 if sit == "na_interno" else 0

        itens.append({
            "codos": o.codos, "empresa": o.empresa, "cliente": o.cliente or o.contato_nome or "—", "contato": o.contato_nome,
            "telefone": o.telefone, "tecnico": o.tecnico, "valor_total": o.valor_total,
            "etapa": et, "etapa_label": ETAPA_LABEL[et],
            "entrou_em": entrou.isoformat() if entrou else None,
            "dias_no_status": (agora - entrou).days if entrou else None,
            "dias_restantes": dias_restantes,
            "mensagens": len(meus), "mensagens_periodo": len(no_periodo),
            "ultimo_envio": ultimo[0].isoformat() if ultimo else None,
            "ultimo_status": STATUS_LABEL.get(ultimo[2], ultimo[2]) if ultimo else None,
            "proxima_cobranca": proxima.isoformat() if proxima and sit in ("em_dia", "aguardando_1a", "atrasada", "falhou") else None,
            "situacao": sit, "situacao_label": SITUACAO_LABEL[sit],
        })

    itens.sort(key=lambda x: (SITUACAO_ORDEM.index(x["situacao"]), -(x["dias_no_status"] or 0)))
    return {"agora": agora.isoformat(), "resumo": list(resumo.values()), "itens": itens}
