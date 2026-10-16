"""
Catálogo do site (etapas 5 e 6 da entrada de nota - pedido do usuário em 15/10/2026).

- O OminiChannel é a fonte do catálogo: o que vai para o site, textos, ficha técnica, fotos
  tratadas, PDFs e vídeos ficam em catalogo_produtos / catalogo_midias.
- Preço, estoque, descrição, marca e grupos vêm SEMPRE do Softsystem (lidos na hora, com cache).
- Os textos da aba "Para Lojas Web" também são gravados no Softsystem (PRODUTOSWEB e
  VIDEOSPRODUTOS), respeitando a chave SOFTSYSTEM_COMPRAS_MODO (teste grava só na cópia).
- O site público (Hostinger) lê a API pública /api/v1/public/site, que devolve os dados no MESMO
  formato que o site servsolda_site já usava (Section / Product do Prisma), para mudar o mínimo nele.
  Menu do site = grupos (seção) > subgrupos N1 (subseção) do Softsystem.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.services.softsystem_service import LOJA_POR_EMPRESA, SoftsystemService, _s

logger = logging.getLogger("catalogo_service")

_RX_YT = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_cache_prod: Dict[str, tuple] = {}
_CACHE_S = 300


def youtube_id(url: str) -> Optional[str]:
    m = _RX_YT.search(url or "")
    return m.group(1) if m else None


# ------------------------------------------------------------------ leitura do Softsystem
def produtos_softsystem(empresa: str, codigos: List[int], usar_cache: bool = True) -> Dict[int, Dict[str, Any]]:
    """{cod: {descricao, preco, estoque, grupo..., marca, ncm, ean, referencia, unidade, inativo}}."""
    agora = time.time()
    res: Dict[int, Dict[str, Any]] = {}
    faltam = []
    for c in {int(x) for x in codigos}:
        k = f"{empresa}:{c}"
        hit = _cache_prod.get(k)
        if usar_cache and hit and agora - hit[0] < _CACHE_S:
            res[c] = hit[1]
        else:
            faltam.append(c)
    loja = LOJA_POR_EMPRESA.get(empresa, 1)
    for i in range(0, len(faltam), 200):
        lote = faltam[i:i + 200]
        marcas = ", ".join("?" for _ in lote)
        rows = SoftsystemService._consultar(empresa, f"""
            SELECT p.CODPRODUTO, p.DESCRICAO, p.PRECO, p.CODGRUPO, p.CODSUBGRUPO, p.CODSUBGRUPONIVEL2, p.CODSUBGRUPONIVEL3,
                   p.CODMARCA, m.MARCA, p.NBM, p.CODBARRAS, p.CODREFERENCIA, p.CODEMBALAGEM, p.INATIVO,
                   (SELECT SUM(e.ESTOQUE) FROM ESTOQUE e WHERE e.LOJA = ? AND e.CODPRODUTO = p.CODPRODUTO)
            FROM PRODUTOS p LEFT JOIN MARCAS m ON m.CODMARCA = p.CODMARCA
            WHERE p.CODPRODUTO IN ({marcas})""", (loja, *lote))
        for r in rows:
            d = {"codigo": int(r[0]), "descricao": _s(r[1]), "preco": round(float(r[2] or 0), 2),
                 "codgrupo": r[3], "codsubgrupo": r[4], "codsubgruponivel2": r[5], "codsubgruponivel3": r[6],
                 "codmarca": r[7], "marca": _s(r[8]), "ncm": _s(r[9]), "ean": _s(r[10]), "referencia": _s(r[11]),
                 "unidade": _s(r[12]) or "UN", "inativo": _s(r[13]) == "T", "estoque": round(float(r[14] or 0), 3)}
            res[d["codigo"]] = d
            _cache_prod[f"{empresa}:{d['codigo']}"] = (agora, d)
    return res


def buscar_para_foto(empresa: str, termo: str, limite: int = 15) -> List[Dict[str, Any]]:
    """Busca do app Foto (15/10/2026): o que a pessoa tiver em mãos - código do Softsystem, código do
    FORNECEDOR (de-para gravado a cada compra em PRODUTOSFORNECEDORES), referência do fabricante,
    EAN ou pedaço da descrição. Só produtos ativos."""
    t = (termo or "").strip().upper()
    if len(t) < 2:
        return []
    achados: Dict[int, Dict[str, Any]] = {}
    for p in SoftsystemService.buscar_produtos(empresa, t, limite):
        achados.setdefault(p["codigo"], p)
    ref = ("p.CODPRODUTO IN (SELECT pf.CODPRODUTO FROM PRODUTOSFORNECEDORES pf WHERE UPPER(pf.CODREFERENCIA) STARTING WITH ?) "
           "OR UPPER(p.CODREFERENCIA) STARTING WITH ?")
    try:
        for p in SoftsystemService._buscar(empresa, ref, (t, t), limite):
            achados.setdefault(p["codigo"], p)
        # várias palavras ("bico extra fire"): todas precisam aparecer na descrição, em qualquer ordem
        palavras = [w for w in t.split() if len(w) >= 2][:6]
        if len(palavras) > 1:
            where = " AND ".join("UPPER(p.DESCRICAO) CONTAINING ?" for _ in palavras) + " AND COALESCE(p.INATIVO, 'F') <> 'T'"
            for p in SoftsystemService._buscar(empresa, where, tuple(palavras), limite):
                achados.setdefault(p["codigo"], p)
    except Exception as e:
        logger.warning(f"[CATALOGO] Busca do app Foto falhou: {e}")
    return list(achados.values())[:limite]


def produtosweb_softsystem(empresa: str, codproduto: int) -> Dict[str, Any]:
    """O que já existe na aba "Para Lojas Web" do Softsystem (para pré-preencher)."""
    r = SoftsystemService._consultar(empresa, """
        SELECT DESCRICAOWEB, COMENTARIOWEB, KEYWORDS, DICA, MATERIAL, COR, MOSTRARNAWEB, FRETEGRATUITO, DESCONTOWEB,
               FLAGNUNCAMOSTRAPRECO FROM PRODUTOSWEB WHERE CODPRODUTO = ?""", (int(codproduto),))
    videos = [_s(v[0]) for v in SoftsystemService._consultar(empresa, "SELECT VIDEO FROM VIDEOSPRODUTOS WHERE CODPRODUTO = ?", (int(codproduto),)) if _s(v[0])]
    if not r:
        return {"videos": videos}
    x = r[0]
    return {"titulo_web": _s(x[0]) or None, "descricao_web": _s(x[1]) or None, "keywords": _s(x[2]) or None, "dica": _s(x[3]) or None,
            "material": _s(x[4]) or None, "cor": _s(x[5]) or None, "mostrar_na_web": _s(x[6]) == "T",
            "frete_gratis": _s(x[7]) == "T", "desconto_web_pct": float(x[8]) if x[8] else None,
            "nunca_mostra_preco": _s(x[9]) == "T", "videos": videos}


# ------------------------------------------------------------------ gravação no Softsystem
def gravar_web_softsystem(empresa: str, codproduto: int, dados: Dict[str, Any], videos: List[str],
                          db_path: Optional[str] = None) -> None:
    """Aba "Para Lojas Web": upsert em PRODUTOSWEB + troca os vídeos em VIDEOSPRODUTOS."""
    from app.services.softsystem_compra_writer import _conectar, _Gravador
    from firebird.driver import TPB, Isolation, TraAccessMode
    con = _conectar(empresa, db_path)
    tpb = TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION, lock_timeout=15)
    tra = con.transaction_manager(tpb.get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        g = _Gravador(cur)
        cod = int(codproduto)
        sim_nao = lambda b: "T" if b else "F"  # noqa: E731
        valores = {
            "DESCRICAOWEB": (dados.get("titulo_web") or "")[:200] or None,
            "COMENTARIOWEB": _texto_plano(dados.get("descricao_web") or "")[:2000] or None,
            "KEYWORDS": (dados.get("keywords") or "")[:255] or None,
            "DICA": (dados.get("dica") or "")[:255] or None,
            "MATERIAL": (dados.get("material") or "")[:200] or None,
            "COR": (dados.get("cor") or "")[:150] or None,
            "MOSTRARNAWEB": sim_nao(dados.get("publicar_site")),
            "FRETEGRATUITO": sim_nao(dados.get("frete_gratis")),
            "DESCONTOWEB": dados.get("desconto_web_pct") or None,
            "FLAGNUNCAMOSTRAPRECO": sim_nao(dados.get("nunca_mostra_preco")),
            "EXPORT": "F",
        }
        cur.execute("SELECT 1 FROM PRODUTOSWEB WHERE CODPRODUTO = ?", (cod,))
        if cur.fetchone():
            # update grava NULL nos campos apagados na tela (o _Gravador.update aceita None)
            g.update("PRODUTOSWEB", valores, {"CODPRODUTO": cod})
        else:
            g.insert("PRODUTOSWEB", {"CODPRODUTO": cod, **valores})
        cur.execute("DELETE FROM VIDEOSPRODUTOS WHERE CODPRODUTO = ?", (cod,))
        for v in videos[:20]:
            g.insert("VIDEOSPRODUTOS", {"CODPRODUTO": cod, "VIDEO": v[:100], "EXPORT": "F"})
        tra.commit()
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


# ------------------------------------------------------------------ foto no Softsystem (os dois bancos)
# Estudado em 15/10/2026 (só leitura): PRODUTOSIMAGENS (chave CODPRODUTO+CODIMAGEM) gravada no banco
# da Servweld é levada pelo GUARDIÃO para o da Centro-Oeste com o MESMO número (ex.: 3375/1743 nos
# dois) - mas o ARQUIVO "Produto {cod} {codimagem}.jpg" não vai para a pasta da Centro-Oeste (por isso
# a loja recadastrava a mesma foto lá à mão). Então: linha só no banco da Servweld + arquivo nas DUAS
# pastas. Numeração = maior número entre os dois bancos + 1 (cada banco tem a sua sequência).
def _pastas_fotos() -> List[str]:
    from app.core.config import settings
    return [p for p in (settings.SOFTSYSTEM_IMAGENS_DIR_SERVWELD, settings.SOFTSYSTEM_IMAGENS_DIR_CENTROOESTE) if p]


def _gravar_arquivo_foto(cod: int, codimagem: int, jpg: bytes) -> List[str]:
    """Grava/substitui "Produto {cod} {codimagem}.jpg" nas pastas das duas lojas. Devolve onde gravou."""
    from app.services.nota_arquivo_service import _com_retentativa
    nome = f"Produto {int(cod)} {int(codimagem)}.jpg"
    feitas = []
    for pasta in _pastas_fotos():
        if not os.path.isdir(pasta):
            logger.warning(f"[CATALOGO] Pasta de fotos inacessível: {pasta}")
            continue
        destino = os.path.join(pasta, nome)

        def _grava(destino=destino):
            tmp = destino + ".tmp"
            with open(tmp, "wb") as f:
                f.write(jpg)
            os.replace(tmp, destino)
        _com_retentativa(_grava)
        feitas.append(pasta)
    return feitas


def gravar_foto_softsystem(cod: int, jpg: bytes, db_path: Optional[str] = None) -> int:
    """Nova foto do produto no Softsystem. Em teste (db_path) grava só a linha na cópia - sem arquivo."""
    from app.services.softsystem_compra_writer import _conectar, _Gravador
    from firebird.driver import TPB, Isolation, TraAccessMode
    try:
        max_co = SoftsystemService._consultar("centrooeste", "SELECT MAX(CODIMAGEM) FROM PRODUTOSIMAGENS")[0][0] or 0
    except Exception:
        max_co = 0
    con = _conectar("servweld", db_path)
    tra = con.transaction_manager(TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION,
                                      lock_timeout=15).get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        cur.execute("SELECT MAX(CODIMAGEM) FROM PRODUTOSIMAGENS")
        codimagem = max(int(cur.fetchone()[0] or 0), int(max_co)) + 1
        _Gravador(cur).insert("PRODUTOSIMAGENS", {"CODPRODUTO": int(cod), "CODIMAGEM": codimagem, "EXPORTWEB": "F",
                                                  "EXCLUIDO": "F", "TRIGGERATIVA": "T"})
        if not db_path:  # produção: arquivo nas duas pastas ANTES de confirmar a linha
            if not _gravar_arquivo_foto(cod, codimagem, jpg):
                raise OSError("pastas de fotos do Softsystem inacessíveis")
        tra.commit()
        return codimagem
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


def aposentar_fotos_antigas(cod: int, manter: set, db_path: Optional[str] = None) -> Dict[str, List[int]]:
    """Foto nova feita pelo OminiChannel passa a ser a foto do produto: as fotos ANTIGAS que não
    estão no catálogo são marcadas EXCLUIDO='T' nos dois bancos (visto em 15/10/2026 no 1568: a
    Centro-Oeste tinha uma foto própria antiga, 1719, que aparecia na frente das novas). O arquivo
    fica na pasta - dá para trazer de volta pelo "Importar fotos do Softsystem".
    Em teste (db_path) só mexe na cópia da Servweld."""
    from app.services.softsystem_compra_writer import _conectar
    from firebird.driver import TPB, Isolation, TraAccessMode
    feitas: Dict[str, List[int]] = {}
    manter = {int(x) for x in manter if x}
    for emp in (("servweld",) if db_path else ("servweld", "centrooeste")):
        con = _conectar(emp, db_path if emp == "servweld" else None)
        tra = con.transaction_manager(TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION,
                                          lock_timeout=15).get_buffer())
        tra.begin()
        try:
            cur = tra.cursor()
            cur.execute("SELECT CODIMAGEM FROM PRODUTOSIMAGENS WHERE CODPRODUTO = ? AND COALESCE(EXCLUIDO, 'F') <> 'T'", (int(cod),))
            antigas = [int(r[0]) for r in cur.fetchall() if int(r[0]) not in manter]
            for n in antigas:
                cur.execute("UPDATE PRODUTOSIMAGENS SET EXCLUIDO = 'T', TRIGGERATIVA = 'T' WHERE CODPRODUTO = ? AND CODIMAGEM = ?", (int(cod), n))
            tra.commit()
            if antigas:
                feitas[emp] = antigas
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
    if feitas:
        logger.info(f"[CATALOGO] Fotos antigas do {cod} retiradas: {feitas}")
    return feitas


def localizacao_produto(cod: int) -> Dict[str, Dict[str, Any]]:
    """Localização 1 e estoque do produto nas DUAS lojas (o Guardião não replica estoque/localização)."""
    res = {}
    for emp in ("servweld", "centrooeste"):
        try:
            r = SoftsystemService._consultar(emp, "SELECT LOCALIZACAO, ESTOQUE FROM ESTOQUE WHERE LOJA = ? AND CODPRODUTO = ? AND LOTE = '0'",
                                             (LOJA_POR_EMPRESA[emp], int(cod)))
            res[emp] = {"localizacao": _s(r[0][0]) if r else None, "estoque": float(r[0][1] or 0) if r else None, "erro": None}
        except Exception as e:
            res[emp] = {"localizacao": None, "estoque": None, "erro": str(e)[:120]}
    return res


def excluir_foto_softsystem(cod: int, codimagem: int, db_path: Optional[str] = None) -> None:
    """Foto apagada no catálogo: marca EXCLUIDO='T' (como o próprio Softsystem faz) - o Guardião replica."""
    from app.services.softsystem_compra_writer import _conectar
    from firebird.driver import TPB, Isolation, TraAccessMode
    con = _conectar("servweld", db_path)
    tra = con.transaction_manager(TPB(access_mode=TraAccessMode.WRITE, isolation=Isolation.READ_COMMITTED_RECORD_VERSION,
                                      lock_timeout=15).get_buffer())
    tra.begin()
    try:
        cur = tra.cursor()
        cur.execute("UPDATE PRODUTOSIMAGENS SET EXCLUIDO = 'T', TRIGGERATIVA = 'T' WHERE CODPRODUTO = ? AND CODIMAGEM = ?",
                    (int(cod), int(codimagem)))
        tra.commit()
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


def _texto_plano(html: str) -> str:
    t = re.sub(r"<\s*br\s*/?>|</p>|</li>", "\n", html or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


# ------------------------------------------------------------------ texto do site pela IA
async def _trechos_rag(tenant_id: Optional[int], produto: Dict[str, Any]) -> tuple:
    """Trechos dos MANUAIS da loja (RAG - pasta DOC. TÉCNICOS) sobre o produto, com as fontes.
    Pedido do usuário em 15/10/2026: "nossa RAG consegue desenvolver os textos? com ela ficaria melhor".
    A busca do RAG já prioriza o manual do MODELO exato (número do modelo no nome do arquivo)."""
    if not tenant_id:
        return "", []
    try:
        from app.services.rag_service import rag_service
        consulta = " ".join(x for x in (produto.get("descricao"), produto.get("marca"), produto.get("referencia"),
                                        "especificações técnicas características aplicação") if x)
        texto = await asyncio.wait_for(rag_service.search_context(tenant_id, consulta, top_k=6, max_total_chars=6000), timeout=40)
    except Exception as e:
        logger.warning(f"[CATALOGO] RAG indisponível para textos de {produto.get('codigo')}: {e}")
        return "", []
    texto = texto if isinstance(texto, str) else str(texto or "")
    fontes = sorted({f.strip() for f in re.findall(r"\[Fonte:\s*([^\]]+)\]", texto)})
    return texto, fontes


async def gerar_textos_ia(produto: Dict[str, Any], api_key: Optional[str], tenant_id: Optional[int] = None) -> Dict[str, Any]:
    """IA sugere título, descrição comercial, ficha técnica e palavras-chave - FONTE PRINCIPAL: os
    manuais da loja no RAG; o Google completa o que faltar. A pessoa revisa antes de salvar (regra
    do usuário: IA sugere, pessoa confirma)."""
    import httpx
    from app.services.market_price_service import GEMINI_URL, _extrair_json
    if not api_key:
        raise ValueError("Chave da IA (Gemini) não configurada.")
    rag, fontes = await _trechos_rag(tenant_id, produto)
    bloco_rag = (f"""
