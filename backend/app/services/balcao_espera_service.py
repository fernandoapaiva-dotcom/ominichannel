from datetime import datetime
from typing import Optional, List, Dict, Any
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_, func

from app.models.models import BalcaoFilaEspera, Contact, Conversation, Message, MessageSender, MessageType, ConversationStatus
from app.services.evolution_service import evolution_service
from app.core.config import settings

logger = logging.getLogger("balcao_espera_service")


class BalcaoEsperaService:
    @staticmethod
    def _adicionar_log_auditoria(historico_atual: Optional[str], novo_evento: str) -> str:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        linha = f"[{timestamp}] {novo_evento}"
        if historico_atual:
            return f"{historico_atual}\n{linha}"
        return linha

    @staticmethod
    async def cadastrar_demanda(
        db: AsyncSession,
        tenant_id: int,
        empresa: str,
        cliente_nome: str,
        cliente_telefone: str,
        produto_nome: str,
        atendente_nome: str,
        produto_codigo: Optional[str] = None,
        produto_ean: Optional[str] = None,
        quantidade_desejada: float = 1.0,
        cliente_documento: Optional[str] = None,
        observacao: Optional[str] = None,
    ) -> BalcaoFilaEspera:
        # Limpa telefone
        import re
        clean_phone = re.sub(r"\D", "", cliente_telefone)
        if len(clean_phone) in (10, 11) and not clean_phone.startswith("55"):
            clean_phone = f"55{clean_phone}"

        log_inicial = f"Demanda registrada no balcão por {atendente_nome} (Loja: {empresa.upper()}). Cliente: {cliente_nome} ({clean_phone}). Qtd: {quantidade_desejada}."
        if observacao:
            log_inicial += f" Obs: {observacao}"

        item = BalcaoFilaEspera(
            tenant_id=tenant_id,
            empresa=empresa.lower(),
            cliente_nome=cliente_nome.strip(),
            cliente_telefone=clean_phone,
            cliente_documento=cliente_documento.strip() if cliente_documento else None,
            produto_nome=produto_nome.strip(),
            produto_codigo=produto_codigo.strip() if produto_codigo else None,
            produto_ean=produto_ean.strip() if produto_ean else None,
            quantidade_desejada=quantidade_desejada,
            atendente_nome=atendente_nome.strip(),
            observacao=observacao.strip() if observacao else None,
            status="aguardando",
            criado_em=datetime.utcnow(),
            historico_auditoria=f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {log_inicial}"
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def notificar_cliente(
        db: AsyncSession,
        demanda_id: int,
        origem_aviso: str = "Disparo manual ou entrada de nota",
        mensagem_customizada: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispara mensagem no WhatsApp do cliente e audita o evento."""
        stmt = select(BalcaoFilaEspera).where(BalcaoFilaEspera.id == demanda_id)
        res = await db.execute(stmt)
        demanda = res.scalar_one_or_none()
        if not demanda:
            return {"success": False, "error": "Demanda não encontrada"}

        nome_loja = "Servweld" if demanda.empresa == "servweld" else "Centro Oeste"
        texto = mensagem_customizada or (
            f"Olá, {demanda.cliente_nome}! Tudo bem?\n\n"
            f"Passando para te avisar que aquele produto que você estava procurando no balcão acabou de chegar no nosso estoque:\n"
            f"📦 *{demanda.produto_nome}*\n\n"
            f"Já temos unidades disponíveis aqui na *{nome_loja}*. Deseja que a gente reserve para você ou prepare o seu pedido?"
        )

        # Envia via Evolution API
        msg_id = None
        erro_envio = None
        try:
            # Seleciona instância ativa de WhatsApp da empresa ou primeira disponível
            instancia = "instancia_vendas"
            resp = await evolution_service.send_text_message(
                instance_name=instancia,
                number=demanda.cliente_telefone,
                text=texto
            )
            msg_id = resp.get("key", {}).get("id") or resp.get("id")
        except Exception as e:
            logger.error(f"Erro ao enviar aviso de chegada para {demanda.cliente_telefone}: {e}")
            erro_envio = str(e)

        if msg_id or not erro_envio:
            demanda.status = "notificado"
            demanda.notificado_em = datetime.utcnow()
            demanda.notificado_msg_id = msg_id
            log_msg = f"Aviso de chegada enviado com sucesso via WhatsApp ({demanda.cliente_telefone}). Origem: {origem_aviso}."
            demanda.historico_auditoria = BalcaoEsperaService._adicionar_log_auditoria(demanda.historico_auditoria, log_msg)
            await db.commit()
            return {"success": True, "msg_id": msg_id, "status": "notificado"}
        else:
            log_erro = f"Tentativa de notificação falhou: {erro_envio}"
            demanda.historico_auditoria = BalcaoEsperaService._adicionar_log_auditoria(demanda.historico_auditoria, log_erro)
            await db.commit()
            return {"success": False, "error": erro_envio}

    @staticmethod
    async def processar_gatilho_entrada_compra(
        db: AsyncSession,
        tenant_id: int,
        empresa: str,
        itens_entrada: List[Dict[str, Any]],
        numero_nf: str,
        compra_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ao confirmar uma NF-e de entrada, busca clientes que estão aguardando
        os itens dessa nota e notifica-os automaticamente.
        """
        notificacoes_realizadas = []

        # Busca demandas aguardando nessa empresa
        stmt = select(BalcaoFilaEspera).where(
            BalcaoFilaEspera.tenant_id == tenant_id,
            BalcaoFilaEspera.empresa == empresa.lower(),
            BalcaoFilaEspera.status == "aguardando"
        )
        res = await db.execute(stmt)
        demandas = res.scalars().all()

        if not demandas:
            return notificacoes_realizadas

        for item_nota in itens_entrada:
            ean_nota = (item_nota.get("ean") or "").strip()
            desc_nota = (item_nota.get("descricao_fornecedor") or "").strip().lower()
            cod_prod_soft = (item_nota.get("softsystem_prod_codigo") or "").strip()

            for d in demandas:
                match = False
                # Match por EAN
                if ean_nota and d.produto_ean and ean_nota == d.produto_ean.strip():
                    match = True
                # Match por código Softsystem
                elif cod_prod_soft and d.produto_codigo and cod_prod_soft == d.produto_codigo.strip():
                    match = True
                # Match parcial por descrição (palavras-chave principais)
                elif d.produto_nome:
                    palavras = [p for p in d.produto_nome.lower().split() if len(p) >= 4]
                    if palavras and all(p in desc_nota for p in palavras[:2]):
                        match = True

                if match and d.status == "aguardando":
                    if compra_id:
                        d.compra_entrada_id = compra_id
                    log_match = f"Produto identificado na entrada da NF-e #{numero_nf}. Disparando aviso automático."
                    d.historico_auditoria = BalcaoEsperaService._adicionar_log_auditoria(d.historico_auditoria, log_match)
                    await db.commit()

                    envio = await BalcaoEsperaService.notificar_cliente(
                        db=db,
                        demanda_id=d.id,
                        origem_aviso=f"Entrada automática NF-e #{numero_nf}"
                    )
                    notificacoes_realizadas.append({
                        "cliente": d.cliente_nome,
                        "telefone": d.cliente_telefone,
                        "produto": d.produto_nome,
                        "resultado": envio
                    })

        return notificacoes_realizadas
