"""
Portal do Técnico: login separado por telefone + PIN (não usa o login/senha do sistema
administrativo). Cada técnico entra pelo próprio celular em /tecnico e vê:
  - GET /board: o quadro geral, igual ao que atendente/admin vê em /os-board/board (sem dados
    financeiros - ver build_board_data em os_board.py).
  - GET /my-orders: o mesmo quadro, filtrado só pras O.S. que batem com o nome dele.

O PIN inicial é definido pelo admin na tela de Técnicos já existente (AdminPanel > Técnicos) - todo PIN
que o admin define (criação, edição ou reset de PIN esquecido) é tratado como provisório
(AuthorizedTechnician.pin_deve_trocar=True) e o técnico é obrigado a trocar pelo próprio no primeiro
acesso via POST /change-pin, antes de usar o resto do portal.
"""
import difflib
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.os_board import build_board_data
from app.api.v1.technicians import clean_phone_digits
from app.core.database import get_db
from app.core.security import create_technician_access_token, get_current_technician, get_password_hash, verify_password
from app.models.models import AuthorizedTechnician, OsBoardOrder, SoftsystemPendingWrite
from app.services.automation_service import normalize_text

logger = logging.getLogger("technician_portal")
router = APIRouter(prefix="/technician-portal", tags=["Portal do Técnico"])


class TechnicianLoginRequest(BaseModel):
    telefone: str
    pin: str


class TechnicianLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    nome: str
    cargo: Optional[str] = None
    must_change_pin: bool = False


class ChangePinRequest(BaseModel):
    new_pin: str


LOGIN_ERROR_DETAIL = "Telefone ou PIN inválido."


@router.post("/login", response_model=TechnicianLoginResponse)
async def technician_login(payload: TechnicianLoginRequest, db: AsyncSession = Depends(get_db)):
    clean_phone = clean_phone_digits(payload.telefone)
    pin = (payload.pin or "").strip()
    if not clean_phone or not pin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR_DETAIL)

    res = await db.execute(select(AuthorizedTechnician).where(
        AuthorizedTechnician.telefone == clean_phone,
        AuthorizedTechnician.ativo == True
    ))
    tech = res.scalar_one_or_none()
    # Mesma mensagem genérica tanto pra telefone não cadastrado quanto pra PIN errado - não dá pista
    # de qual dos dois falhou.
    if not tech or not tech.pin_hash or not verify_password(pin, tech.pin_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_ERROR_DETAIL)

    token = create_technician_access_token(tech)
    return TechnicianLoginResponse(access_token=token, nome=tech.nome, cargo=tech.cargo, must_change_pin=tech.pin_deve_trocar)


@router.get("/me")
async def technician_me(tech: AuthorizedTechnician = Depends(get_current_technician)):
    return {
        "id": tech.id,
        "nome": tech.nome,
        "cargo": tech.cargo,
        "departamento": tech.departamento,
        "must_change_pin": tech.pin_deve_trocar,
    }


@router.post("/change-pin")
async def technician_change_pin(
    payload: ChangePinRequest,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
):
    """Troca o PIN provisório (dado pelo admin no primeiro acesso ou após um reset) por um PIN próprio
    do técnico. Só quem já tem um token válido (ou seja, já passou pelo login com o PIN provisório)
    consegue chamar isso - não pede o PIN antigo de novo."""
    new_pin = (payload.new_pin or "").strip()
    if not re.fullmatch(r"\d{4,6}", new_pin):
        raise HTTPException(status_code=400, detail="O novo PIN deve ter de 4 a 6 dígitos numéricos.")

    tech.pin_hash = get_password_hash(new_pin)
    tech.pin_definido_em = datetime.utcnow()
    tech.pin_deve_trocar = False
    await db.commit()
    return {"status": "success", "message": "PIN atualizado com sucesso."}