TRECHOS DOS MANUAIS TÉCNICOS DA LOJA (fonte PRINCIPAL - use primeiro estas informações; cada trecho
diz de qual manual veio; ignore trechos que forem de OUTRO modelo/produto):
{rag[:6000]}
""" if rag.strip() else "\n(Não há manual deste produto na base da loja - use só fontes confirmadas no Google.)\n")
    prompt = f"""Você escreve o catálogo do site da Servsolda (loja de solda, corte, EPI e ferramentas em Brasília).
Escreva o conteúdo da página deste produto, em português do Brasil:
- descrição na loja: {produto.get('descricao')}
- marca: {produto.get('marca') or '-'} | referência do fabricante: {produto.get('referencia') or '-'} | EAN: {produto.get('ean') or '-'}
{bloco_rag}
Pesquise no Google só para COMPLETAR o que os manuais não trouxerem (fabricante, distribuidores).
Use SÓ informação confirmada. Não invente medida nem especificação.
Responda SOMENTE um JSON:
{{"titulo_web": "nome comercial claro, até 120 caracteres",
 "descricao_web": "2 a 4 parágrafos curtos em HTML simples (<p>, <ul><li>) - para que serve, diferenciais, aplicações",
 "especificacoes": [{{"nome": "Diâmetro", "valor": "0,8 mm"}}],
 "keywords": "até 12 termos separados por vírgula que o cliente usaria no Google",
 "dica": "uma frase curta de uso/dica técnica",
 "material": "material principal ou vazio",
 "garantia": "garantia do fabricante se encontrada, ou vazio",
 "manuais_usados": ["nome EXATO (como aparece em [Fonte: ...]) de cada manual da loja que você realmente usou - [] se nenhum era deste produto"]}}"""
    payload = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.2}}
    async with httpx.AsyncClient(timeout=60.0) as cli:
        r = await cli.post(GEMINI_URL, params={"key": api_key}, json=payload)
    if r.status_code != 200:
        raise ValueError(f"IA indisponível (HTTP {r.status_code}).")
    cand = (r.json().get("candidates") or [{}])[0]
    texto = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    d = _extrair_json(texto) or {}
    specs = [{"nome": str(s.get("nome") or "")[:80], "valor": str(s.get("valor") or "")[:200]}
             for s in (d.get("especificacoes") or []) if isinstance(s, dict) and s.get("nome") and s.get("valor")][:30]
    usados = [str(m).strip() for m in (d.get("manuais_usados") or []) if str(m).strip() in fontes]
    return {"fontes_rag": usados, "manuais_consultados": fontes, "titulo_web": (d.get("titulo_web") or "")[:200], "descricao_web": d.get("descricao_web") or "",
            "especificacoes": specs, "keywords": (d.get("keywords") or "")[:255], "dica": (d.get("dica") or "")[:255],
            "material": (d.get("material") or "")[:200], "garantia": (d.get("garantia") or "")[:200]}


# ------------------------------------------------------------------ formato do site (servsolda_site)
def secao_id(codgrupo, codsubgrupo=None) -> str:
    return f"g{int(codgrupo)}" + (f"s{int(codsubgrupo)}" if codsubgrupo is not None else "")


def produto_site(cat: Any, sw: Dict[str, Any], midias: List[Any], base_url: str, nomes_secao: Dict[str, str]) -> Dict[str, Any]:
    """Converte para o formato Product do site (campos JSON como string, igual ao Prisma do site)."""
    abs_url = lambda u: (base_url.rstrip("/") + u) if u and u.startswith("/") else u  # noqa: E731
    imagens = [abs_url(m.arquivo) for m in sorted(midias, key=lambda m: (m.ordem, m.id)) if m.tipo == "imagem"]
    pdfs = [{"title": m.titulo or "Ficha técnica", "url": abs_url(m.arquivo)} for m in sorted(midias, key=lambda m: (m.ordem, m.id)) if m.tipo == "pdf"]
    videos = [{"title": v.get("titulo") or "", "url": v.get("url")} for v in json.loads(cat.videos_json or "[]") if v.get("url")]
    specs = [{"key": s.get("nome"), "value": s.get("valor")} for s in json.loads(cat.especificacoes_json or "[]") if s.get("nome")]
    if sw.get("marca") and not any((s["key"] or "").lower() == "marca" for s in specs):
        specs.insert(0, {"key": "Marca", "value": sw["marca"]})
    preco = 0.0 if cat.nunca_mostra_preco else float(sw.get("preco") or 0)
    if preco and cat.desconto_web_pct:
        preco = round(preco * (1 - float(cat.desconto_web_pct) / 100), 2)
    sec = secao_id(sw["codgrupo"], sw.get("codsubgrupo")) if sw.get("codsubgrupo") is not None else secao_id(sw["codgrupo"])
    nome = cat.titulo_web or sw["descricao"]
    descricao = cat.descricao_web or ""
    return {
        "id": str(cat.codproduto), "sku": str(cat.codproduto), "name": nome, "price": preco,
        "stock": int(max(sw.get("estoque") or 0, 0)), "description": descricao,
        "specs": json.dumps(specs, ensure_ascii=False), "status": "FEATURED" if cat.destaque else "ACTIVE",
        "images": json.dumps(imagens, ensure_ascii=False), "pdfs": json.dumps(pdfs, ensure_ascii=False),
        "videos": json.dumps(videos, ensure_ascii=False), "metaTitle": f"{nome} | Servsolda"[:70],
        "metaDesc": (_texto_plano(descricao)[:155] or nome), "sectionId": sec,
        "section": {"id": sec, "name": nomes_secao.get(sec, "")}, "warranty": cat.garantia or "",
        "brand": sw.get("marca") or "", "unit": sw.get("unidade") or "UN", "ean": sw.get("ean") or "",
        "freeShipping": bool(cat.frete_gratis), "reviews": [],
        "updatedAt": (cat.atualizado_em or datetime.utcnow()).isoformat(),
    }
