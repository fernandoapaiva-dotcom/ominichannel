"""
Cadastro inteligente de produto novo (etapa 2 da entrada de nota - pedido do usuário em 15/10/2026).

Item da nota que ainda não existe na loja: a pessoa escolhe um produto PARECIDO como modelo e a IA
SUGERE o cadastro no padrão da casa - a pessoa CONFIRMA (decisão do usuário: "IA sugere, pessoa
confirma"). O produto é criado no Softsystem no lançamento da nota, copiando o cadastro do modelo
(tributação, margens, unidade...) com os campos confirmados por cima.

Padrão da casa para a descrição (ex. do usuário: "BICO DE CONTATO ROSCA M-6 28X8.0MM FURO 0.8MM"):
  O QUE É (nome do item) + TIPO/VARIAÇÃO + MEDIDAS + APLICAÇÃO/MODELO compatível [- MARCA quando faz parte]
  tudo em MAIÚSCULAS, sem acento, medidas com ponto decimal e unidade colada (0.8MM, 15KG, 10M),
  dimensões com X (28X8.0MM), "P/" para "para", "C/" para "com", sem código do fornecedor.
A IA recebe descrições reais do mesmo subgrupo do modelo como guia de estilo.
"""
import asyncio
import json
import logging
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

from app.services.softsystem_service import SoftsystemService, _s

logger = logging.getLogger("cadastro_produto_service")

MODELO_IA = "gemini-3.6-flash"
_ARVORE_TTL_S = 600
_cache_arvore: Dict[str, tuple] = {}


