"""
Catálogo de peças a partir de VISTAS EXPLODIDAS (tabela de peças em imagem) - 13/10/2026.

O catálogo do bibliotecário (PartsCatalogItem, ver librarian_service) era montado só com tabelas de
peças que estavam em TEXTO dentro dos manuais (534 documentos). A medição de 13/10/2026 mostrou 729
vistas explodidas/listas de peças em PDF fora dele - a tabela está em imagem, o texto extraído não
tem os códigos. Aqui o Gemini lê o PDF inteiro (ele aceita PDF nativo) e devolve a tabela de peças
em JSON; quase não gasta CPU da VM (o trabalho pesado é no Google), por isso dá pra rodar a noite.

Tabelas próprias (criadas pelo script scripts/catalogo_vistas_explodidas.py):
  catalogo_visao_docs  - quais PDFs já foram lidos (pra não ler de novo) e o resultado;
  catalogo_visao_pecas - as peças lidas. Ficam guardadas à parte porque o catálogo principal é
                         reconstruído do zero toda madrugada a partir do texto do RAG - o
                         librarian_service.rebuild_catalog junta estas de volta a cada reconstrução.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

logger = logging.getLogger("parts_vision")

# Palavras no nome do arquivo que indicam vista explodida / lista de peças
PALAVRAS_VISTA = ("vista explodida", "explodida", "exploded", "pecas reposicao", "pecas de reposicao",
                  "spare part", "parts list", "lista de pecas", "lista pecas")
MAX_BYTES = 40 * 1024 * 1024


class VisaoDoc(Base):
    __tablename__ = "catalogo_visao_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_doc_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))  # 'ok' | 'sem_tabela' | 'erro' | 'grande'
    n_pecas: Mapped[int] = mapped_column(Integer, default=0)
    detalhe: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VisaoPeca(Base):
    __tablename__ = "catalogo_visao_pecas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True)
    parent_doc_id: Mapped[str] = mapped_column(String(80), index=True)
    titulo: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    marca: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    item: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    codigo: Mapped[str] = mapped_column(String(40), index=True)
    part_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    descricao: Mapped[str] = mapped_column(String(255))
    descricao_norm: Mapped[str] = mapped_column(String(255))


PROMPT = (
    "Este PDF é uma vista explodida / lista de peças de reposição de um equipamento ({titulo}).\n"
    "Transcreva TODAS as linhas de TODAS as tabelas de peças do documento, exatamente como estão impressas.\n"
    "Para cada peça devolva:\n"
    '  "item": número da peça na figura (posição), se houver;\n'
    '  "codigo": código / referência / part number da peça, copiado exatamente;\n'
    '  "part_number": um segundo código da mesma linha, se a tabela tiver dois (senão vazio);\n'
    '  "descricao": descrição da peça (no idioma em que está).\n'
    "Regras: não invente nada; campo que não existe fica vazio; não junte linhas diferentes; ignore cabeçalhos.\n"
    "Se o documento NÃO tiver tabela de peças com códigos, devolva [].\n"
    'Responda SÓ com JSON: [{{"item": "", "codigo": "", "part_number": "", "descricao": ""}}]'
)


def _limpa_linhas(dados) -> List[dict]:
    if isinstance(dados, dict):
        dados = dados.get("pecas") or dados.get("items") or dados.get("parts") or []
    out, vistos = [], set()
    for r in dados if isinstance(dados, list) else []:
        if not isinstance(r, dict):
            continue
        codigo = str(r.get("codigo") or "").strip().strip(".")[:40]
        desc = re.sub(r"\s+", " ", str(r.get("descricao") or "")).strip()[:250]
        if not codigo or not any(ch.isdigit() for ch in codigo) or sum(ch.isalpha() for ch in desc) < 2:
            continue
        chave = (codigo.upper(), desc.upper())
        if chave in vistos:
            continue
        vistos.add(chave)
        pn = str(r.get("part_number") or "").strip()[:40] or None
        item = str(r.get("item") or "").strip()[:10] or None
        out.append({"codigo": codigo, "part_number": pn if pn != codigo else None, "item": item, "descricao": desc})
    return out


# ------------------------------------------------------------------------------------------------
# Custo x qualidade (14/10/2026). A 1ª noite (gemini-3.6-flash com "raciocínio" ligado e PDF em
# resolução alta) custou ~R$ 0,12 por PDF. Pedido do usuário: "quero baratear mas sem perder a
# qualidade do ensino". Por isso:
#  - CONFIGS vão da mais barata à completa (a da 1ª noite). A madrugada usa a que foi APROVADA pela
#    comparação (scripts/catalogo_vistas_explodidas.py --comparar N): ela relê PDFs já lidos na
#    configuração completa e só aprova uma mais barata se as peças baterem (ver MIN_CONCORDANCIA).
#    Sem aprovação, continua a completa.
#  - Rede de segurança por PDF: resultado suspeito na configuração barata (poucas peças, itens
#    pulados, códigos estranhos, códigos que não batem com o texto do PDF) -> relê na completa.
#  - Crédito esgotado (402) devolve 'sem_credito': o PDF NÃO é marcado e a madrugada para.
CONFIGS = {
    "economico": {"modelo": "gemini-3.1-flash-lite", "raciocinio": "MINIMAL", "resolucao": "MEDIA_RESOLUTION_MEDIUM"},
    "intermediario": {"modelo": "gemini-3.6-flash", "raciocinio": "MINIMAL", "resolucao": "MEDIA_RESOLUTION_MEDIUM"},
    "sem_raciocinio": {"modelo": "gemini-3.6-flash", "raciocinio": "MINIMAL", "resolucao": None},
    "completo": {"modelo": "gemini-3.6-flash", "raciocinio": None, "resolucao": None},
}
ORDEM_CONFIGS = ("economico", "intermediario", "sem_raciocinio", "completo")
MIN_CONCORDANCIA = 0.98
_CODIGO_TEXTO = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-/]{3,}")


def _sem_credito(erro: Exception) -> bool:
    t = str(erro).lower()
    return bool(re.search(r"\b402\b", t)) or "credits are depleted" in t or ("resource_exhausted" in t and "credit" in t)


def norm_codigo(c: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", (c or "").upper())


def _texto_do_pdf(pdf_bytes: bytes) -> str:
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # PyMuPDF antigo
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return " ".join(pagina.get_text() for pagina in doc)[:400_000]
    except Exception:
        return ""


def motivo_suspeito(pecas: List[dict], texto_pdf: str) -> Optional[str]:
    """Por que um resultado da configuração barata NÃO merece confiança (None = parece bom)."""
    if len(pecas) < 3:
        return f"só {len(pecas)} peça(s)"
    itens = sorted({int(p["item"]) for p in pecas if (p.get("item") or "").isdigit() and int(p["item"]) < 1000})
    if len(itens) >= 5:
        faltando = (itens[-1] - itens[0] + 1) - len(itens)
        if faltando > max(2, 0.15 * len(itens)):
            return f"{faltando} itens pulados na sequência"
    estranhos = sum(1 for p in pecas if len(norm_codigo(p["codigo"])) < 3 or " " in p["codigo"].strip())
    if estranhos > 0.2 * len(pecas):
        return f"{estranhos} códigos em formato estranho"
    # PDF com camada de texto: os códigos lidos têm que aparecer nela
    codigos_texto = {norm_codigo(t) for t in _CODIGO_TEXTO.findall(texto_pdf or "") if any(ch.isdigit() for ch in t)}
    if len(codigos_texto) >= 10:
        achados = sum(1 for p in pecas if norm_codigo(p["codigo"]) in codigos_texto)
        if achados < 0.8 * len(pecas):
            return f"só {achados}/{len(pecas)} códigos batem com o texto do PDF"
    return None


def _config_genai(genai, nome: str, com_extras: bool = True):
    cfg = CONFIGS[nome]
    kw = {"response_mime_type": "application/json", "temperature": 0}
    if com_extras and cfg["raciocinio"]:
        kw["thinking_config"] = genai.types.ThinkingConfig(thinking_level=cfg["raciocinio"])
    if com_extras and cfg["resolucao"]:
        kw["media_resolution"] = cfg["resolucao"]
    return genai.types.GenerateContentConfig(**kw)


def _custo_brl(modelo: str, uso) -> float:
    from app.services import ia_consumo_service as obs
    try:
        precos = obs.ler_precos()
        n = lambda campo: int(getattr(uso, campo, 0) or 0)  # noqa: E731
        usd = obs.custo_usd(precos, modelo, n("prompt_token_count"), n("candidates_token_count"), n("thoughts_token_count"))
        return usd * float(precos.get("cotacao_dolar") or 5.5)
    except Exception:
        return 0.0


async def ler_vista(pdf_bytes: bytes, titulo: str, api_key: str, nome_config: str) -> dict:
    """Uma leitura com UMA configuração. {'status', 'pecas', 'custo_brl', 'erro'}.
    status: 'ok' | 'sem_tabela' | 'erro' | 'sem_credito'."""
    from google import genai
    from app.services.ia_consumo_service import instalar
    instalar()  # tokens/custo vão para o painel Admin > Consumo de IA
    client = genai.Client(api_key=api_key)
    modelo = CONFIGS[nome_config]["modelo"]
    custo, erro = 0.0, ""
    for com_extras in (True, False):  # se o modelo recusar raciocínio/resolução, tenta sem eles
        try:
            resp = await asyncio.wait_for(asyncio.to_thread(
                client.models.generate_content,
                model=modelo,
                contents=[PROMPT.format(titulo=titulo), genai.types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")],
                config=_config_genai(genai, nome_config, com_extras),
            ), timeout=300)
            custo += _custo_brl(modelo, getattr(resp, "usage_metadata", None))
            texto = (resp.text or "").strip() if resp else ""
            linhas = _limpa_linhas(json.loads(texto)) if texto else []
            return {"status": "ok" if linhas else "sem_tabela", "pecas": linhas, "custo_brl": custo, "erro": ""}
        except Exception as e:
            erro = f"{modelo}: {type(e).__name__}: {str(e)[:200]}"
            if _sem_credito(e):
                return {"status": "sem_credito", "pecas": [], "custo_brl": custo, "erro": erro}
            if com_extras and "400" in str(e) and ("thinking" in str(e).lower() or "resolution" in str(e).lower()):
                continue
            break
    logger.warning(f"[VISAO] {titulo} ({nome_config}): {erro}")
    return {"status": "erro", "pecas": [], "custo_brl": custo, "erro": erro}


async def extrair_pecas(pdf_bytes: bytes, titulo: str, api_key: str, nome_config: str = "completo") -> Tuple[str, List[dict], str, float]:
    """(status, peças, detalhe, custo_brl). Status: 'ok' | 'sem_tabela' | 'erro' | 'grande' | 'sem_credito'.
    Lê com a configuração aprovada; se ela for mais barata que a completa e o resultado for suspeito
    (ou der erro), relê na completa."""
    if len(pdf_bytes) > MAX_BYTES:
        return "grande", [], f"{len(pdf_bytes) // (1024 * 1024)} MB", 0.0
    r = await ler_vista(pdf_bytes, titulo, api_key, nome_config)
    if r["status"] == "sem_credito" or nome_config == "completo":
        return r["status"], r["pecas"], r["erro"] or nome_config, r["custo_brl"]
    motivo = r["erro"] or motivo_suspeito(r["pecas"], await asyncio.to_thread(_texto_do_pdf, pdf_bytes))
    if not motivo:
        return r["status"], r["pecas"], nome_config, r["custo_brl"]
    r2 = await ler_vista(pdf_bytes, titulo, api_key, "completo")
    custo = r["custo_brl"] + r2["custo_brl"]
    if r2["status"] == "sem_credito":
        return "sem_credito", [], r2["erro"], custo
    if r2["status"] == "erro" and r["pecas"]:  # completa falhou: fica a barata, que pelo menos leu algo
        return r["status"], r["pecas"], f"{nome_config} (releitura falhou: {motivo})", custo
    return r2["status"], r2["pecas"], f"completo (releitura: {motivo})", custo
