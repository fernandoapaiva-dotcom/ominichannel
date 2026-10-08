"""
Laudo técnico + orçamento pro cliente, montados pela IA a partir do que o técnico JÁ lançou no
Softsystem (peças/mão de obra via ITENSORDEMSERVICO, e a observação que ele escreveu ao mudar o
status da O.S.) - sem duplicar digitação. Pedido original do usuário: o técnico hoje lança tudo no
Softsystem e depois tem que escrever o mesmo problema de novo pro cliente, manualmente.

Gera DOIS textos distintos (corrigido em 07/10/2026, O.S. #1987 revelou que só existia um texto,
indo por engano tanto pro cliente quanto pro campo Observação do Softsystem):
  - internal_note: laudo técnico interno -> campo Observação (EQUIPORDEMSERVICO.OBS).
  - customer_message: diagnóstico/orçamento em tom de atendimento -> PDF mandado ao cliente.

Fluxo, sempre com revisão humana no meio (nunca envia nem grava nada sozinho):
  1. generate_report_draft: monta os dois rascunhos (upsert em OsReportDraft), não manda nada.
  2. Dono revisa no quadro; aprova OU reprova com motivo (reject_report reelabora os dois textos
     levando o motivo em conta e devolve pra revisão de novo).
  3. approve_report: valida rápido e dispara o resto (gerar o PDF, mandar pro cliente no WhatsApp,
     gravar o laudo técnico no campo Observação e o evento "Orçamento Enviado" de volta no
     Softsystem) em segundo plano - pedido do usuário em 07/10/2026 ("tenho 20 O.S. na mesa, não
     posso ficar travado esperando uma de cada vez").
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import OsBoardOrder, OsBoardItem, OsBoardEvent, OsReportDraft, WhatsAppNumber, SoftsystemPendingWrite

logger = logging.getLogger("os_report_service")

EVENTO_ORCAMENTO_ENVIADO = 3

# Janela pra considerar uma segunda chamada de approve_report como clique duplicado, não uma
# aprovação de verdade - um pouco acima do tempo real observado de processamento em segundo
# plano (~25-30s: PDF + 2 mensagens no WhatsApp com o ritmo anti-bloqueio).
APPROVAL_DEDUP_WINDOW_SECONDS = 90


def _clean_phone(raw: Optional[str]) -> str:
    return "".join(filter(str.isdigit, raw or ""))


async def _gather_os_context(db, tenant_id: int, codos: int):
    order = (await db.execute(select(OsBoardOrder).where(
        OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
    ))).scalars().first()
    if not order:
        raise ValueError(f"O.S. #{codos} não encontrada no quadro")

    itens = (await db.execute(select(OsBoardItem).where(
        OsBoardItem.tenant_id == tenant_id, OsBoardItem.empresa == order.empresa, OsBoardItem.codos == codos
    ).order_by(OsBoardItem.id.asc()))).scalars().all()
    pecas = [{"descricao": it.descricao, "quantidade": it.quantidade, "preco": it.preco} for it in itens]

    # Nota do técnico: prioridade pro que ele escreveu direto no campo Observação da O.S. no
    # Softsystem (equip_obs_raw, espelhado pelo vigia - ver db_watcher._board_equip_obs) - é o
    # canal pensado especificamente pra isso (pedido do usuário em 07/10/2026: "posso escrever na
    # observação, a IA capta a informação... e escreve por cima melhorado" - essencial quando a
    # O.S. é só mão de obra/serviço, sem peça física pra 'dar a dica' sozinha). Sem isso, cai pro
    # motivo mais recente de uma mudança de status (ex: "Sem conserto"), fallback já existente.
    tecnico_notas = order.equip_obs_raw
    if not tecnico_notas:
        evs = (await db.execute(select(OsBoardEvent).where(
            OsBoardEvent.tenant_id == tenant_id, OsBoardEvent.empresa == order.empresa, OsBoardEvent.codos == codos,
            OsBoardEvent.obs.isnot(None), OsBoardEvent.obs != ""
        ).order_by(OsBoardEvent.data.desc()))).scalars().first()
        tecnico_notas = evs.obs if evs else None

    # Query do RAG enriquecida com as peças/notas, não só o nome do equipamento - pedido do
    # usuário em 07/10/2026 ("ele instruiu porque a máquina estava em curto... ele deveria dar
    # um diagnóstico... explicando causas"): só "ESAB LHN 150" como busca geralmente acha a
    # página de capa/índice do manual, não a seção que explica a causa de um defeito específico
    # (ex: "IGBT em curto"). Mesma ideia de contexto rico que já funciona bem no Copiloto Técnico.
    rag_context = ""
    pecas_desc = " ".join(p.get("descricao") or "" for p in pecas)
    rag_query = " ".join(filter(None, [order.equipamento, pecas_desc, tecnico_notas]))
    if rag_query.strip():
        try:
            from app.services.rag_service import rag_service
            rag_context = await rag_service.search_context(
                tenant_id=tenant_id, query=rag_query,
                department_id=settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID
            )
        except Exception as e:
            logger.warning(f"[RELATORIO IA] Falha ao buscar contexto RAG pra O.S. #{codos}: {e}")

    return order, pecas, tecnico_notas, rag_context


async def generate_report_draft(tenant_id: int, codos: int, reject_reason: Optional[str] = None) -> dict:
    async with AsyncSessionLocal() as db:
        order, pecas, tecnico_notas, rag_context = await _gather_os_context(db, tenant_id, codos)

        from app.services.gemini_service import gemini_service
        from app.services.settings_service import settings_service

        decrypted_settings = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
        gemini_kwargs = dict(
            tenant_gemini_api_key=decrypted_settings.get("gemini_api_key"),
            tenant_gemini_model_name=decrypted_settings.get("gemini_model_name"),
        )

        # Em paralelo, não em sequência - pedido do usuário em 07/10/2026 ("tem que ser só o tempo
        # de mudar de sistema"): as duas chamadas à IA não dependem uma da outra, rodar junto corta
        # quase pela metade o tempo de geração do rascunho (duas chamadas de ~15s cada viravam ~30s
        # em sequência).
        import asyncio
        internal_note, customer_message = await asyncio.gather(
            gemini_service.generate_internal_diagnostic_note(
                codos=codos, equipamento=order.equipamento or "", pecas=pecas,
                tecnico_notas=tecnico_notas, rag_context=rag_context, reject_reason=reject_reason,
                **gemini_kwargs,
            ),
            gemini_service.generate_customer_diagnostic_report(
                customer_name=order.contato_nome or order.cliente or "Cliente",
                codos=codos, equipamento=order.equipamento or "", pecas=pecas,
                valor_total=order.valor_total, tecnico_notas=tecnico_notas, rag_context=rag_context,
                reject_reason=reject_reason, **gemini_kwargs,
            ),
        )

        draft = (await db.execute(select(OsReportDraft).where(
            OsReportDraft.tenant_id == tenant_id, OsReportDraft.empresa == order.empresa,
            OsReportDraft.loja == order.loja, OsReportDraft.codos == codos
        ))).scalars().first()
        if draft:
            draft.internal_note = internal_note
            draft.customer_message = customer_message
            draft.reject_reason = reject_reason
            draft.revisao = (draft.revisao or 1) + 1
            draft.gerado_em = datetime.utcnow()
            draft.enviado_em = None
        else:
            draft = OsReportDraft(
                tenant_id=tenant_id, empresa=order.empresa, loja=order.loja, codos=codos,
                internal_note=internal_note, customer_message=customer_message,
                reject_reason=reject_reason, revisao=1,
            )
            db.add(draft)
        await db.commit()

        return {
            "codos": codos,
            "cliente": order.contato_nome or order.cliente,
            "equipamento": order.equipamento,
            "valor_total": order.valor_total,
            "pecas": pecas,
            "internal_note": internal_note,
            "customer_message": customer_message,
            "revisao": draft.revisao,
        }


async def reject_report(tenant_id: int, codos: int, reason: str) -> dict:
    return await generate_report_draft(tenant_id, codos, reject_reason=reason)


async def get_pending_draft(tenant_id: int, codos: int) -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        order = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
        ))).scalars().first()
        if not order:
            return None
        draft = (await db.execute(select(OsReportDraft).where(
            OsReportDraft.tenant_id == tenant_id, OsReportDraft.empresa == order.empresa,
            OsReportDraft.loja == order.loja, OsReportDraft.codos == codos,
            OsReportDraft.enviado_em.is_(None)
        ))).scalars().first()
        if not draft:
            return None
        return {
            "codos": codos,
            "internal_note": draft.internal_note,
            "customer_message": draft.customer_message,
            "revisao": draft.revisao,
            "reject_reason": draft.reject_reason,
        }


async def approve_report(tenant_id: int, codos: int, internal_note: str, customer_message: str, approved_by: str) -> dict:
    """
    Aprova rápido (só valida o que PRECISA ser visível na hora - telefone/instância configurados)
    e dispara o resto (gerar PDF, mandar pro WhatsApp, gravar no Softsystem) em segundo plano -
    pedido do usuário em 07/10/2026 ("tenho 20 O.S. na mesa, não posso ficar travado esperando uma
    de cada vez - depois que aprovou, sistema já dispara e segue sem eu ficar preso na tela").
    Mesmo padrão de asyncio.create_task já usado em os_handler_ingest.py (dispatch_orcamento_messages
    etc.) pros envios de PDF via Softsystem.
    """
    async with AsyncSessionLocal() as db:
        order = (await db.execute(select(OsBoardOrder).where(
            OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
        ))).scalars().first()
        if not order:
            raise ValueError(f"O.S. #{codos} não encontrada no quadro")

        phone = _clean_phone(order.telefone)
        if not phone:
            raise ValueError(f"O.S. #{codos} não tem telefone de contato cadastrado")

        wn = (await db.execute(select(WhatsAppNumber).where(
            WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID
        ))).scalar_one_or_none()
        if not wn or not wn.instancia_evolution_api:
            raise ValueError("Número de WhatsApp da Assistência Técnica não configurado")

        # Grava a aprovação DE VERDADE (síncrono, antes de disparar o resto em segundo plano) -
        # rede de segurança pedida pelo usuário em 07/10/2026 ("se der algum problema com o
        # sistema e ele não disparar por algum motivo, tem como pegar depois?"): aprovado_em
        # marcado + enviado_em ainda vazio é o sinal de "aprovação pendente de concluir" que
        # os_report_autodraft_service usa pra retomar sozinho se o servidor cair/reiniciar no meio
        # do processamento (ver _recover_stuck_approvals).
        draft = (await db.execute(select(OsReportDraft).where(
            OsReportDraft.tenant_id == tenant_id, OsReportDraft.empresa == order.empresa,
            OsReportDraft.loja == order.loja, OsReportDraft.codos == codos
        ))).scalars().first()

        # Proteção contra clique duplo - achado em produção em 07/10/2026 (O.S. #1966 mandou o
        # PDF 2x pro cliente): se já tem uma aprovação em andamento (aprovado_em recente, ainda
        # sem enviado_em) pra essa mesma O.S., essa segunda chamada é quase certamente o mesmo
        # clique duplicado, não uma aprovação nova - ignora em vez de disparar outro envio.
        if draft and draft.aprovado_em and not draft.enviado_em:
            seconds_since = (datetime.utcnow() - draft.aprovado_em).total_seconds()
            if seconds_since < APPROVAL_DEDUP_WINDOW_SECONDS:
                logger.warning(f"[RELATORIO IA] O.S. #{codos}: aprovação ignorada (já em processamento há {seconds_since:.0f}s - provável clique duplicado).")
                return {"status": "already_processing", "codos": codos}

        if draft:
            draft.internal_note = internal_note
            draft.customer_message = customer_message
            draft.aprovado_por = approved_by
            draft.aprovado_em = datetime.utcnow()
        else:
            draft = OsReportDraft(
                tenant_id=tenant_id, empresa=order.empresa, loja=order.loja, codos=codos,
                internal_note=internal_note, customer_message=customer_message,
                aprovado_por=approved_by, aprovado_em=datetime.utcnow(),
            )
            db.add(draft)
        await db.commit()

    import asyncio
    asyncio.create_task(_approve_report_background(tenant_id, codos, internal_note, customer_message, approved_by))
    logger.info(f"[RELATORIO IA] Aprovação da O.S. #{codos} por {approved_by} recebida - processando em segundo plano.")
    return {"status": "queued", "codos": codos}


async def _approve_report_background(tenant_id: int, codos: int, internal_note: str, customer_message: str, approved_by: str):
    try:
        async with AsyncSessionLocal() as db:
            order = (await db.execute(select(OsBoardOrder).where(
                OsBoardOrder.tenant_id == tenant_id, OsBoardOrder.codos == codos
            ))).scalars().first()
            if not order:
                logger.error(f"[RELATORIO IA] O.S. #{codos} não encontrada no quadro (processamento em segundo plano)")
                return
            phone = _clean_phone(order.telefone)
            wn = (await db.execute(select(WhatsAppNumber).where(
                WhatsAppNumber.id == settings.ASSISTENCIA_TECNICA_WHATSAPP_NUMBER_ID
            ))).scalar_one_or_none()
            if not phone or not wn or not wn.instancia_evolution_api:
                logger.error(f"[RELATORIO IA] O.S. #{codos}: telefone ou instância sumiram entre a aprovação e o processamento")
                return

            itens = (await db.execute(select(OsBoardItem).where(
                OsBoardItem.tenant_id == tenant_id, OsBoardItem.empresa == order.empresa, OsBoardItem.codos == codos
            ).order_by(OsBoardItem.id.asc()))).scalars().all()
            pecas = [{"descricao": it.descricao, "quantidade": it.quantidade, "preco": it.preco} for it in itens]

            from app.services.os_report_pdf_service import generate_diagnostic_pdf
            from app.api.v1.os_handler_ingest import (
                get_or_create_conversation, extract_evolution_msg_id, save_uploaded_pdf,
                build_os_pdf_filename, resolve_tecnico_phone_by_name, send_and_log_text,
            )
            from app.services.evolution_service import evolution_service
            from app.services.lid_resolver_service import resolve_and_bind_contact
            from app.models.models import Message, MessageSender, MessageType
            import base64

            pdf_bytes = generate_diagnostic_pdf(
                order=order, pecas=pecas, customer_message=customer_message, empresa=order.empresa,
            )
            # Salva em uploads/ (não só manda em memória) - igual o fluxo já existente de PDF de
            # orçamento (os_handler_ingest.py): o marcador CONFIRM_OS_APPROVAL abaixo guarda esse
            # caminho, e tanto o lembrete automático (os_board_followup_service) quanto o aviso de
            # resultado pro grupo/técnico (webhooks.notify_os_approval_result) reabrem esse arquivo
            # depois - sem salvar, essas duas partes já existentes e funcionando ficariam sem PDF.
            saved_rel_path = save_uploaded_pdf(pdf_bytes)
            pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
            file_name = build_os_pdf_filename(codos, order.contato_nome or order.cliente)

            contact = await resolve_and_bind_contact(db, tenant_id, phone, push_name=order.contato_nome or order.cliente)
            await db.flush()
            conversation = await get_or_create_conversation(db, tenant_id, contact.id, wn.id)

            # Só 2 mensagens, não 3 - pedido do usuário em 07/10/2026 ("é só uma mensagem
            # informando que a máquina foi avaliada, manda o PDF com diagnóstico e pergunta se
            # aprova, e pronto... esse tanto de mensagem atrapalha"): o aviso de "diagnóstico
            # pronto" vai como LEGENDA do próprio PDF (uma balão só), não como texto separado antes.
            caption = (
                f"Olá, {order.contato_nome or order.cliente or 'Cliente'}! 👋 A máquina foi avaliada "
                f"e o diagnóstico da sua Ordem de Serviço #{codos} está pronto - segue o PDF com o orçamento."
            )
            approval_prompt = (
                "Você *aprova* a execução do serviço pelo valor informado no orçamento? "
                "Responda *SIM* para aprovar ou *NÃO* para recusar."
            )

            send_res = await evolution_service.send_media_message(
                instance_name=wn.instancia_evolution_api, number=phone, media_type="document",
                mimetype="application/pdf", media=pdf_b64, file_name=file_name, caption=caption,
            )
            success = isinstance(send_res, dict) and send_res.get("success")
            if not success:
                logger.error(f"[RELATORIO IA] Falha ao enviar PDF da O.S. #{codos}: {send_res}")
                return
            msg = Message(
                conversation_id=conversation.id, remetente=MessageSender.SISTEMA, conteudo=f"/uploads/{saved_rel_path}|{file_name}",
                tipo=MessageType.ARQUIVO, status="sent", whatsapp_msg_id=extract_evolution_msg_id(send_res),
                timestamp=datetime.utcnow(),
            )
            db.add(msg)

            await send_and_log_text(db, tenant_id, wn.id, wn.instancia_evolution_api, phone, conversation, approval_prompt, delay_sec=1.0)

            # Mesmo marcador/mecanismo já usado pelo fluxo de orçamento vindo do Softsystem
            # (os_handler_ingest.py) - é o que faz a resposta SIM/NÃO do cliente ser reconhecida
            # (webhooks.py) e disparar o aviso pro grupo "SERV - SOLICITAÇÃO DE O.S." e pro técnico
            # responsável (notify_os_approval_result) - passo que o usuário confirmou que já
            # funciona e não precisava mudar, mas só dispara se esse marcador for setado aqui.
            tecnico_phone = await resolve_tecnico_phone_by_name(db, tenant_id, order.tecnico)
            conversation.assunto_atual = f"CONFIRM_OS_APPROVAL:{codos}|{saved_rel_path}|{tecnico_phone or ''}"

            # Grava de volta no Softsystem de verdade (fila que o vigia executa): laudo técnico
            # SUBSTITUI o campo Observação (NÃO muda etapa) + evento "Orçamento Enviado" (muda a
            # etapa) - quem aprovou fica no OPERADOR via requested_by, auditoria nativa já existente.
            # write_type="nota_defeito_replace" (não "nota_defeito", que só acrescenta): pedido do
            # usuário em 07/10/2026 - ele escreve uma nota crua na Observação (já usada como entrada
            # do laudo, ver _gather_os_context), a IA reelabora e GRAVA POR CIMA, não embaixo.
            db.add(SoftsystemPendingWrite(
                # cod_evento=0: a coluna ainda tem NOT NULL na tabela de verdade (SQLite não altera
                # colunas existentes via create_all, mesmo com o modelo marcado nullable) - mesmo
                # workaround já usado antes pro write_type="nota_defeito".
                tenant_id=tenant_id, empresa=order.empresa, loja=order.loja, codos=codos,
                write_type="nota_defeito_replace", cod_evento=0, obs=internal_note, requested_by=approved_by,
            ))
            db.add(SoftsystemPendingWrite(
                tenant_id=tenant_id, empresa=order.empresa, loja=order.loja, codos=codos,
                # [:255], não [:500]: EVENTOSORDEMSERVICO.OBS é VARCHAR(255) de verdade no Firebird
                # (achado em produção em 07/10/2026 testando O.S. #1987 - o limite de 500 presumido
                # antes causava "string right truncation" e a gravação do evento falhava inteira,
                # silenciosamente, mesmo com o PDF já enviado pro cliente).
                write_type="evento", cod_evento=EVENTO_ORCAMENTO_ENVIADO, obs=customer_message[:255],
                requested_by=approved_by,
            ))
            order.situacao_evento = EVENTO_ORCAMENTO_ENVIADO
            # last_nudge_at = agora (NÃO None): bug achado em produção em 07/10/2026 - None faz
            # os_board_followup_service._list_due_orcamento tratar como "nunca avisado, cobra já"
            # (cai no fallback ultimo_evento_em, que fica velho), disparando a cobrança automática
            # "Só confirmando..." minutos depois do PDF, duplicando a pergunta de aprovação pro
            # cliente. "Agora" é o certo: acabei de avisar, o relógio da cobrança começa daqui.
            order.last_nudge_at = datetime.utcnow()
            order.ultimo_evento_em = datetime.utcnow()
            order.atualizado_em = datetime.utcnow()

            draft = (await db.execute(select(OsReportDraft).where(
                OsReportDraft.tenant_id == tenant_id, OsReportDraft.empresa == order.empresa,
                OsReportDraft.loja == order.loja, OsReportDraft.codos == codos
            ))).scalars().first()
            if draft:
                draft.internal_note = internal_note
                draft.customer_message = customer_message
                draft.aprovado_por = approved_by
                draft.aprovado_em = datetime.utcnow()
                draft.enviado_em = datetime.utcnow()

            await db.commit()
            logger.info(f"[RELATORIO IA] Relatório da O.S. #{codos} aprovado por {approved_by}, PDF enviado e enfileirado pro Softsystem.")
    except Exception as e:
        logger.error(f"[RELATORIO IA] Falha processando aprovação em segundo plano da O.S. #{codos}: {e}", exc_info=True)
