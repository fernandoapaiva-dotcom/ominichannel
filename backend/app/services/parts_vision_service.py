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


async def extrair_pecas(pdf_bytes: bytes, titulo: str, api_key: str) -> Tuple[str, List[dict], str]:
    """(status, peças, detalhe). Status: 'ok' | 'sem_tabela' | 'erro' | 'grande'."""
    from google import genai
    from app.services.ia_consumo_service import instalar
    instalar()  # tokens/custo vão para o painel Admin > Consumo de IA
    if len(pdf_bytes) > MAX_BYTES:
        return "grande", [], f"{len(pdf_bytes) // (1024 * 1024)} MB"
    client = genai.Client(api_key=api_key)
    config = genai.types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
    ultimo_erro = ""
    for modelo in ("gemini-3.6-flash", "gemini-2.5-flash"):
        try:
            resp = await asyncio.wait_for(asyncio.to_thread(
                client.models.generate_content,
                model=modelo,
                contents=[PROMPT.format(titulo=titulo), genai.types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")],
                config=config,
            ), timeout=300)
            texto = (resp.text or "").strip() if resp else ""
            if not texto:
                continue
            linhas = _limpa_linhas(json.loads(texto))
            return ("ok" if linhas else "sem_tabela"), linhas, modelo
        except Exception as e:
            ultimo_erro = f"{modelo}: {type(e).__name__}: {str(e)[:200]}"
            logger.warning(f"[VISAO] {titulo}: {ultimo_erro}")
            await asyncio.sleep(2)
    return "erro", [], ultimo_erro
