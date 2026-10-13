"""
Bibliotecário do Copiloto Técnico - responde pedido de DOCUMENTO (manual, esquema, roteiro...) e de
CÓDIGO DE PEÇA sem chamar a IA. Ideia do usuário em 13/10/2026: "quando alguém pedir código de peça e
pdfs a IA pede para o robô ao invés de ficar gastando tokens... esse robô treinado somente para essa
especialidade teria assertividade".

Por que existe (achado no mesmo dia, conversa do técnico Manoel):
  - "Qual código da placa de controle dela?" logo depois de falar da LHN 242: a busca usava só a
    mensagem atual (sem o modelo) e o manual chama a peça de "CIRCUITO DE CONTROLE", não "placa" -
    a IA respondeu que o código "não consta", mas estava no manual (tabela 3.1, item 30, 0742654);
  - o PDF enviado junto foi o datasheet "TOP242FN" (bateu só o número 242) em vez do manual.

Como funciona:
  1. CATÁLOGO DE PEÇAS (PartsCatalogItem): extraído das tabelas de peças dos manuais que já estão no
     RAG (473 manuais com tabela reconhecível na amostragem de 13/10/2026, ~19 mil linhas) -
     reconstruído de madrugada, fora do horário de uso (a leitura do acervo leva minutos).
  2. EQUIPAMENTO EM FOCO: se a pergunta não cita modelo ("...dela?"), herda o modelo da mensagem
     anterior da mesma conversa que citava um.
  3. PEÇA: consulta direta no catálogo, filtrando pelos manuais do modelo, com sinônimos de oficina
     (placa = circuito = PCB, ventilador = cooler, controle = comando...).
  4. DOCUMENTO: escolhe o arquivo pelo nome (modelo + tipo pedido: esquema, roteiro, vista explodida,
     manual de serviço...).
Se o bibliotecário não tiver certeza, devolve None e a pergunta segue pra IA normal (com o modelo da
conversa já incluído na busca, que também melhora a resposta dela).
"""
import asyncio
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import DateTime, Integer, Text, delete, func, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import AsyncSessionLocal, Base
from app.models.models import PartsCatalogItem

logger = logging.getLogger("librarian")

MAX_OPTIONS = 6  # máximo de documentos numa lista de escolha

# ---------------------------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def _words(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", norm(s))


CODE_INTENT = re.compile(r"\b(c[oó]d(igo|igos)?|cod\.|part ?number|p/n|pn|refer[eê]ncia|ref\.)\b", re.I)
DOC_INTENT = re.compile(
    r"\b(manual|manuais|esquema|esquemas|esquem[aá]tico|diagrama|diagramas|roteiro|vista explodida|"
    r"cat[aá]logo|pdf|datasheet|documento|documenta[cç][aã]o|apostila|folha de dados)\b", re.I)
# Pedido de ENVIAR/ABRIR (não uma pergunta sobre o conteúdo do manual)
SEND_INTENT = re.compile(
    r"\b(manda|mande|mandar|envia|envie|enviar|passa|passe|abre|abra|abrir|cad[eê]|preciso d[oa]s?|"
    r"quero o|quero a|tem o|tem a|tem algum|me v[eê]|pode me enviar|pode mandar|consegue mandar)\b", re.I)
# Pergunta de código de FALHA/ERRO (Hypertherm 0-11-0, E05...) - não é código de peça
FAULT_INTENT = re.compile(r"\b(erro|falha|alarme|defeito|led|pisca|piscando)\b", re.I)
# Código/part number citado na própria pergunta ("o que é o 0742654?") - consulta reversa.
CODE_TOKEN = re.compile(r"\b([A-Z]{0,4}[\-.]?\d[\dA-Z.\-/]{4,16})\b", re.I)

# Tipos de documento: palavra na pergunta -> palavras que precisam estar no nome do arquivo
DOC_TYPES = {
    "esquema": ("esquema", "diagrama", "schematic", "eletrico"),
    "diagrama": ("diagrama", "esquema", "schematic"),
    "roteiro": ("roteiro", "teste", "test"),
    "vista explodida": ("vista explodida", "explodida", "pecas", "reposicao", "spare"),
    "servico": ("servico", "service"),
    "catalogo": ("catalogo", "tabela"),
    "datasheet": ("datasheet",),
}

