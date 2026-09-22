"""
Relatório em PDF do Quadro de Técnicos: produtividade, financeiro e forma de pagamento.

O valor de cada O.S. é a soma dos itens dela no Softsystem (ITENSORDEMSERVICO.QUANTIDADE * PRECO,
capturado pelo vigia - ver db_watcher._board_valores) - é uma REFERÊNCIA para acompanhamento, não
substitui o fechamento contábil oficial (não considera impostos/descontos de última hora lançados
fora da O.S.). O relatório deixa isso explícito no rodapé.
"""
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_CENTER

BRAND_GREEN = colors.HexColor("#059669")
BRAND_DARK = colors.HexColor("#0f172a")
GREY_LINE = colors.HexColor("#cbd5e1")
ROW_ALT = colors.HexColor("#f1f5f9")
RED = colors.HexColor("#dc2626")
AMBER = colors.HexColor("#d97706")

EMPRESA_LABEL = {"servweld": "Servweld", "centrooeste": "Centro-Oeste"}


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _fmt_date(d: Optional[datetime]) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _fmt_datetime(d: Optional[datetime]) -> str:
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def _lista_simples_table(rows: List[Dict[str, Any]], doc: SimpleDocTemplate, thead: ParagraphStyle, cell: ParagraphStyle) -> Table:
    """Uma tabela 'O.S. do técnico' pronta pra entregar - sem valor/forma de pagamento (não é
    o foco quando o objetivo é só mostrar o que está pendente de trabalho)."""
    header = [Paragraph(t, thead) for t in ["O.S.", "Cliente", "Equipamento", "Tipo", "Situação", "Entrada", "Dias"]]
    data = [header]
    # Mais antiga primeiro - é o que o técnico deveria atacar primeiro, diferente da lista do
    # relatório completo (mais recente primeiro, que é o jeito natural de auditar/conferir).
    for o in sorted(rows, key=lambda r: r.get("data_entrada") or datetime.min):
        dias = (datetime.now() - o["data_entrada"]).days if o.get("data_entrada") else None
        data.append([
            str(o["codos"]), Paragraph(o.get("cliente") or "—", cell),
            Paragraph(o.get("equipamento") or "—", cell), Paragraph(o.get("tipo_os") or "—", cell),
            Paragraph(o["situacao"], cell), _fmt_date(o.get("data_entrada")),
            f"{dias}d" if dias is not None else "—",
        ])
    col_w = [14 * mm, doc.width * 0.24, doc.width * 0.24, doc.width * 0.16, doc.width * 0.16, 20 * mm, 14 * mm]
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (5, 0), (6, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, GREY_LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _build_lista_simples(
    story: List[Any], doc: SimpleDocTemplate, orders: List[Dict[str, Any]], filtros: Dict[str, str],
    thead: ParagraphStyle, cell: ParagraphStyle, h2: ParagraphStyle, note: ParagraphStyle,
) -> None:
    MAX_ROWS = 600
    truncado = len(orders) > MAX_ROWS
    listed = orders[:MAX_ROWS]

    # Técnico=Todos (o filtro pedido "geral") agrupa por técnico, senão vira uma lista só (já
    # está tudo do mesmo técnico, repetir o nome em toda linha não ajuda em nada).
    agrupar = filtros.get("Técnico", "Todos") == "Todos"
    if agrupar:
        por_tecnico: Dict[str, List[Dict[str, Any]]] = {}
        for o in listed:
            por_tecnico.setdefault(o["tecnico_label"], []).append(o)
        for tec in sorted(por_tecnico.keys()):
            rows = por_tecnico[tec]
            # Sem KeepTogether aqui: um técnico pode ter dezenas de O.S., o que empurraria a
            # tabela inteira pra próxima página à toa - repeatRows (na tabela) já resolve.
            story.append(Paragraph(f"{tec} <font color='#64748b' size=9>({len(rows)} O.S.)</font>", h2))
            story.append(_lista_simples_table(rows, doc, thead, cell))
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph(f"{len(listed)}{' de ' + str(len(orders)) if truncado else ''} O.S.", h2))
        story.append(_lista_simples_table(listed, doc, thead, cell))

    if truncado:
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Lista limitada às primeiras {MAX_ROWS} O.S. do filtro ({len(orders)} no total) - restrinja o período ou o filtro pra ver o restante.", note))


