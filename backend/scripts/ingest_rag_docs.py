"""
Ingestão em lote de manuais técnicos (pasta "DOC. TÉCNICOS" / "ONDA DE CIRCUITO" em
Z:\\Documentos\\ASSISTENCIA, montada via CIFS) na base de conhecimento RAG (ChromaDB).

Cada arquivo é indexado com metadata de marca/modelo (tirada do caminho da pasta), scope
"geral" (fica disponível pra IA em qualquer departamento) e department_name "Assistência
Técnica".

Uso:
    cd backend && source venv/bin/activate
    python -m scripts.ingest_rag_docs --dry-run                 # só lista o que seria ingerido
    python -m scripts.ingest_rag_docs --limit 20                # ingere só os 20 primeiros (teste)
    python -m scripts.ingest_rag_docs                            # ingere tudo
    python -m scripts.ingest_rag_docs --resume-log ingest.log    # retoma pulando já ingeridos

Roda com pausa entre arquivos pra não sobrecarregar o servidor (--sleep, padrão 0.3s).
"""
import argparse
import asyncio
import hashlib
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Tenant
from app.services.rag_service import rag_service
from app.api.v1.rag import extract_text_from_bytes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("ingest_rag_docs")
logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("PyPDF2").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)

ALLOWED_EXTS = {"pdf", "doc", "docx", "txt", "md"}
DEPARTMENT_NAME = "Assistência Técnica"

# Prompt usado só pro fallback de OCR via Gemini (--ocr), quando a extração normal de texto não
# acha nada - típico de manual/esquema elétrico salvo como PÁGINA ESCANEADA (imagem dentro do
# PDF, sem camada de texto). Pedido do usuário em 07/10/2026 à noite ("aprendizado profundo...
# fique sabendo tudo"): dos 2172 arquivos elegíveis, 138 ficaram de fora só por isso.
OCR_PROMPT = (
    "Você está ajudando a montar a base de conhecimento técnica de uma assistência técnica de "
    "equipamentos de solda/corte (ESAB, VONDER, EUTECTIC etc). Este documento é uma página "
    "ESCANEADA (imagem) de um manual, esquema elétrico, diagrama ou roteiro de calibração - sem "
    "camada de texto extraível.\n\n"
    "Transcreva TUDO que estiver visível, com o máximo de fidelidade e detalhe:\n"
    "- Todo texto (títulos, parágrafos, legendas, notas de rodapé).\n"
    "- Toda TABELA, linha por linha (valores, unidades, nomes de componentes).\n"
    "- Se for um ESQUEMA/DIAGRAMA ELÉTRICO: descreva cada componente visível (nome, código/ref, "
    "ex: J18, VR1, IGBT, resistor, transformador), os valores anotados (tensão, resistência, "
    "corrente) e como os componentes se conectam entre si, da forma mais completa possível - um "
    "técnico vai usar essa descrição pra entender o diagrama SEM ver a imagem original.\n"
    "- Números de modelo, código do equipamento e revisão do documento, se aparecerem.\n\n"
    "Responda só com a transcrição/descrição em si, sem comentários seus. Se a página estiver "
    "em branco, ilegível ou não tiver nenhum conteúdo técnico aproveitável, responda exatamente: "
    "[SEM_CONTEUDO]"
)


async def ocr_with_gemini(content_bytes: bytes, fname: str) -> str:
    """Fallback de OCR pro PDF/DOC que a extração normal não leu (página escaneada/imagem) -
    manda o arquivo original pro Gemini (suporta PDF nativo via Part.from_bytes) e pede uma
    transcrição/descrição técnica completa. Ver OCR_PROMPT acima."""
    from google import genai
    from app.core.config import settings

    ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
    mime = "application/pdf" if ext == "pdf" else (
        "application/msword" if ext == "doc" else
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if ext == "docx" else
        "application/octet-stream"
    )
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    for model_name in ["gemini-3.1-flash-lite", "gemini-3.6-flash"]:
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=[OCR_PROMPT, genai.types.Part.from_bytes(data=content_bytes, mime_type=mime)],
            )
            text = (response.text or "").strip() if response else ""
            if text and "[SEM_CONTEUDO]" not in text:
                return text
            return ""
        except Exception as e:
            logger.warning(f"[OCR] falhou com {model_name} em {fname}: {e}")
            continue
    return ""


def iter_target_files(roots):
    for root in roots:
        if not os.path.isdir(root):
            logger.warning(f"Pasta não encontrada, pulando: {root}")
            continue
        base_parts = len(root.rstrip(os.sep).split(os.sep))
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
                if ext not in ALLOWED_EXTS:
                    continue
                full_path = os.path.join(dirpath, fname)
                rel_parts = dirpath.rstrip(os.sep).split(os.sep)[base_parts:]
                marca = rel_parts[0] if len(rel_parts) >= 1 else ""
                modelo = rel_parts[1] if len(rel_parts) >= 2 else ""
                yield full_path, marca, modelo, fname


def doc_id_for_path(full_path: str) -> str:
    return "doctec_" + hashlib.md5(full_path.encode("utf-8")).hexdigest()


def is_allowed_file(fname: str) -> bool:
    ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
    return ext in ALLOWED_EXTS


def marca_modelo_from_path(root: str, full_path: str):
    base_parts = len(root.rstrip(os.sep).split(os.sep))
    dirpath = os.path.dirname(full_path)
    rel_parts = dirpath.rstrip(os.sep).split(os.sep)[base_parts:]
    marca = rel_parts[0] if len(rel_parts) >= 1 else ""
    modelo = rel_parts[1] if len(rel_parts) >= 2 else ""
    return marca, modelo


