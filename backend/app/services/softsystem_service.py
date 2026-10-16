import os
import re
import unicodedata
from typing import Dict, Any, List, Optional
import firebird.driver as fdb
from firebird.driver import TPB, Isolation, TraAccessMode
import logging

logger = logging.getLogger("softsystem_service")

# Caminhos e credenciais do banco Firebird do Softsystem
SOFTSYSTEM_HOST = os.getenv("SOFTSYSTEM_HOST", "192.168.15.16")
SOFTSYSTEM_USER = os.getenv("SOFTSYSTEM_USER", "SYSDBA")
SOFTSYSTEM_PASS = os.getenv("SOFTSYSTEM_PASS", "masterkey")
SOFTSYSTEM_CHARSET = os.getenv("SOFTSYSTEM_CHARSET", "WIN1252")

DB_PATHS = {
    "servweld": f"{SOFTSYSTEM_HOST}:C:/Softsystem/Base/servsolda.fdb",
    "centrooeste": f"{SOFTSYSTEM_HOST}:C:/Softsystem/Base/CENTROOESTE.fdb",
}
# EMPRESA.CODLOJA de cada banco - ESTOQUE, COMPRAS e CPLANCAMENTOS são chaveados por loja
LOJA_POR_EMPRESA = {"servweld": 1, "centrooeste": 2}

PALAVRAS_IGNORADAS = {
    "COM", "PARA", "DE", "DA", "DO", "DAS", "DOS", "EM", "E", "C/", "S/", "UN", "PC", "PCS",
    "CX", "KIT", "TIPO", "MOD", "MODELO", "REF", "COD", "NOVO", "NOVA",
}

_SELECT_PRODUTO = """
    p.CODPRODUTO, p.CODORIGINAL, p.CODBARRAS, p.DESCRICAO, p.CODEMBALAGEM,
    g.GRUPO AS NOME_GRUPO, sg.SUBGRUPO AS NOME_SUBGRUPO,
    (SELECT COALESCE(SUM(e.ESTOQUE), 0) FROM ESTOQUE e WHERE e.CODPRODUTO = p.CODPRODUTO AND e.LOJA = ?) AS ESTOQUE,
    p.PRECO, p.PRECOAQUISICAO, p.NBM, p.CODCLFISCAL, p.SITTRIB, p.CODGRUPO, p.CODSUBGRUPO,
    p.CODMARCA, p.INATIVO,
    (SELECT FIRST 1 e.CUSTOPONDERADO FROM ESTOQUE e WHERE e.CODPRODUTO = p.CODPRODUTO AND e.LOJA = ?) AS CUSTO_MEDIO,
    (SELECT FIRST 1 e.DATAULTIMAAQUISICAO FROM ESTOQUE e WHERE e.CODPRODUTO = p.CODPRODUTO AND e.LOJA = ?
        ORDER BY e.DATAULTIMAAQUISICAO DESC) AS ULTIMA_COMPRA
"""
_FROM_PRODUTO = """
    FROM PRODUTOS p
    LEFT JOIN GRUPOS g ON g.CODGRUPO = p.CODGRUPO
    LEFT JOIN SUBGRUPOS sg ON sg.CODSUBGRUPO = p.CODSUBGRUPO AND sg.CODGRUPO = p.CODGRUPO
"""


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v))


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9/,.]+", " ", sem_acento.upper()).strip()


def _tokens(texto: str) -> List[str]:
    return [t for t in _normalizar(texto).replace(",", " ").split() if len(t) >= 2 and t not in PALAVRAS_IGNORADAS]


