"""
Custo real de entrada e formação de preço de venda por loja.

Servweld - Lucro Presumido (ICMS regime normal, PIS/COFINS cumulativos):
  - credita o ICMS próprio destacado na nota (e no CT-e, quando a loja é a tomadora) -> sai do custo
  - não credita PIS/COFINS (regime cumulativo) nem IPI (comércio)
  - na venda paga ICMS (alíquota da classificação fiscal, 20% no DF), PIS 0,65%, COFINS 3%,
    IRPJ/CSLL presumidos - todos entram no divisor do preço
  - item com ICMS-ST: o imposto já foi pago na cadeia, não há crédito nem ICMS na venda

Centro Oeste - Simples Nacional:
  - não credita nada: todo imposto pago na compra é custo
  - na venda paga a alíquota efetiva do DAS; item com ST tira do DAS a parcela do ICMS

Preço = custo líquido unitário / (1 - (impostos na venda % + custo fixo % + despesas variáveis % + margem %))
O custo fixo entra como % do faturamento (aluguel + folha + ... / faturamento médio), não como
% sobre o custo - é o método de markup divisor usado por SEBRAE e pelos ERPs de varejo.
"""
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional
import logging
import math
import re

logger = logging.getLogger("compras_custo_service")

CST_COM_ST = {"10", "30", "60", "70", "90"}      # CST ICMS com substituição tributária
CSOSN_COM_ST = {"201", "202", "203", "500"}
CST_SEM_CREDITO = {"40", "41", "50", "60"}        # isenta / não tributada / suspensa / ST retida

# Valores de partida quando a loja ainda não configurou os parâmetros (conferir com o contador)
PADROES_LOJA = {
    "servweld": {
        "regime_tributario": "lucro_presumido",
        "icms_saida_pct": 20.0,           # alíquota interna DF da CLFISCAL 001
        "pis_saida_pct": 0.65,
        "cofins_saida_pct": 3.0,
        "irpj_csll_pct": 2.28,            # IRPJ 15% x 8% + CSLL 9% x 12% (comércio)
        "das_pct": 0.0,
        "das_parcela_icms_pct": 0.0,
        "icms_antecipacao_pct": 0.0,
        "despesas_variaveis_pct": 5.0,    # cartão, comissão, frete de entrega
        "margem_lucro_padrao_pct": 25.0,
        "margem_minima_pct": 10.0,
        "custo_fixo_operacional_pct": 12.0,
    },
    "centrooeste": {
        "regime_tributario": "simples_nacional",
        "icms_saida_pct": 0.0,
        "pis_saida_pct": 0.0,
        "cofins_saida_pct": 0.0,
        "irpj_csll_pct": 0.0,
        "das_pct": 8.5,                   # alíquota efetiva do Anexo I (varia com o faturamento de 12 meses)
        "das_parcela_icms_pct": 33.5,     # quanto do DAS é ICMS (Anexo I) - sai do DAS em item com ST
        "icms_antecipacao_pct": 0.0,
        "despesas_variaveis_pct": 5.0,
        "margem_lucro_padrao_pct": 30.0,
        "margem_minima_pct": 10.0,
        "custo_fixo_operacional_pct": 10.0,
    },
}


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def item_tem_st(item: Dict[str, Any]) -> bool:
    return (
        _f(item.get("v_icms_st")) > 0
        or _f(item.get("v_icms_st_ret")) > 0
        or (item.get("cst_icms") or "") in CST_COM_ST
        or (item.get("csosn") or "") in CSOSN_COM_ST
    )


