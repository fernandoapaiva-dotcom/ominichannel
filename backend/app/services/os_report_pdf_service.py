"""
PDF de diagnóstico + orçamento mandado ao cliente quando o dono aprova o rascunho da IA (ver
os_report_service.approve_report) - layout próprio com identidade visual (papel timbrado), em vez
do texto puro de WhatsApp que era enviado antes. Logos e dados cadastrais (CNPJ, endereço, e-mail)
enviados pelo usuário em 07/10/2026 - um conjunto por empresa (Servweld / Servsolda-Centro-Oeste),
salvos em app/assets/logos/.
"""
import io
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.utils import ImageReader

BRAND_GREEN = colors.HexColor("#059669")
BRAND_DARK = colors.HexColor("#0f172a")
GREY_LINE = colors.HexColor("#cbd5e1")
ROW_ALT = colors.HexColor("#f1f5f9")

# reportlab.Paragraph usa uma mini-linguagem tipo HTML (só entende <b>, <i>, <br/> etc.) - texto
# cru da IA direto nela quebra de duas formas: (1) notação tipo LaTeX ($V_{CE}$) aparece literal
# no PDF, caracteres e tudo (achado em produção em 07/10/2026, O.S. #1987 - o laudo saiu com
# "($V_{CE}$)$" no meio do texto); (2) "&"/"<"/">" sem escapar (ex. nome de cliente "Fulano & Cia")
# derruba o parser de XML do reportlab. _clean_pdf_text resolve as duas.
_LATEX_INLINE_RE = re.compile(r"\$([^$]+)\$")
_BRACE_SCRIPT_RE = re.compile(r"[_^]\{([^}]*)\}")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _clean_pdf_text(text: Optional[str]) -> str:
    if not text:
        return ""
    # Tira notação de fórmula: "$V_{CE}$" -> "V_{CE}" -> "VCE"
    text = _LATEX_INLINE_RE.sub(lambda m: m.group(1), text)
    text = _BRACE_SCRIPT_RE.sub(lambda m: m.group(1), text)
    # Escapa & < > ANTES de reaplicar negrito - senão o escape bagunçaria as tags <b> que a
    # gente mesmo insere a seguir.
    text = _xml_escape(text)
    text = _MD_BOLD_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    return text

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "logos")

# Dados cadastrais reais de cada empresa, pro papel timbrado (mandados pelo usuário em
# 07/10/2026, junto com as logos) - "Servsolda" é o nome fantasia usado pelo cliente pra
# "Centro-Oeste" (chave interna do sistema), nunca o nome interno.
EMPRESA_INFO: Dict[str, Dict[str, str]] = {
    "servweld": {
        "nome_fantasia": "Servweld",
        "razao_social": "Servweld Assistência Técnica Transporte Locação e Comercial LTDA-ME",
        "cnpj": "11.504.286/0001-69",
        "endereco": "SQPS 104, Quadra 05, Conjunto A, Lote 05, Loja 02 - Guará I, Brasília-DF, CEP 71215-226",
        "telefone": "(61) 3234-6622",
        "email": "comercial@servweld.com.br",
        "logo_file": "servweld.png",
    },
    "centrooeste": {
        "nome_fantasia": "Servsolda",
        "razao_social": "Centro Oeste Serviços de Locação de Máquinas de Solda e Comércio de Equipamentos e Consumíveis LTDA",
        "cnpj": "54.804.458/0001-22",
        "endereco": "SQPS 104, Quadra 05, Conjunto A, Lote 05, Loja 02 - Guará I, Brasília-DF, CEP 71215-226",
        "telefone": "(61) 3234-6622",
        "email": "comercial@servsolda.com.br",
        "logo_file": "servsolda.png",
    },
}
EMPRESA_SUBTITLE = "Equipamentos de Solda, Corte e Assistência Técnica"


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _logo_flowable(logo_file: str, max_width: float, max_height: float) -> Optional[Image]:
    """Carrega a logo preservando proporção, limitada por altura OU largura (o que estourar
    primeiro) - as duas logos enviadas têm proporções bem diferentes (Servweld é bem mais
    larga/baixa que a Servsolda)."""
    path = os.path.join(_ASSETS_DIR, logo_file)
    if not os.path.isfile(path):
        return None
    try:
        reader = ImageReader(path)
        iw, ih = reader.getSize()
    except Exception:
        return None
    ratio = iw / ih
    w, h = max_width, max_width / ratio
    if h > max_height:
        h = max_height
        w = max_height * ratio
    return Image(path, width=w, height=h)


