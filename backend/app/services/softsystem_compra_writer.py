"""
Lançamento da entrada de NF-e no Softsystem (Fase 5 do módulo Compras) - pedido do usuário em
14/10/2026: a entrada fechada no OminiChannel tem que ir para o Softsystem "atualizando tudo"
(compra, itens, contas a pagar, estoque pela quantidade CONTADA, custos e preço de venda).

Replica o que o próprio Softsystem grava ao fechar uma compra - estudado em 14/10/2026 na compra
2291 (ESAB, loja 1) e nas anteriores, no banco de produção (só leitura) e na cópia de teste:
  COMPRAS        cabeçalho; CODCOMPRA = último da loja + 1 (não há gerador); STATUS 2 = fechada
  ITEMSCOMPRA    um por item (PK LOJA+CODCOMPRA+NUMITEM)
  CPLANCAMENTOS  uma linha por parcela; PK é LOJA+DATALANCAMENTO, por isso cada parcela leva
                 1 segundo a mais (o Softsystem faz igual: 16:40:34, :35, :36)
  ESTOQUE        soma a quantidade; CUSTOAQUISICAO = preço unitário da nota; CUSTOSOMATORIO =
                 custo líquido unitário (nota - crédito ICMS + IPI + ST + frete); CUSTOPONDERADO =
                 média ponderada pelo estoque anterior; QTDULTIMACOMPRA / DATAULTIMAAQUISICAO
  PRODUTOS       PRECOAQUISICAO e PRECO (venda) - o trigger ALTERAPRECOPRODUTO do Softsystem
                 recalcula CMV, PRECOCALC e DATAPRECO sozinho
  PRODUTOSFORNECEDORES  vínculo produto x fornecedor x código do fornecedor (se ainda não houver)
Triggers do Softsystem (SET_EXPORT_*, ATUALIZAESTOQUEDIA_*) continuam rodando normalmente.

Tudo numa única transação Firebird: qualquer erro desfaz tudo (nunca fica compra pela metade).
`db_path` permite rodar contra a cópia de teste (~/fbtest/servsolda_teste.fdb na VM).
Horários gravados em horário de Brasília, como o Softsystem.
"""
import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import firebird.driver as fdb
from firebird.driver import TPB, Isolation, TraAccessMode

from app.services.softsystem_service import (
    DB_PATHS, LOJA_POR_EMPRESA, SOFTSYSTEM_CHARSET, SOFTSYSTEM_PASS, SOFTSYSTEM_USER, _s,
)

logger = logging.getLogger("softsystem_compra_writer")

OBS_ORIGEM = "Lançado pelo OminiChannel"


class LancamentoErro(Exception):
    """Impede o lançamento (nada é gravado) - mensagem vai para a tela."""


def _agora_brt() -> datetime:
    return (datetime.utcnow() - timedelta(hours=3)).replace(microsecond=0)