def normalizar_descricao(texto: str) -> str:
    """Maiúsculas, sem acento, espaços simples, até 150 caracteres (tamanho de PRODUTOS.DESCRICAO)."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).upper()
    t = re.sub(r"\s+", " ", t).strip()
    return t[:150]


def arvore(empresa: str) -> Dict[str, Any]:
    """Grupos > subgrupos N1 > N2 > N3 e marcas do Softsystem (cache de 10 min)."""
    agora = time.time()
    c = _cache_arvore.get(empresa)
    if c and agora - c[0] < _ARVORE_TTL_S:
        return c[1]
    q = lambda sql: SoftsystemService._consultar(empresa, sql)  # noqa: E731
    grupos = {int(r[0]): {"codigo": int(r[0]), "nome": _s(r[1]), "subgrupos": {}} for r in q("SELECT CODGRUPO, GRUPO FROM GRUPOS")}
    for g, s, n in q("SELECT CODGRUPO, CODSUBGRUPO, SUBGRUPO FROM SUBGRUPOS"):
        if int(g) in grupos:
            grupos[int(g)]["subgrupos"][int(s)] = {"codigo": int(s), "nome": _s(n), "nivel2": {}}
    for g, s, n2, n in q("SELECT CODGRUPO, CODSUBGRUPO, CODSUBGRUPONIVEL2, SUBGRUPONIVEL2 FROM SUBGRUPOSNIVEL2"):
        sg = grupos.get(int(g), {}).get("subgrupos", {}).get(int(s))
        if sg is not None:
            sg["nivel2"][int(n2)] = {"codigo": int(n2), "nome": _s(n), "nivel3": {}}
    for g, s, n2, n3, n in q("SELECT CODGRUPO, CODSUBGRUPO, CODSUBGRUPONIVEL2, CODSUBGRUPONIVEL3, SUBGRUPONIVEL3 FROM SUBGRUPOSNIVEL3"):
        nv2 = grupos.get(int(g), {}).get("subgrupos", {}).get(int(s), {}).get("nivel2", {}).get(int(n2))
        if nv2 is not None:
            nv2["nivel3"][int(n3)] = {"codigo": int(n3), "nome": _s(n)}
    marcas = sorted(({"codigo": int(r[0]), "nome": _s(r[1])} for r in q("SELECT CODMARCA, MARCA FROM MARCAS") if _s(r[1])),
                    key=lambda m: m["nome"])

    def lista(d, filhos=None):
        out = []
        for v in sorted(d.values(), key=lambda x: x["nome"]):
            item = {"codigo": v["codigo"], "nome": v["nome"]}
            if filhos and filhos in v:
                prox = {"subgrupos": "nivel2", "nivel2": "nivel3"}.get(filhos)
                item[filhos] = lista(v[filhos], prox)
            out.append(item)
        return out

    res = {"grupos": lista(grupos, "subgrupos"), "marcas": marcas}
    _cache_arvore[empresa] = (agora, res)
    return res


def caminho(arv: Dict[str, Any], g, s=None, n2=None, n3=None) -> Optional[str]:
    """'GRUPO > SUB > N2 > N3' se os códigos existirem na árvore (None se o grupo não existir)."""
    def acha(lst, cod):
        return next((x for x in lst or [] if cod is not None and x["codigo"] == int(cod)), None)
    gg = acha(arv["grupos"], g)
    if not gg:
        return None
    nomes = [gg["nome"]]
    ss = acha(gg.get("subgrupos"), s)
    if ss:
        nomes.append(ss["nome"])
        nn2 = acha(ss.get("nivel2"), n2)
        if nn2:
            nomes.append(nn2["nome"])
            nn3 = acha(nn2.get("nivel3"), n3)
            if nn3:
                nomes.append(nn3["nome"])
    return " > ".join(nomes)


def classificacao_valida(arv: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, Any]:
    """Zera os níveis que não existem na árvore (a IA pode inventar código)."""
    def acha(lst, cod):
        try:
            return next((x for x in lst or [] if x["codigo"] == int(cod)), None)
        except (TypeError, ValueError):
            return None
    out = {"codgrupo": None, "codsubgrupo": None, "codsubgruponivel2": None, "codsubgruponivel3": None}
    g = acha(arv["grupos"], c.get("codgrupo"))
    if not g:
        return out
    out["codgrupo"] = g["codigo"]
    s = acha(g.get("subgrupos"), c.get("codsubgrupo"))
    if not s:
        return out
    out["codsubgrupo"] = s["codigo"]
    n2 = acha(s.get("nivel2"), c.get("codsubgruponivel2"))
    if not n2:
        return out
    out["codsubgruponivel2"] = n2["codigo"]
    n3 = acha(n2.get("nivel3"), c.get("codsubgruponivel3"))
    if n3:
        out["codsubgruponivel3"] = n3["codigo"]
    return out


def produto_modelo(empresa: str, codigo: int) -> Optional[Dict[str, Any]]:
    r = SoftsystemService._consultar(empresa, """
        SELECT CODPRODUTO, DESCRICAO, CODEMBALAGEM, CODGRUPO, CODSUBGRUPO, CODSUBGRUPONIVEL2, CODSUBGRUPONIVEL3,
               CODMARCA, NBM, CEST, CODCLFISCAL, SITTRIB, PESO, CODREFERENCIA
        FROM PRODUTOS WHERE CODPRODUTO = ?""", (int(codigo),))
    if not r:
        return None
    x = r[0]
    return {"codigo": int(x[0]), "descricao": _s(x[1]), "unidade": _s(x[2]) or "UN", "codgrupo": x[3], "codsubgrupo": x[4],
            "codsubgruponivel2": x[5], "codsubgruponivel3": x[6], "codmarca": x[7], "ncm": _s(x[8]), "cest": _s(x[9]),
            "codclfiscal": _s(x[10]), "sittrib": _s(x[11]), "peso": float(x[12] or 0) or None, "referencia": _s(x[13])}


def exemplos_descricao(empresa: str, m: Dict[str, Any], limite: int = 25) -> List[str]:
    """Descrições reais da loja no mesmo N3 (ou N2/subgrupo) do modelo - guia de estilo para a IA."""
    filtros = [("CODGRUPO", m.get("codgrupo")), ("CODSUBGRUPO", m.get("codsubgrupo")),
               ("CODSUBGRUPONIVEL2", m.get("codsubgruponivel2")), ("CODSUBGRUPONIVEL3", m.get("codsubgruponivel3"))]
    filtros = [(c, v) for c, v in filtros if v is not None]
    vistos: List[str] = []
    while filtros:
        where = " AND ".join(f"{c} = ?" for c, _ in filtros)
        rows = SoftsystemService._consultar(
            empresa, f"SELECT FIRST {limite * 2} DESCRICAO FROM PRODUTOS WHERE {where} AND COALESCE(INATIVO,'F') <> 'T' "
                     "ORDER BY DATACADASTRO DESC NULLS LAST", tuple(v for _, v in filtros))
        for (d,) in rows:
            d = _s(d)
            if d and d not in vistos:
                vistos.append(d)
        if len(vistos) >= 12:
            break
        filtros = filtros[:-1]
    return vistos[:limite]


def _sugestao_sem_ia(item: Dict[str, Any], m: Optional[Dict[str, Any]], arv: Dict[str, Any]) -> Dict[str, Any]:
    base = m or {}
    cls = classificacao_valida(arv, base)
    return {
        "descricao": normalizar_descricao(item.get("descricao_fornecedor") or ""),
        **cls,
        "codmarca": base.get("codmarca"), "marca_nova": None,
        "unidade": base.get("unidade") or (item.get("unidade") or "UN").upper()[:6],
        "ncm": re.sub(r"\D", "", item.get("ncm") or "") or base.get("ncm"),
        "cest": re.sub(r"\D", "", item.get("cest") or "") or base.get("cest") or None,
        "ean": item.get("ean") or None,
        "referencia": (item.get("codigo_fornecedor") or "")[:40] or None,
        "peso": base.get("peso"),
        "explicacao": "Sugestão sem IA: classificação copiada do modelo e descrição do fornecedor padronizada.",
        "origem": "modelo",
    }


async def sugerir(empresa: str, item: Dict[str, Any], modelo_codigo: Optional[int], fornecedor_nome: str,
                  api_key: Optional[str]) -> Dict[str, Any]:
    """Sugestão de cadastro para o item da nota. Sempre devolve algo (sem IA, copia o modelo)."""
    arv = await asyncio.to_thread(arvore, empresa)
    m = await asyncio.to_thread(produto_modelo, empresa, modelo_codigo) if modelo_codigo else None
    base = _sugestao_sem_ia(item, m, arv)
    if not api_key:
        return {**base, "explicacao": "IA sem chave configurada - " + base["explicacao"]}
    exemplos = await asyncio.to_thread(exemplos_descricao, empresa, m) if m else []

    # árvore compacta só do grupo do modelo (+ nomes dos outros grupos) para não gastar token à toa
    def grupo_txt(g):
        linhas = [f"GRUPO {g['codigo']} {g['nome']}"]
        for s in g.get("subgrupos", []):
            linhas.append(f"  SUB {s['codigo']} {s['nome']}")
            for n2 in s.get("nivel2", []):
                linhas.append(f"    N2 {n2['codigo']} {n2['nome']}")
                for n3 in n2.get("nivel3", []):
                    linhas.append(f"      N3 {n3['codigo']} {n3['nome']}")
        return "\n".join(linhas)
    g_modelo = next((g for g in arv["grupos"] if m and g["codigo"] == m.get("codgrupo")), None)
    arvore_txt = grupo_txt(g_modelo) if g_modelo else ""
    outros = ", ".join(f"{g['codigo']} {g['nome']}" for g in arv["grupos"])
    marcas_txt = ", ".join(f"{x['codigo']} {x['nome']}" for x in arv["marcas"])
    modelo_txt = (f"{m['descricao']} | classificação: {caminho(arv, m['codgrupo'], m['codsubgrupo'], m['codsubgruponivel2'], m['codsubgruponivel3'])}"
                  f" (códigos {m['codgrupo']}/{m['codsubgrupo']}/{m['codsubgruponivel2']}/{m['codsubgruponivel3']}) | unidade {m['unidade']}"
                  if m else "nenhum")

    prompt = f"""Você cadastra produtos numa loja de solda, corte, EPI e ferramentas (Servsolda / Servweld).
