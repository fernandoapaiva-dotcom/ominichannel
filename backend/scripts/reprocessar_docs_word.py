"""
Reprocessa no RAG todos os arquivos .doc (Word 97-2003) das pastas de documentos técnicos.

Achado em 13/10/2026: a leitura de .doc devolvia o arquivo BINÁRIO decodificado como texto - um
.doc de 10 MB virava milhares de trechos de lixo na base (ex: "IIER RJLSPT 1.doc" com 452 trechos),
poluindo as buscas do Copiloto, e os .doc grandes travavam o vigia de treinamento. Com a extração
nova (app.api.v1.rag.extract_legacy_doc_text), este script, pra cada .doc:
  1. apaga TODOS os trechos antigos do documento (por parent_doc_id - o delete_document do
     rag_service só apaga o registro principal, não os trechos);
  2. indexa de novo com o texto limpo;
  3. marca como aprendido no log do vigia (não volta pra fila).

Rodar com o vigia PARADO (pra não disputar o mesmo documento):
    pm2 stop rag-folder-watcher
    nice -n 10 venv/bin/python scripts/reprocessar_docs_word.py
    pm2 start rag-folder-watcher
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ingest_rag_docs import doc_id_for_path, ingest_one_file, iter_target_files, load_done_ids  # noqa: E402
from app.services.rag_service import rag_service  # noqa: E402

logging.basicConfig(level=logging.WARNING)
ROOTS = [
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/DOC. TÉCNICOS",
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/ONDA DE CIRCUITO",
]
RESUME_LOG_PATH = "scripts/ingest_esab_resume.log"
TENANT_ID = 1


def _trechos(doc_id: str) -> int:
    return len(rag_service.collection.get(where={"parent_doc_id": doc_id}, include=[]).get("ids") or [])


async def main():
    rag_service._ensure_client()
    feitos = load_done_ids(RESUME_LOG_PATH)
    docs = [(p, m, mo, f) for p, m, mo, f in iter_target_files(ROOTS) if f.lower().endswith(".doc")]
    print(f"{len(docs)} arquivo(s) .doc encontrados")
    for path, marca, modelo, fname in docs:
        doc_id = doc_id_for_path(path)
        antes = _trechos(doc_id)
        rag_service.collection.delete(where={"parent_doc_id": doc_id})
        try:
            r = await asyncio.wait_for(ingest_one_file(path, marca, modelo, fname, TENANT_ID, use_ocr=False), timeout=600)
        except asyncio.TimeoutError:
            r = "timeout"
        depois = _trechos(doc_id)
        if r.startswith("ok") and doc_id not in feitos:
            with open(RESUME_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(doc_id + "\n")
            feitos.add(doc_id)
        print(f"  {marca} / {fname}: {antes} -> {depois} trechos ({r})")


if __name__ == "__main__":
    asyncio.run(main())