# Sinônimos de oficina: cada grupo é UM conceito. Comparação por radical (6 primeiras letras).
SYNONYM_GROUPS = [
    {"placa", "circuito", "pcb", "cartao", "modulo", "plaqueta"},
    {"controle", "comando", "control", "cpu"},
    {"potencia", "power", "forca"},
    {"saida", "output"},
    {"entrada", "input"},
    {"painel", "frontal", "display", "visor", "mostrador", "ihm"},
    {"ventilador", "ventoinha", "cooler", "fan", "exaustor"},
    {"chave", "interruptor", "switch", "disjuntor"},
    {"retificadora", "retificador", "ponte", "diodo"},
    {"sensor", "shunt", "hall"},
    {"knob", "botao", "manopla", "potenciometro"},
    {"tampa", "carenagem", "gabinete", "carcaca"},
    {"conector", "engate", "dinse", "okc", "tomada"},
    {"tocha", "pistola"},
    {"bico", "ponteira", "contato"},
    {"bocal", "difusor"},
    {"capacitor", "condensador", "eletrolitico"},
    {"transformador", "trafo", "indutor", "bobina"},
    {"cabo", "chicote", "fio"},
    {"rele", "contator", "contactora"},
    {"dissipador", "radiador"},
    {"igbt", "transistor", "mosfet"},
    {"alimentador", "tracionador", "arame"},
    {"regulador", "valvula", "solenoide"},
]
_STEM_TO_GROUP: Dict[str, int] = {}
for _gi, _g in enumerate(SYNONYM_GROUPS):
    for _w in _g:
        _STEM_TO_GROUP[_w[:6]] = _gi

# Palavras que não descrevem a peça (pedido, pronome, tipo de pergunta)
_STOP = {
    "qual", "quais", "codigo", "codigos", "cod", "part", "number", "pn", "referencia", "ref", "da", "do",
    "de", "dela", "dele", "dessa", "desse", "deste", "desta", "das", "dos", "a", "o", "as", "os", "e",
    "me", "manda", "mande", "envia", "envie", "passa", "passe", "preciso", "precisa", "queria", "quero",
    "tem", "voce", "vc", "pra", "para", "por", "favor", "pf", "pfv", "na", "no", "nas", "nos", "um", "uma",
    "peca", "pecas", "maquina", "equipamento", "modelo", "numero", "sabe", "pode", "consegue", "ai", "ela",
    "ele", "essa", "esse", "isso", "aquela", "aquele", "agora", "tambem", "mais", "qualquer", "eh",
}


def _concepts(words: List[str]) -> Tuple[set, set]:
    """(grupos de sinônimo, radicais soltos) das palavras que descrevem a peça."""
    groups, loose = set(), set()
    for w in words:
        if w in _STOP or w.isdigit() or len(w) < 3:
            continue
        g = _STEM_TO_GROUP.get(w[:6])
        if g is not None:
            groups.add(g)
        else:
            loose.add(w[:6])
    return groups, loose


# ---------------------------------------------------------------------------------------------
# Extração do catálogo
# ---------------------------------------------------------------------------------------------

_HEADER_KEYWORDS = ["CÓDIGO", "Código", "CODIGO", "PART NUMBER", "Part No", "Part Number", "Cód.", "REF.", "Referência"]
# [item] CÓDIGO [PART NUMBER] DESCRIÇÃO
_ROW = re.compile(
    r"^\s*(?:(\d{1,3})\s+)?([A-Z]{0,4}[\-.]?\d[\dA-Z.\-/]{3,16})\s+(?:([\dA-Z][\dA-Z.\-/]{5,16})\s+)?"
    r"([A-Za-zÀ-ÿ][^\n]{2,120})$")
# Código de falha da Hypertherm (0-11-0, 0-30-1) - aparece em tabela mas não é peça
_FAULT_CODE = re.compile(r"^\d-\d{2}-\d$")


