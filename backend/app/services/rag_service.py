import os
import logging
from typing import Optional
import chromadb
from chromadb.config import Settings

logger = logging.getLogger("rag_service")

class RAGService:
    def __init__(self):
        persist_dir = os.path.join(os.getcwd(), "chroma_data")
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection("tenant_knowledge_base")

    async def add_document(
        self,
        tenant_id: int,
        doc_id: str,
        content: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """Adds or updates a text chunk in the local vector DB for a tenant with scope metadata"""
        try:
            meta = metadata or {}
            meta["tenant_id"] = int(tenant_id)
            meta["scope"] = str(meta.get("scope", "geral"))
            meta["department_id"] = int(meta.get("department_id") or 0)
            meta["department_name"] = str(meta.get("department_name") or "Geral")
            meta["titulo"] = str(meta.get("titulo") or "Documento RAG")
            meta["filename"] = str(meta.get("filename") or "")
            meta["criado_em"] = str(meta.get("criado_em") or os.environ.get("CURRENT_TIME", ""))

            self.collection.upsert(
                documents=[content],
                ids=[f"t{tenant_id}_{doc_id}"],
                metadatas=[meta]
            )
            return True
        except Exception as e:
            logger.error(f"Error adding document to RAG vector store: {e}")
            return False

    async def search_context(
        self,
        tenant_id: int,
        query: str,
        department_id: Optional[int] = None,
        top_k: int = 5
    ) -> str:
        """
        Searches tenant documents by semantic similarity.
        Includes BOTH Geral (company-wide) knowledge and department-specific knowledge.
        """
        try:
            # Query all documents for this tenant
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k,
                where={"tenant_id": int(tenant_id)}
            )
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]

            if not docs:
                return ""

            filtered_docs = []
            for doc, meta in zip(docs, metas):
                m_scope = meta.get("scope", "geral")
                m_dept_id = meta.get("department_id", 0)
                # Keep if document is Geral OR matches department_id
                if m_scope == "geral" or m_dept_id == 0 or (department_id and int(m_dept_id) == int(department_id)):
                    filtered_docs.append(doc)

            return "\n---\n".join(filtered_docs)
        except Exception as e:
            logger.error(f"Error searching RAG vector store: {e}")
            return ""

    async def list_documents(self, tenant_id: int) -> list:
        """Lists all RAG documents index metadata for a tenant"""
        try:
            res = self.collection.get(
                where={"tenant_id": int(tenant_id)},
                include=["metadatas", "documents"]
            )
            ids = res.get("ids", [])
            metas = res.get("metadatas", [])
            docs = res.get("documents", [])

            output = []
            for d_id, meta, doc in zip(ids, metas, docs):
                output.append({
                    "id": d_id.replace(f"t{tenant_id}_", ""),
                    "full_id": d_id,
                    "titulo": meta.get("titulo", "Sem Título"),
                    "scope": meta.get("scope", "geral"),
                    "department_id": meta.get("department_id", 0),
                    "department_name": meta.get("department_name", "Geral"),
                    "filename": meta.get("filename", ""),
                    "snippet": doc[:150] + ("..." if len(doc) > 150 else "")
                })
            return output
        except Exception as e:
            logger.error(f"Error listing RAG documents: {e}")
            return []

    async def delete_document(self, tenant_id: int, doc_id: str) -> bool:
        """Deletes a document from ChromaDB vector store"""
        try:
            full_id = doc_id if doc_id.startswith(f"t{tenant_id}_") else f"t{tenant_id}_{doc_id}"
            self.collection.delete(ids=[full_id])
            return True
        except Exception as e:
            logger.error(f"Error deleting RAG document {doc_id}: {e}")
            return False

rag_service = RAGService()