def build_os_report_pdf(
    *,
    orders: List[Dict[str, Any]],
    stage_labels: Dict[str, str],
    event_labels: Dict[int, str],
    filtros: Dict[str, str],
    gerado_em: datetime,
    incluir_lista: bool = True,
    modo: str = "completo",
) -> bytes:
    """
    `orders` é uma lista de dicts já resolvidos (um por O.S.), com pelo menos:
    codos, empresa, cliente, equipamento, tecnico_label, cod_tipo_os, tipo_os, stage, situacao,
    data_entrada, finalizada_em, valor_total, forma_pagamento, aberta (bool), efetivada_motivo.

    `modo="completo"`: o relatório de gestão de sempre (KPIs, matriz, financeiro, ranking).
    `modo="lista"`: só a lista de O.S. do filtro, sem nenhum número de gestão - pensado pra
    imprimir/entregar pro técnico como lista de tarefas (ex.: "só o que ele tem em Entrada"),
    quando esses dados de acompanhamento não interessam pra essa finalidade.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), topMargin=14 * mm, bottomMargin=12 * mm, leftMargin=14 * mm, rightMargin=14 * mm,
        title="Lista de O.S." if modo == "lista" else "Relatório do Quadro de Técnicos"
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=17, textColor=BRAND_DARK, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12.5, textColor=BRAND_GREEN, spaceBefore=14, spaceAfter=6)
    note = ParagraphStyle("note", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#64748b"))
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    kpi_label = ParagraphStyle("kpi_label", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#475569"), alignment=TA_CENTER)
    kpi_value = ParagraphStyle("kpi_value", parent=styles["Normal"], fontSize=17, textColor=BRAND_DARK, alignment=TA_CENTER, leading=20)
    thead = ParagraphStyle("thead", parent=styles["Normal"], fontSize=7.5, textColor=colors.white, alignment=TA_CENTER, leading=9, fontName="Helvetica-Bold")

    story: List[Any] = []

    # ---------------------------------------------------------------- cabeçalho
    story.append(Paragraph("Lista de O.S." if modo == "lista" else "Relatório do Quadro de Técnicos", h1))
    story.append(Paragraph("Servweld / Servsolda &amp; Centro-Oeste · Assistência Técnica", sub))
    filtro_linhas = " · ".join(f"<b>{k}:</b> {v}" for k, v in filtros.items())
    story.append(Paragraph(filtro_linhas, sub))
    story.append(Paragraph(f"Gerado em {_fmt_datetime(gerado_em)}", sub))
    story.append(Spacer(1, 6))
    story.append(Table([[""]], colWidths=[doc.width], rowHeights=[1], style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1, GREY_LINE)])))

    if modo == "lista":
        _build_lista_simples(story, doc, orders, filtros, thead, cell, h2, note)
        doc.build(story)
        return buf.getvalue()

    total_os = len(orders)
    finalizadas = [o for o in orders if o["stage"] == "finalizada"]
    abertas = [o for o in orders if o.get("aberta")]
    # O.S. que já saiu do quadro ao vivo por ter sido paga/vendida, mas o Softsystem ainda não
    # lançou o evento "Finalizada" nela - fica de fora tanto de "Finalizadas" quanto de "Em
    # aberto" (é por isso que os dois números sozinhos não batiam com o total do filtro).
    efetivadas_nao_finalizadas = [o for o in orders if o.get("efetivada_motivo") and o["stage"] != "finalizada"]
    # Decisão do orçamento na história da O.S. (não só o estágio atual - uma O.S. aprovada e já
    # finalizada continua contando como aprovada aqui, ver os_board.py -> decisao_por_codos)
    aprovadas = [o for o in orders if o.get("decisao") == "aprovado"]
    nao_aprovadas = [o for o in orders if o.get("decisao") == "nao_aprovado"]
    total_decisao = len(aprovadas) + len(nao_aprovadas)
    taxa_aprovacao = (len(aprovadas) / total_decisao * 100) if total_decisao else None
    com_valor = [o for o in orders if o.get("valor_total") is not None]
    valor_total_geral = sum(o["valor_total"] for o in com_valor)
    ticket_medio = (valor_total_geral / len(com_valor)) if com_valor else None

    prazos = []
    for o in finalizadas:
        if o.get("data_entrada") and o.get("finalizada_em"):
            prazos.append((o["finalizada_em"] - o["data_entrada"]).days)
    tempo_medio = (sum(prazos) / len(prazos)) if prazos else None

    # ---------------------------------------------------------------- resumo (KPIs)
    # Taxa de aprovação com o tamanho da amostra ao lado - sem isso, uma única decisão registrada
    # (ex.: "100%" vindo de 1 O.S. só) parece uma estatística confiável do período inteiro e não é.
    if taxa_aprovacao is not None:
        taxa_aprovacao_txt = f"{taxa_aprovacao:.0f}% ({len(aprovadas)}/{total_decisao})"
    else:
        taxa_aprovacao_txt = "—"
    kpis = [
        ("O.S. no filtro", str(total_os)),
        ("Finalizadas", str(len(finalizadas))),
        ("Em aberto", str(len(abertas))),
        ("Efetivadas (pagas, fora do quadro)", str(len(efetivadas_nao_finalizadas))),
        ("Taxa de aprovação", taxa_aprovacao_txt),
        ("Tempo médio (entrada→final)", f"{tempo_medio:.0f} dias" if tempo_medio is not None else "—"),
        ("Ticket médio", _fmt_money(ticket_medio)),
    ]
    kpi_table_data = [[Paragraph(v, kpi_value) for _, v in kpis], [Paragraph(k, kpi_label) for k, _ in kpis]]
    kpi_w = doc.width / len(kpis)
    kt = Table(kpi_table_data, colWidths=[kpi_w] * len(kpis))
    kt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, GREY_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, GREY_LINE),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(KeepTogether([Paragraph("Resumo do período", h2), kt]))

    # ---------------------------------------------------------------- matriz técnico x estágio
    # Uma O.S. pode ter um 2º técnico (TECNICOATENDIMENTO2 no Softsystem, ex.: ajudante) - conta
    # pro relatório "todos os técnicos" de AMBOS, do mesmo jeito que filtrar por um técnico
    # específico já encontra essa O.S. (ver os_board.py, filtro usa tecnico OU tecnico2). Por isso
    # a soma das colunas por técnico pode passar de "O.S. no filtro" quando isso acontece - é
    # esperado (conta como carga de trabalho pras duas pessoas), não é O.S. duplicada.
    def _tec_orders(tec: str) -> List[Dict[str, Any]]:
        return [o for o in orders if o["tecnico_label"] == tec or o.get("tecnico2_label") == tec]

    story.append(Paragraph("Quantidade de O.S. por técnico e por evento", h2))
    tecnicos = sorted({o["tecnico_label"] for o in orders} | {o["tecnico2_label"] for o in orders if o.get("tecnico2_label")})
    stage_keys = list(stage_labels.keys())
    header = [Paragraph("Técnico", thead)] + [Paragraph(stage_labels[k], thead) for k in stage_keys] + [Paragraph("Total", thead)]
    matrix_rows = [header]
    grand_total_col = {k: 0 for k in stage_keys}
    for tec in tecnicos:
        tec_orders = _tec_orders(tec)
        row = [Paragraph(tec, cell)]
        total_tec = 0
        for k in stage_keys:
            n = sum(1 for o in tec_orders if o["stage"] == k)
            grand_total_col[k] += n
            total_tec += n
            row.append(str(n) if n else "—")
        row.append(str(total_tec))
        matrix_rows.append(row)
    total_row = ["Total"] + [str(grand_total_col[k]) for k in stage_keys] + [str(sum(grand_total_col.values()))]
    matrix_rows.append(total_row)

    col_w = [38 * mm] + [(doc.width - 38 * mm - 16 * mm) / max(len(stage_keys), 1)] * len(stage_keys) + [16 * mm]
    mt = Table(matrix_rows, colWidths=col_w, repeatRows=1)
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, GREY_LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(mt)

    # ---------------------------------------------------------------- financeiro por técnico
    if com_valor:
        fin_rows = [["Técnico", "O.S. com valor", "Total"]]
        for tec in tecnicos:
            tec_valores = [o["valor_total"] for o in _tec_orders(tec) if o.get("valor_total") is not None]
            if not tec_valores:
                continue
            fin_rows.append([tec, str(len(tec_valores)), _fmt_money(sum(tec_valores))])
        fin_rows.append(["Total geral", str(len(com_valor)), _fmt_money(valor_total_geral)])
        ft = Table(fin_rows, colWidths=[doc.width * 0.5, doc.width * 0.2, doc.width * 0.3], repeatRows=1)
        ft.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.4, GREY_LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, ROW_ALT]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        # Sem KeepTogether aqui: com muitos técnicos essa tabela pode passar de uma página, e
        # repeatRows=1 (acima) já garante que o cabeçalho reaparece na página seguinte.
        story.append(Paragraph("Total monetário por técnico", h2))
        story.append(ft)

        # ---------------------------------------------------------------- forma de pagamento
        by_pag: Dict[str, List[float]] = {}
        for o in com_valor:
            by_pag.setdefault(o.get("forma_pagamento") or "Não informada", []).append(o["valor_total"])
        pag_rows = [["Forma de pagamento", "O.S.", "Total", "% do total"]]
        for nome, vals in sorted(by_pag.items(), key=lambda kv: -sum(kv[1])):
            pct = (sum(vals) / valor_total_geral * 100) if valor_total_geral else 0
            pag_rows.append([nome, str(len(vals)), _fmt_money(sum(vals)), f"{pct:.0f}%"])
        pt = Table(pag_rows, colWidths=[doc.width * 0.42, doc.width * 0.16, doc.width * 0.26, doc.width * 0.16], repeatRows=1)
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.4, GREY_LINE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        # Poucas formas de pagamento em geral (raramente passa de uma página) - KeepTogether evita
        # o título "Total por forma de pagamento" ficar sozinho no fim de uma página e a tabela
        # inteira pular pra próxima (visto de verdade num relatório real antes desse ajuste).
        story.append(KeepTogether([Paragraph("Total por forma de pagamento", h2), pt]))
    else:
        story.append(Paragraph("Total monetário e forma de pagamento", h2))
        story.append(Paragraph("Nenhuma O.S. deste filtro tem valor de itens lançado no Softsystem.", cell))

    # ---------------------------------------------------------------- distribuição por tipo de O.S.
    by_tipo: Dict[str, int] = {}
    for o in orders:
        by_tipo[o.get("tipo_os") or "Não informado"] = by_tipo.get(o.get("tipo_os") or "Não informado", 0) + 1
    tipo_rows = [["Tipo de O.S.", "Quantidade", "% do total"]]
    for nome, n in sorted(by_tipo.items(), key=lambda kv: -kv[1]):
        tipo_rows.append([nome, str(n), f"{(n / total_os * 100) if total_os else 0:.0f}%"])
    tt = Table(tipo_rows, colWidths=[doc.width * 0.55, doc.width * 0.25, doc.width * 0.2], repeatRows=1)
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.4, GREY_LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(KeepTogether([Paragraph("Distribuição por tipo de O.S.", h2), tt]))

    # ---------------------------------------------------------------- ranking de técnicos
    ranking = sorted(
        ((tec, sum(1 for o in _tec_orders(tec) if o["stage"] == "finalizada")) for tec in tecnicos),
        key=lambda kv: -kv[1]
    )
    rank_rows = [["#", "Técnico", "Finalizadas"]] + [[str(i + 1), tec, str(n)] for i, (tec, n) in enumerate(ranking)]
    rt = Table(rank_rows, colWidths=[12 * mm, doc.width - 12 * mm - 30 * mm, 30 * mm], repeatRows=1)
    rt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, GREY_LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    heading_and_rank = [Paragraph("Ranking de técnicos (finalizadas no período)", h2), rt]
    # Poucos técnicos normalmente cabem numa página só (KeepTogether evita o título órfão); se um
    # dia a lista crescer muito, repeatRows (acima) garante que o cabeçalho reaparece mesmo assim.
    if len(ranking) <= 25:
        story.append(KeepTogether(heading_and_rank))
    else:
        story.extend(heading_and_rank)

    # ---------------------------------------------------------------- lista detalhada
    if incluir_lista and orders:
        story.append(PageBreak())
        MAX_ROWS = 600
        listed = orders[:MAX_ROWS]
        story.append(Paragraph(f"Lista detalhada ({len(listed)}{' de ' + str(len(orders)) if len(orders) > MAX_ROWS else ''} O.S.)", h2))
        det_header = ["O.S.", "Empresa", "Cliente", "Técnico", "Tipo", "Situação", "Entrada", "Valor", "Pagamento"]
        det_rows = [det_header]
        for o in listed:
            # As células já são Paragraph, que quebra linha sozinho dentro da largura da coluna -
            # cortar a string ANTES disso (como era) não encurtava a exibição, apagava o final do
            # nome de verdade (ex.: razão social comprida perdia um pedaço em vez de só quebrar
            # linha, que é o que as outras células mais curtas já faziam sem esse corte).
            det_rows.append([
                str(o["codos"]), EMPRESA_LABEL.get(o["empresa"], o["empresa"]),
                Paragraph(o.get("cliente") or "—", cell), o["tecnico_label"],
                Paragraph(o.get("tipo_os") or "—", cell), Paragraph(o["situacao"], cell),
                _fmt_date(o.get("data_entrada")), _fmt_money(o.get("valor_total")),
                Paragraph(o.get("forma_pagamento") or "—", cell),
            ])
        det_col_w = [13 * mm, 17 * mm, 34 * mm, 20 * mm, 22 * mm, 24 * mm, 17 * mm, 20 * mm, 23 * mm]
        dt = Table(det_rows, colWidths=det_col_w, repeatRows=1)
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.3, GREY_LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(dt)

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "O valor de cada O.S. é a soma dos itens lançados nela no Softsystem (produtos/serviços × preço) - é uma "
        "referência para acompanhamento operacional, não substitui o fechamento contábil oficial (não considera "
        "impostos ou descontos lançados fora da O.S.). Finalizadas e O.S. já efetivadas (pagas/com venda gerada) "
        "não aparecem no quadro ao vivo, mas entram neste relatório quando o filtro pedir. Quando uma O.S. tem "
        "2º técnico (ajudante), ela conta pros dois nas tabelas por técnico - por isso a soma das colunas pode "
        "passar de \"O.S. no filtro\" nesses casos; não é O.S. duplicada.", note
    ))

    doc.build(story)
    return buf.getvalue()
