"""
Ingestão dos documentos de FUNDAMENTOS (conhecimento geral de engenharia por categoria de
equipamento de solda - MIG/MAG, TIG, inversor, plasma etc) na base RAG - complementa os manuais
de marca/modelo específicos já ingeridos (ver ingest_rag_docs.py) com o "livro-texto" que dá à IA
entendimento de arquitetura/princípio de funcionamento/terminologia da categoria inteira, não só
fatos pontuais de um manual. Pedido do usuário em 07/10/2026 à noite.

Esses documentos NÃO têm marca/modelo (são conhecimento geral da categoria) - fica marcado
"categoria_geral": True na metadata, e o prompt (gemini_service.py) trata esse tipo de fonte como
conhecimento confiável de engenharia geral, diferente de um manual de modelo específico.

Uso:
    cd backend && source venv/bin/activate
    python -m scripts.ingest_fundamentos --folder /caminho/pros/15/arquivos/md
"""
import argparse
import asyncio
import hashlib
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import Tenant
from app.services.rag_service import rag_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest_fundamentos")

DEPARTMENT_NAME = "Assistência Técnica"


async def resolve_tenant_id(explicit):
    if explicit:
        return explicit
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant))
        tenants = result.scalars().all()
        for t in tenants:
            if "servweld" in (t.nome or "").lower() or "modelo" in (t.nome or "").lower():
                return t.id
        if tenants:
            return tenants[0].id
        raise RuntimeError("Nenhum tenant encontrado.")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    parser.add_argument("--tenant-id", type=int, default=None)
    args = parser.parse_args()

    tenant_id = await resolve_tenant_id(args.tenant_id)
    logger.info(f"Usando tenant_id={tenant_id}")

    files = sorted(f for f in os.listdir(args.folder) if f.lower().endswith(".md"))
    logger.info(f"{len(files)} documentos de fundamentos encontrados em {args.folder}")

    for fname in files:
        full_path = os.path.join(args.folder, fname)
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Primeira linha "# Fundamentos — X" vira o título.
        first_line = content.split("\n", 1)[0].lstrip("#").strip()
        titulo = first_line or fname

        doc_id = "fundamentos_" + hashlib.md5(fname.encode("utf-8")).hexdigest()
        success = await rag_service.add_document(
            tenant_id=tenant_id,
            doc_id=doc_id,
            content=content,
            metadata={
                "titulo": titulo,
                "filename": fname,
                "source_path": full_path,
                "scope": "geral",
                "department_id": 0,
                "department_name": DEPARTMENT_NAME,
                "marca": "",
                "modelo": "",
                "categoria_geral": True,
            },
        )
        logger.info(f"[{'OK' if success else 'FALHA'}] {titulo} ({len(content)} chars)")

    logger.info("Concluído.")


if __name__ == "__main__":
    asyncio.run(main())