def _parse_rows(text: str) -> List[Tuple[Optional[str], str, Optional[str], str]]:
    rows = []
    for line in (text or "").split("\n"):
        m = _ROW.match(line.strip())
        if not m:
            continue
        item, code, pn, desc = m.groups()
        digits = sum(ch.isdigit() for ch in code)
        if digits < 4 or _FAULT_CODE.match(code):
            continue
        desc = desc.strip()
        if sum(ch.isalpha() for ch in desc) < 3:
            continue
        rows.append((item, code.strip(".-/"), pn, desc[:250]))
    # Só conta como tabela de peças se o trecho tiver várias linhas no formato (não uma linha solta)
    return rows if len(rows) >= 3 else []


def _build_catalog_sync(tenant_id: int) -> List[dict]:
    from app.services.rag_service import rag_service
    rag_service._ensure_client()
    col = rag_service.collection
    seen_chunks = set()
    out: Dict[tuple, dict] = {}
    for kw in _HEADER_KEYWORDS:
        offset = 0
        while True:
            page = rag_service._chroma_call(
                col.get, where={"tenant_id": int(tenant_id)}, where_document={"$contains": kw},
                include=["documents", "metadatas"], limit=1000, offset=offset,
            )
            ids = page.get("ids") or []
            if not ids:
                break
            for cid, doc, meta in zip(ids, page.get("documents") or [], page.get("metadatas") or []):
                if cid in seen_chunks:
                    continue
                seen_chunks.add(cid)
                for item, code, pn, desc in _parse_rows(doc):
                    pdoc = meta.get("parent_doc_id") or ""
                    key = (pdoc, code, norm(desc))
                    if key in out:
                        continue
                    out[key] = {
                        "tenant_id": int(tenant_id), "parent_doc_id": pdoc,
                        "titulo": (meta.get("titulo") or meta.get("filename") or "")[:255],
                        "filename": (meta.get("filename") or "")[:255],
                        "marca": (meta.get("marca") or None),
                        "source_path": meta.get("source_path"),
                        "item": item, "codigo": code[:40], "part_number": (pn or None),
                        "descricao": desc, "descricao_norm": norm(desc)[:255],
                    }
            offset += len(ids)
    return list(out.values())


async def rebuild_catalog(tenant_id: int = 1) -> int:
    t0 = datetime.utcnow()
    rows = await asyncio.to_thread(_build_catalog_sync, tenant_id)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(PartsCatalogItem).where(PartsCatalogItem.tenant_id == tenant_id))
        for i in range(0, len(rows), 1000):
            db.add_all([PartsCatalogItem(**r) for r in rows[i:i + 1000]])
            await db.flush()
        await db.commit()
    docs = len({r["parent_doc_id"] for r in rows})
    logger.info(f"[BIBLIOTECARIO] Catálogo de peças reconstruído: {len(rows)} peças de {docs} documentos em {(datetime.utcnow() - t0).total_seconds():.0f}s.")
    return len(rows)


async def start_librarian_catalog_loop(tenant_ids: Optional[list] = None):
    """Reconstrói o catálogo 1x por dia entre 3h e 4h de Brasília (a leitura do acervo pesa na VM)
    e também logo no primeiro boot se o catálogo estiver vazio (15 min depois, depois do aquecedor
    do RAG terminar)."""
    tenant_ids = tenant_ids or [1]
    await asyncio.sleep(15 * 60)
    last_run: Dict[int, datetime] = {}
    while True:
        for tid in tenant_ids:
            try:
                async with AsyncSessionLocal() as db:
                    count = (await db.execute(select(func.count(PartsCatalogItem.id)).where(PartsCatalogItem.tenant_id == tid))).scalar() or 0
                brasilia_hour = (datetime.utcnow() - timedelta(hours=3)).hour
                due_nightly = brasilia_hour == 3 and (tid not in last_run or datetime.utcnow() - last_run[tid] > timedelta(hours=20))
                if count == 0 or due_nightly:
                    last_run[tid] = datetime.utcnow()
                    await rebuild_catalog(tid)
            except Exception as e:
                logger.error(f"[BIBLIOTECARIO] Erro reconstruindo catálogo do tenant {tid}: {e}", exc_info=True)
        await asyncio.sleep(20 * 60)


# ---------------------------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------------------------