Monte o cadastro do produto NOVO abaixo no PADRÃO DA CASA.

PRODUTO NA NOTA DO FORNECEDOR ({fornecedor_nome}):
- descrição do fornecedor: {item.get('descricao_fornecedor')}
- código do fornecedor: {item.get('codigo_fornecedor') or '-'} | EAN: {item.get('ean') or '-'} | NCM: {item.get('ncm') or '-'} | unidade: {item.get('unidade') or '-'}
- informação adicional do item: {item.get('info_adicional') or '-'}

PRODUTO MODELO escolhido pela loja (parecido; copiar a classificação dele quando servir): {modelo_txt}

DESCRIÇÕES REAIS da loja no mesmo subgrupo (siga ESTE estilo):
{chr(10).join('- ' + e for e in exemplos) or '- (sem exemplos)'}

REGRAS DA DESCRIÇÃO (padrão da casa, ex.: "BICO DE CONTATO ROSCA M-6 28X8.0MM FURO 0.8MM"):
1. Ordem: O QUE É + tipo/variação + MEDIDAS + aplicação/modelo compatível; marca só no fim quando o item é da marca (ex. "- ESAB").
2. MAIÚSCULAS, sem acento, sem código do fornecedor, sem palavras de marketing.
3. Medidas com ponto decimal e unidade colada: 0.8MM, 3.25MM, 15KG, 5M, 220V; dimensões com X (28X8.0MM); rosca como M-6.
4. Abreviações da casa: P/ (para), C/ (com), S/ (sem). Máximo 120 caracteres.
5. Não invente medida que não está na nota.

