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

    async def add_document(self, tenant_id: int, doc_id: str, content: str, metadata: Optional[dict] = None) -> bool:
        """Adds or updates a text chunk in the local vector DB for a tenant"""
        try:
            meta = metadata or {}
            meta["tenant_id"] = tenant_id
            self.collection.upsert(
                documents=[content],
                ids=[f"t{tenant_id}_{doc_id}"],
                metadatas=[meta]
            )
            return True
        except Exception as e:
            logger.error(f"Error adding document to RAG vector store: {e}")
            return False

    async def search_context(self, tenant_id: int, query: str, top_k: int = 3) -> str:
        """Searches tenant documents by semantic similarity and formats context string"""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k,
                where={"tenant_id": tenant_id}
            )
            docs = results.get("documents", [[]])[0]
            if not docs:
                return ""
            return "\n---\n".join(docs)
        except Exception as e:
            logger.error(f"Error searching RAG vector store: {e}")
            return ""

rag_service = RAGService()