async def ingest_one_file(full_path: str, marca: str, modelo: str, fname: str, tenant_id: int, use_ocr: bool = False) -> str:
    """Extracts text from one file and upserts it into RAG. Returns 'ok', 'ok_ocr', 'empty', or 'error'."""
    doc_id = doc_id_for_path(full_path)
    titulo = " / ".join([p for p in [marca, modelo, fname] if p])

    try:
        with open(full_path, "rb") as f:
            content_bytes = f.read()
        extracted_text = extract_text_from_bytes(fname, content_bytes)
    except Exception as e:
        logger.warning(f"[ERRO LEITURA] {full_path}: {e}")
        return "error"

    via_ocr = False
    if not extracted_text or not extracted_text.strip():
        if use_ocr:
            try:
                extracted_text = await ocr_with_gemini(content_bytes, fname)
                via_ocr = bool(extracted_text and extracted_text.strip())
            except Exception as e:
                logger.warning(f"[OCR ERRO] {titulo}: {e}")
                extracted_text = ""
        if not extracted_text or not extracted_text.strip():
            logger.info(f"[SEM TEXTO] {titulo}")
            return "empty"

    success = await rag_service.add_document(
        tenant_id=tenant_id,
        doc_id=doc_id,
        content=extracted_text,
        metadata={
            "titulo": titulo,
            "filename": fname,
            "source_path": full_path,
            "scope": "geral",
            "department_id": 0,
            "department_name": DEPARTMENT_NAME,
            "marca": marca or "",
            "modelo": modelo or "",
            "via_ocr": via_ocr,
        },
    )
    if success:
        logger.info(f"[{'OCR' if via_ocr else 'OK'}] {titulo} ({len(extracted_text)} chars)")
        return "ok_ocr" if via_ocr else "ok"
    else:
        logger.warning(f"[FALHA INDEXAR] {titulo}")
        return "error"


async def resolve_tenant_id():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()
        if not tenants:
            raise RuntimeError("Nenhum tenant encontrado no banco.")
        if len(tenants) == 1:
            return tenants[0].id
        for t in tenants:
            if "servweld" in (t.nome or "").lower():
                return t.id
        raise RuntimeError(
            f"Múltiplos tenants encontrados ({[(t.id, t.nome) for t in tenants]}); "
            "passe --tenant-id explicitamente."
        )


def load_done_ids(resume_log_path):
    done = set()
    if resume_log_path and os.path.exists(resume_log_path):
        with open(resume_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done.add(line)
    return done


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roots",
        nargs="+",
        default=[
            "/mnt/softsystem_drive/Documentos/ASSISTENCIA/DOC. TÉCNICOS",
            "/mnt/softsystem_drive/Documentos/ASSISTENCIA/ONDA DE CIRCUITO",
        ],
    )
    parser.add_argument("--tenant-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument("--ocr-sleep", type=float, default=1.5, help="Pausa extra (segundos) só depois de uma chamada de OCR via Gemini, pra não estourar limite de taxa da API.")
    parser.add_argument("--resume-log", default=None, help="Arquivo de log pra pular doc_ids já ingeridos numa retomada.")
    parser.add_argument("--ocr", action="store_true", help="Quando a extração normal não achar texto (página escaneada), tenta OCR via Gemini antes de desistir do arquivo.")
    args = parser.parse_args()

    tenant_id = args.tenant_id or await resolve_tenant_id()
    logger.info(f"Usando tenant_id={tenant_id}")

    done_ids = load_done_ids(args.resume_log)
    if done_ids:
        logger.info(f"Retomando: {len(done_ids)} documentos já ingeridos serão pulados.")

    resume_fh = open(args.resume_log, "a", encoding="utf-8") if (args.resume_log and not args.dry_run) else None

    total = 0
    indexed = 0
    indexed_ocr = 0
    skipped_empty = 0
    skipped_done = 0
    errors = 0

    for full_path, marca, modelo, fname in iter_target_files(args.roots):
        if args.limit and total >= args.limit:
            break
        total += 1

        doc_id = doc_id_for_path(full_path)

        if doc_id in done_ids:
            skipped_done += 1
            continue

        if args.dry_run:
            titulo = " / ".join([p for p in [marca, modelo, fname] if p])
            logger.info(f"[DRY-RUN] indexaria: {titulo}")
            indexed += 1
            continue

        result = await ingest_one_file(full_path, marca, modelo, fname, tenant_id, use_ocr=args.ocr)
        if result in ("ok", "ok_ocr"):
            indexed += 1
            if result == "ok_ocr":
                indexed_ocr += 1
            if resume_fh:
                resume_fh.write(doc_id + "\n")
                resume_fh.flush()
        elif result == "empty":
            skipped_empty += 1
        else:
            errors += 1

        if result == "ok_ocr" and args.ocr_sleep:
            time.sleep(args.ocr_sleep)
        elif args.sleep:
            time.sleep(args.sleep)

    if resume_fh:
        resume_fh.close()

    logger.info(
        f"Concluído. total_visto={total} indexados={indexed} (via_ocr={indexed_ocr}) "
        f"sem_texto={skipped_empty} ja_feitos={skipped_done} erros={errors}"
    )


if __name__ == "__main__":
    asyncio.run(main())