# Palavras que aparecem em nome de arquivo mas não identificam um equipamento - não servem de prova
# de que o documento é "daquele" equipamento (ver _rank_docs).
_NOT_EQUIPMENT = _STOP | {
    "tocha", "tochas", "solda", "maquina", "fonte", "inversora", "inversor", "manual", "manuais",
    "esquema", "vista", "explodida", "servico", "problema", "ajuda", "ajudar", "consegue", "estou",
    "esta", "com", "sem", "pdf", "rev", "pt", "br", "en", "es", "doc", "tecnico", "tecnicos", "documento",
}


def _doc_name(meta: dict) -> str:
    return norm((meta.get("filename") or "") + " " + (meta.get("titulo") or ""))


_vocab_cache: Dict[str, object] = {"key": None, "vocab": set()}
_NARROW_NAME = ("calibracao", "roteiro", "instrucao", "transformacao")


def _equipment_vocab(index: list) -> set:
    """Palavras (3+ letras) que aparecem no NOME de algum documento da base, tirando as que não
    identificam equipamento (tipo de documento, categoria, nome de peça). É o que permite reconhecer
    "lhn", "mdc", "tig", "esab", "handyarc"... - a busca antiga por modelo só considerava palavras de
    5+ letras e não via "lhn" (achado em 13/10/2026: "me envia manual da lhn" devolveu Powermax)."""
    from app.services.rag_service import rag_service
    key = f"{id(index)}:{len(index)}"
    if _vocab_cache["key"] != key:
        generic = {norm(w) for w in getattr(rag_service, "_GENERIC_WORDS", set())}
        vocab = set()
        for m in index:
            vocab.update(w for w in re.findall(r"[a-z]+", _doc_name(m)) if len(w) >= 3)
        _vocab_cache["key"] = key
        _vocab_cache["vocab"] = {w for w in vocab if w not in _NOT_EQUIPMENT and w not in generic and w[:6] not in _STEM_TO_GROUP}
    return _vocab_cache["vocab"]  # type: ignore[return-value]


def _doc_index(tenant_id: int) -> list:
    from app.services.rag_service import rag_service
    try:
        return rag_service._get_doc_index(tenant_id) or []
    except Exception:
        return []


def _query_signal(tenant_id: int, text: str) -> Tuple[set, set]:
    """(palavras de equipamento, números) citados no texto."""
    vocab = _equipment_vocab(_doc_index(tenant_id))
    t = norm(text)
    words = {w for w in re.findall(r"[a-z]+", t) if len(w) >= 3 and w in vocab}
    nums = set(re.findall(r"\d+", t))
    return words, nums


def _rank_docs(tenant_id: int, text: str) -> list:
    """Documentos cujo NOME bate com o equipamento do texto, no formato (pontos, estreito, trechos,
    meta), do melhor pro pior. Precisa bater pelo menos uma PALAVRA de equipamento quando o texto cita
    uma (achado em 13/10/2026: "Me envia manual" sobre o Hardcut 52 mandou a vista explodida de uma
    furadeira INGCO, que só batia número solto); sem palavra, só vale número de 3+ dígitos."""
    from app.services.rag_service import MODEL_NUMBER_IN_NAME
    words, nums = _query_signal(tenant_id, text)
    if not words and not any(len(n) >= 3 for n in nums):
        return []
    out = []
    for m in _doc_index(tenant_id):
        name = _doc_name(m)
        name_words = set(re.findall(r"[a-z]+", name))
        name_nums = set(re.findall(MODEL_NUMBER_IN_NAME, (m.get("filename") or "") + " " + (m.get("titulo") or "")))
        wm = len(words & name_words)
        nm = len(nums & name_nums)
        if words and not wm:
            continue
        if not words and not any(len(n) >= 3 for n in nums & name_nums):
            continue
        narrow = any(x in name for x in _NARROW_NAME)
        out.append((wm * 2 + nm * 2, 1 if narrow else 0, int(m.get("total_chunks") or 1), m))
    out.sort(key=lambda x: (-x[0], x[1], -x[2]))
    return out


