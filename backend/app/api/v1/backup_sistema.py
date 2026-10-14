"""
Status e "rodar agora" do backup do RAG e do sistema no Google Drive (ver
app/services/sistema_backup_drive_service.py). Montado dentro do router de /settings (fim de settings.py).
"""
import asyncio

from fastapi import APIRouter, Depends

from app.core.security import get_admin_user
from app.models.models import User
from app.services import sistema_backup_drive_service as bkp

router = APIRouter(prefix="/backup-sistema")
_tarefas: set = set()


@router.get("/status")
async def status_backup(admin_user: User = Depends(get_admin_user)):
    estado = bkp.ler_estado()
    return {
        "rag": estado.get("rag", {}),
        "sistema": estado.get("sistema", {}),
        "em_andamento": len(_tarefas) > 0,
    }


@router.post("/rodar-agora")
async def rodar_backup_agora(admin_user: User = Depends(get_admin_user)):
    if _tarefas:
        return {"iniciado": False, "mensagem": "Já existe um backup em andamento."}
    tarefa = asyncio.create_task(bkp.rodar(forcar=True))
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)
    return {"iniciado": True, "mensagem": "Backup do RAG e do sistema iniciado - o RAG tem ~1 GB, pode levar alguns minutos."}
