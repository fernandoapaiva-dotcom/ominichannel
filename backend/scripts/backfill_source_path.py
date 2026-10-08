"""
Remendo rápido pros documentos já indexados antes do source_path existir na metadata -
não reprocessa texto nenhum (rápido), só caminha pelas pastas de novo recalculando o
doc_id (igual ingest_rag_docs.py) e grava source_path na metadata de cada chunk via
collection.update() (metadata-only, não mexe no texto já indexado).

Uso:
    cd backend && source venv/bin/activate
    python -m scripts.backfill_source_path
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ingest_rag_docs import iter_target_files, doc_id_for_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_source_path")

ROOTS = [
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/DOC. TÉCNICOS",
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/ONDA DE CIRCUITO",
]


def main():
    import chromadb
    client = chromadb.PersistentClient(path=os.path.join(os.getcwd(), "chroma_data"))
    collection = client.get_or_create_collection("tenant_knowledge_base")

    patched = 0
    already_ok = 0
    not_found_in_db = 0
    total = 0

    for full_path, _marca, _modelo, _fname in iter_target_files(ROOTS):
        total += 1
        doc_id = doc_id_for_path(full_path)

        res = collection.get(where={"parent_doc_id": doc_id}, include=["metadatas"])
        ids = res.get("ids", [])
        metas = res.get("metadatas", [])
        if not ids:
            not_found_in_db += 1
            continue

        ids_to_patch = []
        metas_to_patch = []
        for cid, meta in zip(ids, metas):
            if meta.get("source_path") == full_path:
                continue
            meta = dict(meta)
            meta["source_path"] = full_path
            ids_to_patch.append(cid)
            metas_to_patch.append(meta)

        if ids_to_patch:
            collection.update(ids=ids_to_patch, metadatas=metas_to_patch)
            patched += len(ids_to_patch)
        else:
            already_ok += 1

        if total % 100 == 0:
            logger.info(f"progresso: {total} arquivos verificados, {patched} chunks remendados")

    logger.info(f"Concluído. total_arquivos={total} chunks_remendados={patched} ja_ok={already_ok} nao_estava_no_banco={not_found_in_db}")


if __name__ == "__main__":
    main()