def resolve_equipment(tenant_id: int, mensagem: str, history: List[dict]) -> Tuple[str, list]:
    """Texto que identifica o equipamento da pergunta + documentos que batem com ele.
      - A mensagem cita equipamento ("lhn", "powermax 65"): usa SÓ ela - nunca herda outro da conversa
        (achado em 13/10/2026: "me envia manual da lhn" logo depois de falar da Powermax devolvia
        Powermax, porque "lhn" não era reconhecida e o modelo era herdado).
      - Só número ("240", resposta a "qual modelo?"): junta com a palavra de equipamento mais recente
        do técnico na conversa ("lhn" + "240").
      - Nada: herda da mensagem mais recente DO TÉCNICO que citava equipamento, ou do título do
        documento já mandado - nunca do texto da IA (número de exemplo, tensão...)."""
    words, nums = _query_signal(tenant_id, mensagem)
    if words:
        return mensagem, _rank_docs(tenant_id, mensagem)

    anteriores = []
    for h in reversed(history):
        if h.get("remetente") == "tecnico" and h.get("conteudo"):
            anteriores.append(h["conteudo"])
        if h.get("documento_titulo"):
            anteriores.append(h["documento_titulo"])

    if nums:
        for prev in anteriores:
            pw, _ = _query_signal(tenant_id, prev)
            if pw:
                combinado = " ".join(sorted(pw)) + " " + mensagem
                r = _rank_docs(tenant_id, combinado)
                if r:
                    return combinado, r
                break
        r = _rank_docs(tenant_id, mensagem)
        if r:
            return mensagem, r

    for prev in anteriores:
        r = _rank_docs(tenant_id, prev)
        if r:
            return prev, r
    return "", []


def equipment_label(tenant_id: int, text: str) -> str:
    words, _ = _query_signal(tenant_id, text)
    return " ".join(sorted(w.upper() for w in words))


def _model_tokens(equip_text: str) -> Tuple[set, set]:
    ws = _words(equip_text)
    numbers = {w for w in ws if w.isdigit()}
    letters = {w for w in ws if not w.isdigit() and 2 <= len(w) <= 12 and w not in _STOP}
    return numbers, letters


def _score_part(desc_norm: str, groups: set, loose: set) -> int:
    dws = set(w[:6] for w in re.findall(r"[a-z0-9]+", desc_norm))
    dgroups = {_STEM_TO_GROUP[w] for w in dws if w in _STEM_TO_GROUP}
    return 3 * len(groups & dgroups) + len(loose & dws)


async def find_parts(tenant_id: int, mensagem: str, equip_text: str, ranked_docs: list, limit: int = 5) -> List[PartsCatalogItem]:
    numbers, letters = _model_tokens(equip_text)
    # Palavras do MODELO (ex: "lhn") não descrevem a peça - só as que também aparecem no nome do manual
    top_names = " ".join(norm((m.get("filename") or "") + " " + (m.get("titulo") or "")) for _o, _n, _c, m in ranked_docs[:4])
    model_words = {w for w in letters if w in top_names}
    groups, loose = _concepts([w for w in _words(mensagem) if w not in model_words and not any(ch.isdigit() for ch in w)])
    if not groups and not loose:
        return []
    needed = 3 * len(groups) + len(loose)
    doc_ids = [meta.get("parent_doc_id") for _ov, _n, _c, meta in ranked_docs[:4] if meta.get("parent_doc_id")]

    async with AsyncSessionLocal() as db:
        pools = []
        if doc_ids:
            pools.append((await db.execute(select(PartsCatalogItem).where(
                PartsCatalogItem.tenant_id == tenant_id, PartsCatalogItem.parent_doc_id.in_(doc_ids)))).scalars().all())
        if numbers:
            # Peça cujo NOME cita o modelo (ex: "CIRCUITO DE CONTROLE LHN 242I"), mesmo vindo de outro catálogo
            conds = [PartsCatalogItem.descricao_norm.like(f"%{n}%") for n in numbers]
            q = select(PartsCatalogItem).where(PartsCatalogItem.tenant_id == tenant_id)
            for c in conds:
                q = q.where(c)
            pools.append((await db.execute(q.limit(3000))).scalars().all())

    best: List[Tuple[int, PartsCatalogItem]] = []
    seen = set()
    for pool_idx, pool in enumerate(pools):
        for p in pool:
            key = (p.codigo, p.descricao_norm)
            if key in seen:
                continue
            seen.add(key)
            s = _score_part(p.descricao_norm, groups, loose)
            if s <= 0:
                continue
            if pool_idx == 1:
                pw = set(re.findall(r"[a-z0-9]+", p.descricao_norm))
                if not (numbers & {re.sub(r"[a-z]+$", "", w) for w in pw}):
                    continue  # o número precisa aparecer como token do modelo, não dentro de outro código
                if letters and not (letters & pw):
                    s -= 1
            best.append((s, p))
    if not best:
        return []
    top = max(s for s, _ in best)
    # Exige que bata os conceitos principais (ex: "placa" E "controle", não só "placa") - tolera 1
    # palavra solta a mais na pergunta quando ela descreve a peça com várias palavras.
    if top < (needed if needed <= 3 else needed - 1):
        return []
    return [p for s, p in sorted(best, key=lambda x: -x[0]) if s == top][:limit]


