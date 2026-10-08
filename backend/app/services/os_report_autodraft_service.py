"""
Detecta sozinho quando uma O.S. já tem peças/mão de obra lançadas (o técnico só mexeu no
Softsystem, nada no nosso sistema) e manda a IA montar o rascunho do laudo - mas NÃO grava nada
no Softsystem nem manda nada pro cliente sozinho (mudou em 07/10/2026: antes escrevia direto no
Softsystem e só avisava "terminei"; usuário pediu revisão antes - "aprovo ou reprovo informando
porque, se reprovar o sistema relabora... aprovando, o sistema grava no Observação e muda o
status"). Agora só gera o rascunho (os_report_service.generate_report_draft, dois textos: laudo
técnico interno + mensagem pro cliente - ver OsReportDraft) e avisa que está pronto pra revisar.
A gravação de verdade só acontece quando o dono aprovar no sistema (os_report_service.approve_report).

Dois gatilhos pra gerar o rascunho de uma O.S., os dois chamando try_draft_one:
  1. EM TEMPO REAL (principal) - os_board.sync_board chama na hora que os dados (peças/observação)
     chegam do vigia, sem esperar nada - pedido do usuário em 07/10/2026 ("terminei de lançar, fui
     lá no sistema e ele ainda não tinha gerado... tem que ser só o tempo de mudar de sistema").
  2. VARREDURA PERIÓDICA (rede de segurança) - start_report_autodraft_loop, pro caso do gatilho em
     tempo real falhar silenciosamente por algum motivo (erro de rede entre vigia/backend, etc.).

Fluxo de try_draft_one, pra cada O.S. elegível (valor_total>0 + peças lançadas, ainda numa fase
"em aberto" de verdade, sem rascunho gerado ainda):
  1. Marca report_draft_sent_at JÁ, antes de chamar a IA (reserva o "slot" - evita gerar duas vezes
     se os dois gatilhos acima disparam quase juntos pra mesma O.S.).
  2. Gera os dois textos (os_report_service.generate_report_draft) - fica salvo em OsReportDraft,
     pendente de revisão.
  3. Manda um aviso simples no WhatsApp (número fixo pra aprovação, não o técnico de cada O.S. -
     pedido do usuário: "se depender deles nunca dará certo") dizendo que o rascunho está pronto
     pra revisar/aprovar no sistema.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import OsBoardOrder, OsBoardItem, OsReportDraft, WhatsAppNumber

logger = logging.getLogger("os_report_autodraft")

CHECK_INTERVAL_SECONDS = 45  # rede de segurança - o gatilho em tempo real (os_board.sync_board) cobre o caminho rápido
PER_ITEM_GAP_SECONDS = 2

# Rede de segurança pedida pelo usuário em 07/10/2026 ("se der algum problema com o sistema e ele
# não disparar por algum motivo, tem como pegar depois?") - compara com o jeito antigo (gatilho
# direto do evento no Softsystem, sem passo intermediário). approve_report grava aprovado_em
# IMEDIATAMENTE (síncrono) antes de disparar o PDF/WhatsApp/Softsystem em segundo plano; se esse
# segundo plano morrer no meio (servidor reiniciou, caiu, deu erro) sem terminar (enviado_em
# continua vazio), essa varredura reconhece e tenta de novo sozinha. Folga de 2 min antes de
# considerar "travado" pra não brigar com uma aprovação ainda em andamento normalmente.
RECOVERY_GRACE_SECONDS = 120

# Aviso de "observação preenchida" vai pra esse número (pedido explícito do usuário em
# 07/10/2026: "se depender deles nunca dará certo, direciona todas para esse telefone").
APPROVAL_OVERRIDE_PHONE = "5561992136622"

# Fases em que a O.S. já está "decidida" - não faz mais sentido preencher observação de orçamento
# pra uma O.S. que já foi enviada, aprovada, recusada/não autorizada, finalizada, descartada ou
# já está aguardando retirada. 12 = "Não Autorizada" (tratado igual "Não Aprovado" no resto do
# sistema - ver os_board.py BOARD_STAGES) - faltava aqui, achado em produção em 07/10/2026 (O.S.
# #1704 já estava Não Autorizada e mesmo assim recebeu um aviso de orçamento, à toa).
EVENTO_ORCAMENTO_ENVIADO = 3
EVENTO_APROVADO = 15
EVENTO_NAO_APROVADO = 16
EVENTO_NAO_AUTORIZADA = 12
EVENTO_FINALIZADA = 7
EVENTO_DESCARTE = 14
EVENTO_RETIRADA = 6
_STAGES_PASSADAS = {
    EVENTO_ORCAMENTO_ENVIADO, EVENTO_APROVADO, EVENTO_NAO_APROVADO, EVENTO_NAO_AUTORIZADA,
    EVENTO_FINALIZADA, EVENTO_DESCARTE, EVENTO_RETIRADA,
}


async def try_draft_one(tenant_id: int, codos: int) -> bool:
    """Gera (se elegível) o rascunho de UMA O.S. e avisa pra revisão - chamada tanto pelo gatilho
    em tempo real (os_board.sync_board) quanto pela varredura periódica abaixo. Marca
    report_draft_sent_at ANTES de chamar a IA (não depois) pra reservar o slot e evitar gerar duas
    vezes se os dois gatilhos disparam quase juntos pra mesma O.S."""
    async with AsyncSessionLocal() as db:
        order = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos,
            OsBoardOrder.report_draft_sent_at.is_(None),
        ))).scalars().first()
        if not order:
            return False
        if order.situacao_evento in _STAGES_PASSADAS:
            return False
        if not order.valor_total or order.valor_total <= 0:
            return False
        itens = (await db.execute(select(OsBoardItem.id).where(
            OsBoardItem.tenant_id == tenant_id, OsBoardItem.empresa == order.empresa, OsBoardItem.codos == codos
        ).limit(1))).scalars().first()
        if not itens:
            return False
        order.report_draft_sent_at = datetime.utcnow()
        await db.commit()

    try:
        from app.services.os_report_service import generate_report_draft
        from app.services.evolution_service import evolution_service

        draft = await generate_report_draft(tenant_id, codos)

        async with AsyncSessionLocal() as db2:
            wn = (await db2.execute(select(WhatsAppNumber).where(
                WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID
            ))).scalar_one_or_none()
            if wn and wn.instancia_evolution_api:
                aviso = (
                    f"📝 *O.S. #{codos}* ({draft['cliente']}): rascunho de laudo/orçamento pronto pra revisar. "
                    f"Abra a O.S. no sistema pra aprovar ou reprovar com um motivo."
                )
                await evolution_service.send_text_message(
                    instance_name=wn.instancia_evolution_api, number=APPROVAL_OVERRIDE_PHONE, text=aviso
                )

        logger.info(f"[RELATORIO AUTO] O.S. #{codos}: rascunho gerado e aviso mandado pra revisão.")
        return True
    except Exception as e:
        logger.error(f"[RELATORIO AUTO] Erro processando O.S. #{codos}: {e}", exc_info=True)
        return False


async def _process_once() -> int:
    processados = 0
    async with AsyncSessionLocal() as db:
        candidatos = (await db.execute(select(OsBoardOrder.tenant_id, OsBoardOrder.codos).where(
            OsBoardOrder.report_draft_sent_at.is_(None),
            OsBoardOrder.valor_total.isnot(None),
            OsBoardOrder.valor_total > 0,
        ))).all()

    for tenant_id, codos in candidatos:
        if await try_draft_one(tenant_id, codos):
            processados += 1
        await asyncio.sleep(PER_ITEM_GAP_SECONDS)

    return processados


async def _recover_stuck_approvals() -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=RECOVERY_GRACE_SECONDS)
    async with AsyncSessionLocal() as db:
        stuck = (await db.execute(select(OsReportDraft).where(
            OsReportDraft.aprovado_em.isnot(None),
            OsReportDraft.enviado_em.is_(None),
            OsReportDraft.aprovado_em < cutoff,
        ))).scalars().all()
        items = [(d.tenant_id, d.codos, d.internal_note, d.customer_message, d.aprovado_por) for d in stuck]

    if not items:
        return 0

    from app.services.os_report_service import _approve_report_background
    for tenant_id, codos, internal_note, customer_message, aprovado_por in items:
        logger.warning(f"[RELATORIO AUTO] O.S. #{codos}: aprovação de {aprovado_por} ficou travada (sem concluir) - retomando.")
        await _approve_report_background(tenant_id, codos, internal_note, customer_message, aprovado_por or "Recuperação automática")
        await asyncio.sleep(PER_ITEM_GAP_SECONDS)
    return len(items)


async def start_report_autodraft_loop():
    logger.info(f"Preenchimento automático de observação (IA) iniciado (varredura a cada {CHECK_INTERVAL_SECONDS}s).")
    while True:
        try:
            n = await _process_once()
            if n:
                logger.info(f"[RELATORIO AUTO] {n} O.S. processada(s) nesta varredura.")
        except Exception as e:
            logger.error(f"[RELATORIO AUTO] Erro na varredura: {e}", exc_info=True)
        try:
            r = await _recover_stuck_approvals()
            if r:
                logger.info(f"[RELATORIO AUTO] {r} aprovação(ões) travada(s) retomada(s).")
        except Exception as e:
            logger.error(f"[RELATORIO AUTO] Erro na recuperação de aprovações travadas: {e}", exc_info=True)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
