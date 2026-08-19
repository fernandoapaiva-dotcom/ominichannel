from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import io
import uuid

from app.core.database import get_db
from app.core.security import get_admin_user
from app.models.models import User, AuditLog, WhatsAppNumber
from app.services.rag_service import rag_service
from app.services.gemini_service import gemini_service
from app.services.settings_service import settings_service

router = APIRouter(prefix="/rag", tags=["Base de Conhecimento RAG"])

class RAGDocumentCreate(BaseModel):
    doc_id: Optional[str] = None
    content: str
    titulo: str
    scope: str = "geral"  # "geral" or "setor"
    department_id: Optional[int] = None
    department_name: Optional[str] = "Geral"

class RAGTestFlowResponse(BaseModel):
    success: bool
    pergunta: str
    contexto_rag: str
    resposta_ia: str
    escalar_humano: bool
    nova_memoria: str
    tokens: Dict[str, int]
    mensagem: str

def extract_text_from_bytes(filename: str, content_bytes: bytes) -> str:
    ext = filename.lower().split('.')[-1]
    if ext in ['txt', 'md', 'json', 'csv', 'log']:
        return content_bytes.decode('utf-8', errors='ignore')
    elif ext == 'pdf':
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content_bytes))
            text_pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(text_pages).strip()
        except Exception:
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(content_bytes))
                text_pages = [page.extract_text() or "" for page in reader.pages]
                return "\n".join(text_pages).strip()
            except Exception:
                return content_bytes.decode('utf-8', errors='ignore')
    elif ext in ['docx', 'doc']:
        try:
            import docx
            doc = docx.Document(io.BytesIO(content_bytes))
            return "\n".join([p.text for p in doc.paragraphs if p.text]).strip()
        except Exception:
            return content_bytes.decode('utf-8', errors='ignore')
    return content_bytes.decode('utf-8', errors='ignore')

@router.get("/documents")
async def list_rag_documents(
    admin_user: User = Depends(get_admin_user)
):
    """Lists all indexed RAG documents for the tenant"""
    docs = await rag_service.list_documents(admin_user.tenant_id)
    return docs

@router.delete("/documents/{doc_id}")
async def delete_rag_document(
    doc_id: str,
    admin_user: User = Depends(get_admin_user)
):
    """Deletes a RAG document from ChromaDB"""
    success = await rag_service.delete_document(admin_user.tenant_id, doc_id)
    if not success:
        raise HTTPException(status_code=500, detail="Erro ao excluir documento da base RAG")
    return {"status": "success", "message": "Documento excluído com sucesso"}

@router.post("/upload")
async def upload_rag_document(
    doc_in: RAGDocumentCreate,
    admin_user: User = Depends(get_admin_user)
):
    """
    Uploads text snippet into tenant RAG knowledge base (Geral or Sector Specific).
    """
    d_id = doc_in.doc_id or f"doc_{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:6]}"
    success = await rag_service.add_document(
        tenant_id=admin_user.tenant_id,
        doc_id=d_id,
        content=doc_in.content,
        metadata={
            "titulo": doc_in.titulo,
            "scope": doc_in.scope,
            "department_id": doc_in.department_id or 0,
            "department_name": doc_in.department_name or "Geral"
        }
    )
    if not success:
        raise HTTPException(status_code=500, detail="Erro ao indexar documento na base RAG")
    return {"status": "success", "message": "Conhecimento RAG adicionado com sucesso"}