async def find_by_code(tenant_id: int, mensagem: str) -> List[PartsCatalogItem]:
    codes = {m.group(1).strip(".-/").upper() for m in CODE_TOKEN.finditer(mensagem) if sum(ch.isdigit() for ch in m.group(1)) >= 5}
    if not codes:
        return []
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PartsCatalogItem).where(
            PartsCatalogItem.tenant_id == tenant_id,
            (PartsCatalogItem.codigo.in_(codes)) | (PartsCatalogItem.part_number.in_(codes)),
        ).limit(10))
        return res.scalars().all()


def pick_document(mensagem: str, ranked_docs: list) -> Tuple[Optional[dict], List[dict], Optional[str]]:
    """(documento escolhido, alternativas, tipo pedido que NÃO foi encontrado no nome)."""
    msg_n = norm(mensagem)
    wanted = None
    for k in DOC_TYPES:
        if k in msg_n or (k == "servico" and "manual de servico" in msg_n):
            wanted = k
            break
    cands = []
    for ov, narrow, chunks, meta in ranked_docs[:12]:
        sp = meta.get("source_path")
        if not sp or not os.path.exists(sp):
            continue
        name_n = norm((meta.get("filename") or "") + " " + (meta.get("titulo") or ""))
        type_hit = bool(wanted) and any(t in name_n for t in DOC_TYPES[wanted])
        score = ov * 10 + (8 if type_hit else 0) - (3 if (narrow and not type_hit) else 0)
        cands.append((score, type_hit, meta))
    if not cands:
        return None, [], wanted
    cands.sort(key=lambda c: -c[0])
    best_score, best_type_hit, best = cands[0]
    alts = [c[2] for c in cands[1:MAX_OPTIONS] if c[0] >= best_score - 10]
    missing_type = wanted if (wanted and not best_type_hit) else None
    return best, alts, missing_type


def format_parts_answer(parts: List[PartsCatalogItem]) -> str:
    src = parts[0].filename or parts[0].titulo
    lines = [f"📘 Bibliotecário - achei na tabela de peças do manual {src}:"]
    for p in parts:
        extra = f" · part number {p.part_number}" if p.part_number else ""
        item = f" (item {p.item})" if p.item else ""
        lines.append(f"• {p.descricao} - código {p.codigo}{extra}{item}")
    lines.append("")
    lines.append("Abri o manual já na página dessa peça - confira o modelo/revisão do seu equipamento antes de pedir.")
    return "\n".join(lines)


def format_code_lookup_answer(parts: List[PartsCatalogItem]) -> str:
    lines = ["📘 Bibliotecário - esse código aparece em:"]
    for p in parts[:5]:
        extra = f" · part number {p.part_number}" if p.part_number else ""
        lines.append(f"• {p.descricao} - código {p.codigo}{extra} ({p.filename or p.titulo})")
    return "\n".join(lines)


