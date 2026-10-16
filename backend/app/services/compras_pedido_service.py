import csv
import io
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

class ComprasPedidoService:
    @staticmethod
    def gerar_csv_telecontrol(itens: List[Dict[str, Any]], limite_linhas: int = 500) -> List[Dict[str, Any]]:
        """
        Gera arquivos CSV no padrão Telecontrol / Fabricante:
        Delimitador: ';'
        Layout: referencia;quantidade
        Limite de 500 linhas por arquivo.
        Retorna lista de dicts: [{"nome_arquivo": "...", "conteudo_csv": "..."}]
        """
        arquivos = []
        lote_atual = []
        lote_num = 1

        for it in itens:
            ref = str(it.get("referencia") or "").strip()
            qtd = float(it.get("quantidade") or 1.0)
            # Remove ponto flutuante se for número inteiro
            qtd_str = f"{int(qtd)}" if qtd.is_integer() else f"{qtd:.2f}".replace(".", ",")
            lote_atual.append((ref, qtd_str))

            if len(lote_atual) >= limite_linhas:
                arquivos.append(ComprasPedidoService._montar_csv_str(lote_atual, lote_num))
                lote_atual = []
                lote_num += 1

        if lote_atual or not arquivos:
            arquivos.append(ComprasPedidoService._montar_csv_str(lote_atual, lote_num if arquivos else None))

        return arquivos

    @staticmethod
    def _montar_csv_str(linhas: List[tuple], lote_num: Optional[int]) -> Dict[str, Any]:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
        for ref, qtd in linhas:
            writer.writerow([ref, qtd])
        
        nome = f"pedido_telecontrol{f'_parte{lote_num}' if lote_num else ''}.csv"
        return {
            "nome_arquivo": nome,
            "linhas_total": len(linhas),
            "conteudo_csv": output.getvalue()
        }

    @staticmethod
    def gerar_pdf_pedido(pedido: Dict[str, Any], itens: List[Dict[str, Any]]) -> bytes:
        """Gera PDF timbrado do pedido de compra para envio ao fornecedor."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontSize=16,
            leading=20,
            textColor=colors.HexColor('#1E293B'),
            spaceAfter=4
        )
        subtitle_style = ParagraphStyle(
            'SubtitleStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#64748B'),
            spaceAfter=12
        )
        normal_bold = ParagraphStyle(
            'NormalBold',
            parent=styles['Normal'],
            fontSize=9,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0F172A')
        )
        normal_text = ParagraphStyle(
            'NormalText',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#334155')
        )

        elements = []

        # Cabeçalho da Loja
        empresa_nome = "SERVWELD SOLUÇÕES EM SOLDA E CORTE" if pedido.get("empresa") == "servweld" else "CENTRO OESTE SOLDA E CORTE"
        elements.append(Paragraph(f"<b>{empresa_nome}</b>", title_style))
        elements.append(Paragraph(f"PEDIDO DE COMPRA DE PEÇAS / MATERIAIS — Nº {pedido.get('id'):05d}", subtitle_style))
        elements.append(Spacer(1, 8))

        # Dados do Fornecedor / Fabricante
        dt_criacao = pedido.get("criado_em")
        if isinstance(dt_criacao, datetime):
            dt_str = dt_criacao.strftime("%d/%m/%Y")
        else:
            dt_str = str(dt_criacao)[:10] if dt_criacao else datetime.now().strftime("%d/%m/%Y")

        info_header = [
            [
                Paragraph(f"<b>Fabricante / Fornecedor:</b> {pedido.get('fabricante_nome')}", normal_text),
                Paragraph(f"<b>Data:</b> {dt_str}", normal_text)
            ],
            [
                Paragraph(f"<b>Contato:</b> {pedido.get('contato_nome') or 'Depto Comercial'}", normal_text),
                Paragraph(f"<b>Status:</b> {str(pedido.get('status')).upper()}", normal_text)
            ]
        ]
        if pedido.get("fornecedor_email") or pedido.get("fornecedor_whatsapp"):
            info_header.append([
                Paragraph(f"<b>E-mail:</b> {pedido.get('fornecedor_email') or '-'}", normal_text),
                Paragraph(f"<b>WhatsApp:</b> {pedido.get('fornecedor_whatsapp') or '-'}", normal_text)
            ])

        t_header = Table(info_header, colWidths=[340, 200])
        t_header.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(t_header)
        elements.append(Spacer(1, 14))

        # Tabela de Itens
        table_data = [
            [
                Paragraph("<b>Item</b>", normal_bold),
                Paragraph("<b>Referência / Código</b>", normal_bold),
                Paragraph("<b>Descrição do Produto</b>", normal_bold),
                Paragraph("<b>Qtd</b>", normal_bold),
                Paragraph("<b>Un</b>", normal_bold),
            ]
        ]

        total_pecas = 0.0
        for idx, it in enumerate(itens, 1):
            qtd = float(it.get("quantidade") or 1.0)
            total_pecas += qtd
            qtd_str = f"{int(qtd)}" if qtd.is_integer() else f"{qtd:.2f}"
            table_data.append([
                Paragraph(f"{idx:02d}", normal_text),
                Paragraph(str(it.get("referencia") or "-"), normal_bold),
                Paragraph(str(it.get("descricao") or "-"), normal_text),
                Paragraph(qtd_str, normal_text),
                Paragraph(str(it.get("unidade") or "UN"), normal_text),
            ])

        t_itens = Table(table_data, colWidths=[35, 110, 295, 55, 45])
        t_itens.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('TOPPADDING', (0,0), (-1,0), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('ALIGN', (3,1), (3,-1), 'RIGHT'),
            ('ALIGN', (4,1), (4,-1), 'CENTER'),
        ]))
        elements.append(t_itens)
        elements.append(Spacer(1, 10))

        # Resumo final
        resumo_p = Paragraph(f"<b>Total de Itens:</b> {len(itens)} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Total de Peças:</b> {int(total_pecas) if total_pecas.is_integer() else total_pecas:.2f}", normal_text)
        elements.append(resumo_p)

        if pedido.get("observacao"):
            elements.append(Spacer(1, 10))
            elements.append(Paragraph(f"<b>Observações do Pedido:</b><br/>{pedido.get('observacao')}", normal_text))

        doc.build(elements)
        return buffer.getvalue()

    @staticmethod
    def verificar_similaridade(termo1: str, termo2: str) -> bool:
        """Verifica se há similaridade semântica ou de palavras-chave nos produtos."""
        if not termo1 or not termo2:
            return False
        
        def limpar(t: str):
            t = t.lower()
            t = re.sub(r"[^\w\s]", " ", t)
            return set(w for w in t.split() if len(w) > 2)

        palavras1 = limpar(termo1)
        palavras2 = limpar(termo2)
        
        if not palavras1 or not palavras2:
            return False

        # Palavras em comum
        intersecao = palavras1.intersection(palavras2)
        
        # Palavras-chave essenciais de solda/corte
        chaves_relevantes = {"tocha", "bico", "difusor", "isolador", "regulador", "eletrodo", "arame", "mascara", "cabo", "porta", "garra", "conector", "rolete", "guia"}
        inter_chaves = intersecao.intersection(chaves_relevantes)
        if inter_chaves:
            return True

        # Se mais de 40% das palavras baterem
        taxa = len(intersecao) / min(len(palavras1), len(palavras2))
        return taxa >= 0.4

