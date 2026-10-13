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
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Response
from fastapi.responses import FileResponse

from app.api.v1.os_board import build_board_data, EVENT_LABELS
from app.api.v1.technicians import clean_phone_digits
from app.api.v1.webhooks import _wants_diagram
from app.core.database import get_db
from app.core.security import create_technician_access_token, get_current_technician, get_password_hash, verify_password
from app.models.models import AuthorizedTechnician, OsBoardOrder, OsTechnicianCopilotMessage, OsTechnicianNote, SoftsystemPendingWrite
from app.services.automation_service import normalize_text
from app.services.gemini_service import gemini_service
from app.services import librarian_service
from app.services import copilot_media_service
from app.services.rag_service import rag_service
from app.services.settings_service import settings_service

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
        # Vai na marca d'água do Copiloto (13/10/2026): print de manual/código que vazar leva o
        # nome + telefone de quem estava com o aparelho.
        "telefone": tech.telefone,
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


# Copiloto do técnico DENTRO do portal (chat com histórico, estilo Claude) - pedido do usuário em
# 11/10/2026: desligar o apoio técnico por IA no WhatsApp (ver TECH_WHATSAPP_AI_DISABLED em
# webhooks.py) e substituir por esse chat in-app. Documentos encontrados abrem só em visualização
# embutida (GET /copilot/document/{id}) - nunca como arquivo baixável/anexo.

class _BibliotecarioRespondeu(Exception):
    """Interrompe o fluxo do bibliotecário quando a mensagem já foi respondida (ex: escolha de número)."""


class CopilotAskRequest(BaseModel):
    mensagem: str
    thread_id: Optional[str] = None  # vazio/None = nova conversa


def _copilot_message_out(m: OsTechnicianCopilotMessage, midia: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": m.id,
        "thread_id": m.thread_id,
        "remetente": m.remetente,
        "conteudo": m.conteudo,
        "documento_titulo": m.documento_titulo,
        "tem_documento": bool(m.documento_source_path),
        "documento_busca": m.documento_busca,
        "midia": midia,  # 'audio' | 'imagem' | 'video' quando o técnico mandou um arquivo
        "criado_em": m.criado_em.isoformat() if m.criado_em else None,
    }