def pretty_title(meta: dict) -> str:
    """Nome legível do documento pra mostrar ao técnico: sem ".pdf", sem o caminho de pastas, sem
    "__"/"_" do nome de arquivo, com a marca no fim quando ela não aparece no nome.
    "HYPERTHERM / POWERMAX 45XP - MANUAL DE SERVICO.pdf" -> "POWERMAX 45XP - MANUAL DE SERVICO (Hypertherm)"."""
    titulo = (meta.get("titulo") or "").strip()
    segs = [x.strip() for x in titulo.split(" / ") if x.strip()] if titulo else []
    marca = (meta.get("marca") or (segs[0] if len(segs) >= 2 else "")).strip()
    partes = segs[1:] if len(segs) >= 2 else [meta.get("filename") or titulo or "Documento"]

    def limpa(x: str) -> str:
        x = re.sub(r"\.pdf$", "", x, flags=re.I).replace("__", " - ").replace("_", " ")
        return re.sub(r"\s+", " ", x).strip(" -")

    nome = " · ".join(limpa(x) for x in partes if limpa(x))
    # Tira código interno de produto (6+ dígitos: "742528 - LHN 242I 752315") - só polui a lista
    nome = re.sub(r"(?<![\w.])\d{6,}(?![\w.])\s*-?\s*", "", nome)
    nome = re.sub(r"\s+·\s+", " · ", re.sub(r"\s{2,}", " ", nome)).strip(" -·")
    if marca and norm(marca) not in norm(nome):
        nome += f" ({marca.title()})"
    return nome or "Documento"


def format_document_answer(doc: dict, alts: List[dict], missing_type: Optional[str]) -> str:
    titulo = pretty_title(doc)
    if missing_type:
        return (f"📘 Bibliotecário - não achei um {missing_type} específico desse modelo na base. "
                f"O documento mais próximo é: {titulo}. Se quiser, me pergunta o que precisa que eu monto a partir dele.")
    return f"📘 Bibliotecário - aqui está: {titulo}."


# ---------------------------------------------------------------------------------------------
# Lista numerada de documentos - pedido do usuário em 13/10/2026: "lista eles com números e pede
# pro técnico escolher um número, e ele manda o manual do número correspondente". Antes ia um
# documento + "Também tenho: A; B; C" numa linha só, com o nome de arquivo inteiro - bagunçado.
# ---------------------------------------------------------------------------------------------

class CopilotDocOption(Base):
    """Opções que o bibliotecário ofereceu numa mensagem (o técnico responde com o número). Fica
    aqui e não em models.py de propósito: tabela de uso só do bibliotecário, criada sozinha no boot
    (create_all) por estar registrada no mesmo Base."""
    __tablename__ = "copilot_doc_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    opcoes_json: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# "2", "o 2", "opção 2", "nº 2", "manda o 2"
CHOICE = re.compile(r"^\s*(?:op[cç][aã]o|n[uú]mero|num|n[ºo°]\.?|quero o|quero a|manda o|manda a|o|a)?\s*(\d{1,2})\s*[.!)]?\s*$", re.I)


def parse_option_choice(mensagem: str) -> Optional[int]:
    m = CHOICE.match(mensagem or "")
    return int(m.group(1)) if m else None


def document_options(doc: dict, alts: List[dict]) -> List[dict]:
    return [
        {"nome": pretty_title(d), "titulo": d.get("titulo") or d.get("filename"), "source_path": d.get("source_path")}
        for d in [doc] + list(alts)
    ][:MAX_OPTIONS]


def format_document_choices(options: List[dict]) -> str:
    linhas = [f"📘 Bibliotecário - achei {len(options)} documentos:", ""]
    linhas += [f"{i}. {o['nome']}" for i, o in enumerate(options, 1)]
    linhas += ["", "Responda só com o número que eu abro o documento aqui."]
    return "\n".join(linhas)


async def save_options(message_id: int, options: List[dict]) -> None:
    async with AsyncSessionLocal() as db:
        db.add(CopilotDocOption(message_id=message_id, opcoes_json=json.dumps(options, ensure_ascii=False)))
        await db.commit()


async def load_latest_options(message_ids: List[int]) -> Optional[List[dict]]:
    """A lista numerada mais recente entre essas mensagens - o técnico pode escolher o 2 e depois
    pedir o 5 da MESMA lista, sem o bibliotecário ter que listar de novo."""
    if not message_ids:
        return None
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(CopilotDocOption).where(CopilotDocOption.message_id.in_(message_ids)).order_by(CopilotDocOption.message_id.desc()).limit(1)
        )).scalar_one_or_none()
    return json.loads(row.opcoes_json) if row else None


