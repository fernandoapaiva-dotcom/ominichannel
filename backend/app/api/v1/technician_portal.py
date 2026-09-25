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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.os_board import build_board_data
from app.api.v1.technicians import clean_phone_digits
from app.core.database import get_db
from app.core.security import create_technician_access_token, get_current_technician, get_password_hash, verify_password
from app.models.models import AuthorizedTechnician
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