@router.post("/upload-files")
async def upload_rag_files(
    files: List[UploadFile] = File(...),
    scope: str = Form("geral"),
    department_id: Optional[int] = Form(None),
    department_name: Optional[str] = Form("Geral"),
    admin_user: User = Depends(get_admin_user)
):
    """
    Uploads and indexes multiple files (.pdf, .txt, .docx, .md) into the RAG knowledge base.
    """
    indexed_count = 0
    errors = []

    for file_item in files:
        try:
            content_bytes = await file_item.read()
            extracted_text = extract_text_from_bytes(file_item.filename, content_bytes)

            if not extracted_text or not extracted_text.strip():
                errors.append(f"Arquivo '{file_item.filename}' não contém texto legível.")
                continue

            d_id = f"file_{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:6]}"
            success = await rag_service.add_document(
                tenant_id=admin_user.tenant_id,
                doc_id=d_id,
                content=extracted_text,
                metadata={
                    "titulo": file_item.filename,
                    "filename": file_item.filename,
                    "scope": scope,
                    "department_id": department_id or 0,
                    "department_name": department_name or "Geral"
                }
            )
            if success:
                indexed_count += 1
            else:
                errors.append(f"Falha ao indexar '{file_item.filename}'.")
        except Exception as e:
            errors.append(f"Erro no arquivo '{file_item.filename}': {str(e)}")

    if indexed_count == 0 and errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    return {
        "status": "success",
        "message": f"{indexed_count} arquivo(s) indexado(s) com sucesso na base RAG!",
        "indexed_count": indexed_count,
        "warnings": errors
    }

@router.post("/test-flow", response_model=RAGTestFlowResponse)
async def test_rag_flow_endpoint(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Executes live end-to-end RAG + Gemini AI triage test using tenant's encrypted key from DB.
    Reports token metrics and records entry in AuditLog.
    """
    # 1. Fetch decrypted settings from DB (IntegrationSettings table)
    decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, admin_user.tenant_id)
    api_key_from_db = decrypted_settings.get("gemini_api_key")

    if not api_key_from_db:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma chave do Gemini cadastrada no banco de dados. Insira a chave na aba 'Integrações & Segurança' e salve primeiro."
        )

    # 2. Ensure test RAG document exists in ChromaDB
    doc_content = (
        "MANUAL DE COMPRAS E REGRAS DE LOCACAO 2026 - DEMOLICAO E COMERCIO:\n"
        "- Andaime Tubular 1,5m: R$ 120,00 a diaria por peça.\n"
        "- Taxa de Entrega e Frete na Grande SP: R$ 50,00 valor fixo.\n"
        "- Formas de pagamento aceitas: Pix à vista com 5% de desconto ou Cartao de Credito em ate 3x sem juros.\n"
        "- Horario de devolução: Ate as 17:00h do ultimo dia de contrato."
    )
    await rag_service.add_document(
        tenant_id=admin_user.tenant_id,
        doc_id="doc_andaimes_teste_2026",
        content=doc_content,
        metadata={"titulo": "Tabela Andaimes Teste"}
    )

    pergunta = "Qual é o valor da diária do andaime tubular e quais as formas de pagamento aceitas?"

    # 3. Retrieve RAG context
    rag_context = await rag_service.search_context(tenant_id=admin_user.tenant_id, query=pergunta)

    # 4. Generate AI response using key and model fetched from DB
    output = await gemini_service.generate_concierge_response(
        customer_name="Cliente Teste Painel",
        department_name="Locação e Equipamentos",
        user_message=pergunta,
        conversation_history=[],
        memory_summary=None,
        rag_context=rag_context,
        tenant_gemini_api_key=api_key_from_db,
        tenant_gemini_model_name=decrypted_settings.get("gemini_model_name")
    )

    tokens = output.get("tokens", {"prompt_tokens": 0, "response_tokens": 0, "total_tokens": 0})

    # 5. Log audit entry
    audit = AuditLog(
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        user_name=admin_user.nome,
        acao="TESTOU_FLUXO_RAG_GEMINI",
        detalhes=f"Teste RAG concluído. Consumo: {tokens.get('total_tokens', 0)} tokens ({tokens.get('prompt_tokens', 0)} prompt + {tokens.get('response_tokens', 0)} resposta).",
        timestamp=datetime.utcnow()
    )
    db.add(audit)
    await db.commit()

    return RAGTestFlowResponse(
        success=True,
        pergunta=pergunta,
        contexto_rag=rag_context,
        resposta_ia=output["resposta"],
        escalar_humano=output["escalar_humano"],
        nova_memoria=output["nova_memoria"],
        tokens=tokens,
        mensagem=f"Teste executado com sucesso! Consumiu {tokens.get('total_tokens', 0)} tokens."
    )