@router.get("/board")
async def technician_board(
    empresa: Optional[str] = None,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
):
    """Quadro geral - mesma visão que o atendente/admin vê em /os-board/board. O portal não tem o
    modal de "ver todas as N O.S." que o TechBoard.tsx usa no desktop, então traz mais cartões por
    célula de uma vez (o cartão do técnico é leve - sem valores financeiros)."""
    return await build_board_data(db, tech.tenant_id, empresa, cards_per_cell=50)


def _matches_technician(row_name: str, tech_name_norm: str) -> bool:
    row_norm = normalize_text(row_name)
    if not row_norm or row_norm == normalize_text("SEM TÉCNICO"):
        return False
    if row_norm in tech_name_norm or tech_name_norm in row_norm:
        return True
    return bool(difflib.get_close_matches(tech_name_norm, [row_norm], n=1, cutoff=0.7))


@router.get("/my-orders")
async def technician_my_orders(
    empresa: Optional[str] = None,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Mesmo quadro geral, mas só com as linhas de técnico que batem com o nome deste técnico logado
    (o Softsystem guarda o técnico como texto livre em OsBoardOrder.tecnico/tecnico2, sem FK - o
    casamento por nome normalizado/aproximado é o mesmo usado em resolve_tecnico_phone_by_name,
    ver os_handler_ingest.py)."""
    board = await build_board_data(db, tech.tenant_id, empresa, cards_per_cell=50)
    tech_name_norm = normalize_text(tech.nome)
    matched = [row for row in board["technicians"] if _matches_technician(row["name"], tech_name_norm)]
    # Recalcula os totais por estágio só sobre as linhas filtradas - senão os números no topo de cada
    # coluna mostrariam o total da loja inteira, não das O.S. deste técnico.
    totals = {key: 0 for key in board["totals"]}
    for row in matched:
        for stage_key, cell in row["cells"].items():
            totals[stage_key] += cell["count"]
    total_open = sum(row["total_open"] for row in matched)
    return {**board, "technicians": matched, "totals": totals, "total_open": total_open}


@router.get("/search")
async def technician_search(
    q: str,
    empresa: Optional[str] = None,
    escopo: str = "meus",
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Busca por número da O.S., cliente ou equipamento (ver os_board._search_orders). escopo=meus
    (padrão) filtra só pras O.S. do técnico logado, igual /my-orders; escopo=geral não filtra."""
    from app.api.v1.os_board import _search_orders
    results = await _search_orders(db, tech.tenant_id, q, empresa, [])
    if escopo != "geral":
        tech_name_norm = normalize_text(tech.nome)
        results = [r for r in results if _matches_technician(r.get("tecnico") or "", tech_name_norm)]
    return {"results": results}


@router.get("/order/{codos}")
async def technician_order_detail(
    codos: int,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Detalhe de uma O.S. (histórico + peças + fotos) pro modal do Portal do Técnico - ver os_board._order_detail."""
    from app.api.v1.os_board import _order_detail
    return await _order_detail(db, tech.tenant_id, codos)


@router.post("/order/{codos}/photos")
async def technician_upload_order_photo(
    codos: int,
    file: UploadFile = File(...),
    send_to_customer: bool = Form(True),
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
):
    """Sobe uma foto/arquivo da O.S. direto no app do técnico - ver os_board.upload_order_photo."""
    from app.services.os_board_photo_service import handle_os_photo_upload
    file_bytes = await file.read()
    try:
        return await handle_os_photo_upload(
            tenant_id=tech.tenant_id, codos=codos, file_bytes=file_bytes,
            original_filename=file.filename or "foto.jpg", content_type=file.content_type or "image/jpeg",
            uploaded_by=tech.nome or "Técnico", send_to_customer=send_to_customer,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# Estágios que o técnico pode definir pelo app - restrito a só estes três, pedido explícito do
# usuário em 29/09/2026. De propósito, de fora dessa lista: "Avaliação"/"Execução"/"Aguardando
# peça" (fluxo normal, lançado no Softsystem), "Orçamento enviado" (é o atendente que manda o
# orçamento), "Aprovado"/"Não aprovado" (só o cliente decide, respondendo no WhatsApp) e
# "Desmanche e Descarte" (só automático, por prazo vencido) - ver os_board_followup_service.py e
# ingest_db_event_common.
TECHNICIAN_ALLOWED_STATUSES: Dict[int, str] = {
    6: "Aguardando retirada",
    11: "Sem conserto",
    13: "Sem defeito",
}
EVENTO_AGUARDANDO_RETIRADA = 6


class UpdateOsStatusRequest(BaseModel):
    codos: int
    status: int
    obs: Optional[str] = None


@router.post("/os/status")
async def technician_update_os_status(
    payload: UpdateOsStatusRequest,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
):
    """
    Muda a etapa de uma O.S. pelo app. Não escreve direto no Softsystem (o backend roda na nuvem e
    não alcança o Firebird da loja) - só enfileira o pedido (SoftsystemPendingWrite) pro vigia
    (tools/os_db_watcher/poll_pending_writes) executar de verdade lá e confirmar. Atualiza o quadro
    aqui na hora (otimista) pra não deixar o técnico esperando o próximo ciclo do vigia pra ver o
    resultado - se a escrita falhar de verdade no Softsystem, o próximo ciclo do vigia corrige
    sozinho (sync_board_empresa lê o Firebird de novo e sobrescreve).
    """
    if payload.status not in TECHNICIAN_ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="Status inválido para alteração pelo Portal do Técnico.")

    res = await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == tech.tenant_id, OsBoardOrder.codos == payload.codos
    ))
    orders = res.scalars().all()
    if not orders:
        raise HTTPException(status_code=404, detail=f"O.S. #{payload.codos} não encontrada no quadro.")

    tech_name_norm = normalize_text(tech.nome)
    order = next((o for o in orders if _matches_technician(o.tecnico or "", tech_name_norm) or _matches_technician(o.tecnico2 or "", tech_name_norm)), None)
    if order is None:
        raise HTTPException(status_code=403, detail="Essa O.S. não está atribuída a você.")

    # Ressalva pedida pelo usuário (29/09/2026): não deixa marcar "Aguardando retirada" numa O.S.
    # sem nada lançado (sem histórico de peças/mão de obra) - não faz sentido dizer que o
    # equipamento está pronto pra retirada se nada foi de fato registrado nela. valor_total é a
    # soma dos itens da O.S. (ITENSORDEMSERVICO, ver os_db_watcher._board_valores) - a melhor
    # aproximação disponível aqui pra "tem peça/mão de obra lançada", já que o backend não alcança
    # o Firebird pra conferir ao vivo.
    if payload.status == EVENTO_AGUARDANDO_RETIRADA and not order.valor_total:
        raise HTTPException(
            status_code=422,
            detail=f"O.S. #{payload.codos} está sem peças/mão de obra lançadas - não é possível marcar como Aguardando retirada."
        )

    # A observação vai crua pro Softsystem (é dela que o "Sem conserto" tira o {motivo} da
    # mensagem ao cliente - ver AutomationService.sem_conserto_motivo). Sem observação do técnico,
    # cai no texto fixo, sem motivo.
    obs = (payload.obs or "").strip() or f"Alterado via Portal do Técnico por {tech.nome}"
    now = datetime.utcnow()
    db.add(SoftsystemPendingWrite(
        tenant_id=tech.tenant_id, empresa=order.empresa, loja=order.loja, codos=order.codos,
        cod_evento=payload.status, obs=obs, requested_by=tech.nome,
    ))
    order.situacao_evento = payload.status
    order.ultimo_evento_em = now
    order.last_nudge_at = None
    order.atualizado_em = now
    await db.commit()

    return {
        "status": "success",
        "message": f"O.S. #{payload.codos} marcada como \"{TECHNICIAN_ALLOWED_STATUSES[payload.status]}\". Enviando pro Softsystem...",
    }