@router.get("/copilot/threads")
async def copilot_threads(
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista de conversas do técnico, mais recente primeiro - pro menu lateral estilo Claude.ai
    (pedido do usuário em 11/10/2026). O título de cada conversa é a primeira pergunta dele
    nela (como o Claude.ai também faz), não existe uma tabela de "thread" própria - é só um
    agrupamento por thread_id em cima das mensagens mesmo.
    """
    res = await db.execute(
        select(OsTechnicianCopilotMessage)
        .where(
            OsTechnicianCopilotMessage.tenant_id == tech.tenant_id,
            OsTechnicianCopilotMessage.technician_id == tech.id,
            OsTechnicianCopilotMessage.thread_id.isnot(None),
        )
        .order_by(OsTechnicianCopilotMessage.id.asc())
    )
    threads: Dict[str, Dict[str, Any]] = {}
    for m in res.scalars().all():
        t = threads.setdefault(m.thread_id, {"thread_id": m.thread_id, "titulo": None, "ultima_em": None})
        if t["titulo"] is None and m.remetente == "tecnico":
            t["titulo"] = m.conteudo[:60] + ("…" if len(m.conteudo) > 60 else "")
        t["ultima_em"] = m.criado_em.isoformat() if m.criado_em else None
    out = list(threads.values())
    out.sort(key=lambda t: t["ultima_em"] or "", reverse=True)
    return out


@router.get("/copilot/threads/{thread_id}/messages")
async def copilot_thread_messages(
    thread_id: str,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db),
):
    """Mensagens de UMA conversa - persiste entre sessões, igual um chat de verdade (não é um
    Q&A avulso que esquece tudo ao fechar o app)."""
    res = await db.execute(
        select(OsTechnicianCopilotMessage)
        .where(
            OsTechnicianCopilotMessage.tenant_id == tech.tenant_id,
            OsTechnicianCopilotMessage.technician_id == tech.id,
            OsTechnicianCopilotMessage.thread_id == thread_id,
        )
        .order_by(OsTechnicianCopilotMessage.id.asc())
    )
    msgs = res.scalars().all()
    tipos = await copilot_media_service.tipos_por_mensagem([m.id for m in msgs])
    return [_copilot_message_out(m, tipos.get(m.id)) for m in msgs]


@router.post("/copilot/ask")
async def copilot_ask(
    payload: CopilotAskRequest,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db),
):
    mensagem = (payload.mensagem or "").strip()
    if not mensagem:
        raise HTTPException(status_code=422, detail="Mensagem vazia.")
    resposta, _tech_msg_id = await _copilot_responder(tech, db, mensagem, payload.thread_id)
    return resposta


async def _copilot_responder(
    tech: AuthorizedTechnician,
    db: AsyncSession,
    mensagem: str,
    thread_id_in: Optional[str],
    conteudo_exibido: Optional[str] = None,
):
    """Responde uma pergunta do técnico (digitada ou transcrita de áudio) e devolve (resposta, id da
    mensagem do técnico). `conteudo_exibido` é o que fica no histórico (ex: "🎤 ..." pro áudio) -
    a lógica usa sempre `mensagem` (sem o ícone), pra "2" falado escolher da lista igual digitado."""
    thread_id = (thread_id_in or "").strip() or uuid.uuid4().hex[:20]

    tech_msg = OsTechnicianCopilotMessage(
        tenant_id=tech.tenant_id, technician_id=tech.id, thread_id=thread_id, remetente="tecnico", conteudo=conteudo_exibido or mensagem,
    )
    db.add(tech_msg)
    await db.commit()
    await db.refresh(tech_msg)

    # Últimas mensagens DESSA conversa dão contexto pro Gemini (mesmo padrão do antigo copiloto
    # do WhatsApp) - sem isso cada pergunta seria tratada isolada, sem lembrar o que já foi
    # perguntado antes na mesma conversa. Escopado por thread_id - uma conversa nova (ex: outro
    # equipamento) não herda contexto de uma conversa antiga sem relação.
    hist_res = await db.execute(
        select(OsTechnicianCopilotMessage)
        .where(
            OsTechnicianCopilotMessage.tenant_id == tech.tenant_id,
            OsTechnicianCopilotMessage.technician_id == tech.id,
            OsTechnicianCopilotMessage.thread_id == thread_id,
        )
        .order_by(OsTechnicianCopilotMessage.id.desc())
        .limit(10)
    )
    recent = list(reversed(hist_res.scalars().all()))
    history = [{"remetente": m.remetente, "conteudo": m.conteudo, "documento_titulo": m.documento_titulo} for m in recent[:-1]]  # sem a que acabou de entrar

    documento_titulo = None
    documento_source_path = None
    documento_busca = None
    resposta_texto = None

    # Bibliotecário (ver librarian_service) - pedido de código de peça / documento é respondido por
    # consulta direta, sem chamar a IA, quando ele tem certeza; senão a pergunta segue pra IA já com
    # o modelo da conversa ("...dela?" herda a LHN 242 da mensagem anterior).
    equip_text, ranked_docs = "", []
    opcoes_oferecidas = None  # lista numerada que esta resposta oferece (técnico responde com o número)
    try:
        # Resposta com o NÚMERO de uma lista que o bibliotecário acabou de oferecer ("2", "o 2")
        escolha = librarian_service.parse_option_choice(mensagem)
        ids_assistente = [m.id for m in recent[:-1] if m.remetente == "assistente"]
        opcoes_anteriores = (await librarian_service.load_latest_options(ids_assistente)) if escolha else None
        if opcoes_anteriores:
            if 1 <= escolha <= len(opcoes_anteriores):
                op = opcoes_anteriores[escolha - 1]
                if op.get("source_path") and os.path.exists(op["source_path"]):
                    resposta_texto = f"📘 Bibliotecário - aqui está o {escolha}: {op['nome']}."
                    documento_titulo = op["nome"]
                    documento_source_path = op["source_path"]
                else:
                    resposta_texto = f"⚠️ O documento {escolha} ({op['nome']}) não está mais disponível no servidor."
            else:
                resposta_texto = f"Escolha um número de 1 a {len(opcoes_anteriores)}."
                opcoes_oferecidas = opcoes_anteriores  # continua valendo a mesma lista
            raise _BibliotecarioRespondeu  # já respondido - pula o resto do bibliotecário

        equip_text, ranked_docs = librarian_service.resolve_equipment(tech.tenant_id, mensagem, history)
        ultima_resp = next((h for h in reversed(history) if h.get("remetente") == "assistente"), None)
        ultima_resposta_era_documento = bool(ultima_resp and (ultima_resp.get("documento_titulo") or str(ultima_resp.get("conteudo") or "").startswith("📘")))
        ultima_resposta_pediu_modelo = bool(ultima_resp and "De qual modelo você precisa" in str(ultima_resp.get("conteudo") or ""))
        wants_send = bool(librarian_service.SEND_INTENT.search(mensagem)) or len(mensagem.split()) <= 9
        is_fault_question = bool(librarian_service.FAULT_INTENT.search(mensagem))

        if librarian_service.CODE_INTENT.search(mensagem) and not is_fault_question:
            by_code = await librarian_service.find_by_code(tech.tenant_id, mensagem)
            parts = by_code or await librarian_service.find_parts(tech.tenant_id, mensagem, equip_text, ranked_docs)
            if parts:
                resposta_texto = (librarian_service.format_code_lookup_answer(parts) if by_code
                                  else librarian_service.format_parts_answer(parts))
                if parts[0].source_path and os.path.exists(parts[0].source_path):
                    documento_titulo = parts[0].titulo or parts[0].filename
                    documento_source_path = parts[0].source_path
                    documento_busca = parts[0].codigo
        elif ranked_docs and (
            (librarian_service.DOC_INTENT.search(mensagem) and wants_send)
            # Correção ("eu pedi da lhn", "não é esse") logo depois de um documento/lista
            or (librarian_service.CORRECTION_INTENT.search(mensagem) and ultima_resposta_era_documento)
            # Resposta à pergunta "de qual modelo?" ("240")
            or (ultima_resposta_pediu_modelo and len(mensagem.split()) <= 4)
        ):
            dec = librarian_service.decide_documents(tech.tenant_id, mensagem, ranked_docs, equip_text)
            if not dec.get("faltando"):
                if dec["tipo"] == "lista":
                    # Mais de um documento possível: lista numerada, o técnico escolhe pelo número
                    opcoes_oferecidas = dec["opcoes"]
                    resposta_texto = librarian_service.format_document_choices(opcoes_oferecidas)
                elif dec["tipo"] == "modelo":
                    resposta_texto = librarian_service.format_ask_model(dec["rotulo"], dec["modelos"], dec.get("nao_achado"))
                elif dec["tipo"] == "unico":
                    doc = dec["doc"]
                    resposta_texto = librarian_service.format_document_answer(doc, [], None)
                    documento_titulo = librarian_service.pretty_title(doc)
                    documento_source_path = doc.get("source_path")
        if resposta_texto:
            logger.info(f"[BIBLIOTECARIO] Respondeu sem IA pro técnico {tech.nome}: '{mensagem[:80]}' -> {documento_titulo or ('lista de %d documentos' % len(opcoes_oferecidas) if opcoes_oferecidas else '(sem documento)')}")
    except _BibliotecarioRespondeu:
        logger.info(f"[BIBLIOTECARIO] Escolha '{mensagem[:20]}' do técnico {tech.nome} -> {documento_titulo or '(sem documento)'}")
    except Exception as e:
        logger.error(f"[BIBLIOTECARIO] Falha (segue pra IA): {e}", exc_info=True)
        resposta_texto = None

    if resposta_texto is None:
        # Pergunta sem o modelo ("...dela?"): a busca leva o equipamento da conversa junto
        rag_query = mensagem if (not equip_text or equip_text == mensagem) else f"{mensagem} ({equip_text[:120]})"
        rag_context = await rag_service.search_context(tenant_id=tech.tenant_id, query=rag_query, department_id=0)
        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tech.tenant_id)

        ai_output = await gemini_service.generate_concierge_response(
            customer_name=tech.nome,
            department_name=tech.departamento or "Assistência Técnica",
            user_message=mensagem,
            conversation_history=[{"remetente": h["remetente"], "conteudo": h["conteudo"]} for h in history],
            memory_summary=None,
            rag_context=rag_context,
            available_departments=[],
            available_attendants=[],
            protocol_number=None,
            should_announce_protocol=False,
            is_technician_or_admin=True,
            customer_phone=None,
            tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
            tenant_gemini_model_name=decrypted_settings.get("gemini_model_name"),
        )

        resposta_texto = (ai_output or {}).get("resposta") or "Não consegui gerar uma resposta agora, tenta de novo."

        search_terms = (ai_output or {}).get("documento_solicitado")
        if search_terms:
            try:
                # Quem escolhe o arquivo é o bibliotecário. Sem a busca "por significado" de reserva
                # (até 13/10/2026: anexava qualquer arquivo parecido). E o equipamento sai do QUE A
                # IA PEDIU - só herda da conversa se o pedido não citar equipamento nenhum (antes
                # juntava o equipamento antigo da conversa e "manual da LHN" virava Powermax de novo).
                terms_ranked = librarian_service._rank_docs(tech.tenant_id, search_terms) or \
                    librarian_service.resolve_equipment(tech.tenant_id, search_terms, history)[1]
                dec = librarian_service.decide_documents(tech.tenant_id, search_terms, terms_ranked)
                if dec["tipo"] == "unico":
                    documento_titulo = librarian_service.pretty_title(dec["doc"])
                    documento_source_path = dec["doc"]["source_path"]
                elif dec["tipo"] == "lista":
                    opcoes_oferecidas = dec["opcoes"]
                    resposta_texto += "\n\n" + librarian_service.format_document_choices(opcoes_oferecidas)
                elif dec["tipo"] == "modelo":
                    resposta_texto += "\n\n" + librarian_service.format_ask_model(dec["rotulo"], dec["modelos"], dec.get("nao_achado"))
                elif _wants_diagram(search_terms):
                    resposta_texto += "\n\n⚠️ Não encontrei esse esquema/diagrama específico na base - tenta descrever o modelo com mais detalhes."
                else:
                    resposta_texto += f"\n\n⚠️ Não encontrei um documento de \"{search_terms}\" na base técnica."
            except Exception as e:
                logger.error(f"[COPILOTO PORTAL] Falha buscando documento pra '{search_terms}': {e}")

    assistant_msg = OsTechnicianCopilotMessage(
        tenant_id=tech.tenant_id, technician_id=tech.id, thread_id=thread_id, remetente="assistente", conteudo=resposta_texto,
        documento_titulo=documento_titulo, documento_source_path=documento_source_path, documento_busca=documento_busca,
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)
    if opcoes_oferecidas:
        await librarian_service.save_options(assistant_msg.id, opcoes_oferecidas)

    return _copilot_message_out(assistant_msg), tech_msg.id


@router.get("/copilot/document/{message_id}")
async def copilot_document(
    message_id: int,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db),
):
    """
    PDF embutido pra visualização - nunca como anexo baixável (pedido explícito do usuário em
    11/10/2026: o conhecimento técnico fica só dentro do sistema). Content-Disposition "inline"
    some com o botão de download nativo do visualizador do navegador, mas não é DRM de verdade -
    é o limite razoável do que dá pra fazer num visualizador embutido de navegador.
    """
    res = await db.execute(select(OsTechnicianCopilotMessage).where(
        OsTechnicianCopilotMessage.id == message_id,
        OsTechnicianCopilotMessage.tenant_id == tech.tenant_id,
        OsTechnicianCopilotMessage.technician_id == tech.id,
    ))
    msg = res.scalar_one_or_none()
    if not msg or not msg.documento_source_path:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    if not os.path.exists(msg.documento_source_path):
        raise HTTPException(status_code=404, detail="Arquivo não está mais disponível.")

    with open(msg.documento_source_path, "rb") as f:
        content = f.read()

    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": "inline"})


# Áudio, foto e vídeo do técnico no Copiloto - pedido do usuário em 13/10/2026 ("botão de áudio pra
# ele mandar áudio e a IA transcrever, e envio de multimídia pra IA analisar e dar sugestões do que
# ele pode fazer na hora da manutenção"). Áudio: transcreve e segue EXATAMENTE o caminho da mensagem
# digitada (bibliotecário, IA, lista numerada...). Foto/vídeo: a IA analisa junto com a conversa, o
# equipamento em foco e os trechos dos manuais, e responde o que vê + o que fazer agora.
@router.post("/copilot/ask-media")
async def copilot_ask_media(
    file: UploadFile = File(...),
    mensagem: str = Form(""),
    thread_id: str = Form(""),
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db),
):
    mime = (file.content_type or "").split(";")[0].strip().lower()
    tipo = copilot_media_service.tipo_da_midia(mime)
    if not tipo:
        raise HTTPException(status_code=415, detail="Envie um áudio, uma foto ou um vídeo.")
    dados = await file.read()
    if not dados:
        raise HTTPException(status_code=422, detail="Arquivo vazio.")
    limite = copilot_media_service.MAX_BYTES[tipo]
    if len(dados) > limite:
        raise HTTPException(status_code=413, detail=f"Arquivo grande demais (máximo {limite // (1024 * 1024)} MB). Para vídeo, grave até uns 30 segundos.")

    legenda = (mensagem or "").strip()
    settings_dec = await settings_service.get_tenant_decrypted_settings(db, tech.tenant_id)
    api_key = settings_dec.get("gemini_api_key")
    model_name = settings_dec.get("gemini_model_name")

    if tipo == "audio":
        tr = await gemini_service.process_audio_message(dados, mime_type=mime, tenant_gemini_api_key=api_key, tenant_gemini_model_name=model_name)
        texto = ((tr or {}).get("transcription") or "").strip()
        if texto:
            resposta, tech_msg_id = await _copilot_responder(tech, db, texto, thread_id, conteudo_exibido=f"🎤 {texto}")
            await copilot_media_service.salvar(tech_msg_id, "audio", mime, dados)
            logger.info(f"[COPILOTO MIDIA] Áudio de {tech.nome} transcrito: '{texto[:80]}'")
            pergunta = {"id": tech_msg_id, "thread_id": resposta["thread_id"], "remetente": "tecnico", "conteudo": f"🎤 {texto}",
                        "documento_titulo": None, "tem_documento": False, "documento_busca": None, "midia": "audio",
                        "criado_em": resposta["criado_em"]}
            return {"pergunta": pergunta, "resposta": resposta}
        # Não deu pra entender o áudio: fica registrado na conversa, com o aviso
        tid = thread_id.strip() or uuid.uuid4().hex[:20]
        tech_msg = OsTechnicianCopilotMessage(tenant_id=tech.tenant_id, technician_id=tech.id, thread_id=tid, remetente="tecnico", conteudo="🎤 (áudio)")
        db.add(tech_msg)
        await db.commit()
        await db.refresh(tech_msg)
        await copilot_media_service.salvar(tech_msg.id, "audio", mime, dados)
        aviso = (tr or {}).get("fallback_message") or "Não consegui entender o áudio - tenta de novo mais perto do microfone ou escreve."
        resp_msg = OsTechnicianCopilotMessage(tenant_id=tech.tenant_id, technician_id=tech.id, thread_id=tid, remetente="assistente", conteudo=f"⚠️ {aviso}")
        db.add(resp_msg)
        await db.commit()
        await db.refresh(resp_msg)
        return {"pergunta": _copilot_message_out(tech_msg, "audio"), "resposta": _copilot_message_out(resp_msg)}

    # Foto / vídeo da bancada
    tid = thread_id.strip() or uuid.uuid4().hex[:20]
    exibido = legenda or ("📷 Foto da bancada" if tipo == "imagem" else "🎥 Vídeo da bancada")
    tech_msg = OsTechnicianCopilotMessage(tenant_id=tech.tenant_id, technician_id=tech.id, thread_id=tid, remetente="tecnico", conteudo=exibido)
    db.add(tech_msg)
    await db.commit()
    await db.refresh(tech_msg)
    await copilot_media_service.salvar(tech_msg.id, tipo, mime, dados)

    hist_res = await db.execute(
        select(OsTechnicianCopilotMessage)
        .where(
            OsTechnicianCopilotMessage.tenant_id == tech.tenant_id,
            OsTechnicianCopilotMessage.technician_id == tech.id,
            OsTechnicianCopilotMessage.thread_id == tid,
            OsTechnicianCopilotMessage.id < tech_msg.id,
        )
        .order_by(OsTechnicianCopilotMessage.id.desc())
        .limit(10)
    )
    history = [{"remetente": m.remetente, "conteudo": m.conteudo, "documento_titulo": m.documento_titulo}
               for m in reversed(hist_res.scalars().all())]
    equip_text = ""
    try:
        equip_text = librarian_service.resolve_equipment(tech.tenant_id, legenda, history)[0]
    except Exception as e:
        logger.warning(f"[COPILOTO MIDIA] Falha identificando o equipamento: {e}")
    rag_query = " ".join(x for x in (legenda, equip_text) if x).strip()
    rag_context = await rag_service.search_context(tenant_id=tech.tenant_id, query=rag_query, department_id=0) if rag_query else ""

    analise = await gemini_service.analyze_bench_media(
        dados, mime, technician_name=tech.nome, caption=legenda, conversation_history=history,
        equipment=equip_text, rag_context=rag_context, tenant_gemini_api_key=api_key, tenant_gemini_model_name=model_name,
    )
    resp_msg = OsTechnicianCopilotMessage(tenant_id=tech.tenant_id, technician_id=tech.id, thread_id=tid, remetente="assistente",
                                          conteudo=analise.get("text") or "Não consegui analisar agora.")
    db.add(resp_msg)
    await db.commit()
    await db.refresh(resp_msg)
    logger.info(f"[COPILOTO MIDIA] {tipo} de {tech.nome} analisado ({len(dados) // 1024} KB, equipamento: '{equip_text[:60]}')")
    return {"pergunta": _copilot_message_out(tech_msg, tipo), "resposta": _copilot_message_out(resp_msg)}


@router.get("/copilot/media/{message_id}")
async def copilot_media(
    message_id: int,
    tech: AuthorizedTechnician = Depends(get_current_technician),
    db: AsyncSession = Depends(get_db),
):
    """Áudio/foto/vídeo que o PRÓPRIO técnico mandou - só pra ver dentro do Copiloto."""
    res = await db.execute(select(OsTechnicianCopilotMessage).where(
        OsTechnicianCopilotMessage.id == message_id,
        OsTechnicianCopilotMessage.tenant_id == tech.tenant_id,
        OsTechnicianCopilotMessage.technician_id == tech.id,
    ))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")
    midia = await copilot_media_service.da_mensagem(message_id)
    if not midia or not os.path.exists(midia.caminho):
        raise HTTPException(status_code=404, detail="Arquivo não está mais disponível.")
    return FileResponse(midia.caminho, media_type=midia.mimetype,
                        headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store"})