CLASSIFICAÇÃO - árvore do grupo do modelo:
{arvore_txt or '(sem modelo)'}
Outros grupos (código nome): {outros}

MARCAS cadastradas (código nome): {marcas_txt}

Responda SOMENTE um JSON:
{{"descricao": "...", "codgrupo": 0, "codsubgrupo": 0, "codsubgruponivel2": 0, "codsubgruponivel3": 0,
 "codmarca": 0 ou null, "marca_nova": "NOME" ou null (só se a marca do produto não estiver na lista),
 "unidade": "UN|PC|CX|RL|KG|M|PAR|JG|KIT", "referencia": "código/modelo do fabricante ou null",
 "peso_kg": número ou null, "explicacao": "uma frase dizendo por que escolheu essa classificação"}}"""

    try:
        from google import genai
        from app.services.ia_consumo_service import instalar
        instalar()  # tokens/custo vão para o painel Admin > Consumo de IA
        client = genai.Client(api_key=api_key)
        cfg = genai.types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1,
                                                thinking_config=genai.types.ThinkingConfig(thinking_level="MINIMAL"))
        resp = await asyncio.wait_for(asyncio.to_thread(
            client.models.generate_content, model=MODELO_IA, contents=prompt, config=cfg), timeout=60)
        ia = json.loads((resp.text or "").strip() or "{}")
    except Exception as e:
        logger.warning(f"[CADASTRO] IA indisponível para '{item.get('descricao_fornecedor')}': {e}")
        return {**base, "explicacao": f"IA indisponível agora ({type(e).__name__}) - " + base["explicacao"]}

    cls = classificacao_valida(arv, ia)
    if cls["codgrupo"] is None:  # IA errou o grupo: fica a do modelo
        cls = classificacao_valida(arv, m or {})
    codmarca = ia.get("codmarca")
    if codmarca is not None and not any(x["codigo"] == _int(codmarca) for x in arv["marcas"]):
        codmarca = None
    marca_nova = normalizar_descricao(ia.get("marca_nova") or "")[:40] or None
    if marca_nova:
        existente = next((x for x in arv["marcas"] if x["nome"] == marca_nova), None)
        if existente:
            codmarca, marca_nova = existente["codigo"], None
    return {
        **base,
        "descricao": normalizar_descricao(ia.get("descricao") or "") or base["descricao"],
        **cls,
        "codmarca": _int(codmarca) if codmarca is not None else (None if marca_nova else base["codmarca"]),
        "marca_nova": marca_nova,
        "unidade": (normalizar_descricao(ia.get("unidade") or "") or base["unidade"])[:6],
        "referencia": str(ia.get("referencia") or base["referencia"])[:40] if (ia.get("referencia") or base["referencia"]) else None,
        "peso": _float(ia.get("peso_kg")) or base["peso"],
        "explicacao": ia.get("explicacao") or "",
        "origem": "ia",
    }


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def validar_cadastro(arv: Dict[str, Any], cad: Dict[str, Any]) -> List[str]:
    """Confere o cadastro confirmado pela pessoa antes de gravar."""
    erros = []
    if len(normalizar_descricao(cad.get("descricao") or "")) < 5:
        erros.append("Descrição muito curta.")
    cls = classificacao_valida(arv, cad)
    if cls["codgrupo"] is None or cls["codsubgrupo"] is None:
        erros.append("Escolha pelo menos o grupo e o subgrupo.")
    if not re.sub(r"\D", "", cad.get("ncm") or ""):
        erros.append("Informe o NCM.")
    if not cad.get("modelo_codigo"):
        erros.append("Escolha o produto modelo (de onde vem a tributação).")
    if cad.get("codmarca") is None and not cad.get("marca_nova"):
        erros.append("Escolha a marca (ou informe uma nova).")
    return erros