def _f(v, padrao: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else padrao
    except (TypeError, ValueError):
        return padrao


def cfop_entrada(cfop_saida: str, com_st: bool) -> str:
    """CFOP da nota do fornecedor (saída) -> CFOP de entrada da loja.
    5xxx->1xxx (mesmo estado), 6xxx->2xxx (outro estado), 7xxx->3xxx (exterior).
    Revenda com ST -> x403; bonificação/brinde -> x910; demais compras para revenda -> x102."""
    c = re.sub(r"\D", "", cfop_saida or "")
    if len(c) != 4:
        return ""
    prefixo = {"5": "1", "6": "2", "7": "3"}.get(c[0])
    if not prefixo:
        return c
    resto = c[1:]
    if resto in ("910", "911"):
        return prefixo + resto
    if com_st or resto in ("401", "402", "403", "404", "405"):
        return prefixo + "403"
    return prefixo + "102"


# ---------------------------------------------------------------------------- montagem (pura)
def _parcelas_validas(parcelas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parc = []
    for i, p in enumerate(parcelas or [], start=1):
        valor = _f(p.get("valor"))
        venc = p.get("vencimento")
        if valor <= 0 or not venc:
            continue
        parc.append({"numero": p.get("numero") or f"{i:03d}", "vencimento": str(venc)[:10], "valor": round(valor, 2)})
    return parc


def montar_plano(entrada: Dict[str, Any], itens: List[Dict[str, Any]], parcelas: List[Dict[str, Any]],
                 operador: str, parcelas_cte: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Converte a entrada do OminiChannel no que vai para o Softsystem - sem tocar no banco (testável).
    `itens`: dicts com os campos de ComprasEntradaItem + `calculo` (calculo_json já decodificado).
    Quantidades/preços vão na UNIDADE DA LOJA (quantidade da nota x fator_conversao).
    `entrada["cte"]`: CT-e interpretado quando a loja paga o frete (FOB) - o valor entra no frete
    da compra (VALORFRETEREAL, como a loja já faz) e vira conta a pagar da transportadora.
    """
    nota = entrada.get("nota") or {}
    totais = nota.get("totais") or {}
    erros: List[str] = []
    linhas = []
    for it in sorted(itens, key=lambda x: x.get("numero_item") or 0):
        calc = it.get("calculo") or {}
        cod = str(it.get("softsystem_prod_codigo") or "").strip()
        novo = it.get("cadastro_novo") or None
        if not cod.isdigit():
            if not novo or not novo.get("confirmado"):
                erros.append(f"Item {it.get('numero_item')} ({it.get('descricao_fornecedor')}) é produto novo: "
                             "abra \"Cadastro do produto novo\", confira a sugestão e confirme." if it.get("produto_modelo_codigo") or novo
                             else f"Item {it.get('numero_item')} ({it.get('descricao_fornecedor')}) não está vinculado a um produto do Softsystem.")
                continue
        fator = _f(it.get("fator_conversao"), 1.0) or 1.0
        qtd_nota = _f(it.get("quantidade")) * fator
        if qtd_nota <= 0:
            erros.append(f"Item {it.get('numero_item')} com quantidade zerada.")
            continue
        qtd_contada = it.get("qtd_contada")
        qtd_estoque = _f(qtd_contada) if qtd_contada is not None else qtd_nota
        valor_total = _f(it.get("valor_total"))
        preco_unit = valor_total / qtd_nota
        custo_liquido_total = _f(calc.get("custo_liquido_total"), valor_total)
        com_st = bool(calc.get("tem_st"))
        linhas.append({
            "numero_item": len(linhas) + 1,
            "codproduto": int(cod) if cod.isdigit() else None,
            "novo": novo if not cod.isdigit() else None,
            "item_id": it.get("id"),
            "codigo_fornecedor": (it.get("codigo_fornecedor") or "").strip(),
            "qtd_nota": round(qtd_nota, 4),
            "qtd_estoque": round(qtd_estoque, 4),
            "preco_unit": round(preco_unit, 6),
            "valor_total": round(valor_total, 2),
            "custo_unit_liquido": round(custo_liquido_total / qtd_nota, 6),
            "preco_venda": round(_f(it.get("preco_venda_final") or calc.get("preco_venda_final")), 2),
            "p_icms": _f(calc.get("p_icms")),
            "v_icms": _f(calc.get("v_icms")),
            "v_bc_icms": _f(calc.get("v_bc_icms")),
            "p_ipi": _f(calc.get("p_ipi")),
            "v_ipi": _f(calc.get("v_ipi") or it.get("v_ipi")),
            "v_icms_st": _f(calc.get("v_icms_st") or it.get("v_icms_st")),
            "v_bc_st": _f(calc.get("v_bc_st")),
            "credito_icms": _f(calc.get("credito_icms")),
            "cst_ipi": calc.get("cst_ipi") or "",
            "cst_pis": calc.get("cst_pis") or "",
            "cst_cofins": calc.get("cst_cofins") or "",
            "p_pis": _f(calc.get("p_pis")), "v_pis": _f(calc.get("v_pis")),
            "p_cofins": _f(calc.get("p_cofins")), "v_cofins": _f(calc.get("v_cofins")),
            "origem": calc.get("origem") or "",
            "csosn": calc.get("csosn") or "",
            "ncm": it.get("ncm") or calc.get("ncm") or "",
            "cfop_entrada": cfop_entrada(it.get("cfop") or calc.get("cfop") or "", com_st),
            "com_st": com_st,
        })
    if not linhas and not erros:
        erros.append("A entrada não tem itens.")

    parc = _parcelas_validas(parcelas)
    soma_parc = round(sum(p["valor"] for p in parc), 2)
    total_nota = round(_f(entrada.get("valor_total_nota") or totais.get("valor_total_nf")), 2)
    if parc and abs(soma_parc - total_nota) > 0.05:
        erros.append(f"As parcelas somam R$ {soma_parc:.2f}, mas a nota é de R$ {total_nota:.2f}. Ajuste os vencimentos antes de lançar.")

    # CT-e da transportadora (frete por conta da loja)
    cte_plano = None
    cte = entrada.get("cte") or {}
    valor_cte = round(_f(entrada.get("valor_frete_cte")), 2)
    if valor_cte > 0:
        transp = cte.get("transportadora") or {}
        cad = transp.get("cadastro") or {}
        cnpj_t = re.sub(r"\D", "", transp.get("cnpj") or cad.get("cnpj") or "")
        parc_cte = _parcelas_validas(parcelas_cte or [])
        if not cnpj_t:
            erros.append("O CT-e da transportadora não foi carregado por completo (sem CNPJ) - carregue o XML do CT-e de novo.")
        if not parc_cte:
            erros.append(f"Informe o vencimento do frete do CT-e {cte.get('numero_cte') or ''} (contas a pagar da transportadora).")
        elif abs(sum(p["valor"] for p in parc_cte) - valor_cte) > 0.05:
            erros.append(f"Os vencimentos do frete somam R$ {sum(p['valor'] for p in parc_cte):.2f}, mas o CT-e é de R$ {valor_cte:.2f}.")
        cte_plano = {
            "chave": cte.get("chave_acesso"),
            "numero": str(cte.get("numero_cte") or "").strip(),
            "data_emissao": cte.get("data_emissao"),
            "valor": valor_cte,
            "cnpj": cnpj_t,
            "nome": transp.get("razao_social") or cad.get("razao_social") or "",
            "cadastro": cad or None,
            "parcelas": parc_cte,
        }

    cfops = [l["cfop_entrada"] for l in linhas if l["cfop_entrada"]]
    cfop_cab = max(set(cfops), key=cfops.count) if cfops else ""
    aliqs = sorted({l["p_icms"] for l in linhas if l["p_icms"]})
    return {
        "erros": erros,
        "operador": (operador or "OMINICHANNEL").upper()[:20],
        "chave": entrada.get("chave_acesso"),
        "numero_nf": str(entrada.get("numero_nf") or nota.get("numero_nf") or "")[:10],
        "serie": str(entrada.get("serie") or nota.get("serie") or "0")[:3],
        "data_emissao": entrada.get("data_emissao"),
        "fornecedor_cnpj": re.sub(r"\D", "", entrada.get("fornecedor_cnpj") or ""),
        "fornecedor_nome": entrada.get("fornecedor_nome"),
        "fornecedor_cadastro": (nota.get("fornecedor") or {}).get("cadastro") or None,
        "cte": cte_plano,
        "entrada_id": entrada.get("id"),
        "cfop": cfop_cab,
        "aliq_icms": aliqs[0] if len(aliqs) == 1 else None,
        "totais": {
            "produtos": round(_f(totais.get("valor_produtos")) or sum(l["valor_total"] for l in linhas), 2),
            "frete": round(_f(totais.get("valor_frete")), 2),
            "frete_cte": cte_plano["valor"] if cte_plano else 0.0,
            "seguro": round(_f(totais.get("valor_seguro")), 2),
            "desconto": round(_f(totais.get("valor_desconto")), 2),
            "outras": round(_f(totais.get("valor_outras_despesas")), 2),
            "bc_icms": round(_f(totais.get("valor_bc_icms")), 2),
            "icms": round(_f(totais.get("valor_icms")), 2),
            "bc_st": round(_f(totais.get("valor_bc_st")), 2),
            "st": round(_f(totais.get("valor_st")) + _f(totais.get("valor_fcp_st")), 2),
            "ipi": round(_f(totais.get("valor_ipi")), 2),
            "credito_icms": round(sum(l["credito_icms"] for l in linhas), 2),
            "nota": total_nota,
            "peso_liquido": _f((nota.get("volumes") or {}).get("peso_liquido")),
            "peso_bruto": _f((nota.get("volumes") or {}).get("peso_bruto")),
        },
        "itens": linhas,
        "parcelas": parc,
    }


# ---------------------------------------------------------------------------- gravação
def _conectar(empresa: str, db_path: Optional[str]):
    if db_path:  # cópia de teste local (Firebird embutido na VM)
        return fdb.connect(db_path, user=SOFTSYSTEM_USER, charset=SOFTSYSTEM_CHARSET)
    return fdb.connect(DB_PATHS[empresa], user=SOFTSYSTEM_USER, password=SOFTSYSTEM_PASS, charset=SOFTSYSTEM_CHARSET)


class _Gravador:
    """INSERT/UPDATE por nome de coluna, convertendo cada valor para o tipo REAL da coluna no
    Firebird (lido do dicionário RDB$): o driver não aceita float em coluna NUMERIC/inteira, e
    montar por nome evita errar a ordem dos valores."""

    def __init__(self, cur):
        self.cur = cur
        self._tipos: Dict[str, Dict[str, tuple]] = {}

    def tipos(self, tabela: str) -> Dict[str, tuple]:
        if tabela not in self._tipos:
            self.cur.execute("""
                SELECT TRIM(rf.RDB$FIELD_NAME), f.RDB$FIELD_TYPE, COALESCE(f.RDB$FIELD_SCALE, 0), f.RDB$CHARACTER_LENGTH
                FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
                WHERE rf.RDB$RELATION_NAME = ?""", (tabela,))
            self._tipos[tabela] = {n: (t, s, l) for n, t, s, l in self.cur.fetchall()}
        return self._tipos[tabela]

    def _conv(self, tabela: str, col: str, v):
        if v is None:
            return None
        info = self.tipos(tabela).get(col)
        if not info:
            raise LancamentoErro(f"Coluna {tabela}.{col} não existe no Softsystem (versão diferente?).")
        tipo, escala, tamanho = info
        if tipo in (7, 8, 16):  # SMALLINT / INTEGER / BIGINT (com escala = NUMERIC/DECIMAL)
            if escala < 0:
                return Decimal(str(round(float(v), -escala)))
            return int(round(float(v)))
        if tipo in (10, 27):  # FLOAT / DOUBLE
            return float(v)
        if tipo in (14, 37):  # CHAR / VARCHAR - corta no tamanho da coluna
            s = str(v)
            return s[:tamanho] if tamanho else s
        return v

    def insert(self, tabela: str, valores: Dict[str, Any]):
        # coluna sem valor fica de fora (o banco aplica NULL/padrão): mandar NULL explícito em
        # SITTRIBIPI/PIS/COFINS (VARCHAR 2) dá "string right truncation" no driver - visto em 15/10/2026
        cols = [c for c, v in valores.items() if v is not None]
        self.cur.execute(
            f"INSERT INTO {tabela} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(self._conv(tabela, c, valores[c]) for c in cols),
        )

    def update(self, tabela: str, valores: Dict[str, Any], where: Dict[str, Any]):
        sets = list(valores)
        wh = list(where)
        self.cur.execute(
            f"UPDATE {tabela} SET {', '.join(f'{c} = ?' for c in sets)} WHERE {' AND '.join(f'{c} = ?' for c in wh)}",
            tuple(self._conv(tabela, c, valores[c]) for c in sets) + tuple(self._conv(tabela, c, where[c]) for c in wh),
        )


def _garantir_fornecedor(g: "_Gravador", um, cnpj: str, nome: str, cadastro: Optional[Dict[str, Any]],
                         op: str, agora: datetime, quem: str) -> tuple:
    """Código do fornecedor/transportadora pelo CNPJ; se não existir, cadastra com os dados do XML
    (mesmos campos que a loja preenche ao cadastrar no Softsystem - ver fornecedor 2000010).
    Devolve (codigo, criado: bool)."""
    forn = um("SELECT FIRST 1 CODFORNECEDOR FROM FORNECEDORES WHERE CGC = ? AND COALESCE(INATIVO, 'F') <> 'T'", (cnpj,))
    if forn:
        return _s(forn[0]), False
    cad = cadastro or {}
    if not cnpj or not (cad.get("razao_social") or nome):
        raise LancamentoErro(f"{quem} {nome} (CNPJ {cnpj}) não está cadastrado no Softsystem e o XML não traz os dados para cadastrar. Cadastre-o lá e tente de novo.")
    # código = maior código numérico + 1 (não há gerador; hoje a série está em 2000010)
    ult = um("SELECT MAX(CAST(CODFORNECEDOR AS BIGINT)) FROM FORNECEDORES WHERE CODFORNECEDOR SIMILAR TO '[0-9]+'")
    codigo = str((ult[0] or 0) + 1)
    ibge = re.sub(r"\D", "", str(cad.get("cod_ibge") or ""))
    g.insert("FORNECEDORES", {
        "CODFORNECEDOR": codigo, "RAZAOSOCIAL": (cad.get("razao_social") or nome).upper(),
        "NOMEFANTASIA": (cad.get("nome_fantasia") or "").upper() or None, "CGC": cnpj, "IE": cad.get("ie") or None,
        "ENDERECO": (cad.get("logradouro") or "").upper() or None, "BAIRRO": (cad.get("bairro") or "").upper() or None,
        "CIDADE": (cad.get("cidade") or "").upper() or None, "UF": (cad.get("uf") or "").upper() or None,
        "CEP": cad.get("cep") or None, "DDD": cad.get("ddd") or None, "FONE": cad.get("fone") or None,
        "OBS": f"{OBS_ORIGEM} a partir do XML", "DATACADASTRO": agora, "DATAATUALIZACAO": agora,
        "OPERADORCADASTRO": op, "OPERADORATUALIZACAO": op, "EXPORT": "T", "TRIGGERATIVA": "T",
        "CODCIDADEIBGE": int(ibge) if ibge else None, "CODPAIS": 1058, "PAIS": "BRASIL", "INATIVO": "F",
    })
    return codigo, True


# Campos do modelo que NÃO passam para o produto novo (identidade, preços/custos, datas, operador,
# controle de exportação/etiqueta e dados físicos do outro item). O resto (tributação, margens,
# unidade, tipo de frete, PIS/COFINS de entrada...) é copiado do modelo - pedido do usuário:
# "produto novo: perguntar qual produto simular e copiar o cadastro".
_NAO_COPIAR_DO_MODELO = {
    "CODPRODUTO", "CODORIGINAL", "DESCRICAO", "DESCRICAONF", "CODBARRAS", "CODREFERENCIA", "PRECO", "PRECOAUISICAO",
    "PRECOPROMOCAO", "PRECOAQUISICAO", "CMV", "PRECOCALC", "DATAATUALIZACAO", "DATAPROMOCAO", "DATAPROMOCAOINICIO",
    "DATAPRECO", "DATACADASTRO", "OPERADORCADASTRO", "OPERADORATUALIZACAO", "EXPORT", "LOTEEXPORT", "EXPORTWEB",
    "LLCALC_GRAVADO", "LLPROM_GRAVADO", "LOCALIZACAO", "CODFORNECEDOR", "CODFOR", "PRECOCOMP", "PRECOCOMP2", "CUSTOPART",
    "QTREAL", "DISP", "DISPONIBILIDADE", "ICMULTCOMP", "PESO", "PESOLIQUIDO", "MKPRECOAQUISICAO", "MKPRECOCALCULADO",
    "VALORADUANEIRO", "CODTABLOIDE", "CODGRUPOPROMOCAO", "CODFEIRA", "INATIVO", "FLAGETIQ", "EMISETIQ", "NUMEROITEM",
    "OBS", "FCI", "COD", "TAM", "COMP", "FAMILIA", "CODGRADE", "CEST", "NBM", "CODMARCA", "CODEMBALAGEM",
    "CODGRUPO", "CODSUBGRUPO", "CODSUBGRUPONIVEL2", "CODSUBGRUPONIVEL3", "TRIGGERATIVA",
}


def _criar_produto(g: "_Gravador", um, cur, cad: Dict[str, Any], linha: Dict[str, Any], cod_forn: str,
                   op: str, agora: datetime) -> int:
    """Cria o produto novo no Softsystem copiando o modelo + campos confirmados. Devolve o código."""
    ean = re.sub(r"\D", "", str(cad.get("ean") or ""))
    if len(ean) >= 8:
        ja = um("SELECT FIRST 1 CODPRODUTO, DESCRICAO FROM PRODUTOS WHERE CODBARRAS = ?", (ean,))
        if ja:
            raise LancamentoErro(f"Já existe o produto {ja[0]} ({_s(ja[1])}) com o EAN {ean} - vincule o item a ele em vez de cadastrar um novo.")
    else:
        ean = ""
    cur.execute("SELECT * FROM PRODUTOS WHERE CODPRODUTO = ?", (int(cad["modelo_codigo"]),))
    row = cur.fetchone()
    if not row:
        raise LancamentoErro(f"O produto modelo {cad['modelo_codigo']} não existe mais no Softsystem.")
    nomes = [d[0].strip() for d in cur.description]
    base = {k: v for k, v in zip(nomes, row) if k not in _NAO_COPIAR_DO_MODELO and v is not None}

    # marca nova (a pessoa confirmou um nome que não estava na lista)
    codmarca = cad.get("codmarca")
    if codmarca is None and cad.get("marca_nova"):
        nome_marca = str(cad["marca_nova"]).strip().upper()[:40]
        ja = um("SELECT FIRST 1 CODMARCA FROM MARCAS WHERE UPPER(TRIM(MARCA)) = ?", (nome_marca,))
        if ja:
            codmarca = int(ja[0])
        else:
            codmarca = (um("SELECT MAX(CODMARCA) FROM MARCAS")[0] or 0) + 1
            g.insert("MARCAS", {"CODMARCA": codmarca, "MARCA": nome_marca, "EXPORT": "T", "TRIGGERATIVA": "T"})

    # código: a loja cadastra na série 2000001+ (último + 1)
    ult = um("SELECT MAX(CODPRODUTO) FROM PRODUTOS WHERE CODPRODUTO >= 2000000")[0]
    codigo = int(ult) + 1 if ult else (um("SELECT MAX(CODPRODUTO) FROM PRODUTOS")[0] or 0) + 1
    g.insert("PRODUTOS", {
        **base,
        "CODPRODUTO": codigo,
        "DESCRICAO": str(cad["descricao"]).strip().upper()[:150],
        "CODEMBALAGEM": (cad.get("unidade") or "UN").upper()[:6],
        "CODGRUPO": cad.get("codgrupo"), "CODSUBGRUPO": cad.get("codsubgrupo"),
        "CODSUBGRUPONIVEL2": cad.get("codsubgruponivel2"), "CODSUBGRUPONIVEL3": cad.get("codsubgruponivel3"),
        "CODMARCA": codmarca,
        "NBM": re.sub(r"\D", "", str(cad.get("ncm") or "")) or None,
        "CEST": re.sub(r"\D", "", str(cad.get("cest") or "")) or None,
        "CODBARRAS": ean or None,
        "CODREFERENCIA": (str(cad.get("referencia") or "").strip()[:40] or None),
        "PESO": cad.get("peso") or None,
        "CODFORNECEDOR": cod_forn,
        "PRECO": linha.get("preco_venda") or None,
        "PRECOAQUISICAO": round(linha["preco_unit"], 4),
        "DATACADASTRO": agora, "DATAATUALIZACAO": agora, "OPERADORCADASTRO": op, "OPERADORATUALIZACAO": op,
        "INATIVO": "F", "EXPORTWEB": "F", "TRIGGERATIVA": "T",
        "OBS": f"{OBS_ORIGEM} (copiado do produto {cad['modelo_codigo']})",
    })
    return codigo


def lancar_compra(empresa: str, plano: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    if plano.get("erros"):
        raise LancamentoErro(" ".join(plano["erros"]))
    loja = LOJA_POR_EMPRESA[empresa]
    con = _conectar(empresa, db_path)
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION, lock_timeout=15)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        g = _Gravador(cur)

        def um(sql, params=()):
            cur.execute(sql, params)
            return cur.fetchone()

        # 1) nunca duplicar
        ja = um("SELECT FIRST 1 CODCOMPRA FROM COMPRAS WHERE LOJA = ? AND CHAVE = ? AND COALESCE(STATUS, 0) <> 9", (loja, plano["chave"]))
        if ja:
            raise LancamentoErro(f"Esta nota já está lançada no Softsystem (compra {ja[0]}).")

        agora = _agora_brt()
        op = plano["operador"]

        # 2) fornecedor (e transportadora do CT-e): se não existir, cadastra com os dados do XML
        cod_forn, forn_criado = _garantir_fornecedor(
            g, um, plano["fornecedor_cnpj"], plano["fornecedor_nome"], plano.get("fornecedor_cadastro"), op, agora, "O fornecedor")
        cte = plano.get("cte")
        cod_transp, transp_criada, cte_ja_lancado = None, False, False
        if cte:
            cod_transp, transp_criada = _garantir_fornecedor(
                g, um, cte["cnpj"], cte["nome"], cte.get("cadastro"), op, agora, "A transportadora")
            # CT-e lançado à mão no contas a pagar antes? não duplica a conta
            cte_ja_lancado = bool(cte["numero"]) and bool(um(
                "SELECT FIRST 1 1 FROM CPLANCAMENTOS WHERE LOJA = ? AND CODFORNECEDOR = ? AND NUMNOTA = ?",
                (loja, cod_transp, cte["numero"])))

        # 2b) produtos novos (cadastro confirmado na tela) - criados copiando o modelo
        produtos_criados: Dict[Any, int] = {}
        for l in plano["itens"]:
            if l["codproduto"] is None and l.get("novo"):
                l["codproduto"] = _criar_produto(g, um, cur, l["novo"], l, cod_forn, op, agora)
                produtos_criados[l.get("item_id") or l["numero_item"]] = l["codproduto"]

        # 3) produtos precisam existir
        prods: Dict[int, tuple] = {}
        for l in plano["itens"]:
            r = um("SELECT CODORIGINAL, DESCRICAO, CODCLFISCAL, NBM, SITTRIB FROM PRODUTOS WHERE CODPRODUTO = ?", (l["codproduto"],))
            if not r:
                raise LancamentoErro(f"Produto {l['codproduto']} (item {l['numero_item']}) não existe no Softsystem.")
            prods[l["codproduto"]] = r

        hoje = agora.replace(hour=0, minute=0, second=0)
        emissao = plano["data_emissao"]
        if isinstance(emissao, str) and emissao:
            emissao = datetime.fromisoformat(emissao[:19])
        t = plano["totais"]
        # frete real da compra = frete destacado na NF + CT-e pago pela loja (a loja já soma os
        # dois em VALORFRETEREAL; FATORFRETEP = frete / produtos, como nas compras 2272-2289)
        frete_real = round(t["frete"] + t.get("frete_cte", 0.0), 2)
        total_pecas = sum(l["qtd_nota"] for l in plano["itens"])

        # 4) número da compra (último da loja + 1, igual ao Softsystem)
        codcompra = (um("SELECT MAX(CODCOMPRA) FROM COMPRAS WHERE LOJA = ?", (loja,))[0] or 0) + 1

        # 5) cabeçalho (mesmos campos que o Softsystem preenche - ver compra 2291)
        g.insert("COMPRAS", {
            "LOJA": loja, "CODCOMPRA": codcompra, "CODFORNECEDOR": cod_forn, "DATA": hoje, "HORA": agora,
            "TOTALPRODUTOS": t["produtos"], "VALORFRETEREAL": frete_real or None,
            "FATORFRETEP": (frete_real / t["produtos"]) if frete_real and t["produtos"] else None,
            "TRANSPORTADORA": (cte["nome"].upper() if cte else None), "VALORICMSSUBST": t["st"] or None,
            "VALORIPI": t["ipi"] or None, "VALORCREDITOICMS": t["credito_icms"] or None,
            "VALOROUTRASDESPESAS": (t["outras"] + t["seguro"]) or None, "VALORDESCONTO": t["desconto"] or None,
            "OBS": f"{OBS_ORIGEM} (entrada #{plano['entrada_id']}) por {op}"
                   + (f" - frete CT-e {cte['numero']} R$ {cte['valor']:.2f} ({cte['nome']})" if cte else ""),
            "NUMERONOTA": plano["numero_nf"],
            "SERIENOTA": plano["serie"], "OPERADOR": op, "TOTALPAGO": t["nota"], "NUMEROPECAS": total_pecas,
            "MOVIMENTACAO": 1, "DATAEMISSAO": emissao, "ATUALIZARPRECOTABELA": "F", "EXPORT": "F",
            "CFOP": plano["cfop"] or None, "CFOPN": plano["cfop"] or None, "BASECALCICMS": t["bc_icms"] or None,
            "ALIQICMS": plano["aliq_icms"], "VALORICMS": t["icms"] or None, "BASECALCICMSSUBTRIB": t["bc_st"] or None,
            "VALORCONTABIL": t["nota"], "SUBSTRIB": "T" if t["st"] > 0 else "F", "STATUS": 2, "DATASTATUS": agora,
            "OPERADORSTATUS": op, "TOTALPEDIDO": t["nota"], "NUMPECASPED": total_pecas, "CONDICAOFRETE": 1,
            "TRIGGERATIVA": "T", "MODELONOTA": "55", "OPTANTESIMPLESNACIONAL": "F", "CHAVE": plano["chave"],
            "SOMARFRETEBASEIPI": "F", "PESOLIQUIDO": t["peso_liquido"] or None, "PESOBRUTO": t["peso_bruto"] or None,
        })

        # 6) itens
        for l in plano["itens"]:
            orig, desc, clfiscal, nbm, sittrib = prods[l["codproduto"]]
            g.insert("ITEMSCOMPRA", {
                "LOJA": loja, "CODCOMPRA": codcompra, "NUMITEM": l["numero_item"], "CODPRODUTO": l["codproduto"],
                "CODORIGINAL": orig, "DESCRICAO": desc, "QUANTIDADE": l["qtd_nota"], "PRECO": l["preco_unit"],
                "SITTRIB": sittrib, "IPI": l["p_ipi"] or None, "QUANTCHEGADA": l["qtd_estoque"], "LOTE": "0",
                "PRECOPEDIDO": l["preco_unit"], "QTDPEDIDO": l["qtd_nota"], "EXPORT": "F",
                "CREDITOICMS": l["p_icms"] or None, "TIPOFRETE": 1, "TRIGGERATIVA": "T",
                "PRECOVENDA": l["preco_venda"] or None, "CFOPN": l["cfop_entrada"] or None, "NBM": l["ncm"] or nbm,
                "USALOTE": "F", "CODCLFISCAL": clfiscal,
                "ORIGEMIMPORTACAO": int(l["origem"]) if str(l["origem"]).isdigit() else None,
                "SITTRIBIPI": l["cst_ipi"] or None, "SITTRIBPIS": l["cst_pis"] or None, "PIS": l["p_pis"] or None,
                "SITTRIBCOFINS": l["cst_cofins"] or None, "COFINS": l["p_cofins"] or None,
                "VALORCONTABIL": round(l["valor_total"] + l["v_ipi"] + l["v_icms_st"], 2),
                "BASEICMS": l["v_bc_icms"] or None, "VALORICMS": l["v_icms"] or None,
                "BASEICMSST": l["v_bc_st"] or None, "VALORICMSST": l["v_icms_st"] or None, "CSOSN": l["csosn"] or None,
                "VALORPIS": l["v_pis"] or None, "VALORCOFINS": l["v_cofins"] or None, "VALORIPI": l["v_ipi"] or None,
                "OBS": f"Contado: {l['qtd_estoque']:g}" if abs(l["qtd_estoque"] - l["qtd_nota"]) > 0.0001 else None,
            })

        # 7) contas a pagar - uma linha por parcela; DATALANCAMENTO é a chave da tabela, então
        # cada parcela leva 1 segundo a mais (igual ao Softsystem)
        emissao_cp = emissao or hoje
        momento = agora
        for p in plano["parcelas"]:
            while um("SELECT 1 FROM CPLANCAMENTOS WHERE LOJA = ? AND DATALANCAMENTO = ?", (loja, momento)):
                momento += timedelta(seconds=1)
            g.insert("CPLANCAMENTOS", {
                "LOJA": loja, "DATALANCAMENTO": momento, "CODFORNECEDOR": cod_forn,
                "DATAVENCIMENTO": datetime.fromisoformat(p["vencimento"]), "VALOR": p["valor"],
                "NUMDOCUMENTO": f"{plano['numero_nf']}-{str(p['numero'])[-3:].zfill(3)}", "NUMPEDIDO": codcompra,
                "DATAEMISSAO": emissao_cp, "OPERADOR": op, "NUMNOTA": plano["numero_nf"], "EXPORT": "F",
                "STATUS": 2, "TRIGGERATIVA": "T",
            })
            momento += timedelta(seconds=1)

        # 7b) contas a pagar da transportadora (CT-e), ligadas à mesma compra pelo NUMPEDIDO
        if cte and not cte_ja_lancado:
            emissao_cte = cte.get("data_emissao")
            emissao_cte = datetime.fromisoformat(emissao_cte[:19]) if isinstance(emissao_cte, str) and emissao_cte else emissao_cp
            for p in cte["parcelas"]:
                while um("SELECT 1 FROM CPLANCAMENTOS WHERE LOJA = ? AND DATALANCAMENTO = ?", (loja, momento)):
                    momento += timedelta(seconds=1)
                g.insert("CPLANCAMENTOS", {
                    "LOJA": loja, "DATALANCAMENTO": momento, "CODFORNECEDOR": cod_transp,
                    "DATAVENCIMENTO": datetime.fromisoformat(p["vencimento"]), "VALOR": p["valor"],
                    "NUMDOCUMENTO": f"{cte['numero']}-{str(p['numero'])[-3:].zfill(3)}", "NUMPEDIDO": codcompra,
                    "DATAEMISSAO": emissao_cte, "OPERADOR": op, "NUMNOTA": cte["numero"], "EXPORT": "F",
                    "HISTORICO": f"FRETE CT-E {cte['numero']} - NF {plano['numero_nf']} {plano['fornecedor_nome'] or ''}".upper(),
                    "STATUS": 2, "TRIGGERATIVA": "T",
                })
                momento += timedelta(seconds=1)

        # 8) estoque + custos (agrupa itens repetidos do mesmo produto)
        por_prod: "OrderedDict[int, Dict[str, float]]" = OrderedDict()
        for l in plano["itens"]:
            a = por_prod.setdefault(l["codproduto"], {"qtd_estoque": 0.0, "qtd_nota": 0.0, "custo_total": 0.0, "preco_total": 0.0, "preco_venda": 0.0})
            a["qtd_estoque"] += l["qtd_estoque"]
            a["qtd_nota"] += l["qtd_nota"]
            a["custo_total"] += l["custo_unit_liquido"] * l["qtd_nota"]
            a["preco_total"] += l["preco_unit"] * l["qtd_nota"]
            a["preco_venda"] = l["preco_venda"] or a["preco_venda"]
        estoque_antes = {}
        for cod, a in por_prod.items():
            custo_novo = a["custo_total"] / a["qtd_nota"]
            preco_novo = a["preco_total"] / a["qtd_nota"]
            # WITH LOCK: trava a linha até o fim da transação - uma venda no meio não se perde nem
            # bagunça a média ponderada
            atual = um("SELECT ESTOQUE, CUSTOPONDERADO FROM ESTOQUE WHERE LOJA = ? AND CODPRODUTO = ? AND LOTE = '0' WITH LOCK", (loja, cod))
            if atual:
                est_ant, pond_ant = _f(atual[0]), _f(atual[1])
                estoque_antes[cod] = est_ant
                if est_ant > 0 and pond_ant > 0:
                    pond = (est_ant * pond_ant + a["qtd_estoque"] * custo_novo) / (est_ant + a["qtd_estoque"])
                else:
                    pond = custo_novo
                cur.execute("UPDATE ESTOQUE SET ESTOQUE = COALESCE(ESTOQUE, 0) + ? WHERE LOJA = ? AND CODPRODUTO = ? AND LOTE = '0'",
                            (g._conv("ESTOQUE", "ESTOQUE", a["qtd_estoque"]), loja, cod))
                g.update("ESTOQUE", {
                    "CUSTOAQUISICAO": round(preco_novo, 4),
                    "CUSTOSOMATORIO": round(custo_novo, 4), "CUSTOPONDERADO": round(pond, 6),
                    "QTDULTIMACOMPRA": a["qtd_estoque"], "DATAULTIMAAQUISICAO": agora, "TRIGGERATIVA": "T",
                }, {"LOJA": loja, "CODPRODUTO": cod, "LOTE": "0"})
            else:
                estoque_antes[cod] = None
                g.insert("ESTOQUE", {
                    "LOJA": loja, "CODPRODUTO": cod, "LOTE": "0", "ESTOQUE": a["qtd_estoque"],
                    "CUSTOAQUISICAO": round(preco_novo, 4), "CUSTOSOMATORIO": round(custo_novo, 4),
                    "CUSTOPONDERADO": round(custo_novo, 6), "QTDULTIMACOMPRA": a["qtd_estoque"],
                    "DATAULTIMAAQUISICAO": agora, "EXPORT": "F", "TRIGGERATIVA": "T",
                })

            # 9) produto: preço de aquisição e de venda (o trigger ALTERAPRECOPRODUTO do Softsystem
            # recalcula CMV, PRECOCALC e DATAPRECO sozinho)
            campos = {"PRECOAQUISICAO": round(preco_novo, 4), "DATAATUALIZACAO": agora, "OPERADORATUALIZACAO": op, "TRIGGERATIVA": "T"}
            if a["preco_venda"] > 0:
                campos["PRECO"] = a["preco_venda"]
            g.update("PRODUTOS", campos, {"CODPRODUTO": cod})

        # 10) vínculo produto x fornecedor (código do fornecedor) - só se ainda não existir
        for l in plano["itens"]:
            ref = l["codigo_fornecedor"]
            if ref and not um("SELECT 1 FROM PRODUTOSFORNECEDORES WHERE CODPRODUTO = ? AND CODFORNECEDOR = ? AND CODREFERENCIA = ?",
                              (l["codproduto"], cod_forn, g._conv("PRODUTOSFORNECEDORES", "CODREFERENCIA", ref))):
                g.insert("PRODUTOSFORNECEDORES", {"CODPRODUTO": l["codproduto"], "CODFORNECEDOR": cod_forn,
                                                  "CODREFERENCIA": ref, "EXPORT": "F", "TRIGGERATIVA": "T"})

        tra.commit()
        logger.info(f"[SOFTSYSTEM] Compra {codcompra} (loja {loja}) lançada: NF {plano['numero_nf']}, {len(plano['itens'])} itens, "
                    f"{len(plano['parcelas'])} parcela(s), por {op}{' [TESTE ' + db_path + ']' if db_path else ''}.")
        return {"codcompra": codcompra, "loja": loja, "fornecedor": cod_forn, "fornecedor_criado": forn_criado,
                "transportadora": cod_transp, "transportadora_criada": transp_criada,
                "cte_lancado": bool(cte) and not cte_ja_lancado, "cte_ja_existia": cte_ja_lancado,
                "produtos_criados": produtos_criados,
                "estoque_antes": estoque_antes}
    except Exception:
        try:
            tra.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------- acerto de estoque
# Pedido do usuário em 15/10/2026: estoque do Softsystem não bate com o físico (ex.: eletrodo 913
# com 105 no sistema e 32 na prateleira). Grava um "Ajuste de Estoque" igual ao que a loja já faz
# no Softsystem (estudado nos ajustes 1021-1025 de produção):
#   AJUSTEESTOQUE       cabeçalho; CODAJUSTE = último da loja + 1; FECHADO 'T'; STATUS 1;
#                       NUMITEMSENT/NUMITEMSSAIDA = total de PEÇAS; VALORENTRADA/VALORSAIDA = qtd x custo
#   ITEMSAJUSTEENTRADA  sobras (físico > sistema)   } ESTOQUEATUAL = estoque ANTES do ajuste,
#   ITEMSAJUSTESAIDA    faltas (físico < sistema)   } PRECO = venda, PRECOCUSTO = custo médio
#   ESTOQUE             passa a ser exatamente a quantidade física contada
def lancar_ajuste(empresa: str, itens: List[Dict[str, Any]], operador: str, motivo: str,
                  db_path: Optional[str] = None) -> Dict[str, Any]:
    """itens: [{"codproduto": int, "quantidade_fisica": float}]. Calcula a diferença contra o
    estoque do momento (linha travada) - nunca contra um número velho da tela."""
    if not itens:
        raise LancamentoErro("Nenhum produto para acertar.")
    loja = LOJA_POR_EMPRESA[empresa]
    op = (operador or "OMINICHANNEL").upper()[:20]
    con = _conectar(empresa, db_path)
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION, lock_timeout=15)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        g = _Gravador(cur)

        def um(sql, params=()):
            cur.execute(sql, params)
            return cur.fetchone()

        agora = _agora_brt()
        entradas, saidas, resumo = [], [], []
        for it in itens:
            cod = int(it["codproduto"])
            fisica = round(_f(it["quantidade_fisica"]), 4)
            if fisica < 0:
                raise LancamentoErro(f"Quantidade física negativa no produto {cod}.")
            p = um("SELECT CODORIGINAL, DESCRICAO, CODEMBALAGEM, PRECO, PRECOAQUISICAO FROM PRODUTOS WHERE CODPRODUTO = ?", (cod,))
            if not p:
                raise LancamentoErro(f"Produto {cod} não existe no Softsystem.")
            e = um("SELECT ESTOQUE, CUSTOPONDERADO, CUSTOSOMATORIO FROM ESTOQUE WHERE LOJA = ? AND CODPRODUTO = ? AND LOTE = '0' WITH LOCK", (loja, cod))
            atual = _f(e[0]) if e else 0.0
            custo = (_f(e[1]) or _f(e[2])) if e else 0.0
            custo = custo or _f(p[4])
            dif = round(fisica - atual, 4)
            resumo.append({"codproduto": cod, "descricao": _s(p[1]), "antes": atual, "depois": fisica, "diferenca": dif})
            if abs(dif) < 0.0001:
                continue
            linha = {"cod": cod, "orig": _s(p[0]), "desc": _s(p[1]), "emb": _s(p[2]) or "UN", "qtd": abs(dif),
                     "preco": _f(p[3]), "custo": custo, "antes": atual}
            (entradas if dif > 0 else saidas).append(linha)
            if e:
                g.update("ESTOQUE", {"ESTOQUE": fisica, "TRIGGERATIVA": "T"}, {"LOJA": loja, "CODPRODUTO": cod, "LOTE": "0"})
            else:
                g.insert("ESTOQUE", {"LOJA": loja, "CODPRODUTO": cod, "LOTE": "0", "ESTOQUE": fisica, "CUSTOPONDERADO": custo or None,
                                     "EXPORT": "F", "TRIGGERATIVA": "T"})

        if not entradas and not saidas:
            tra.rollback()
            return {"codajuste": None, "loja": loja, "itens": resumo, "mensagem": "Nada a ajustar: o estoque do Softsystem já bate com o físico."}

        codajuste = (um("SELECT MAX(CODAJUSTE) FROM AJUSTEESTOQUE WHERE LOJA = ?", (loja,))[0] or 0) + 1
        g.insert("AJUSTEESTOQUE", {
            "LOJA": loja, "CODAJUSTE": codajuste, "OPERADOR": op,
            "NUMITEMSENT": sum(l["qtd"] for l in entradas) or None, "NUMITEMSSAIDA": sum(l["qtd"] for l in saidas) or None,
            "VALORENTRADA": round(sum(l["qtd"] * l["custo"] for l in entradas), 2) or None,
            "VALORSAIDA": round(sum(l["qtd"] * l["custo"] for l in saidas), 2) or None,
            "FECHADO": "T", "DATA": agora, "HORA": agora, "STATUS": 1, "EXPORT": "F", "DATASTATUS": agora,
            "OBS": f"{OBS_ORIGEM} - acerto de estoque por {op}: {motivo}".strip(),
        })
        for tabela, linhas in (("ITEMSAJUSTEENTRADA", entradas), ("ITEMSAJUSTESAIDA", saidas)):
            for n, l in enumerate(linhas, start=1):
                g.insert(tabela, {
                    "LOJA": loja, "CODAJUSTE": codajuste, "NUMITEM": n, "CODPRODUTO": l["cod"], "DESCRICAO": l["desc"],
                    "EMBALAGEM": l["emb"], "QUANTIDADE": l["qtd"], "PRECO": l["preco"] or None, "CODORIGINAL": l["orig"],
                    "LOTE": "0", "EXPORT": "F", "PRECOCUSTO": round(l["custo"], 4) or None, "ESTOQUEATUAL": l["antes"],
                })
        tra.commit()
        logger.info(f"[SOFTSYSTEM] Ajuste de estoque {codajuste} (loja {loja}) por {op}: {len(entradas)} entrada(s), "
                    f"{len(saidas)} saída(s){' [TESTE ' + db_path + ']' if db_path else ''}.")
        return {"codajuste": codajuste, "loja": loja, "itens": resumo,
                "mensagem": f"Ajuste de estoque {codajuste} gravado no Softsystem."}
    except Exception:
        try:
            tra.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------- localização
# Etapa 4 da entrada de nota (pedido do usuário em 15/10/2026): depois de lançar, a pessoa diz
# onde o material ficou guardado -> ESTOQUE.LOCALIZACAO (campo "Localização 1" do Softsystem).
def gravar_localizacao(empresa: str, locais: Dict[int, str], operador: str,
                       db_path: Optional[str] = None) -> Dict[str, Any]:
    """locais: {codproduto: "texto da localização"}. Só altera a linha do lote '0' (a que o
    Softsystem usa); produto sem linha de estoque é ignorado e devolvido em `sem_estoque`."""
    if not locais:
        return {"gravados": [], "sem_estoque": []}
    loja = LOJA_POR_EMPRESA[empresa]
    con = _conectar(empresa, db_path)
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION, lock_timeout=15)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        g = _Gravador(cur)
        gravados, sem_estoque = [], []
        for cod, loc in locais.items():
            cur.execute("SELECT 1 FROM ESTOQUE WHERE LOJA = ? AND CODPRODUTO = ? AND LOTE = '0'", (loja, int(cod)))
            if not cur.fetchone():
                sem_estoque.append(int(cod))
                continue
            g.update("ESTOQUE", {"LOCALIZACAO": (loc or "").strip().upper() or None, "TRIGGERATIVA": "T"},
                     {"LOJA": loja, "CODPRODUTO": int(cod), "LOTE": "0"})
            gravados.append(int(cod))
        tra.commit()
        logger.info(f"[SOFTSYSTEM] Localização gravada (loja {loja}) por {(operador or '')[:20]}: {gravados}"
                    f"{' [TESTE ' + db_path + ']' if db_path else ''}.")
        return {"gravados": gravados, "sem_estoque": sem_estoque}
    except Exception:
        try:
            tra.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------- preço depois do lançamento
# Pedido do usuário em 15/10/2026: "não consigo alterar o valor" - a entrada já tinha sido lançada e o
# preço de venda só ia para o Softsystem no lançamento. Grava PRODUTOS.PRECO (o trigger
# ALTERAPRECOPRODUTO recalcula CMV/PRECOCALC; o Guardião leva o cadastro para a Centro-Oeste).
def atualizar_preco_venda(empresa: str, precos: Dict[int, float], operador: str,
                          db_path: Optional[str] = None) -> List[int]:
    if not precos:
        return []
    op = (operador or "OMINICHANNEL").upper()[:20]
    con = _conectar(empresa, db_path)
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION, lock_timeout=15)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        g = _Gravador(cur)
        feitos = []
        agora = _agora_brt()
        for cod, preco in precos.items():
            if not preco or preco <= 0:
                raise LancamentoErro(f"Preço inválido para o produto {cod}.")
            g.update("PRODUTOS", {"PRECO": round(float(preco), 2), "DATAATUALIZACAO": agora, "OPERADORATUALIZACAO": op,
                                  "TRIGGERATIVA": "T"}, {"CODPRODUTO": int(cod)})
            feitos.append(int(cod))
        tra.commit()
        logger.info(f"[SOFTSYSTEM] Preço de venda atualizado por {op}: {precos}{' [TESTE]' if db_path else ''}")
        return feitos
    except Exception:
        try:
            tra.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass


def cadastrar_produto_direto(empresa: str, cad: Dict[str, Any], operador: str,
                             db_path: Optional[str] = None) -> int:
    """
    Cadastra um novo produto diretamente no Softsystem a partir do modelo base.
    Usado no Pedido de Compra / Balcão quando o item ainda não existe no catálogo.
    """
    loja = LOJA_POR_EMPRESA[empresa]
    op = (operador or "OMINICHANNEL").upper()[:20]
    con = _conectar(empresa, db_path)
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION, lock_timeout=15)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        g = _Gravador(cur)

        def um(sql, params=()):
            cur.execute(sql, params)
            return cur.fetchone()

        agora = _agora_brt()
        linha_mock = {
            "preco_venda": _f(cad.get("preco_venda")),
            "preco_unit": _f(cad.get("preco_custo")) or _f(cad.get("preco_aquisicao")) or 0.0,
        }
        cod_forn = str(cad.get("codfornecedor") or "0")
        novo_cod = _criar_produto(g, um, cur, cad, linha_mock, cod_forn, op, agora)
        tra.commit()
        logger.info(f"[SOFTSYSTEM] Produto {novo_cod} cadastrado diretamente por {op} ({cad.get('descricao')})")
        return novo_cod
    except Exception:
        try:
            tra.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass

