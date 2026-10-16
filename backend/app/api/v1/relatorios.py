"""
Módulo Relatórios - pedido do usuário em 14/10/2026. Por enquanto um relatório só: avisos e
cobranças por WhatsApp das O.S. em "Aguardando aprovação" e "Aguardando retirada" (ver
app/services/os_envio_report_service.py), na tela e em PDF. Novos relatórios/filtros entram aqui.
"""
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User
from app.services.os_envio_report_service import build_report

router = APIRouter(prefix="/relatorios", tags=["Relatórios"])


def _parse_periodo(inicio: Optional[str], fim: Optional[str]):
    try:
        d_ini = date.fromisoformat(inicio) if inicio else None
        d_fim = date.fromisoformat(fim) if fim else None
    except ValueError:
        raise HTTPException(status_code=422, detail="Data inválida (use AAAA-MM-DD)")
    if d_ini and d_fim and d_ini > d_fim:
        raise HTTPException(status_code=422, detail="A data inicial é depois da final")
    return d_ini, d_fim


@router.get("/cobrancas-os")
async def relatorio_cobrancas_os(
    inicio: Optional[str] = Query(None, description="AAAA-MM-DD (horário de Brasília); vazio = desde o começo"),
    fim: Optional[str] = Query(None, description="AAAA-MM-DD; vazio = até hoje"),
    etapa: Optional[str] = Query(None, description="orcamento | retirada | vazio = as duas"),
    cliente: Optional[str] = Query(None, description="Razão social, contato, telefone ou nº da O.S."),
    empresa: Optional[str] = Query(None, description="servweld | centrooeste | vazio = as duas"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d_ini, d_fim = _parse_periodo(inicio, fim)
    return await build_report(db, current_user.tenant_id, d_ini, d_fim, etapa, cliente, empresa)


@router.get("/cobrancas-os/pdf")
async def relatorio_cobrancas_os_pdf(
    inicio: Optional[str] = None,
    fim: Optional[str] = None,
    etapa: Optional[str] = None,
    cliente: Optional[str] = None,
    empresa: Optional[str] = None,
    visao: str = Query("envios", description="envios | clientes"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    d_ini, d_fim = _parse_periodo(inicio, fim)
    data = await build_report(db, current_user.tenant_id, d_ini, d_fim, etapa, cliente, empresa)
    pdf = _render_pdf(data, visao, current_user.nome or "")
    nome = f"relatorio-cobrancas-os-{(inicio or 'inicio')}-a-{(fim or 'hoje')}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nome}"'})


def _fmt_dt(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).strftime("%d/%m/%y %H:%M")


def _fmt_d(iso: Optional[str]) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def _money(v) -> str:
    if v is None:
        return "—"
    return ("R$ " + f"{v:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def _render_pdf(data: dict, visao: str, gerado_por: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from app.services.os_report_pdf_service import _clean_pdf_text

    verde = colors.HexColor("#059669")
    escuro = colors.HexColor("#0f172a")
    cinza = colors.HexColor("#64748b")
    titulo = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=escuro, spaceAfter=4)
    sub = ParagraphStyle("s", fontName="Helvetica", fontSize=9, textColor=cinza)
    cel = ParagraphStyle("c", fontName="Helvetica", fontSize=7.5, leading=9, textColor=escuro)
    falha = ParagraphStyle("f", parent=cel, fontName="Helvetica-Bold", textColor=colors.HexColor("#dc2626"))
    cab = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.white)

    def P(t, st=cel):
        return Paragraph(_clean_pdf_text(str(t)) if t not in (None, "") else "—", st)

    f = data["filtros"]
    periodo = (
        f"{_fmt_d(f['inicio'])} a {_fmt_d(f['fim'])}" if f["inicio"] and f["fim"] and f["inicio"] != f["fim"]
        else (_fmt_d(f["inicio"] or f["fim"]) or "Todo o período")
    )
    filtros_txt = [f"Período: {periodo}"]
    if f.get("etapa"):
        filtros_txt.append({"orcamento": "Aguardando aprovação", "retirada": "Aguardando retirada"}.get(f["etapa"], f["etapa"]))
    if f.get("empresa"):
        filtros_txt.append({"servweld": "Servweld", "centrooeste": "Centro-Oeste"}.get(f["empresa"], f["empresa"]))
    if f.get("cliente"):
        filtros_txt.append(f"Cliente: {f['cliente']}")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title="Relatório de cobranças de O.S.")
    story = [
        Paragraph("Relatório de avisos e cobranças de O.S. (WhatsApp)", titulo),
        Paragraph(_clean_pdf_text(" · ".join(filtros_txt)) + f" · Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                  + (f" por {_clean_pdf_text(gerado_por)}" if gerado_por else ""), sub),
        Spacer(1, 8),
    ]

    r = data["resumo"]
    kpis = [
        ("Envios no período", r["total"]), ("Aguard. aprovação", r["orcamento"]), ("Aguard. retirada", r["retirada"]),
        ("Sucesso", f"{r['sucesso']} ({round(100 * r['sucesso'] / r['total']) if r['total'] else 0}%)"),
        ("Falhas", r["falhas"]), ("Lidas", r["lidas"]), ("Responderam", r["respondidas"]),
        ("Valor aguardando aprovação", _money(r["valor_aguardando_aprovacao"])),
    ]
    kpi_tbl = Table([[P(k, ParagraphStyle("k", parent=sub, fontSize=7)) for k, _ in kpis],
                     [P(v, ParagraphStyle("v", parent=cel, fontName="Helvetica-Bold", fontSize=10)) for _, v in kpis]])
    kpi_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story += [kpi_tbl, Spacer(1, 10)]

    # Conferência: foto de agora - quantas O.S. no status x quantas receberam mensagem
    cob = data.get("cobertura") or {"resumo": [], "itens": []}
    linhas_cob = [[P(h, cab) for h in ["Status (agora)", "O.S. no status", "Receberam mensagem", "Com envio no período", "Atrasadas", "Com falha", "Sem telefone", "Interno (N/A)", "Mensagens"]]]
    for c in cob["resumo"]:
        pct = round(100 * c["avisadas"] / c["total"]) if c["total"] else 0
        linhas_cob.append([P(c["label"]), P(c["total"]), P(f"{c['avisadas']} ({pct}%)"), P(c["no_periodo"]),
                           P(c["atrasadas"], cel if not c["atrasadas"] else falha), P(c["falhas"], cel if not c["falhas"] else falha),
                           P(c["sem_telefone"]), P(c["na_interno"] if c["etapa"] == "orcamento" else "—"), P(c["mensagens"])])
    if cob["resumo"]:
        t_cob = Table(linhas_cob, colWidths=[w * mm for w in [44, 26, 32, 32, 24, 24, 26, 26, 24]])
        t_cob.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), escuro), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story += [t_cob, Spacer(1, 10)]

    if visao == "conferencia":
        head = ["Cobrança", "O.S.", "Cliente", "Status", "No status", "Msgs", "Última mensagem", "Próxima cobrança", "Valor", "Técnico"]
        body = []
        for x in cob["itens"]:
            no_status = f"{x['dias_no_status']} dia(s)" if x["dias_no_status"] is not None else "—"
            if x["dias_restantes"] is not None:
                no_status += f" · restam {x['dias_restantes']}"
            ultima = f"{_fmt_dt(x['ultimo_envio'])} · {x['ultimo_status']}" if x["ultimo_envio"] else "nenhuma"
            body.append([
                P(x["situacao_label"], falha if x["situacao"] in ("atrasada", "falhou") else cel), P(f"#{x['codos']}"),
                P(x["cliente"]), P(x["etapa_label"]), P(no_status), P(x["mensagens"]), P(ultima),
                P(_fmt_dt(x["proxima_cobranca"]) if x["proxima_cobranca"] else "—"), P(_money(x["valor_total"])), P(x["tecnico"]),
            ])
        widths = [34, 13, 62, 28, 24, 11, 32, 24, 20, 22]
    elif visao == "clientes":
        head = ["Cliente", "Contato / telefone", "O.S.", "Envios aprov.", "Cobr. aprov.", "Envios retir.", "Cobr. retir.", "Desc.", "Falhas", "Resp.", "Último envio"]
        body = [[
            P(c["cliente"]), P(" · ".join(filter(None, [c["contato"], c["telefone"]]))), P(", ".join(f"#{n}" for n in c["os"])),
            P(c["orcamento_envios"]), P(c["orcamento_cobrancas"]), P(c["retirada_envios"]), P(c["retirada_cobrancas"]),
            P(c["descarte"]), P(c["falhas"]), P(c["respondidas"]), P(_fmt_dt(c["ultimo_envio"])),
        ] for c in data["por_cliente"]]
        widths = [58, 42, 32, 16, 16, 16, 16, 13, 14, 13, 24]
    else:
        head = ["Data/hora", "O.S.", "Cliente", "Etapa", "Tipo", "Nº cobr.", "WhatsApp", "Resp.", "Situação atual", "Valor", "Técnico"]
        body = [[
            P(_fmt_dt(x["data_hora"])), P(f"#{x['codos']}"), P(x["cliente"]), P(x["etapa_label"]), P(x["tipo_label"]),
            P(f"{x['tentativa']}ª" if x["tentativa"] else "—"), P(x["status_label"], cel if x["sucesso"] else falha), P("Sim" if x["respondeu"] else "Não"),
            P(x["resultado"]), P(_money(x["valor_total"])), P(x["tecnico"]),
        ] for x in data["rows"]]
        widths = [22, 13, 66, 28, 20, 13, 18, 15, 30, 20, 21]

    if not body:
        story.append(Paragraph("Nenhum envio encontrado com esses filtros.", sub))
    else:
        tbl = Table([[P(h, cab) for h in head]] + body, colWidths=[w * mm for w in widths], repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), verde),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        tbl.setStyle(TableStyle(estilo))
        story.append(tbl)

    doc.build(story)
    return buf.getvalue()
