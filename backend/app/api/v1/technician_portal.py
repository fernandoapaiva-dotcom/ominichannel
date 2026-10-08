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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.os_board import build_board_data, EVENT_LABELS
from app.api.v1.technicians import clean_phone_digits
from app.core.database import get_db
from app.core.security import create_technician_access_token, get_current_technician, get_password_hash, verify_password
from app.models.models import AuthorizedTechnician, OsBoardOrder, OsTechnicianNote, SoftsystemPendingWrite
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


@router.get("/my-notes")
async def technician_my_notes(
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Observações/lembretes ativos deixados pro técnico logado, em qualquer O.S. - pedido do
    usuário em 07/10/2026, mesmo casamento de nome por aproximação já usado em /my-orders."""
    rows = (await db.execute(select(OsTechnicianNote).where(
        OsTechnicianNote.tenant_id == tech.tenant_id, OsTechnicianNote.resolved_at.is_(None)
    ).order_by(OsTechnicianNote.criado_em.desc()))).scalars().all()
    tech_name_norm = normalize_text(tech.nome)
    matched = [n for n in rows if _matches_technician(n.tecnico, tech_name_norm)]
    return {"notes": [
        {"id": n.id, "codos": n.codos, "mensagem": n.mensagem, "criado_por": n.criado_por, "criado_em": n.criado_em.isoformat()}
        for n in matched
    ]}


@router.get("/order/{codos}/notes")
async def technician_order_notes(
    codos: int,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db)
):
    """Observações ativas dessa O.S. específica - mesmo formato de os_board.list_order_notes,
    pra mostrar na tela de detalhe quando o técnico abre a própria O.S."""
    rows = (await db.execute(select(OsTechnicianNote).where(
        OsTechnicianNote.tenant_id == tech.tenant_id, OsTechnicianNote.codos == codos,
        OsTechnicianNote.resolved_at.is_(None)
    ).order_by(OsTechnicianNote.criado_em.desc()))).scalars().all()
    return [
        {"id": n.id, "mensagem": n.mensagem, "tecnico": n.tecnico, "criado_por": n.criado_por, "criado_em": n.criado_em.isoformat()}
        for n in rows
    ]


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


class SendReportRequest(BaseModel):
    internal_note: str
    customer_message: str


class RejectReportRequest(BaseModel):
    reason: str


@router.get("/order/{codos}/report")
async def technician_get_order_report(
    codos: int,
    tech: AuthorizedTechnician = Depends(get_current_technician),
):
    """Rascunho pendente de revisão - ver os_board.get_order_report."""
    from app.services.os_report_service import get_pending_draft
    draft = await get_pending_draft(tech.tenant_id, codos)
    if not draft:
        raise HTTPException(status_code=404, detail="Nenhum rascunho pendente pra essa O.S.")
    return draft


@router.post("/order/{codos}/draft-report")
async def technician_draft_order_report(
    codos: int,
    tech: AuthorizedTechnician = Depends(get_current_technician),
):
    """Rascunho do laudo técnico + mensagem pro cliente - ver os_board.draft_order_report."""
    from app.services.os_report_service import generate_report_draft
    try:
        return await generate_report_draft(tech.tenant_id, codos)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/order/{codos}/reject-report")
async def technician_reject_order_report(
    codos: int,
    payload: RejectReportRequest,
    tech: AuthorizedTechnician = Depends(get_current_technician),
):
    """Reprova o rascunho com um motivo e pede nova versão - ver os_board.reject_order_report."""
    from app.services.os_report_service import reject_report
    try:
        return await reject_report(tech.tenant_id, codos, payload.reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/order/{codos}/send-report")
async def technician_send_order_report(
    codos: int,
    payload: SendReportRequest,
    tech: AuthorizedTechnician = Depends(get_current_technician),
):
    """Aprova e envia o relatório (já revisado pelo técnico) pro cliente - ver os_board.send_order_report."""
    from app.services.os_report_service import approve_report
    try:
        return await approve_report(
            tech.tenant_id, codos, payload.internal_note, payload.customer_message, tech.nome or "Técnico"
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


EVENTO_ENTRADA = 1
EVENTO_AVALIACAO = 2
EVENTO_EXECUCAO = 4
EVENTO_AGUARDANDO_RETIRADA = 6
EVENTO_FINALIZADA = 7
EVENTO_AGUARDANDO_PECA = 8
EVENTO_SEM_CONSERTO = 11
EVENTO_SEM_DEFEITO = 13
EVENTO_DESCARTE = 14
EVENTO_APROVADO = 15

# Transições permitidas pelo app, por ESTÁGIO ATUAL da O.S. - expandido em 07/10/2026 (antes só
# tinha 3 opções fixas, iguais em qualquer estágio). De propósito, sem entrada pra "Orçamento
# enviado" (3), "Aguardando retirada" (6), "Não aprovado"/"Não autorizada" (16/12) e "Finalizada"
# (7) como ORIGEM - o técnico não tem nenhuma ação disponível a partir desses estágios (confirmado
# com o usuário).
TECHNICIAN_ALLOWED_TRANSITIONS: Dict[int, List[int]] = {
    EVENTO_ENTRADA: [EVENTO_SEM_CONSERTO, EVENTO_SEM_DEFEITO],
    EVENTO_AVALIACAO: [EVENTO_SEM_CONSERTO, EVENTO_SEM_DEFEITO],
    EVENTO_APROVADO: [EVENTO_EXECUCAO, EVENTO_AGUARDANDO_PECA, EVENTO_AGUARDANDO_RETIRADA],
    EVENTO_AGUARDANDO_PECA: [EVENTO_EXECUCAO],
    EVENTO_EXECUCAO: [EVENTO_AGUARDANDO_RETIRADA],
    EVENTO_SEM_CONSERTO: [EVENTO_FINALIZADA],
    EVENTO_SEM_DEFEITO: [EVENTO_FINALIZADA],
    EVENTO_DESCARTE: [EVENTO_FINALIZADA],
}

STATUS_LABELS: Dict[int, str] = {
    EVENTO_EXECUCAO: "Execução",
    EVENTO_AGUARDANDO_PECA: "Aguardando peça",
    EVENTO_AGUARDANDO_RETIRADA: "Aguardando retirada",
    EVENTO_SEM_CONSERTO: "Sem conserto",
    EVENTO_SEM_DEFEITO: "Sem defeito",
    EVENTO_FINALIZADA: "Finalizada",
}

# Transições que gravam o evento no Softsystem só pra controle interno/auditoria da loja - SEM
# mandar a mensagem automática padrão pro cliente (ver SoftsystemPendingWrite.suppress_customer_notice
# e o bloco correspondente em ingest_db_event_common). Pedido do usuário em 07/10/2026: "sem
# reparo/desmanche e descarte -> finalizada, não manda recado pro cliente".
SILENT_TRANSITIONS = {
    (EVENTO_SEM_CONSERTO, EVENTO_FINALIZADA),
    (EVENTO_SEM_DEFEITO, EVENTO_FINALIZADA),
    (EVENTO_DESCARTE, EVENTO_FINALIZADA),
}


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
    res = await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == tech.tenant_id, OsBoardOrder.codos == payload.codos
    ))
    orders = res.scalars().all()
    if not orders:
        raise HTTPException(status_code=404, detail=f"O.S. #{payload.codos} não encontrada no quadro.")

    # Qualquer técnico autorizado pode mudar o status de uma O.S. de outro técnico (pedido do
    # usuário em 07/10/2026 - cobertura em imprevistos, folga do técnico titular etc.) - a
    # restrição por "é minha O.S.?" foi removida. Em troca, quem mudou fica sempre registrado:
    # SoftsystemPendingWrite.requested_by (nossa auditoria) E o campo OPERADOR de verdade no
    # Softsystem (ver tools/os_db_watcher/db_watcher.py::poll_pending_writes), nunca mais um
    # literal fixo "PORTAL_TECNICO" sem saber quem foi.
    tech_name_norm = normalize_text(tech.nome)
    order = next((o for o in orders if _matches_technician(o.tecnico or "", tech_name_norm) or _matches_technician(o.tecnico2 or "", tech_name_norm)), None)
    if order is None:
        order = orders[0]

    estagio_atual = order.situacao_evento
    permitidos = TECHNICIAN_ALLOWED_TRANSITIONS.get(estagio_atual, [])
    if payload.status not in permitidos:
        nome_atual = EVENT_LABELS.get(estagio_atual, f"estágio {estagio_atual}")
        raise HTTPException(
            status_code=422,
            detail=f"O.S. #{payload.codos} está em \"{nome_atual}\" - não é possível mudar pra esse status a partir daí pelo app."
        )

    # Ressalva pedida pelo usuário (29/09/2026, reforçada em 07/10/2026): não deixa marcar
    # "Aguardando retirada" numa O.S. sem nada lançado (sem histórico de peças/mão de obra) - não
    # faz sentido dizer que o equipamento está pronto pra retirada se nada foi de fato registrado
    # nela. valor_total é a soma dos itens da O.S. (ITENSORDEMSERVICO, ver
    # os_db_watcher._board_valores) - a melhor aproximação disponível aqui, já que o backend não
    # alcança o Firebird pra conferir ao vivo.
    if payload.status == EVENTO_AGUARDANDO_RETIRADA and not order.valor_total:
        raise HTTPException(
            status_code=422,
            detail=f"O.S. #{payload.codos} está sem peças/mão de obra lançadas - não é possível marcar como Aguardando retirada."
        )

    # Ressalva pedida pelo usuário em 07/10/2026: pulando direto de "Aprovado" pra "Aguardando
    # retirada" (sem passar pela Execução) precisa de uma observação de verdade explicando o que
    # foi feito - não pode cair no texto fixo genérico, já que não existe nenhum outro registro do
    # que foi executado nesse caminho mais curto.
    if estagio_atual == EVENTO_APROVADO and payload.status == EVENTO_AGUARDANDO_RETIRADA and not (payload.obs or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Pulando direto de \"Aprovado\" pra \"Aguardando retirada\", é obrigatório preencher uma observação explicando o que foi feito."
        )

    # A observação vai crua pro Softsystem (é dela que o "Sem conserto" tira o {motivo} da
    # mensagem ao cliente - ver AutomationService.sem_conserto_motivo). Sem observação do técnico,
    # cai no texto fixo, sem motivo.
    obs = (payload.obs or "").strip() or f"Alterado via Portal do Técnico por {tech.nome}"
    now = datetime.utcnow()
    db.add(SoftsystemPendingWrite(
        tenant_id=tech.tenant_id, empresa=order.empresa, loja=order.loja, codos=order.codos,
        cod_evento=payload.status, obs=obs, requested_by=tech.nome,
        suppress_customer_notice=(estagio_atual, payload.status) in SILENT_TRANSITIONS,
    ))
    order.situacao_evento = payload.status
    order.ultimo_evento_em = now
    order.last_nudge_at = None
    order.atualizado_em = now
    await db.commit()

    return {
        "status": "success",
        "message": f"O.S. #{payload.codos} marcada como \"{STATUS_LABELS.get(payload.status, payload.status)}\". Enviando pro Softsystem...",
    }