async def load_options(message_id: int) -> Optional[List[dict]]:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(CopilotDocOption).where(CopilotDocOption.message_id == message_id))).scalar_one_or_none()
    return json.loads(row.opcoes_json) if row else None


# Correção do técnico ("eu pedi da lhn", "não é esse", "quero o da lhn") - vale como pedido de
# documento quando a última resposta foi um documento/lista (achado em 13/10/2026).
CORRECTION_INTENT = re.compile(
    r"\b(pedi|quero|queria|errad[oa]|confundiu|n[aã]o (?:é|e|era) (?:esse|essa|isso)|n[aã]o quero|outr[oa])\b", re.I)


def _models_next_to(words: set, metas: list) -> set:
    """Números de modelo que aparecem LOGO DEPOIS da palavra da linha no nome do documento
    ("lhn 240", "lhn_242i", "lhn220i", "powermax 65-85", "handyarc_130i_140i_160i") - e não qualquer
    número do nome (rev02, código 733920...)."""
    out = set()
    for m in metas:
        name = _doc_name(m)
        for w in words:
            for occ in re.finditer(re.escape(w), name):
                tail = name[occ.end():occ.end() + 40]
                seq = re.match(r"(?:[\s_\-/·]*\d{2,4}[a-z]?(?![0-9]))+", tail)
                if seq:
                    out.update(re.findall(r"\d{2,4}", seq.group(0)))
    return out


def decide_documents(tenant_id: int, mensagem: str, ranked_docs: list, equip_text: str = "") -> dict:
    """O que fazer com um pedido de documento:
      {"tipo": "unico", "doc"}                 - um documento certo: manda
      {"tipo": "lista", "opcoes"}              - poucos possíveis: lista numerada
      {"tipo": "modelo", "modelos", "rotulo", "nao_achado"} - a linha tem vários modelos e o pedido não
                                                 diz qual (ou diz um que não existe): pergunta o modelo
      {"tipo": "nenhum"}
    Em todos, "faltando" = tipo pedido (esquema, roteiro...) que não existe no nome dos documentos.
    `equip_text` = texto que identificou o equipamento (pode ser "lhn 242" juntando a conversa)."""
    texto = equip_text or mensagem
    doc, alts, missing = pick_document(mensagem, ranked_docs)
    if not doc:
        return {"tipo": "nenhum", "faltando": missing}
    words, nums = _query_signal(tenant_id, texto)
    melhor = ranked_docs[0][0] if ranked_docs else 0
    empatados = [m for pts, _n, _c, m in ranked_docs if pts == melhor]
    modelos_linha = _models_next_to(words, [m for _p, _n, _c, m in ranked_docs]) if words else set()
    pedido_existe = bool(nums & modelos_linha) or bool(nums & _models_next_to(words, empatados))
    numero_pedido = sorted(n for n in nums if 2 <= len(n) <= 4)
    if len(modelos_linha) >= 2 and not pedido_existe and (len(empatados) > MAX_OPTIONS or numero_pedido):
        return {"tipo": "modelo", "modelos": sorted(modelos_linha, key=int)[:20],
                "rotulo": " ".join(sorted(w.upper() for w in words)),
                "nao_achado": numero_pedido[0] if numero_pedido else None, "faltando": missing}
    if alts:
        return {"tipo": "lista", "opcoes": document_options(doc, alts), "faltando": missing}
    return {"tipo": "unico", "doc": doc, "faltando": missing}


def format_ask_model(rotulo: str, modelos: List[str], nao_achado: Optional[str] = None) -> str:
    linha = f" da {rotulo}" if rotulo else ""
    aviso = f"Não achei documento do modelo {nao_achado}{linha}. " if nao_achado else ""
    return (f"📘 Bibliotecário - {aviso}Tenho documentos destes modelos{linha}: {', '.join(modelos)}.\n\n"
            f"De qual modelo você precisa? (pode responder só o número)")