class SoftsystemService:
    @staticmethod
    def _get_connection(empresa: str):
        empresa_norm = (empresa or "").lower().strip()
        db_path = DB_PATHS.get(empresa_norm, DB_PATHS["servweld"])
        return fdb.connect(
            db_path,
            user=SOFTSYSTEM_USER,
            password=SOFTSYSTEM_PASS,
            charset=SOFTSYSTEM_CHARSET,
        )

    @classmethod
    def _consultar(cls, empresa: str, sql: str, params: tuple = ()) -> List[tuple]:
        """Executa SELECT numa transação explicitamente SOMENTE LEITURA."""
        conn = None
        try:
            conn = cls._get_connection(empresa)
            tpb = TPB(access_mode=TraAccessMode.READ, isolation=Isolation.READ_COMMITTED_RECORD_VERSION)
            tra = conn.transaction_manager(tpb.get_buffer())
            tra.begin()
            cur = tra.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            tra.commit()
            return rows
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _produto_dict(r: tuple) -> Dict[str, Any]:
        return {
            "codigo": r[0],
            "cod_original": _s(r[1]),
            "cod_barras": _s(r[2]),
            "descricao": _s(r[3]),
            "unidade": _s(r[4]) or "UN",
            "grupo": _s(r[5]),
            "subgrupo": _s(r[6]),
            "estoque": float(r[7] or 0.0),
            "preco_venda": float(r[8] or 0.0),
            "preco_aquisicao": float(r[9] or 0.0),
            "ncm": _s(r[10]),
            "cod_clfiscal": _s(r[11]),
            "sittrib": _s(r[12]),
            "cod_grupo": r[13],
            "cod_subgrupo": r[14],
            "cod_marca": r[15],
            "inativo": _s(r[16]) == "T",
            "custo_medio": float(r[17] or 0.0),
            "ultima_compra": r[18].isoformat() if r[18] else None,
        }

    @classmethod
    def _buscar(cls, empresa: str, where: str, params: tuple, limite: int) -> List[Dict[str, Any]]:
        loja = LOJA_POR_EMPRESA.get(empresa, 1)
        sql = f"SELECT FIRST {int(limite)} {_SELECT_PRODUTO} {_FROM_PRODUTO} WHERE {where}"
        rows = cls._consultar(empresa, sql, (loja, loja, loja) + params)
        return [cls._produto_dict(r) for r in rows]

    @classmethod
    def buscar_produtos(cls, empresa: str, termo: str, limite: int = 20) -> List[Dict[str, Any]]:
        """
        Busca produtos no Softsystem pelo código interno (CODPRODUTO),
        código original (CODORIGINAL), código de barras (CODBARRAS) ou descrição.
        """
        if not termo or not termo.strip():
            return []
        termo_clean = termo.strip()
        try:
            if termo_clean.isdigit():
                where = "p.CODPRODUTO = ? OR p.CODORIGINAL = ? OR p.CODBARRAS = ?"
                cod_int = int(termo_clean) if len(termo_clean) <= 9 else -1
                return cls._buscar(empresa, where, (cod_int, termo_clean, termo_clean), limite)
            where = "p.CODORIGINAL STARTING WITH ? OR UPPER(p.DESCRICAO) CONTAINING ?"
            return cls._buscar(empresa, where, (termo_clean.upper(), termo_clean.upper()), limite)
        except Exception as e:
            logger.error(f"Erro ao buscar produtos no Softsystem ({empresa}): {e}")
            raise

    @classmethod
    def buscar_por_codigo(cls, empresa: str, codigo: int) -> Optional[Dict[str, Any]]:
        """Busca exata pelo CODPRODUTO."""
        produtos = cls._buscar(empresa, "p.CODPRODUTO = ?", (int(codigo),), 1)
        return produtos[0] if produtos else None

    @classmethod
    def vincular_item(cls, empresa: str, cod_fornecedor_soft: Optional[str], item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Encontra o produto da loja para um item da nota, na ordem de confiabilidade:
        1. código do fornecedor já vinculado antes (PRODUTOSFORNECEDORES - é o "de-para" que o
           próprio Softsystem grava a cada entrada),
        2. EAN / código de barras,
        3. nada -> o usuário escolhe um similar ou cadastra.
        """
        cod_ref = _s(item.get("codigo_fornecedor"))
        if cod_fornecedor_soft and cod_ref:
            where = (
                "p.CODPRODUTO IN (SELECT pf.CODPRODUTO FROM PRODUTOSFORNECEDORES pf "
                "WHERE pf.CODFORNECEDOR = ? AND (pf.CODREFERENCIA = ? OR pf.CODREFERENCIA = ?))"
            )
            achados = cls._buscar(empresa, where, (cod_fornecedor_soft, cod_ref, cod_ref.lstrip("0")), 2)
            if achados:
                return {"metodo": "codigo_fornecedor", "produto": achados[0]}

        ean = _s(item.get("ean"))
        if ean and len(ean) >= 8:
            achados = cls._buscar(empresa, "p.CODBARRAS = ? AND COALESCE(p.INATIVO, 'F') <> 'T'", (ean,), 2)
            if not achados:
                where = "p.CODPRODUTO IN (SELECT pc.CODPRODUTO FROM PRODUTOSCODIGOS pc WHERE pc.CODBARRAS = ?)"
                try:
                    achados = cls._buscar(empresa, where, (ean,), 2)
                except Exception:
                    achados = []  # PRODUTOSCODIGOS pode não ter CODBARRAS em versões antigas
            if achados:
                return {"metodo": "ean", "produto": achados[0]}

        return {"metodo": None, "produto": None}

    @classmethod
    def buscar_similares(cls, empresa: str, descricao: str, ncm: Optional[str] = None, limite: int = 8) -> List[Dict[str, Any]]:
        """
        Sugere produtos parecidos para copiar o cadastro (grupo, NCM, tributação) quando o item
        da nota ainda não existe na loja. Pontua por palavras em comum + mesmo NCM.
        """
        toks = _tokens(descricao)
        if not toks and not ncm:
            return []
        # As palavras mais longas costumam ser as mais distintivas ("TOCHA", "ELETRODO", "6013")
        chaves = sorted(set(toks), key=len, reverse=True)[:3]
        candidatos: Dict[int, Dict[str, Any]] = {}
        consultas = []
        if chaves:
            consultas.append((" AND ".join(["UPPER(p.DESCRICAO) CONTAINING ?"] * min(2, len(chaves))), tuple(chaves[:2])))
            for c in chaves:
                consultas.append(("UPPER(p.DESCRICAO) CONTAINING ?", (c,)))
        if ncm:
            consultas.append(("p.NBM = ?", (re.sub(r"\D", "", ncm),)))
        for where, params in consultas:
            try:
                for p in cls._buscar(empresa, f"({where}) AND COALESCE(p.INATIVO, 'F') <> 'T'", params, 40):
                    candidatos[p["codigo"]] = p
            except Exception as e:
                logger.warning(f"Busca de similares falhou ({where}): {e}")
            if len(candidatos) >= 60:
                break

        ncm_limpo = re.sub(r"\D", "", ncm or "")
        set_toks = set(toks)
        ranqueados = []
        for p in candidatos.values():
            ptoks = set(_tokens(p["descricao"]))
            comuns = set_toks & ptoks
            score = len(comuns) / max(len(set_toks | ptoks), 1)
            if ncm_limpo and p["ncm"] == ncm_limpo:
                score += 0.35
            elif ncm_limpo and p["ncm"][:4] == ncm_limpo[:4]:
                score += 0.15
            ranqueados.append({**p, "similaridade": round(min(score, 1.0) * 100), "palavras_em_comum": sorted(comuns)})
        ranqueados.sort(key=lambda x: (-x["similaridade"], -x["estoque"]))
        return ranqueados[:limite]

    @classmethod
    def tributacao_produto(cls, empresa: str, cod_clfiscal: str) -> List[Dict[str, Any]]:
        """Regras de ICMS/PIS/COFINS da classificação fiscal (CLFISCAL) - uma linha por situação fiscal."""
        loja = LOJA_POR_EMPRESA.get(empresa, 1)
        rows = cls._consultar(empresa, """
            SELECT CODSITFISCAL, SITTRIB, ALIQUOTA, REDUCAOBASE, ICMSST, SITTRIBPIS, PIS,
                   SITTRIBCOFINS, COFINS, CODCFOP, CODSITOPSIMPNAC, CLASSTRIBIBSCBS
            FROM CLFISCAL WHERE CODCLFISCAL = ? AND LOJA = ?
        """, (cod_clfiscal, loja))
        return [{
            "cod_sitfiscal": _s(r[0]), "sittrib": _s(r[1]), "aliquota_icms": float(r[2] or 0),
            "reducao_base": float(r[3] or 0), "icms_st": float(r[4] or 0),
            "cst_pis": _s(r[5]), "pis": float(r[6] or 0), "cst_cofins": _s(r[7]), "cofins": float(r[8] or 0),
            "cfop": _s(r[9]), "csosn": r[10], "class_trib_ibscbs": _s(r[11]),
        } for r in rows]

    @classmethod
    def localizar_documento_destinado(cls, chave: str) -> Optional[Dict[str, Any]]:
        """
        Procura a chave em DOCUMENTOSDESTINADOS (o Softsystem sincroniza com a SEFAZ os
        documentos emitidos contra as lojas). Diz de qual loja é a nota e o NSU - que é o que
        permite baixar CT-e (só sai por NSU) e NF-e sem gastar consulta por chave.
        """
        for empresa in ("servweld", "centrooeste"):
            try:
                rows = cls._consultar(empresa, """
                    SELECT FIRST 1 NSU, TIPO, CGC, NOME, VALORTOTAL, SITUACAO, SITUACAOMANIFESTACAO, DATA
                    FROM DOCUMENTOSDESTINADOS
                    WHERE CHAVE = ? AND COALESCE(TIPOEVENTO, 0) = 0
                    ORDER BY DATA DESC
                """, (chave,))
            except Exception as e:
                logger.warning(f"Falha ao consultar DOCUMENTOSDESTINADOS ({empresa}): {e}")
                continue
            if rows:
                r = rows[0]
                return {
                    "empresa": empresa,
                    "nsu": _s(r[0]),
                    "tipo": r[1],
                    "emitente_cnpj": _s(r[2]),
                    "emitente_nome": _s(r[3]),
                    "valor_total": float(r[4] or 0),
                    "situacao": r[5],
                    "situacao_manifestacao": r[6],
                    "data": r[7].isoformat() if r[7] else None,
                }
        return None

    @classmethod
    def compra_ja_lancada(cls, empresa: str, chave: str) -> Optional[Dict[str, Any]]:
        """Evita entrada em dobro: a nota já foi lançada no Softsystem por fora do sistema?"""
        rows = cls._consultar(empresa, """
            SELECT FIRST 1 CODCOMPRA, STATUS, DATA, OPERADOR FROM COMPRAS
            WHERE CHAVE = ? AND COALESCE(STATUS, 0) <> 9
        """, (chave,))
        if not rows:
            return None
        r = rows[0]
        return {"codcompra": r[0], "status": r[1], "data": r[2].isoformat() if r[2] else None, "operador": _s(r[3])}

    @classmethod
    def listar_grupos(cls, empresa: str) -> List[Dict[str, Any]]:
        """Lista grupos e subgrupos cadastrados."""
        try:
            rows = cls._consultar(empresa, """
                SELECT g.CODGRUPO, g.GRUPO, sg.CODSUBGRUPO, sg.SUBGRUPO
                FROM GRUPOS g
                LEFT JOIN SUBGRUPOS sg ON sg.CODGRUPO = g.CODGRUPO
                ORDER BY g.GRUPO, sg.SUBGRUPO
            """)
        except Exception as e:
            logger.error(f"Erro ao listar grupos no Softsystem ({empresa}): {e}")
            return []

        grupos_map: Dict[int, Dict[str, Any]] = {}
        for cod_g, nome_g, cod_sg, nome_sg in rows:
            if cod_g not in grupos_map:
                grupos_map[cod_g] = {"cod_grupo": cod_g, "nome_grupo": _s(nome_g), "subgrupos": []}
            if cod_sg is not None and nome_sg:
                grupos_map[cod_g]["subgrupos"].append({"cod_subgrupo": cod_sg, "nome_subgrupo": _s(nome_sg)})
        return list(grupos_map.values())

    # ------------------------------------------------------------------ localização / estoque
    # Pedido do usuário em 14/10/2026: na contagem da mercadoria mostrar ONDE o produto fica - no
    # Softsystem é a aba Estoque do produto, campos "Localização 1/2/3" (por loja/lote, tabela
    # ESTOQUE) - e o estoque atual (campo ESTOQUE). Os nomes das colunas de localização são
    # descobertos no próprio banco (RDB$RELATION_FIELDS, colunas de texto que começam com
    # "LOCALIZ") em vez de fixos aqui - não temos o dicionário de dados oficial do Softsystem.
    _colunas_localizacao: Dict[str, List[str]] = {}

    @classmethod
    def colunas_localizacao(cls, empresa: str) -> List[str]:
        if empresa in cls._colunas_localizacao:
            return cls._colunas_localizacao[empresa]
        rows = cls._consultar(empresa, """
            SELECT TRIM(rf.RDB$FIELD_NAME)
            FROM RDB$RELATION_FIELDS rf
            JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
            WHERE rf.RDB$RELATION_NAME = 'ESTOQUE'
              AND rf.RDB$FIELD_NAME STARTING WITH 'LOCALIZ'
              AND f.RDB$FIELD_TYPE IN (14, 37)
            ORDER BY rf.RDB$FIELD_POSITION
        """)
        cols = [c for (c,) in rows if c and re.fullmatch(r"[A-Z0-9_]+", c)]
        cls._colunas_localizacao[empresa] = cols
        logger.info(f"Colunas de localização em ESTOQUE ({empresa}): {cols}")
        return cols

    @classmethod
    def localizacao_estoque(cls, empresa: str, codigos: List[int]) -> Dict[int, Dict[str, Any]]:
        """{codproduto: {"localizacao": "A3 · P2", "estoque": 5.0}} da loja da empresa (soma os lotes)."""
        codigos = sorted({int(str(c).strip()) for c in codigos if c is not None and str(c).strip().isdigit()})
        if not codigos:
            return {}
        cols = cls.colunas_localizacao(empresa)
        loja = LOJA_POR_EMPRESA.get(empresa, 1)
        extra = "".join(f", e.{c}" for c in cols)
        resultado: Dict[int, Dict[str, Any]] = {}
        for i in range(0, len(codigos), 200):
            lote = codigos[i:i + 200]
            marcas = ", ".join("?" for _ in lote)
            rows = cls._consultar(
                empresa,
                f"SELECT e.CODPRODUTO, e.ESTOQUE{extra} FROM ESTOQUE e WHERE e.LOJA = ? AND e.CODPRODUTO IN ({marcas})",
                (loja, *lote),
            )
            for r in rows:
                cod = int(r[0])
                item = resultado.setdefault(cod, {"estoque": 0.0, "_locs": []})
                item["estoque"] += float(r[1] or 0)
                for v in r[2:]:
                    v = _s(v)
                    if v and v not in item["_locs"]:
                        item["_locs"].append(v)
        for item in resultado.values():
            item["localizacao"] = " · ".join(item.pop("_locs")) or None
            item["estoque"] = round(item["estoque"], 3)
        return resultado

    @classmethod
    def buscar_fornecedor_por_cnpj(cls, empresa: str, cnpj: str) -> Optional[Dict[str, Any]]:
        """Busca fornecedor no Softsystem pelo CNPJ (campo CGC)."""
        cnpj_clean = re.sub(r"\D", "", cnpj or "")
        if not cnpj_clean:
            return None
        try:
            rows = cls._consultar(empresa, """
                SELECT FIRST 1 CODFORNECEDOR, RAZAOSOCIAL, NOMEFANTASIA, CGC
                FROM FORNECEDORES
                WHERE CGC = ? AND COALESCE(INATIVO, 'F') <> 'T'
            """, (cnpj_clean,))
        except Exception as e:
            logger.error(f"Erro ao buscar fornecedor ({empresa}): {e}")
            return None
        if not rows:
            return None
        r = rows[0]
        return {"codigo": _s(r[0]), "razao_social": _s(r[1]), "nome_fantasia": _s(r[2]), "cnpj": _s(r[3])}