def generate_diagnostic_pdf(order, pecas: List[Dict[str, Any]], customer_message: str, empresa: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title=f"Diagnóstico O.S. {order.codos}"
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, textColor=BRAND_DARK, spaceAfter=0)
    subtitle = ParagraphStyle("subtitle", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#64748b"))
    label = ParagraphStyle("label", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#64748b"))
    value = ParagraphStyle("value", parent=styles["Normal"], fontSize=11, textColor=BRAND_DARK, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10.5, leading=15, textColor=BRAND_DARK)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=BRAND_GREEN, spaceBefore=10, spaceAfter=4)
    thead = ParagraphStyle("thead", parent=styles["Normal"], fontSize=9, textColor=colors.white, fontName="Helvetica-Bold")
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9.5, textColor=BRAND_DARK)
    footer = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#94a3b8"), leading=10)

    info = EMPRESA_INFO.get(empresa, {})
    empresa_nome = info.get("nome_fantasia", empresa.title())
    story = []

    logo = _logo_flowable(info.get("logo_file", ""), max_width=55 * mm, max_height=16 * mm)
    if logo:
        story.append(logo)
    else:
        story.append(Paragraph(empresa_nome, h1))
        story.append(Paragraph(EMPRESA_SUBTITLE, subtitle))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.2, color=BRAND_GREEN))
    story.append(Spacer(1, 12))

    info_data = [
        [Paragraph("O.S.", label), Paragraph("CLIENTE", label), Paragraph("EQUIPAMENTO", label), Paragraph("DATA", label)],
        [
            Paragraph(f"#{order.codos}", value),
            Paragraph(_clean_pdf_text(order.contato_nome or order.cliente) or "—", value),
            Paragraph(_clean_pdf_text(order.equipamento) or "—", value),
            Paragraph(datetime.now().strftime("%d/%m/%Y"), value),
        ],
    ]
    info_table = Table(info_data, colWidths=[doc.width * 0.15, doc.width * 0.35, doc.width * 0.35, doc.width * 0.15])
    info_table.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2), ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
    ]))
    story.append(info_table)
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_LINE))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Diagnóstico", h2))
    for paragrafo in (customer_message or "").split("\n"):
        if paragrafo.strip():
            story.append(Paragraph(_clean_pdf_text(paragrafo.strip()), body))
            story.append(Spacer(1, 4))

    if pecas:
        story.append(Paragraph("Peças e Serviços", h2))
        header = [Paragraph(t, thead) for t in ["Descrição", "Qtd.", "Valor Unit.", "Total"]]
        data = [header]
        total = 0.0
        for p in pecas:
            qtd = p.get("quantidade") or 1
            preco = p.get("preco") or 0
            item_total = qtd * preco
            total += item_total
            data.append([
                Paragraph(_clean_pdf_text(p.get("descricao")) or "—", cell),
                Paragraph(f"{qtd:g}", cell),
                Paragraph(_fmt_money(preco), cell),
                Paragraph(_fmt_money(item_total), cell),
            ])
        col_w = [doc.width * 0.52, doc.width * 0.12, doc.width * 0.18, doc.width * 0.18]
        t = Table(data, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.3, GREY_LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))

        valor_exibido = order.valor_total if order.valor_total is not None else total
        total_table = Table(
            [[Paragraph("VALOR TOTAL", label), Paragraph(_fmt_money(valor_exibido), value)]],
            colWidths=[doc.width * 0.82, doc.width * 0.18]
        )
        total_table.setStyle(TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT")]))
        story.append(total_table)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_LINE))
    story.append(Spacer(1, 4))
    if info:
        rodape_empresa = (
            f"{info['razao_social']} - CNPJ {info['cnpj']}<br/>"
            f"{info['endereco']}<br/>"
            f"Tel: {info['telefone']} - {info['email']}"
        )
        story.append(Paragraph(rodape_empresa, footer))
        story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Documento gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M')}. "
        "Este orçamento não substitui a nota fiscal/venda oficial.",
        footer
    ))

    doc.build(story)
    return buf.getvalue()
