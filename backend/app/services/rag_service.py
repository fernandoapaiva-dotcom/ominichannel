import os
import logging
from typing import Optional
import chromadb
from chromadb.config import Settings

logger = logging.getLogger("rag_service")

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> list:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

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
        """Adds or updates document chunks in the local vector DB for a tenant with scope metadata"""
        try:
            meta = metadata or {}
            meta["tenant_id"] = int(tenant_id)
            meta["scope"] = str(meta.get("scope", "geral"))
            meta["department_id"] = int(meta.get("department_id") or 0)
            meta["department_name"] = str(meta.get("department_name") or "Geral")
            meta["titulo"] = str(meta.get("titulo") or "Documento RAG")
            meta["filename"] = str(meta.get("filename") or "")
            meta["criado_em"] = str(meta.get("criado_em") or os.environ.get("CURRENT_TIME", ""))
            meta["parent_doc_id"] = str(doc_id)

            if len(content) > 1500:
                chunks = chunk_text(content, chunk_size=1500, overlap=200)
                chunk_ids = [f"t{tenant_id}_{doc_id}_c{i}" for i in range(len(chunks))]
                chunk_metas = []
                for i in range(len(chunks)):
                    c_meta = dict(meta)
                    c_meta["chunk_index"] = i
                    c_meta["total_chunks"] = len(chunks)
                    chunk_metas.append(c_meta)
                self.collection.upsert(
                    documents=chunks,
                    ids=chunk_ids,
                    metadatas=chunk_metas
                )
            else:
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
        top_k: int = 5,
        max_total_chars: int = 7000
    ) -> str:
        """
        Searches tenant documents by semantic similarity with token-safe length capping.
        Includes BOTH Geral (company-wide) knowledge and department-specific knowledge.
        """
        try:
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
            total_chars = 0
            for doc, meta in zip(docs, metas):
                m_scope = meta.get("scope", "geral")
                m_dept_id = meta.get("department_id", 0)
                # Keep if document is Geral OR matches department_id
                if m_scope == "geral" or m_dept_id == 0 or (department_id and int(m_dept_id) == int(department_id)):
                    if len(doc) > 2500:
                        # Extract keyword-relevant snippets rather than full huge file
                        query_words = [w.lower() for w in query.split() if len(w) > 2 and w.lower() not in ["para", "com", "uma", "como", "qual", "onde"]]
                        snippets = []
                        doc_lower = doc.lower()
                        for qw in query_words:
                            idx = doc_lower.find(qw)
                            if idx != -1:
                                start = max(0, idx - 400)
                                end = min(len(doc), idx + 1200)
                                snippets.append(doc[start:end])
                        excerpt = "\n[...]\n".join(snippets[:3]) if snippets else doc[:1500]
                    else:
                        excerpt = doc

                    if total_chars + len(excerpt) > max_total_chars:
                        remaining = max_total_chars - total_chars
                        if remaining > 300:
                            filtered_docs.append(excerpt[:remaining] + "\n[...]")
                        break
                    filtered_docs.append(excerpt)
                    total_chars += len(excerpt)

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