class ComprasCustoService:
    @staticmethod
    def parametros_efetivos(empresa: str, salvos: Optional[Dict[str, Any]] = None,
                            custo_fixo_calculado_pct: Optional[float] = None) -> Dict[str, Any]:
        """Junta padrões + parâmetros salvos; se houver custos fixos lançados, o % vem deles."""
        p = dict(PADROES_LOJA.get(empresa, PADROES_LOJA["servweld"]))
        for k, v in (salvos or {}).items():
            if v is not None and k in p:
                p[k] = v
        p["custo_fixo_origem"] = "manual"
        if custo_fixo_calculado_pct is not None:
            p["custo_fixo_operacional_pct"] = round(custo_fixo_calculado_pct, 2)
            p["custo_fixo_origem"] = "custos_fixos_lancados"
        p["empresa"] = empresa
        return p

    @staticmethod
    def impostos_saida_pct(params: Dict[str, Any], com_st: bool) -> Dict[str, float]:
        if params["regime_tributario"] == "simples_nacional":
            das = _f(params["das_pct"])
            if com_st:
                das = das * (1 - _f(params["das_parcela_icms_pct"]) / 100.0)
            return {"das": round(das, 4)}
        return {
            "icms": 0.0 if com_st else _f(params["icms_saida_pct"]),
            "pis": _f(params["pis_saida_pct"]),
            "cofins": _f(params["cofins_saida_pct"]),
            "irpj_csll": _f(params["irpj_csll_pct"]),
        }

    @staticmethod
    def preco_por_margem(custo_unit: float, impostos_pct: float, params: Dict[str, Any], margem_pct: float) -> Optional[float]:
        deducoes = impostos_pct + _f(params["custo_fixo_operacional_pct"]) + _f(params["despesas_variaveis_pct"]) + margem_pct
        if deducoes >= 95.0 or custo_unit <= 0:
            return None
        return custo_unit / (1.0 - deducoes / 100.0)

    @staticmethod
    def margem_por_preco(custo_unit: float, impostos_pct: float, params: Dict[str, Any], preco: float) -> Optional[float]:
        if preco <= 0:
            return None
        return (1.0 - custo_unit / preco) * 100.0 - impostos_pct - _f(params["custo_fixo_operacional_pct"]) - _f(params["despesas_variaveis_pct"])

    @staticmethod
    def calcular(
        itens: List[Dict[str, Any]],
        totais: Dict[str, Any],
        params: Dict[str, Any],
        frete_cte: float = 0.0,
        icms_cte: float = 0.0,
        despesas_extras: Optional[List[Dict[str, Any]]] = None,
        tipo_rateio: str = "valor",
    ) -> Dict[str, Any]:
        """
        Calcula custo líquido unitário, impostos embutidos e preço sugerido de cada item.
        Frete/seguro/outras despesas da própria nota vêm por item no XML (vFrete, vSeg, vOutro);
        frete do CT-e e despesas extras são rateados por valor, quantidade ou peso.
        """
        regime = params["regime_tributario"]
        presumido = regime != "simples_nacional"
        total_extras = sum(_f(d.get("valor")) for d in (despesas_extras or []))

        soma_valor = sum(_f(i.get("valor_total")) for i in itens) or 1.0
        soma_qtd = sum(_f(i.get("quantidade"), 1.0) for i in itens) or 1.0

        # Frete da nota informado só no total (sem vFrete por item) -> rateia também
        frete_nota_itens = sum(_f(i.get("valor_frete_item")) for i in itens)
        frete_nota_sem_item = max(_f(totais.get("valor_frete")) - frete_nota_itens, 0.0)
        outras_itens = sum(_f(i.get("valor_outras_desp_item")) + _f(i.get("valor_seguro_item")) for i in itens)
        outras_sem_item = max(_f(totais.get("valor_outras_despesas")) + _f(totais.get("valor_seguro")) - outras_itens, 0.0)

        resultado = []
        for item in itens:
            qtd = _f(item.get("quantidade"), 1.0) or 1.0
            v_prod = _f(item.get("valor_total"))
            fator = (qtd / soma_qtd) if tipo_rateio == "quantidade" else (v_prod / soma_valor)
            com_st = item_tem_st(item)

            frete_item = _f(item.get("valor_frete_item")) + frete_nota_sem_item * fator
            outras_item = _f(item.get("valor_outras_desp_item")) + _f(item.get("valor_seguro_item")) + outras_sem_item * fator
            frete_cte_item = frete_cte * fator
            extras_item = total_extras * fator
            desconto = _f(item.get("valor_desconto_item"))
            v_ipi = _f(item.get("v_ipi"))
            v_st = _f(item.get("v_icms_st")) + _f(item.get("v_fcp_st"))

            # ICMS antecipado na entrada interestadual (configurável; no Presumido vira crédito,
            # então só pesa no custo do Simples)
            antecipacao = 0.0
            if (item.get("cfop") or "").startswith("6") and not com_st and not presumido:
                antecipacao = (v_prod + v_ipi + frete_item - desconto) * _f(params.get("icms_antecipacao_pct")) / 100.0

            custo_bruto = v_prod - desconto + v_ipi + v_st + frete_item + outras_item + frete_cte_item + extras_item + antecipacao

            # Créditos recuperáveis (só regime normal de ICMS - Servweld)
            credito_icms = 0.0
            credito_icms_cte = 0.0
            if presumido and not com_st and (item.get("cst_icms") or "") not in CST_SEM_CREDITO:
                credito_icms = _f(item.get("v_icms")) or _f(item.get("v_cred_icms_sn"))
                credito_icms_cte = icms_cte * fator
            creditos = credito_icms + credito_icms_cte

            custo_liquido = custo_bruto - creditos
            custo_unit = custo_liquido / qtd

            impostos = ComprasCustoService.impostos_saida_pct(params, com_st)
            impostos_pct = sum(impostos.values())
            margem = _f(item.get("margem_lucro_pct"), _f(params["margem_lucro_padrao_pct"]))
            preco_sugerido = ComprasCustoService.preco_por_margem(custo_unit, impostos_pct, params, margem)

            preco_final = _f(item.get("preco_venda_final")) or (round(preco_sugerido, 2) if preco_sugerido else 0.0)
            margem_real = ComprasCustoService.margem_por_preco(custo_unit, impostos_pct, params, preco_final)

            # Opções de margem para o usuário escolher na finalização
            opcoes = []
            if preco_sugerido:
                opcoes.append({"rotulo": "Margem padrão da loja", "margem_pct": round(margem, 1), "preco": round(preco_sugerido, 2)})
            preco_atual = _f(item.get("softsystem_preco_venda"))
            if preco_atual > 0:
                m = ComprasCustoService.margem_por_preco(custo_unit, impostos_pct, params, preco_atual)
                if m is not None:
                    opcoes.append({"rotulo": "Manter preço atual do Softsystem", "margem_pct": round(m, 1), "preco": round(preco_atual, 2)})
            med = _f(item.get("preco_mercado_med"))
            if med > 0:
                alvo = round(med * 0.98, 2)  # um pouco abaixo da média do mercado
                m = ComprasCustoService.margem_por_preco(custo_unit, impostos_pct, params, alvo)
                if m is not None:
                    opcoes.append({"rotulo": "Alinhado ao mercado (2% abaixo da média)", "margem_pct": round(m, 1), "preco": alvo,
                                   "abaixo_da_minima": m < _f(params["margem_minima_pct"])})

            # Composição do preço final em R$ (para o gráfico/tabela "para onde vai cada real")
            composicao = None
            if preco_final > 0:
                composicao = {
                    "custo_mercadoria": round(custo_unit, 2),
                    "impostos_venda": round(preco_final * impostos_pct / 100.0, 2),
                    "custo_fixo": round(preco_final * _f(params["custo_fixo_operacional_pct"]) / 100.0, 2),
                    "despesas_variaveis": round(preco_final * _f(params["despesas_variaveis_pct"]) / 100.0, 2),
                }
                composicao["lucro"] = round(preco_final - sum(composicao.values()), 2)

            alertas = []
            if margem_real is not None and margem_real < _f(params["margem_minima_pct"]):
                alertas.append(f"Margem real {margem_real:.1f}% abaixo da mínima da loja ({_f(params['margem_minima_pct']):.0f}%).")
            custo_anterior = _f(item.get("softsystem_custo_medio")) or _f(item.get("softsystem_preco_aquisicao"))
            variacao_custo = None
            if custo_anterior > 0:
                variacao_custo = (custo_unit / custo_anterior - 1) * 100.0
                if abs(variacao_custo) >= 10:
                    alertas.append(f"Custo {'subiu' if variacao_custo > 0 else 'caiu'} {abs(variacao_custo):.0f}% em relação ao custo atual do Softsystem.")
            if preco_sugerido is None:
                alertas.append("Soma de impostos, custo fixo, despesas e margem passa de 95% - preço não calculável.")

            r = dict(item)
            r.update({
                "tem_st": com_st,
                "frete_rateado": round(frete_item + frete_cte_item, 2),
                "frete_cte_rateado": round(frete_cte_item, 2),
                "desp_acessorias_rateada": round(outras_item, 2),
                "despesas_extras_rateada": round(extras_item, 2),
                "icms_antecipacao": round(antecipacao, 2),
                "custo_bruto_total": round(custo_bruto, 2),
                "credito_icms": round(credito_icms, 2),
                "credito_icms_cte": round(credito_icms_cte, 2),
                "custo_liquido_total": round(custo_liquido, 2),
                "custo_unitario_fornecedor": round(v_prod / qtd, 4),
                "custo_unitario_real": round(custo_unit, 4),
                "impostos_saida": impostos,
                "impostos_saida_pct": round(impostos_pct, 2),
                "custo_fixo_pct": _f(params["custo_fixo_operacional_pct"]),
                "despesas_variaveis_pct": _f(params["despesas_variaveis_pct"]),
                "margem_minima_pct": _f(params["margem_minima_pct"]),
                "custo_fixo_rateado": round((preco_final or 0) * _f(params["custo_fixo_operacional_pct"]) / 100.0, 2),
                "margem_lucro_pct": round(margem, 2),
                "preco_venda_sugerido": round(preco_sugerido, 2) if preco_sugerido else 0.0,
                "preco_venda_final": round(preco_final, 2),
                "margem_real_pct": round(margem_real, 2) if margem_real is not None else None,
                "markup_multiplicador": round(preco_final / custo_unit, 3) if custo_unit > 0 and preco_final else None,
                "variacao_custo_pct": round(variacao_custo, 1) if variacao_custo is not None else None,
                "opcoes_margem": opcoes,
                "composicao_preco": composicao,
                "alertas": alertas,
                "empresa_regime": regime,
            })
            resultado.append(r)

        resumo = {
            "valor_produtos": round(sum(_f(i.get("valor_total")) for i in itens), 2),
            "custo_bruto_total": round(sum(r["custo_bruto_total"] for r in resultado), 2),
            "creditos_total": round(sum(r["credito_icms"] + r["credito_icms_cte"] for r in resultado), 2),
            "custo_liquido_total": round(sum(r["custo_liquido_total"] for r in resultado), 2),
            "frete_cte": round(frete_cte, 2),
            "despesas_extras": round(total_extras, 2),
            "venda_total_prevista": round(sum(r["preco_venda_final"] * _f(r.get("quantidade"), 1.0) for r in resultado), 2),
        }
        resumo["lucro_previsto"] = round(sum(
            (r["composicao_preco"] or {}).get("lucro", 0) * _f(r.get("quantidade"), 1.0) for r in resultado
        ), 2)
        return {"itens": resultado, "resumo": resumo, "parametros": params}

    @staticmethod
    def gerar_parcelas(valor_total: float, data_base: date, condicao: str) -> List[Dict[str, Any]]:
        """
        Gera parcelas a partir de uma condição tipo "30/60/90" (dias após a data base).
        Os centavos são truncados e a sobra vai para a última parcela - mesmo critério do
        Softsystem (ex.: 1742,36 em 3x = 580,78 + 580,78 + 580,80).
        """
        dias = [int(d) for d in re.findall(r"\d+", condicao or "")] or [0]
        n = len(dias)
        base = math.floor(round(valor_total * 100 / n, 6)) / 100
        parcelas = []
        for idx, d in enumerate(dias):
            valor = base if idx < n - 1 else round(valor_total - base * (n - 1), 2)
            parcelas.append({
                "numero": f"{idx + 1:03d}",
                "vencimento": (data_base + timedelta(days=d)).isoformat(),
                "valor": valor,
                "origem": "condicao",
            })
        return parcelas

    @staticmethod
    def vencimentos_no_texto(texto: str, total: float, data_base: date) -> Optional[Dict[str, Any]]:
        """
        Pedido do usuário (15/10/2026): fornecedor que não manda as duplicatas no XML costuma
        escrever os vencimentos nos dados adicionais - ex.: "VENCIMENTOS: 15/11/2026 R$ 500,00
        15/12/2026 R$ 500,00", "COND. PAGTO 30/60/90 DDL", "BOLETO 28 DIAS". Lê o texto e devolve
        {"parcelas": [...], "trecho": "..."} ou None. A pessoa sempre confere na tela.
        """
        if not texto or total <= 0:
            return None
        achou = _RX_PALAVRA_PGTO.search(texto)
        if not achou:
            return None
        janela = texto[achou.start():achou.start() + 500]

        # 1) datas explícitas (com ou sem valor ao lado)
        datas = []
        for m in _RX_DATA.finditer(janela):
            d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            a = a + 2000 if a < 100 else a
            try:
                dt = date(a, mes, d)
            except ValueError:
                continue
            if data_base - timedelta(days=1) <= dt <= data_base + timedelta(days=540):
                datas.append((m, dt))
        if datas:
            valores = []
            for i, (m, _) in enumerate(datas):
                fim = datas[i + 1][0].start() if i + 1 < len(datas) else len(janela)
                ini = datas[i - 1][0].end() if i > 0 else 0
                depois = _RX_VALOR.search(janela[m.end():min(fim, m.end() + 40)])
                antes = list(_RX_VALOR.finditer(janela[max(ini, m.start() - 40):m.start()]))
                v = depois.group(1) if depois else (antes[-1].group(1) if antes else None)
                valores.append(_valor_br(v) if v else None)
            trecho = janela[:datas[-1][0].end() + 20].strip()
            if all(v for v in valores) and abs(sum(valores) - total) <= 0.05:
                return {"trecho": trecho, "parcelas": [
                    {"numero": f"{i + 1:03d}", "vencimento": dt.isoformat(), "valor": round(v, 2), "origem": "dados_adicionais"}
                    for i, ((_, dt), v) in enumerate(zip(datas, valores))]}
            # datas sem valor (ou valores que não fecham com a nota): divide o total pelas datas
            n = len(datas)
            base = math.floor(round(total * 100 / n, 6)) / 100
            return {"trecho": trecho, "parcelas": [
                {"numero": f"{i + 1:03d}", "vencimento": dt.isoformat(),
                 "valor": base if i < n - 1 else round(total - base * (n - 1), 2), "origem": "dados_adicionais"}
                for i, (_, dt) in enumerate(datas)]}

        # 2) prazo em dias ("30/60/90 DDL", "28 DIAS", "DDL 30/60")
        m = _RX_PRAZO.search(janela) or _RX_PRAZO_PREFIXO.search(janela)
        if m:
            dias = [int(x) for x in re.findall(r"\d+", m.group(1))]
            if dias and all(0 <= x <= 365 for x in dias) and dias == sorted(dias):
                parc = ComprasCustoService.gerar_parcelas(total, data_base, "/".join(map(str, dias)))
                for p in parc:
                    p["origem"] = "dados_adicionais"
                return {"trecho": janela[:m.end()].strip(), "parcelas": parc}
        if _RX_A_VISTA.search(janela):
            return {"trecho": _RX_A_VISTA.search(janela).group(0), "parcelas": [
                {"numero": "001", "vencimento": data_base.isoformat(), "valor": round(total, 2), "origem": "dados_adicionais"}]}
        return None

    @staticmethod
    def parcelas_do_documento(doc: Dict[str, Any], total: float, condicao_padrao: str = "30") -> Dict[str, Any]:
        """
        Vencimentos de uma NF-e ou CT-e, nesta ordem: duplicatas do XML -> dados adicionais
        (texto do fornecedor) -> condição padrão da loja a partir da emissão.
        Devolve {"parcelas": [...], "origem": "xml"|"dados_adicionais"|"condicao", "trecho": str|None}.
        """
        dups = doc.get("duplicatas") or []
        if dups:
            return {"origem": "xml", "trecho": None, "parcelas": [{
                "numero": (d.get("numero") or f"{i + 1:03d}")[-3:].zfill(3),
                "vencimento": d.get("vencimento"),
                "valor": round(_f(d.get("valor")), 2),
                "origem": "xml",
            } for i, d in enumerate(dups)]}
        emissao = (doc.get("data_emissao") or "")[:10]
        try:
            data_base = datetime.strptime(emissao, "%Y-%m-%d").date()
        except ValueError:
            data_base = date.today()
        lido = ComprasCustoService.vencimentos_no_texto(doc.get("informacoes_complementares") or "", total, data_base)
        if lido:
            return {"origem": "dados_adicionais", "trecho": lido["trecho"], "parcelas": lido["parcelas"]}
        return {"origem": "condicao", "trecho": None,
                "parcelas": ComprasCustoService.gerar_parcelas(total, data_base, condicao_padrao)}

    @staticmethod
    def parcelas_da_nota(nota: Dict[str, Any], condicao_padrao: str = "30") -> List[Dict[str, Any]]:
        """Duplicatas do XML; sem elas, dados adicionais; sem nada, condição padrão a partir da emissão."""
        total = _f((nota.get("fatura") or {}).get("valor_liquido")) or _f((nota.get("totais") or {}).get("valor_total_nf"))
        return ComprasCustoService.parcelas_do_documento(nota, total, condicao_padrao)["parcelas"]


_RX_PALAVRA_PGTO = re.compile(r"venc|parcela|duplicata|boleto|pagto|pgto|pagamento|fatura|cobran|prazo|cond\.?\s*pag|ddl", re.I)
_RX_DATA = re.compile(r"(?<![\d/])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d/])")
_RX_VALOR = re.compile(r"(?:R\$\s*)?(?<![\d.,/])(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})(?![\d,])")
_RX_PRAZO = re.compile(r"(?<![\d/.,])(\d{1,3}(?:\s*[/\-]\s*\d{1,3}){0,11})\s*(?:dias|ddl|dd|d\.d\.l\.?)(?![a-z])", re.I)
_RX_PRAZO_PREFIXO = re.compile(r"(?:ddl|dias|prazo)\s*:?\s*(\d{1,3}(?:\s*[/\-]\s*\d{1,3}){0,11})(?![\d/])", re.I)
_RX_A_VISTA = re.compile(r"\b(?:a\s+vista|à\s+vista|antecipado)\b", re.I)


def _valor_br(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))
