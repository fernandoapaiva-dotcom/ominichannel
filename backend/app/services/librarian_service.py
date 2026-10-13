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
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.models import PartsCatalogItem

logger = logging.getLogger("librarian")

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


def _rank_docs(tenant_id: int, text: str) -> list:
    """Documentos cujo NOME bate com o equipamento do texto - mas só os que batem pelo menos uma
    PALAVRA do equipamento (marca/linha: lhn, powermax, hardcut...). Achado em 13/10/2026: "Me envia
    manual" numa conversa sobre a tocha do Hardcut 52 mandou a vista explodida de uma furadeira
    INGCO, que só batia NÚMERO solto com o texto. Número sozinho só vale se tiver 3+ dígitos e o
    texto não citar palavra nenhuma de equipamento (ex: "manual do 0205322")."""
    from app.services.rag_service import rag_service, MODEL_NUMBER_IN_NAME
    try:
        ranked = rag_service._rank_docs_by_model_number(tenant_id, text, 0)
    except Exception:
        return []
    if not ranked:
        return []
    words = {w for w in _words(text) if not w.isdigit() and len(w) >= 3 and w not in _NOT_EQUIPMENT}
    numbers = {w for w in _words(text) if w.isdigit()}
    out = []
    for item in ranked:
        meta = item[3]
        name = (meta.get("filename") or "") + " " + (meta.get("titulo") or "")
        name_words = set(_words(name))
        if words & name_words:
            out.append(item)
        elif not words:
            name_numbers = set(re.findall(MODEL_NUMBER_IN_NAME, name))
            if any(len(n) >= 3 for n in numbers & name_numbers):
                out.append(item)
    return out


def resolve_equipment(tenant_id: int, mensagem: str, history: List[dict]) -> Tuple[str, list]:
    """Texto que identifica o equipamento da pergunta + documentos que batem com ele. Se a pergunta
    não cita modelo, herda da mensagem mais recente DO TÉCNICO que citava, ou do título do documento
    que já foi mandado na conversa - nunca do texto da IA (que tem número de exemplo, valor de
    tensão etc. e fazia herdar um "modelo" que ninguém pediu)."""
    ranked = _rank_docs(tenant_id, mensagem)
    if ranked:
        return mensagem, ranked
    for h in reversed(history):
        texts = [h.get("documento_titulo") or ""]
        if h.get("remetente") == "tecnico":
            texts.insert(0, h.get("conteudo") or "")
        for text in texts:
            if not text:
                continue
            r = _rank_docs(tenant_id, text)
            if r:
                return text, r
    return "", []


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
    alts = [c[2] for c in cands[1:4] if c[0] >= best_score - 10]
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


def format_document_answer(doc: dict, alts: List[dict], missing_type: Optional[str]) -> str:
    titulo = doc.get("titulo") or doc.get("filename")
    if missing_type:
        text = (f"📘 Bibliotecário - não achei um {missing_type} específico desse modelo na base. "
                f"O documento mais próximo é: {titulo}. Se quiser, me pergunta o que precisa que eu monto a partir dele.")
    else:
        text = f"📘 Bibliotecário - aqui está: {titulo}."
    if alts:
        text += "\n\nTambém tenho: " + "; ".join((a.get("titulo") or a.get("filename")) for a in alts) + ". É só pedir pelo nome."
    return text
