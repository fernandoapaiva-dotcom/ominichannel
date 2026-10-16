import asyncio
import json
import os
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, get_admin_user
from app.models.models import (
    User, UserRole, LojaParametrosCusto, LojaCustoFixo, BalcaoFilaEspera,
    ComprasEntrada, ComprasEntradaItem, ComprasEntradaEvento,
)
from app.services.nfe_xml_service import NfeXmlService, CNPJ_POR_EMPRESA
from app.services.compras_custo_service import ComprasCustoService, PADROES_LOJA
from app.services.market_price_service import MarketPriceService
from app.services.balcao_espera_service import BalcaoEsperaService
from app.services.softsystem_service import SoftsystemService
from app.services.sefaz_dfe_service import SefazService, SefazErro, SefazAguarde
from app.services.settings_service import settings_service

logger = logging.getLogger("compras_api")

router = APIRouter(prefix="/compras", tags=["Compras & Balcão"])

EMPRESAS = ("servweld", "centrooeste")
CAMPOS_PARAMETROS = (
    "regime_tributario", "custo_fixo_operacional_pct", "despesas_variaveis_pct", "margem_lucro_padrao_pct",
    "margem_minima_pct", "icms_saida_pct", "pis_saida_pct", "cofins_saida_pct", "irpj_csll_pct", "das_pct",
    "das_parcela_icms_pct", "icms_antecipacao_pct", "faturamento_medio_mensal", "condicao_pagamento_padrao",
)
# Tolerância de divergência na contagem (diferença de arredondamento de itens a granel)
TOLERANCIA_CONTAGEM = 0.001


def _usuario(u: User) -> str:
    return u.nome or u.login


def _empresa_valida(empresa: str) -> str:
    e = (empresa or "").lower().strip()
    if e not in EMPRESAS:
        raise HTTPException(status_code=400, detail=f"Loja inválida: {empresa}")
    return e


# ============================================================ Schemas
class DecodificarChavePayload(BaseModel):
    chave_acesso: str


class BuscarNotaPayload(BaseModel):
    chave_nfe: str
    chave_cte: Optional[str] = None
    empresa: Optional[str] = None  # loja sugerida; a nota/Softsystem dizem a verdadeira


class ManifestarPayload(BaseModel):
    chave: str
    empresa: str
    tipo: str = "ciencia"  # ciencia (até 10 dias da emissão) | confirmacao (mercadoria recebida, até 180 dias)


_MSG_PRAZO_CIENCIA = (
    "Passaram os 10 dias que a SEFAZ permite para a Ciência da Operação (nota emitida há mais tempo). "
    "Para baixar o XML: confirme a operação (a mercadoria chegou) ou importe o arquivo XML."
)


class CalcularPayload(BaseModel):
    empresa: str
    itens: List[Dict[str, Any]]
    totais: Dict[str, Any]
    frete_cte: float = 0.0
    icms_cte: float = 0.0
    despesas_extras: Optional[List[Dict[str, Any]]] = None
    tipo_rateio: str = "valor"


class BuscarPrecoMercadoPayload(BaseModel):
    descricao: str
    ean: Optional[str] = None
    ncm: Optional[str] = None
    custo_unitario: Optional[float] = None


class ParametrosCustoPayload(BaseModel):
    empresa: str
    regime_tributario: Optional[str] = None
    custo_fixo_operacional_pct: Optional[float] = None
    despesas_variaveis_pct: Optional[float] = None
    margem_lucro_padrao_pct: Optional[float] = None
    margem_minima_pct: Optional[float] = None
    icms_saida_pct: Optional[float] = None
    pis_saida_pct: Optional[float] = None
    cofins_saida_pct: Optional[float] = None
    irpj_csll_pct: Optional[float] = None
    das_pct: Optional[float] = None
    das_parcela_icms_pct: Optional[float] = None
    icms_antecipacao_pct: Optional[float] = None
    faturamento_medio_mensal: Optional[float] = None
    condicao_pagamento_padrao: Optional[str] = None


class CustoFixoPayload(BaseModel):
    id: Optional[int] = None
    empresa: str
    categoria: str
    descricao: str
    valor_mensal: float
    ativo: bool = True


class CriarEntradaPayload(BaseModel):
    empresa: str
    origem_xml: Optional[str] = None
    nota: Dict[str, Any]
    cte: Optional[Dict[str, Any]] = None
    itens: List[Dict[str, Any]]  # itens já calculados e vinculados
    despesas_extras: Optional[List[Dict[str, Any]]] = None
    tipo_rateio: str = "valor"
    parcelas: List[Dict[str, Any]] = []
    parcelas_cte: List[Dict[str, Any]] = []


class ContagemItem(BaseModel):
    item_id: int
    qtd_contada: float


class ContagemPayload(BaseModel):
    itens: List[ContagemItem]


class AprovarDivergenciaPayload(BaseModel):
    justificativa: str


class PrecificacaoPayload(BaseModel):
    itens: List[Dict[str, Any]]  # {item_id, margem_lucro_pct?, preco_venda_final?, vínculo...}
    parcelas: Optional[List[Dict[str, Any]]] = None
    parcelas_cte: Optional[List[Dict[str, Any]]] = None
    despesas_extras: Optional[List[Dict[str, Any]]] = None
    tipo_rateio: Optional[str] = None


class BalcaoDemandaCreate(BaseModel):
    empresa: str = "servweld"
    cliente_nome: str
    cliente_telefone: str
    cliente_documento: Optional[str] = None
    produto_nome: str
    produto_codigo: Optional[str] = None
    produto_ean: Optional[str] = None
    quantidade_desejada: float = 1.0
    observacao: Optional[str] = None


# ============================================================ Helpers
async def _parametros_loja(db: AsyncSession, tenant_id: int, empresa: str) -> Dict[str, Any]:
    res = await db.execute(select(LojaParametrosCusto).where(
        LojaParametrosCusto.tenant_id == tenant_id, LojaParametrosCusto.empresa == empresa
    ))
    salvo = res.scalar_one_or_none()
    salvos = {c: getattr(salvo, c) for c in CAMPOS_PARAMETROS} if salvo else {}

    res = await db.execute(select(LojaCustoFixo).where(
        LojaCustoFixo.tenant_id == tenant_id, LojaCustoFixo.empresa == empresa, LojaCustoFixo.ativo == True  # noqa: E712
    ))
    total_fixos = sum(c.valor_mensal or 0 for c in res.scalars().all())
    faturamento = (salvo.faturamento_medio_mensal if salvo else None) or 0
    custo_fixo_calc = (total_fixos / faturamento * 100.0) if total_fixos > 0 and faturamento > 0 else None

    params = ComprasCustoService.parametros_efetivos(empresa, salvos, custo_fixo_calc)
    params["total_custos_fixos_mensal"] = round(total_fixos, 2)
    params["faturamento_medio_mensal"] = faturamento or None
    return params


def _registrar_evento(db: AsyncSession, entrada_id: int, usuario: str, acao: str, detalhe: str = "", item_id: Optional[int] = None):
    db.add(ComprasEntradaEvento(
        entrada_id=entrada_id, item_id=item_id, usuario=usuario, acao=acao, detalhe=detalhe, quando=datetime.utcnow()
    ))


# --------------------------------------------------------------------------- XML "aguardando"
# Pedido do usuário em 14/10/2026: a Ciência da Operação travava o lançamento ("preciso que seja
# imediato"). Agora, quando a SEFAZ só traz o resumo, a Ciência é registrada sozinha, a nota é
# consultada de novo na hora e, se o XML ainda não saiu, uma tarefa em segundo plano continua
# tentando (espaçamento em SefazService.RETENTATIVAS_APOS_CIENCIA_S) e grava no cache - a tela
# fica perguntando de novo e a nota abre sozinha assim que chegar.
_xml_pendentes: Dict[str, Dict[str, Any]] = {}


def _aguardando(chave: str, empresa: str, resumo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    pend = _xml_pendentes.get(chave) or {}
    espera = SefazService.segundos_ate_poder_consultar(chave)
    return {
        "status": "aguardando_xml", "empresa": empresa, "resumo": resumo or pend.get("resumo"),
        "proxima_tentativa_s": espera,
        "mensagem": (
            "Ciência da Operação registrada automaticamente. A SEFAZ ainda está liberando o XML completo - "
            f"o sistema tenta de novo sozinho (próxima em ~{max(espera, 1)} s) e a nota abre aqui assim que chegar."
        ),
    }


async def _tentar_xml_em_segundo_plano(chave: str, empresa: str):
    pend = _xml_pendentes.setdefault(chave, {})
    pend.update({"rodando": True, "falhou": None})
    try:
        while SefazService.tentativas_apos_ciencia_restantes(chave) > 0:
            await asyncio.sleep(max(1, SefazService.segundos_ate_poder_consultar(chave)))
            if await asyncio.to_thread(NfeXmlService.localizar_xml_local, chave):
                return  # chegou por outro caminho (pasta do Softsystem / outra busca)
            try:
                r = await asyncio.to_thread(SefazService.consultar_nfe, chave, empresa, None)
            except SefazAguarde:
                continue
            except SefazErro as e:
                pend["falhou"] = str(e)
                return
            if r.get("xml"):
                await asyncio.to_thread(NfeXmlService.salvar_xml_cache, chave, r["xml"])
                logger.info(f"[NF-e] XML de {chave} liberado pela SEFAZ após a Ciência (segundo plano).")
                return
            if r.get("cStat") == "656":
                pend["falhou"] = "A SEFAZ bloqueou as consultas deste CNPJ por 1 hora (consumo indevido). Importe o arquivo XML."
                return
        pend["falhou"] = (
            "A SEFAZ ainda não liberou o XML completo desta nota depois de várias tentativas. "
            "Peça o XML ao fornecedor e use \"Importar arquivo XML\" (ou tente de novo mais tarde)."
        )
    except Exception as e:  # nunca deixa a tarefa morrer calada
        logger.error(f"[NF-e] Erro buscando XML de {chave} em segundo plano: {e}", exc_info=True)
        pend["falhou"] = f"Erro ao buscar o XML na SEFAZ: {e}"
    finally:
        pend["rodando"] = False


def _iniciar_segundo_plano(chave: str, empresa: str, resumo: Optional[Dict[str, Any]] = None):
    pend = _xml_pendentes.setdefault(chave, {})
    if resumo:
        pend["resumo"] = resumo
    if not pend.get("rodando"):
        pend["rodando"] = True
        asyncio.create_task(_tentar_xml_em_segundo_plano(chave, empresa))


async def _obter_xml(chave: str, tipo: str, empresa_hint: Optional[str]) -> Dict[str, Any]:
    """
    Procura o XML: 1) pasta do Softsystem / cache local, 2) SEFAZ com o certificado da loja.
    Retorna {status: ok|aguardando_xml|precisa_ciencia|nao_encontrado, xml, origem, empresa, resumo, mensagem}.
    """
    caminho = await asyncio.to_thread(NfeXmlService.localizar_xml_local, chave)
    if caminho:
        _xml_pendentes.pop(chave, None)
        with open(caminho, "rb") as fh:
            origem = "cache_local" if caminho.startswith(settings.NFE_XML_CACHE_DIR) else "pasta_softsystem"
            return {"status": "ok", "xml": fh.read(), "origem": origem, "empresa": None}

    # já tem tarefa tentando essa nota: responde na hora, sem gastar consulta na SEFAZ
    pend = _xml_pendentes.get(chave)
    if tipo != "CTE" and pend:
        if pend.get("rodando"):
            return _aguardando(chave, pend.get("empresa") or empresa_hint or "servweld")
        if pend.get("falhou"):
            msg = pend["falhou"]
            _xml_pendentes.pop(chave, None)  # próxima busca começa do zero (respeitando as travas)
            return {"status": "nao_encontrado", "empresa": pend.get("empresa"), "resumo": pend.get("resumo"), "mensagem": msg}

    doc = None
    try:
        doc = await asyncio.to_thread(SoftsystemService.localizar_documento_destinado, chave)
    except Exception as e:
        logger.warning(f"DOCUMENTOSDESTINADOS indisponível para {chave}: {e}")
    empresa = (doc or {}).get("empresa") or empresa_hint or "servweld"

    if not SefazService.certificado_configurado(empresa):
        return {
            "status": "nao_encontrado", "empresa": empresa, "documento_destinado": doc,
            "mensagem": (
                f"Para buscar esta nota direto na SEFAZ falta o certificado digital da "
                f"{'Servweld' if empresa == 'servweld' else 'Centro Oeste'}: envie o arquivo .pfx em "
                "Compras & Balcão > Parâmetros de Custo > Certificado digital. Enquanto isso, dá para importar o XML."
            ),
        }

    try:
        if tipo == "CTE":
            if not doc or not doc.get("nsu"):
                return {
                    "status": "nao_encontrado", "empresa": empresa,
                    "mensagem": (
                        "Este CT-e ainda não apareceu nos documentos destinados do Softsystem (a SEFAZ só "
                        "entrega CT-e pelo NSU). Aguarde a próxima sincronização do Softsystem ou importe o XML."
                    ),
                }
            r = await asyncio.to_thread(SefazService.consultar_cte, chave, empresa, doc["nsu"])
        else:
            r = await asyncio.to_thread(SefazService.consultar_nfe, chave, empresa, (doc or {}).get("nsu"))
    except SefazAguarde as e:
        if tipo != "CTE":
            # já consultada há pouco (só resumo): em vez de travar 1 hora, registra a Ciência (se
            # ainda não tem) e deixa a tarefa em segundo plano buscar o XML no ritmo seguro
            if not SefazService.ciencia_registrada(chave):
                try:
                    ciencia = await asyncio.to_thread(SefazService.manifestar_ciencia, chave, empresa)
                except SefazErro as e2:
                    ciencia = {"sucesso": False, "xMotivo": str(e2)}
                if not ciencia.get("sucesso"):
                    if ciencia.get("cStat") == "596":
                        return {"status": "precisa_confirmacao", "empresa": empresa, "mensagem": _MSG_PRAZO_CIENCIA}
                    return {"status": "nao_encontrado", "empresa": empresa, "mensagem": f"{e} (Ciência automática recusada: {ciencia.get('xMotivo')})"}
            _xml_pendentes.setdefault(chave, {})["empresa"] = empresa
            _iniciar_segundo_plano(chave, empresa)
            return _aguardando(chave, empresa)
        return {"status": "nao_encontrado", "empresa": empresa, "mensagem": str(e)}
    except SefazErro as e:
        return {"status": "nao_encontrado", "empresa": empresa, "mensagem": str(e)}

    if r.get("xml"):
        await asyncio.to_thread(NfeXmlService.salvar_xml_cache, chave, r["xml"])
        return {"status": "ok", "xml": r["xml"], "origem": "sefaz", "empresa": empresa}
    resumo = r.get("resumo")
    if resumo and resumo.get("situacao") == "3":
        return {"status": "nao_encontrado", "empresa": empresa, "resumo": resumo,
                "mensagem": "A SEFAZ informa que esta nota foi CANCELADA pelo emitente - não dá para lançar a entrada."}
    if resumo and tipo != "CTE":
        # Só veio o resumo: registra a Ciência sozinho e tenta de novo na hora
        try:
            ciencia = await asyncio.to_thread(SefazService.manifestar_ciencia, chave, empresa)
        except SefazErro as e:
            ciencia = {"sucesso": False, "cStat": "", "xMotivo": str(e)}
        if ciencia.get("sucesso"):
            logger.info(f"[NF-e] Ciência automática de {chave} ({empresa}): {ciencia.get('cStat')} {ciencia.get('xMotivo')}")
            _xml_pendentes[chave] = {"empresa": empresa, "resumo": resumo}
            try:
                await asyncio.sleep(max(1, SefazService.segundos_ate_poder_consultar(chave)))
                r2 = await asyncio.to_thread(SefazService.consultar_nfe, chave, empresa, None)
                if r2.get("xml"):
                    await asyncio.to_thread(NfeXmlService.salvar_xml_cache, chave, r2["xml"])
                    _xml_pendentes.pop(chave, None)
                    return {"status": "ok", "xml": r2["xml"], "origem": "sefaz", "empresa": empresa}
            except SefazErro as e:
                logger.info(f"[NF-e] Re-consulta imediata de {chave} não trouxe o XML: {e}")
            _iniciar_segundo_plano(chave, empresa, resumo)
            return _aguardando(chave, empresa, resumo)
        logger.warning(f"[NF-e] Ciência automática de {chave} recusada: {ciencia.get('cStat')} {ciencia.get('xMotivo')}")
        if ciencia.get("cStat") == "596":  # fora do prazo de 10 dias - só a Confirmação libera agora
            return {"status": "precisa_confirmacao", "empresa": empresa, "resumo": resumo, "mensagem": _MSG_PRAZO_CIENCIA}
        return {
            "status": "precisa_ciencia", "empresa": empresa, "resumo": resumo,
            "mensagem": (
                f"A SEFAZ só liberou o resumo e recusou a Ciência automática ({ciencia.get('cStat')} - "
                f"{ciencia.get('xMotivo')}). Tente registrar de novo abaixo ou importe o XML."
            ),
        }
    if r.get("resumo"):
        return {
            "status": "precisa_ciencia", "empresa": empresa, "resumo": r["resumo"],
            "mensagem": (
                "A SEFAZ só liberou o resumo desta nota. Para baixar o XML completo é preciso registrar a "
                "Ciência da Operação em nome da loja (evento oficial - não aceita nem recusa a nota)."
            ),
        }
    return {"status": "nao_encontrado", "empresa": empresa, "mensagem": f"SEFAZ: {r.get('cStat')} - {r.get('xMotivo')}"}


async def _enriquecer_itens(empresa: str, fornecedor_cnpj: str, itens: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Vincula cada item ao produto do Softsystem (código do fornecedor -> EAN)."""
    def _rodar():
        forn = SoftsystemService.buscar_fornecedor_por_cnpj(empresa, fornecedor_cnpj)
        cod_forn = forn["codigo"] if forn else None
        saida = []
        for it in itens:
            novo = dict(it)
            # Unidade de compra x unidade de venda: o XML traz a quantidade tributável quando difere
            if it.get("quantidade_tributavel") and it.get("quantidade") and it.get("unidade_tributavel") \
                    and it.get("unidade_tributavel") != it.get("unidade"):
                novo["fator_conversao_sugerido"] = round(float(it["quantidade_tributavel"]) / float(it["quantidade"]), 4)
            try:
                v = SoftsystemService.vincular_item(empresa, cod_forn, it)
            except Exception as e:
                logger.warning(f"Vínculo do item {it.get('codigo_fornecedor')} falhou: {e}")
                v = {"metodo": None, "produto": None}
            p = v["produto"]
            if p:
                novo.update({
                    "softsystem_status": "vinculado",
                    "vinculo_metodo": v["metodo"],
                    "softsystem_prod_codigo": str(p["codigo"]),
                    "softsystem_descricao": p["descricao"],
                    "softsystem_grupo": p["grupo"],
                    "softsystem_subgrupo": p["subgrupo"],
                    "softsystem_unidade": p["unidade"],
                    "softsystem_estoque": p["estoque"],
                    "softsystem_preco_venda": p["preco_venda"],
                    "softsystem_preco_aquisicao": p["preco_aquisicao"],
                    "softsystem_custo_medio": p["custo_medio"],
                    "softsystem_ncm": p["ncm"],
                    "softsystem_cod_clfiscal": p["cod_clfiscal"],
                    "alerta_ncm_diferente": bool(p["ncm"] and it.get("ncm") and p["ncm"] != it.get("ncm")),
                })
            else:
                novo["softsystem_status"] = "novo"
            saida.append(novo)
        return {"fornecedor_softsystem": forn, "itens": saida}

    try:
        return await asyncio.to_thread(_rodar)
    except Exception as e:
        logger.error(f"Softsystem indisponível ao vincular itens: {e}")
        return {"fornecedor_softsystem": None, "itens": [{**i, "softsystem_status": "indefinido"} for i in itens],
                "erro_softsystem": str(e)}


def _serializar_item(it: ComprasEntradaItem, ocultar_qtd: bool = False) -> Dict[str, Any]:
    calc = json.loads(it.calculo_json) if it.calculo_json else {}
    d = {
        **calc,
        "id": it.id,
        "numero_item": it.numero_item,
        "codigo_fornecedor": it.codigo_fornecedor,
        "ean": it.ean,
        "descricao_fornecedor": it.descricao_fornecedor,
        "ncm": it.ncm,
        "cfop": it.cfop,
        "unidade": it.unidade,
        "quantidade": it.quantidade,
        "fator_conversao": it.fator_conversao or 1.0,
        "qtd_esperada": round(it.quantidade * (it.fator_conversao or 1.0), 4),
        "qtd_contada": it.qtd_contada,
        "contado_por": it.contado_por,
        "contado_em": it.contado_em.isoformat() if it.contado_em else None,
        "recontagens": it.recontagens or 0,
        "softsystem_prod_codigo": it.softsystem_prod_codigo,
        "softsystem_descricao": it.softsystem_descricao,
        "vinculo_metodo": it.vinculo_metodo,
        "produto_modelo_codigo": it.produto_modelo_codigo,
        "margem_lucro_pct": it.margem_lucro_pct,
        "preco_venda_final": it.preco_venda_final,
        "custo_unitario_real": it.custo_unitario_real,
        "localizacao": it.localizacao_estoque,
        "cadastro_novo": json.loads(it.cadastro_novo_json) if it.cadastro_novo_json else None,
        "estoque_auditado": it.estoque_auditado,
        "auditado_por": it.auditado_por,
        "auditado_em": it.auditado_em.isoformat() if it.auditado_em else None,
    }
    if it.qtd_contada is not None:
        d["divergencia"] = round(it.qtd_contada - d["qtd_esperada"], 4)
    if ocultar_qtd:
        for k in ("quantidade", "qtd_esperada", "divergencia", "valor_total", "valor_unitario",
                  "quantidade_tributavel", "custo_bruto_total", "custo_liquido_total"):
            d.pop(k, None)
    return d


def _serializar_entrada(e: ComprasEntrada, com_itens: bool = True, ocultar_qtd: bool = False) -> Dict[str, Any]:
    d = {
        "id": e.id,
        "empresa": e.empresa,
        "chave_acesso": e.chave_acesso,
        "numero_nf": e.numero_nf,
        "serie": e.serie,
        "data_emissao": e.data_emissao.isoformat() if e.data_emissao else None,
        "fornecedor_cnpj": e.fornecedor_cnpj,
        "fornecedor_nome": e.fornecedor_nome,
        "transportadora_nome": e.transportadora_nome,
        "cte_chave": e.cte_chave,
        "cte_numero": e.cte_numero,
        "valor_frete_cte": e.valor_frete_cte or 0,
        "valor_icms_cte": e.valor_icms_cte or 0,
        "valor_produtos": e.valor_produtos,
        "valor_total_nota": e.valor_total_nota,
        "tipo_rateio_frete": e.tipo_rateio_frete,
        "status": e.status,
        "origem_xml": e.origem_xml,
        "criado_em": e.criado_em.isoformat() if e.criado_em else None,
        "criado_por": e.criado_por,
        "conferente": e.conferente,
        "conferencia_finalizada_em": e.conferencia_finalizada_em.isoformat() if e.conferencia_finalizada_em else None,
        "divergencia_aprovada_por": e.divergencia_aprovada_por,
        "divergencia_justificativa": e.divergencia_justificativa,
        "fechada_em": e.fechada_em.isoformat() if e.fechada_em else None,
        "fechada_por": e.fechada_por,
        "softsystem_codcompra": e.softsystem_codcompra,
        "softsystem_modo": _modo_lancamento(),
        "parcelas": json.loads(e.parcelas_json) if e.parcelas_json else [],
        "parcelas_cte": json.loads(e.parcelas_cte_json) if e.parcelas_cte_json else [],
        "despesas_extras": json.loads(e.despesas_extras_json) if e.despesas_extras_json else [],
    }
    if com_itens:
        d["itens"] = [_serializar_item(i, ocultar_qtd) for i in sorted(e.itens, key=lambda x: x.numero_item)]
        d["eventos"] = [{
            "quando": ev.quando.isoformat(), "usuario": ev.usuario, "acao": ev.acao,
            # Eventos de contagem citam quantidades contadas - escondidos junto durante a contagem cega
            "detalhe": ev.detalhe if not (ocultar_qtd and ev.acao in ("contagem", "recontagem", "importada")) else "(oculto durante a contagem)",
            "item_id": ev.item_id,
        } for ev in sorted(e.eventos, key=lambda x: x.quando)]
        d["quantidades_ocultas"] = ocultar_qtd
    if ocultar_qtd:
        for k in ("valor_produtos", "valor_total_nota"):
            d.pop(k, None)
    return d


async def _carregar_entrada(db: AsyncSession, tenant_id: int, entrada_id: int) -> ComprasEntrada:
    res = await db.execute(
        select(ComprasEntrada)
        .options(selectinload(ComprasEntrada.itens), selectinload(ComprasEntrada.eventos))
        .where(ComprasEntrada.id == entrada_id, ComprasEntrada.tenant_id == tenant_id)
    )
    entrada = res.scalar_one_or_none()
    if not entrada:
        raise HTTPException(status_code=404, detail="Entrada não encontrada")
    return entrada


def _safe_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        val_str = str(val).strip().replace("R$", "").replace(" ", "").replace(",", ".")
        return float(val_str)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 1) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, int):
        return val
    try:
        return int(float(str(val).strip().replace(",", ".")))
    except (ValueError, TypeError):
        return default


def _aplicar_calculo_no_item(item_db: ComprasEntradaItem, calc: Dict[str, Any]):
    item_db.frete_rateado = _safe_float(calc.get("frete_rateado"), 0.0)
    item_db.custo_fixo_rateado = _safe_float(calc.get("custo_fixo_rateado"), 0.0)
    item_db.custo_unitario_real = _safe_float(calc.get("custo_unitario_real"), 0.0)
    item_db.margem_lucro_pct = _safe_float(calc.get("margem_lucro_pct"), 0.0)
    item_db.preco_venda_sugerido = _safe_float(calc.get("preco_venda_sugerido"), 0.0)
    item_db.preco_venda_final = _safe_float(calc.get("preco_venda_final"), 0.0)
    item_db.preco_mercado_min = _safe_float(calc.get("preco_mercado_min"), None)
    item_db.preco_mercado_med = _safe_float(calc.get("preco_mercado_med"), None)
    item_db.preco_mercado_max = _safe_float(calc.get("preco_mercado_max"), None)
    item_db.calculo_json = json.dumps(calc, ensure_ascii=False, default=str)


# ============================================================ 1. Buscar nota pela chave
@router.post("/decodificar-chave")
async def decodificar_chave_endpoint(payload: DecodificarChavePayload, current_user: User = Depends(get_current_user)):
    """Confere o dígito verificador e separa os dados embutidos na chave (UF, CNPJ, número)."""
    try:
        return {"success": True, "data": NfeXmlService.decodificar_chave_acesso(payload.chave_acesso)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/nota/buscar")
async def buscar_nota_por_chave(
    payload: BuscarNotaPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Digitou a chave -> traz a nota completa (pasta do Softsystem ou SEFAZ), vincula os itens
    ao Softsystem, soma o frete do CT-e da transportadora e já calcula custos e vencimentos.
    """
    try:
        chave = NfeXmlService.validar_chave(payload.chave_nfe)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if chave[20:22] != "55":
        raise HTTPException(status_code=400, detail="A chave principal precisa ser de uma NF-e (modelo 55). A do CT-e vai no campo da transportadora.")

    res = await db.execute(select(ComprasEntrada).where(
        ComprasEntrada.tenant_id == current_user.tenant_id,
        ComprasEntrada.chave_acesso == chave,
        ComprasEntrada.status != "cancelada",
    ))
    existente = res.scalar_one_or_none()
    if existente:
        return {"status": "ja_importada", "entrada_id": existente.id, "entrada_status": existente.status,
                "mensagem": f"Esta nota já foi importada (entrada #{existente.id}, {existente.status})."}

    obtido = await _obter_xml(chave, "NFE", payload.empresa)
    if obtido["status"] != "ok":
        return {**{k: v for k, v in obtido.items() if k != "xml"}, "chave": chave,
                "dados_chave": NfeXmlService.decodificar_chave_acesso(chave)}

    try:
        nota = NfeXmlService.parse_xml_content(obtido["xml"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    avisos: List[str] = []
    empresa = nota["empresa_destino"]
    if nota["destinatario"]["cnpj"] not in CNPJ_POR_EMPRESA.values():
        avisos.append(f"O destinatário da nota ({nota['destinatario']['razao_social']}) não é nenhuma das lojas.")

    try:
        ja = await asyncio.to_thread(SoftsystemService.compra_ja_lancada, empresa, chave)
        if ja:
            avisos.append(
                f"ATENÇÃO: esta nota já está lançada no Softsystem (compra {ja['codcompra']}, "
                f"operador {ja['operador']}). Fechar aqui vai duplicar a entrada."
            )
    except Exception as e:
        logger.warning(f"Não deu para checar duplicidade no Softsystem: {e}")

    enr = await _enriquecer_itens(empresa, nota["fornecedor"]["cnpj"], nota["itens"])
    nota["itens"] = enr["itens"]
    nota["fornecedor_softsystem"] = enr.get("fornecedor_softsystem")
    if enr.get("erro_softsystem"):
        avisos.append(f"Softsystem fora do ar - vínculo dos produtos não foi feito ({enr['erro_softsystem']}).")
    elif not enr.get("fornecedor_softsystem"):
        avisos.append("Fornecedor ainda não cadastrado no Softsystem - será cadastrado no fechamento.")

    # CT-e da transportadora
    cte = None
    if payload.chave_cte:
        cte = await _carregar_cte(payload.chave_cte, chave, empresa, avisos)

    if nota["transportadora"].get("modalidade_frete") == "1" and not cte:
        avisos.append("Frete por conta da loja (FOB) na nota: se veio CT-e da transportadora, informe a chave dele para somar o frete ao custo.")

    params = await _parametros_loja(db, current_user.tenant_id, empresa)
    calculo = ComprasCustoService.calcular(
        nota["itens"], nota["totais"], params,
        frete_cte=(cte or {}).get("valor_frete_total", 0.0) if (cte or {}).get("frete_da_loja") else 0.0,
        icms_cte=(cte or {}).get("icms", {}).get("v_icms", 0.0) if (cte or {}).get("frete_da_loja") else 0.0,
    )
    condicao = params.get("condicao_pagamento_padrao") or "30"
    total_nf = float((nota.get("fatura") or {}).get("valor_liquido") or 0) or float(nota["totais"].get("valor_total_nf") or 0)
    venc = ComprasCustoService.parcelas_do_documento(nota, total_nf, condicao)
    _aviso_vencimentos(avisos, "A nota", venc, condicao)

    return {
        "status": "ok",
        "origem": obtido["origem"],
        "empresa": empresa,
        "nota": nota,
        "cte": cte,
        "calculo": calculo,
        "parcelas": venc["parcelas"],
        "parcelas_cte": _parcelas_cte(cte, condicao, avisos),
        "avisos": avisos,
    }


def _aviso_vencimentos(avisos: List[str], quem: str, venc: Dict[str, Any], condicao: str) -> None:
    if venc["origem"] == "sem_cobranca":
        avisos.append(f"{quem} é uma {venc.get('trecho', 'operação sem cobrança')} - nenhum vencimento/conta a pagar gerado.")
    elif venc["origem"] == "dados_adicionais":
        avisos.append(f"{quem} não traz duplicatas - vencimentos lidos dos dados adicionais (\"{(venc['trecho'] or '')[:120]}\"). Confira.")
    elif venc["origem"] == "condicao":
        avisos.append(f"{quem} não traz duplicatas nem vencimento nos dados adicionais - gerados pela condição padrão ({condicao} dias). Confira.")



def _parcelas_cte(cte: Optional[Dict[str, Any]], condicao: str, avisos: List[str]) -> List[Dict[str, Any]]:
    """Contas a pagar da transportadora (só quando a loja é a tomadora do CT-e)."""
    if not cte or not cte.get("carregado") or not cte.get("frete_da_loja"):
        return []
    total = float((cte.get("fatura") or {}).get("valor_liquido") or 0) or float(cte.get("valor_frete_total") or 0)
    if total <= 0:
        return []
    venc = ComprasCustoService.parcelas_do_documento(cte, total, condicao)
    _aviso_vencimentos(avisos, f"O CT-e {cte.get('numero_cte')}", venc, condicao)
    return venc["parcelas"]


async def _carregar_cte(chave_cte_raw: str, chave_nfe: str, empresa: str, avisos: List[str]) -> Optional[Dict[str, Any]]:
    try:
        chave_cte = NfeXmlService.validar_chave(chave_cte_raw)
    except ValueError as e:
        avisos.append(f"Chave do CT-e: {e}")
        return None
    if chave_cte[20:22] != "57":
        avisos.append("A chave da transportadora não é de um CT-e (modelo 57).")
        return None
    obtido = await _obter_xml(chave_cte, "CTE", empresa)
    if obtido["status"] != "ok":
        avisos.append(f"CT-e não carregado: {obtido.get('mensagem')}")
        return {"chave_acesso": chave_cte, "carregado": False, "mensagem": obtido.get("mensagem"),
                "dados_chave": NfeXmlService.decodificar_chave_acesso(chave_cte)}
    try:
        cte = NfeXmlService.parse_xml_content(obtido["xml"])
    except ValueError as e:
        avisos.append(f"CT-e inválido: {e}")
        return None
    cte["carregado"] = True
    cte["origem"] = obtido["origem"]
    if cte.get("chaves_nfe") and chave_nfe not in cte["chaves_nfe"]:
        avisos.append(f"O CT-e {cte['numero_cte']} não cita esta NF-e - confira se é o frete certo.")
    elif len(cte.get("chaves_nfe") or []) > 1:
        avisos.append(f"O CT-e {cte['numero_cte']} transporta {len(cte['chaves_nfe'])} notas - ajuste o valor do frete se ele for dividido entre elas.")
    cte["frete_da_loja"] = cte.get("empresa_tomadora") == empresa
    if not cte["frete_da_loja"]:
        avisos.append("A loja não é a tomadora (pagadora) deste CT-e - o frete não entra no custo.")
    return cte


@router.post("/nota/manifestar-ciencia")
async def manifestar_ciencia(payload: ManifestarPayload, current_user: User = Depends(get_current_user)):
    """Manifestação pedida pelo usuário: Ciência (210210) ou Confirmação da Operação (210200 - quando
    a Ciência já passou do prazo de 10 dias; declara que a mercadoria foi recebida)."""
    empresa = _empresa_valida(payload.empresa)
    tipo = payload.tipo if payload.tipo in ("ciencia", "confirmacao") else "ciencia"
    nome = "Confirmação da Operação" if tipo == "confirmacao" else "Ciência da Operação"
    try:
        chave = NfeXmlService.validar_chave(payload.chave)
        r = await asyncio.to_thread(SefazService.manifestar, chave, empresa, tipo)
    except (ValueError, SefazErro) as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"{nome} {chave} por {_usuario(current_user)}: {r}")
    if not r["sucesso"]:
        if tipo == "ciencia" and r.get("cStat") == "596":
            raise HTTPException(status_code=400, detail=_MSG_PRAZO_CIENCIA)
        raise HTTPException(status_code=400, detail=f"SEFAZ recusou: {r['cStat']} - {r['xMotivo']}")
    return {"success": True, **r, "tipo": tipo,
            "mensagem": f"{nome} registrada. Buscando a nota - se a SEFAZ demorar, o sistema continua tentando sozinho."}


@router.post("/parse-xml")
async def parse_xml_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Plano B: importar o arquivo XML (NF-e ou CT-e) direto."""
    try:
        content = await file.read()
        parsed = NfeXmlService.parse_xml_content(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao processar XML: {str(e)}")

    if parsed["tipo_documento"] == "CTE":
        parsed["carregado"] = True
        parsed["origem"] = "upload"
        empresa_cte = parsed.get("empresa_tomadora")
        parsed["frete_da_loja"] = bool(empresa_cte)
        avisos: List[str] = []
        params = await _parametros_loja(db, current_user.tenant_id, empresa_cte or "servweld")
        return {"status": "ok", "tipo": "CTE", "cte": parsed, "avisos": avisos,
                "parcelas_cte": _parcelas_cte(parsed, params.get("condicao_pagamento_padrao") or "30", avisos)}

    await asyncio.to_thread(NfeXmlService.salvar_xml_cache, parsed["chave_acesso"], content)
    empresa = parsed["empresa_destino"]
    enr = await _enriquecer_itens(empresa, parsed["fornecedor"]["cnpj"], parsed["itens"])
    parsed["itens"] = enr["itens"]
    parsed["fornecedor_softsystem"] = enr.get("fornecedor_softsystem")
    params = await _parametros_loja(db, current_user.tenant_id, empresa)
    return {
        "status": "ok", "tipo": "NFE", "origem": "upload", "empresa": empresa, "nota": parsed, "cte": None,
        "calculo": ComprasCustoService.calcular(parsed["itens"], parsed["totais"], params),
        "parcelas": ComprasCustoService.parcelas_da_nota(parsed, params.get("condicao_pagamento_padrao") or "30"),
        "avisos": [],
    }


@router.post("/calcular")
async def calcular_endpoint(
    payload: CalcularPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recalcula custos/preços ao vivo (troca de margem, rateio, despesa extra, loja)."""
    empresa = _empresa_valida(payload.empresa)
    params = await _parametros_loja(db, current_user.tenant_id, empresa)
    return ComprasCustoService.calcular(
        payload.itens, payload.totais, params, payload.frete_cte, payload.icms_cte,
        payload.despesas_extras, payload.tipo_rateio,
    )


# ============================================================ 2. Softsystem (consulta)
@router.get("/softsystem/buscar-produto")
async def buscar_produto_softsystem(
    empresa: str = Query("servweld"),
    termo: str = Query(...),
    limite: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """Busca produtos no Softsystem por código interno, código original, EAN ou descrição."""
    try:
        produtos = await asyncio.to_thread(SoftsystemService.buscar_produtos, _empresa_valida(empresa), termo, limite)
        return {"success": True, "total": len(produtos), "produtos": produtos}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {str(e)}")


# ============================================================ Acerto de estoque (inventário)
# Pedido do usuário em 15/10/2026 (estoque do Softsystem não bate com o físico). Grava um Ajuste de
# Estoque no Softsystem igual ao da tela dele - ver softsystem_compra_writer.lancar_ajuste. Mesma
# chave de segurança do lançamento de compras (SOFTSYSTEM_COMPRAS_MODO: desligado|teste|producao).
class AcertoItem(BaseModel):
    codproduto: int
    quantidade_fisica: float


class AcertoPayload(BaseModel):
    empresa: str
    motivo: str
    itens: List[AcertoItem]


@router.get("/estoque/produto/{codigo}")
async def estoque_produto(codigo: int, empresa: str = Query("servweld"), current_user: User = Depends(get_current_user)):
    """Produto + estoque atual + localização (Softsystem) para a tela de acerto."""
    emp = _empresa_valida(empresa)
    try:
        prod = await asyncio.to_thread(SoftsystemService.buscar_por_codigo, emp, codigo)
        if not prod:
            raise HTTPException(status_code=404, detail=f"Produto {codigo} não encontrado no Softsystem.")
        loc = (await asyncio.to_thread(SoftsystemService.localizacao_estoque, emp, [codigo])).get(codigo) or {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")
    return {"success": True, "produto": {**prod, "localizacao": loc.get("localizacao")}}


@router.post("/estoque/acerto")
async def gravar_acerto_estoque(payload: AcertoPayload, current_user: User = Depends(get_admin_user)):
    from app.services.softsystem_compra_writer import lancar_ajuste, LancamentoErro
    emp = _empresa_valida(payload.empresa)
    if not payload.motivo or len(payload.motivo.strip()) < 3:
        raise HTTPException(status_code=400, detail="Informe o motivo do acerto (fica gravado no Softsystem).")
    modo = _modo_lancamento()
    if modo == "desligado":
        raise HTTPException(status_code=400, detail="A gravação no Softsystem ainda não foi liberada neste servidor.")
    db_teste = settings.SOFTSYSTEM_COMPRAS_DB_TESTE if modo == "teste" else None
    try:
        r = await asyncio.to_thread(
            lancar_ajuste, emp, [i.dict() for i in payload.itens], _operador_softsystem(current_user), payload.motivo.strip(), db_teste,
        )
    except LancamentoErro as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[SOFTSYSTEM] Falha no acerto de estoque ({emp}): {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Erro ao gravar no Softsystem - nada foi gravado. ({e})")
    logger.info(f"Acerto de estoque {r.get('codajuste')} ({emp}) por {_usuario(current_user)}: {payload.motivo}")
    if modo == "teste" and r.get("codajuste"):
        r["mensagem"] = f"TESTE: ajuste {r['codajuste']} gravado na cópia de teste (o Softsystem de verdade não mudou)."
    return {"success": True, "modo": modo, **r}


@router.get("/estoque/acertos")
async def listar_acertos_estoque(empresa: str = Query("servweld"), current_user: User = Depends(get_current_user)):
    """Últimos ajustes de estoque do Softsystem (feitos aqui ou lá) - histórico da tela."""
    emp = _empresa_valida(empresa)
    from app.services.softsystem_service import LOJA_POR_EMPRESA
    try:
        rows = await asyncio.to_thread(SoftsystemService._consultar, emp, """
            SELECT FIRST 15 CODAJUSTE, DATA, OPERADOR, NUMITEMSENT, NUMITEMSSAIDA, VALORENTRADA, VALORSAIDA, OBS, FECHADO
            FROM AJUSTEESTOQUE WHERE LOJA = ? ORDER BY CODAJUSTE DESC""", (LOJA_POR_EMPRESA[emp],))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")
    return {"success": True, "modo": _modo_lancamento(), "acertos": [{
        "codajuste": r[0], "data": r[1].isoformat() if r[1] else None, "operador": (r[2] or "").strip(),
        "pecas_entrada": float(r[3] or 0), "pecas_saida": float(r[4] or 0),
        "valor_entrada": float(r[5] or 0), "valor_saida": float(r[6] or 0),
        "obs": (r[7] or "").strip(), "fechado": (r[8] or "") == "T",
    } for r in rows]}


@router.get("/softsystem/similares")
async def similares_softsystem(
    empresa: str = Query("servweld"),
    descricao: str = Query(...),
    ncm: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """Produtos parecidos para copiar o cadastro (grupo, NCM, tributação) de um item novo."""
    try:
        produtos = await asyncio.to_thread(SoftsystemService.buscar_similares, _empresa_valida(empresa), descricao, ncm)
        return {"success": True, "produtos": produtos}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {str(e)}")


@router.get("/softsystem/tributacao")
async def tributacao_softsystem(
    empresa: str = Query("servweld"),
    cod_clfiscal: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    try:
        regras = await asyncio.to_thread(SoftsystemService.tributacao_produto, _empresa_valida(empresa), cod_clfiscal)
        return {"success": True, "regras": regras}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {str(e)}")


# ------------------------------------------------- etapa 2: cadastro inteligente de produto novo
@router.get("/softsystem/arvore-cadastro")
async def arvore_cadastro(empresa: str = Query("servweld"), current_user: User = Depends(get_current_user)):
    """Grupos > subgrupos N1 > N2 > N3 e marcas, para os seletores do cadastro."""
    from app.services import cadastro_produto_service as cps
    try:
        return {"success": True, **(await asyncio.to_thread(cps.arvore, _empresa_valida(empresa)))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")


class SugerirCadastroPayload(BaseModel):
    modelo_codigo: Optional[int] = None


class CadastroNovoPayload(BaseModel):
    modelo_codigo: int
    descricao: str
    codgrupo: Optional[int] = None
    codsubgrupo: Optional[int] = None
    codsubgruponivel2: Optional[int] = None
    codsubgruponivel3: Optional[int] = None
    codmarca: Optional[int] = None
    marca_nova: Optional[str] = None
    unidade: str = "UN"
    ncm: Optional[str] = None
    cest: Optional[str] = None
    ean: Optional[str] = None
    referencia: Optional[str] = None
    peso: Optional[float] = None


async def _item_editavel(db: AsyncSession, current_user: User, entrada_id: int, item_id: int):
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status in ("enviada_softsystem", "cancelada"):
        raise HTTPException(status_code=400, detail="Entrada já lançada/cancelada - o cadastro não pode mais mudar por aqui.")
    item = next((i for i in entrada.itens if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    if item.softsystem_prod_codigo:
        raise HTTPException(status_code=400, detail="Este item já está vinculado a um produto existente da loja.")
    return entrada, item


@router.post("/entradas/{entrada_id}/itens/{item_id}/sugerir-cadastro")
async def sugerir_cadastro_item(entrada_id: int, item_id: int, payload: SugerirCadastroPayload,
                                db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """IA sugere o cadastro do produto novo no padrão da casa (a pessoa confere e confirma)."""
    from app.services import cadastro_produto_service as cps
    entrada, item = await _item_editavel(db, current_user, entrada_id, item_id)
    modelo = payload.modelo_codigo or (int(item.produto_modelo_codigo) if (item.produto_modelo_codigo or "").isdigit() else None)
    nota = json.loads(entrada.nota_json or "{}")
    item_nota = next((i for i in nota.get("itens") or [] if i.get("numero_item") == item.numero_item), {}) if nota.get("itens") else {}
    dados = {"descricao_fornecedor": item.descricao_fornecedor, "codigo_fornecedor": item.codigo_fornecedor, "ean": item.ean,
             "ncm": item.ncm, "unidade": item.unidade, "cest": item_nota.get("cest"), "info_adicional": item_nota.get("info_adicional")}
    decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
    try:
        sug = await cps.sugerir(entrada.empresa, dados, modelo, entrada.fornecedor_nome,
                                decrypted.get("gemini_api_key") or settings.GEMINI_API_KEY)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")
    if modelo and str(modelo) != (item.produto_modelo_codigo or ""):
        item.produto_modelo_codigo = str(modelo)
        await db.commit()
    return {"success": True, "sugestao": {**sug, "modelo_codigo": modelo}}


@router.put("/entradas/{entrada_id}/itens/{item_id}/cadastro-novo")
async def confirmar_cadastro_item(entrada_id: int, item_id: int, payload: CadastroNovoPayload,
                                  db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """A pessoa confirma o cadastro - o produto é criado no Softsystem quando a nota for lançada."""
    from app.services import cadastro_produto_service as cps
    entrada, item = await _item_editavel(db, current_user, entrada_id, item_id)
    try:
        arv = await asyncio.to_thread(cps.arvore, entrada.empresa)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")
    cad = payload.dict()
    cad["descricao"] = cps.normalizar_descricao(cad["descricao"])
    cad["marca_nova"] = cps.normalizar_descricao(cad.get("marca_nova") or "")[:40] or None
    erros = cps.validar_cadastro(arv, cad)
    if erros:
        raise HTTPException(status_code=400, detail=" ".join(erros))
    cad.update(cps.classificacao_valida(arv, cad))
    cad.update({"confirmado": True, "confirmado_por": _usuario(current_user), "confirmado_em": datetime.utcnow().isoformat()})
    item.cadastro_novo_json = json.dumps(cad, ensure_ascii=False)
    item.produto_modelo_codigo = str(payload.modelo_codigo)
    item.softsystem_descricao = cad["descricao"][:255]
    _registrar_evento(db, entrada.id, _usuario(current_user), "cadastro_confirmado",
                      f"Item {item.numero_item}: produto novo \"{cad['descricao']}\" ({cps.caminho(arv, cad['codgrupo'], cad['codsubgrupo'], cad['codsubgruponivel2'], cad['codsubgruponivel3'])}), "
                      f"copiando o cadastro do {payload.modelo_codigo}.", item.id)
    await db.commit()
    return {"success": True, "cadastro": cad}


@router.get("/softsystem/grupos")
async def listar_grupos_softsystem(empresa: str = Query("servweld"), current_user: User = Depends(get_current_user)):
    grupos = await asyncio.to_thread(SoftsystemService.listar_grupos, _empresa_valida(empresa))
    return {"success": True, "grupos": grupos}


# ============================================================ 3. Preço de mercado (concorrentes)
@router.post("/buscar-preco-mercado")
async def buscar_preco_mercado_endpoint(
    payload: BuscarPrecoMercadoPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
    res = await MarketPriceService.pesquisar_preco_mercado(
        descricao=payload.descricao, ean=payload.ean, ncm=payload.ncm, api_key=decrypted.get("gemini_api_key"),
    )
    return {"success": True, "benchmark": res}


# ============================================================ 4. Parâmetros e custos fixos
@router.get("/parametros-custo")
async def get_parametros_custo(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    params = {e: await _parametros_loja(db, current_user.tenant_id, e) for e in EMPRESAS}
    return {"success": True, "parametros": params, "padroes": PADROES_LOJA}


@router.post("/parametros-custo")
async def salvar_parametros_custo(
    payload: ParametrosCustoPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    empresa = _empresa_valida(payload.empresa)
    res = await db.execute(select(LojaParametrosCusto).where(
        LojaParametrosCusto.tenant_id == current_user.tenant_id, LojaParametrosCusto.empresa == empresa
    ))
    item = res.scalar_one_or_none()
    if not item:
        padrao = PADROES_LOJA[empresa]
        item = LojaParametrosCusto(
            tenant_id=current_user.tenant_id, empresa=empresa, regime_tributario=padrao["regime_tributario"],
        )
        db.add(item)
    for campo in CAMPOS_PARAMETROS:
        valor = getattr(payload, campo)
        if valor is not None:
            setattr(item, campo, valor)
    item.atualizado_por = _usuario(current_user)
    item.atualizado_em = datetime.utcnow()
    await db.commit()
    return {"success": True, "parametros": await _parametros_loja(db, current_user.tenant_id, empresa)}


@router.get("/custos-fixos")
async def listar_custos_fixos(
    empresa: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    empresa = _empresa_valida(empresa)
    res = await db.execute(select(LojaCustoFixo).where(
        LojaCustoFixo.tenant_id == current_user.tenant_id, LojaCustoFixo.empresa == empresa
    ).order_by(LojaCustoFixo.categoria, LojaCustoFixo.descricao))
    custos = res.scalars().all()
    return {"success": True, "custos": [{
        "id": c.id, "empresa": c.empresa, "categoria": c.categoria, "descricao": c.descricao,
        "valor_mensal": c.valor_mensal, "ativo": c.ativo, "atualizado_por": c.atualizado_por,
        "atualizado_em": c.atualizado_em.isoformat() if c.atualizado_em else None,
    } for c in custos]}


@router.post("/custos-fixos")
async def salvar_custo_fixo(
    payload: CustoFixoPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    empresa = _empresa_valida(payload.empresa)
    if payload.id:
        res = await db.execute(select(LojaCustoFixo).where(
            LojaCustoFixo.id == payload.id, LojaCustoFixo.tenant_id == current_user.tenant_id
        ))
        custo = res.scalar_one_or_none()
        if not custo:
            raise HTTPException(status_code=404, detail="Custo fixo não encontrado")
    else:
        custo = LojaCustoFixo(tenant_id=current_user.tenant_id)
        db.add(custo)
    custo.empresa = empresa
    custo.categoria = payload.categoria.strip()
    custo.descricao = payload.descricao.strip()
    custo.valor_mensal = max(payload.valor_mensal, 0.0)
    custo.ativo = payload.ativo
    custo.atualizado_por = _usuario(current_user)
    custo.atualizado_em = datetime.utcnow()
    await db.commit()
    return {"success": True, "id": custo.id}


@router.delete("/custos-fixos/{custo_id}")
async def excluir_custo_fixo(custo_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_admin_user)):
    res = await db.execute(select(LojaCustoFixo).where(
        LojaCustoFixo.id == custo_id, LojaCustoFixo.tenant_id == current_user.tenant_id
    ))
    custo = res.scalar_one_or_none()
    if not custo:
        raise HTTPException(status_code=404, detail="Custo fixo não encontrado")
    await db.delete(custo)
    await db.commit()
    return {"success": True}


@router.get("/certificados")
async def listar_certificados(current_user: User = Depends(get_current_user)):
    """Situação do certificado A1 de cada loja (titular, CNPJ, validade) - nunca a senha."""
    return {"success": True, "certificados": {e: await asyncio.to_thread(SefazService.info_certificado, e) for e in EMPRESAS}}


@router.post("/certificados")
async def enviar_certificado(
    empresa: str = Form(...),
    senha: str = Form(...),
    arquivo: UploadFile = File(...),
    current_user: User = Depends(get_admin_user),
):
    """Recebe o .pfx da loja pela tela: confere senha, validade e CNPJ antes de guardar."""
    empresa = _empresa_valida(empresa)
    conteudo = await arquivo.read()
    if len(conteudo) > 50_000:
        raise HTTPException(status_code=400, detail="Arquivo grande demais para ser um certificado .pfx.")
    try:
        dados = await asyncio.to_thread(SefazService.salvar_certificado, empresa, conteudo, senha)
    except SefazErro as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"Certificado da {empresa} enviado por {_usuario(current_user)}")
    return {"success": True, "certificado": {"configurado": True, **dados}}


# ============================================================ 5. Entradas: criar, contar, precificar, fechar
@router.post("/entradas")
async def criar_entrada(
    payload: CriarEntradaPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Salva a nota importada e libera para a contagem física (cega)."""
    try:
        empresa = _empresa_valida(payload.empresa)
        nota = payload.nota
        chave = nota.get("chave_acesso") or ""
        # Se já existe entrada para essa chave:
        # Se for 'cancelada', remove para permitir reimportação limpa sem violar a restrição UNIQUE.
        # Se for qualquer outro status, informa que já está importada.
        res_antiga = await db.execute(select(ComprasEntrada).where(
            ComprasEntrada.tenant_id == current_user.tenant_id,
            ComprasEntrada.chave_acesso == chave,
        ))
        existente = res_antiga.scalar_one_or_none()
        if existente:
            if existente.status == "cancelada":
                await db.delete(existente)
                await db.flush()
            else:
                raise HTTPException(status_code=409, detail=f"Esta nota já foi importada (entrada #{existente.id}, status: {existente.status}).")

        cte = payload.cte or {}
        frete_cte = _safe_float(cte.get("valor_frete_total"), 0.0) if cte.get("frete_da_loja") else 0.0
        data_emissao = None
        try:
            data_emissao = datetime.fromisoformat((nota.get("data_emissao") or "")[:19])
        except (ValueError, TypeError):
            pass
        totais = nota.get("totais") or {}

        entrada = ComprasEntrada(
            tenant_id=current_user.tenant_id,
            empresa=empresa,
            chave_acesso=chave,
            numero_nf=str(nota.get("numero_nf") or ""),
            serie=str(nota.get("serie") or "") if nota.get("serie") is not None else None,
            data_emissao=data_emissao,
            fornecedor_cnpj=(nota.get("fornecedor") or {}).get("cnpj", ""),
            fornecedor_nome=(nota.get("fornecedor") or {}).get("razao_social", ""),
            transportadora_cnpj=(cte.get("transportadora") or {}).get("cnpj") or (nota.get("transportadora") or {}).get("cnpj"),
            transportadora_nome=(cte.get("transportadora") or {}).get("razao_social") or (nota.get("transportadora") or {}).get("razao_social"),
            valor_produtos=_safe_float(totais.get("valor_produtos"), 0.0),
            valor_frete_nota=_safe_float(totais.get("valor_frete"), 0.0),
            valor_frete_extra_transportadora=_safe_float(frete_cte, 0.0),
            tipo_rateio_frete=payload.tipo_rateio or "valor",
            valor_despesas_acessorias=_safe_float(totais.get("valor_outras_despesas"), 0.0) + _safe_float(totais.get("valor_seguro"), 0.0),
            valor_total_nota=_safe_float(totais.get("valor_total_nf"), 0.0),
            status="aguardando_contagem",
            criado_em=datetime.utcnow(),
            criado_por=_usuario(current_user),
            origem_xml=payload.origem_xml,
            nota_json=json.dumps(nota, ensure_ascii=False, default=str),
            cte_chave=cte.get("chave_acesso") if cte.get("carregado") else None,
            cte_numero=cte.get("numero_cte"),
            valor_frete_cte=_safe_float(frete_cte, 0.0),
            valor_icms_cte=_safe_float((cte.get("icms") or {}).get("v_icms"), 0.0) if cte.get("frete_da_loja") else 0.0,
            despesas_extras_json=json.dumps(payload.despesas_extras or [], ensure_ascii=False),
            parcelas_json=json.dumps(payload.parcelas or [], ensure_ascii=False),
            parcelas_cte_json=json.dumps(payload.parcelas_cte or [], ensure_ascii=False),
            cte_json=json.dumps(cte, ensure_ascii=False, default=str) if cte.get("carregado") else None,
        )
        db.add(entrada)
        await db.flush()

        for it in payload.itens:
            mod_cod = it.get("produto_modelo_codigo")
            if mod_cod is not None:
                mod_cod = str(mod_cod)
            soft_cod = it.get("softsystem_prod_codigo")
            if soft_cod is not None:
                soft_cod = str(soft_cod)

            item_db = ComprasEntradaItem(
                entrada_id=entrada.id,
                numero_item=_safe_int(it.get("numero_item"), 1),
                codigo_fornecedor=str(it.get("codigo_fornecedor") or ""),
                ean=str(it.get("ean")) if it.get("ean") else None,
                descricao_fornecedor=str(it.get("descricao_fornecedor") or ""),
                ncm=str(it.get("ncm")) if it.get("ncm") else None,
                cfop=str(it.get("cfop")) if it.get("cfop") else None,
                unidade=str(it.get("unidade") or "UN"),
                quantidade=_safe_float(it.get("quantidade"), 1.0),
                valor_unitario=_safe_float(it.get("valor_unitario"), 0.0),
                valor_total=_safe_float(it.get("valor_total"), 0.0),
                v_ipi=_safe_float(it.get("v_ipi"), 0.0),
                v_icms=_safe_float(it.get("v_icms"), 0.0),
                v_icms_st=_safe_float(it.get("v_icms_st"), 0.0),
                v_pis=_safe_float(it.get("v_pis"), 0.0),
                v_cofins=_safe_float(it.get("v_cofins"), 0.0),
                softsystem_prod_codigo=soft_cod,
                softsystem_descricao=it.get("softsystem_descricao"),
                softsystem_grupo=it.get("softsystem_grupo"),
                softsystem_subgrupo=it.get("softsystem_subgrupo"),
                fator_conversao=_safe_float(it.get("fator_conversao"), 1.0),
                vinculo_metodo=it.get("vinculo_metodo"),
                produto_modelo_codigo=mod_cod,
                cadastro_novo_json=json.dumps(it.get("cadastro_novo"), ensure_ascii=False) if it.get("cadastro_novo") else None,
                recontagens=0,
            )
            _aplicar_calculo_no_item(item_db, it)
            db.add(item_db)

        _registrar_evento(db, entrada.id, _usuario(current_user), "importada",
                          f"NF-e {entrada.numero_nf} de {entrada.fornecedor_nome} importada ({payload.origem_xml or 'manual'}), "
                          f"{len(payload.itens)} itens, total R$ {entrada.valor_total_nota:.2f}. Aguardando contagem física.")
        await db.commit()

        # já cria a pasta ANO/MÊS/FORNECEDOR/N.F da via da nota (em segundo plano, não atrasa a tela)
        asyncio.create_task(_preparar_pasta_bg(entrada.id, entrada.empresa, entrada.chave_acesso, entrada.numero_nf,
                                               nota.get("fornecedor") or {"razao_social": entrada.fornecedor_nome}))
        return {"success": True, "entrada_id": entrada.id}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[CRIAR_ENTRADA] Erro inesperado ao criar entrada: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao salvar entrada: {e}")



async def _preparar_pasta_bg(entrada_id: int, empresa: str, chave: str, numero_nf: str, fornecedor: Dict[str, Any]):
    from app.core.database import AsyncSessionLocal
    from app.services.nota_arquivo_service import preparar_pasta
    try:
        rel = await asyncio.to_thread(preparar_pasta, empresa, chave, numero_nf, fornecedor)
    except Exception as e:
        logger.warning(f"[ARQUIVO] Pasta da entrada #{entrada_id} não criada na importação (cria no lançamento): {e}")
        return
    if not rel:
        return
    async with AsyncSessionLocal() as s:
        e = await s.get(ComprasEntrada, entrada_id)
        if e:
            e.pasta_notas = rel
            await s.commit()


@router.get("/entradas")
async def listar_entradas(
    empresa: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(ComprasEntrada).where(ComprasEntrada.tenant_id == current_user.tenant_id)
    if empresa and empresa != "todas":
        stmt = stmt.where(ComprasEntrada.empresa == empresa)
    if status and status != "todos":
        stmt = stmt.where(ComprasEntrada.status.in_(status.split(",")))
    res = await db.execute(stmt.order_by(desc(ComprasEntrada.criado_em)).limit(200))
    return {"success": True, "entradas": [_serializar_entrada(e, com_itens=False) for e in res.scalars().all()]}


@router.get("/entradas/{entrada_id}")
async def detalhe_entrada(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    # Contagem cega de verdade: enquanto a mercadoria não foi contada, só administrador vê as
    # quantidades da nota (senão o conferente abre o detalhe e copia o número).
    ocultar = entrada.status in ("aguardando_contagem", "contagem_divergente") and current_user.role != UserRole.ADMIN
    return {"success": True, "entrada": _serializar_entrada(entrada, ocultar_qtd=ocultar)}


@router.get("/entradas/{entrada_id}/contagem")
async def tela_contagem(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Lista para a contagem CEGA: o conferente vê o produto, mas nunca a quantidade da nota.
    Depois de uma contagem divergente, marca quais itens precisam ser recontados (ainda sem
    mostrar o número esperado).
    """
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status not in ("aguardando_contagem", "contagem_divergente"):
        raise HTTPException(status_code=400, detail=f"Esta entrada não está em contagem (status: {entrada.status}).")
    # Onde fica cada produto na loja + estoque atual (Softsystem) - ajuda a guardar a mercadoria.
    # Softsystem fora do ar não pode travar a contagem: só não mostra.
    locais: Dict[int, Dict[str, Any]] = {}
    codigos = [it.softsystem_prod_codigo for it in entrada.itens if it.softsystem_prod_codigo]
    if codigos:
        try:
            locais = await asyncio.to_thread(SoftsystemService.localizacao_estoque, entrada.empresa, codigos)
        except Exception as e:
            logger.warning(f"Localização/estoque do Softsystem indisponível na contagem #{entrada.id}: {e}")
    itens = []
    for it in sorted(entrada.itens, key=lambda x: x.numero_item):
        esperado = it.quantidade * (it.fator_conversao or 1.0)
        divergente = it.qtd_contada is not None and abs(it.qtd_contada - esperado) > TOLERANCIA_CONTAGEM
        cod = str(it.softsystem_prod_codigo or "").strip()
        loc = locais.get(int(cod)) if cod.isdigit() else None
        calc = json.loads(it.calculo_json) if it.calculo_json else {}
        itens.append({
            "item_id": it.id,
            "numero_item": it.numero_item,
            "descricao": it.softsystem_descricao or it.descricao_fornecedor,
            "descricao_fornecedor": it.descricao_fornecedor,
            "codigo_loja": it.softsystem_prod_codigo,
            "codigo_fornecedor": it.codigo_fornecedor,
            "ean": it.ean,
            "unidade_contagem": calc.get("softsystem_unidade") or (it.unidade if (it.fator_conversao or 1) == 1 else "UN"),
            "ja_contado": it.qtd_contada is not None,
            "recontar": entrada.status == "contagem_divergente" and divergente,
            "recontagens": it.recontagens or 0,
            "localizacao": (loc or {}).get("localizacao"),
            "estoque_atual": (loc or {}).get("estoque"),
        })
    return {"success": True, "entrada": {
        "id": entrada.id, "numero_nf": entrada.numero_nf, "fornecedor_nome": entrada.fornecedor_nome,
        "status": entrada.status, "empresa": entrada.empresa,
    }, "itens": itens}


@router.post("/entradas/{entrada_id}/contagem")
async def registrar_contagem(
    entrada_id: int,
    payload: ContagemPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status not in ("aguardando_contagem", "contagem_divergente"):
        raise HTTPException(status_code=400, detail="Esta entrada não está em contagem.")
    usuario = _usuario(current_user)
    agora = datetime.utcnow()
    por_id = {i.id: i for i in entrada.itens}
    if not entrada.conferencia_iniciada_em:
        entrada.conferencia_iniciada_em = agora
        _registrar_evento(db, entrada.id, usuario, "contagem_iniciada", "Conferência física iniciada.")
    for c in payload.itens:
        it = por_id.get(c.item_id)
        if not it:
            raise HTTPException(status_code=400, detail=f"Item {c.item_id} não pertence a esta entrada.")
        if c.qtd_contada < 0:
            raise HTTPException(status_code=400, detail="Quantidade contada não pode ser negativa.")
        anterior = it.qtd_contada
        if anterior is not None and abs(anterior - c.qtd_contada) <= TOLERANCIA_CONTAGEM:
            continue
        if anterior is not None:
            it.recontagens = (it.recontagens or 0) + 1
        it.qtd_contada = c.qtd_contada
        it.contado_por = usuario
        it.contado_em = agora
        _registrar_evento(
            db, entrada.id, usuario, "recontagem" if anterior is not None else "contagem",
            f"Item {it.numero_item} ({it.softsystem_descricao or it.descricao_fornecedor}): contado {c.qtd_contada:g}"
            + (f" (antes {anterior:g})" if anterior is not None else ""),
            item_id=it.id,
        )
    entrada.conferente = usuario
    await db.commit()
    return {"success": True}


@router.post("/entradas/{entrada_id}/contagem/finalizar")
async def finalizar_contagem(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Compara contado x nota. Bateu -> 'contada'. Não bateu -> 'contagem_divergente': a tela pede
    recontagem dos itens marcados (sem revelar o número da nota); se persistir, só um
    administrador libera, com justificativa.
    """
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status not in ("aguardando_contagem", "contagem_divergente"):
        raise HTTPException(status_code=400, detail="Esta entrada não está em contagem.")
    faltando = [i.numero_item for i in entrada.itens if i.qtd_contada is None]
    if faltando:
        raise HTTPException(status_code=400, detail=f"Ainda faltam contar os itens: {', '.join(map(str, sorted(faltando)))}.")

    divergentes = []
    for it in entrada.itens:
        esperado = it.quantidade * (it.fator_conversao or 1.0)
        if abs(it.qtd_contada - esperado) > TOLERANCIA_CONTAGEM:
            divergentes.append(it)

    usuario = _usuario(current_user)
    entrada.conferencia_finalizada_em = datetime.utcnow()
    if not divergentes:
        entrada.status = "contada"
        _registrar_evento(db, entrada.id, usuario, "contagem_ok", "Contagem bateu 100% com a nota.")
        await db.commit()
        return {"success": True, "status": "contada", "divergentes": []}

    ja_recontados = all((i.recontagens or 0) > 0 for i in divergentes)
    entrada.status = "contagem_divergente"
    _registrar_evento(
        db, entrada.id, usuario, "contagem_divergente",
        f"{len(divergentes)} item(ns) não bateram com a nota: "
        + ", ".join(f"#{i.numero_item}" for i in sorted(divergentes, key=lambda x: x.numero_item))
        + (" (após recontagem - aguarda aprovação do gestor)" if ja_recontados else " - recontagem solicitada"),
    )
    await db.commit()
    return {
        "success": True,
        "status": "contagem_divergente",
        "precisa_aprovacao": ja_recontados,
        "divergentes": [i.id for i in divergentes],
        "mensagem": (
            "A contagem continua diferente da nota depois da recontagem. Um administrador precisa aprovar com justificativa."
            if ja_recontados else
            "Alguns itens não bateram com a nota. Reconte os itens marcados."
        ),
    }


@router.post("/entradas/{entrada_id}/aprovar-divergencia")
async def aprovar_divergencia(
    entrada_id: int,
    payload: AprovarDivergenciaPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    """Gestor aceita a diferença. O estoque entra pela quantidade CONTADA, nunca pela da nota."""
    if len(payload.justificativa.strip()) < 10:
        raise HTTPException(status_code=400, detail="Descreva a justificativa (mínimo 10 caracteres).")
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status != "contagem_divergente":
        raise HTTPException(status_code=400, detail="Não há divergência pendente nesta entrada.")
    linhas = []
    for it in sorted(entrada.itens, key=lambda x: x.numero_item):
        esperado = it.quantidade * (it.fator_conversao or 1.0)
        dif = (it.qtd_contada or 0) - esperado
        if abs(dif) > TOLERANCIA_CONTAGEM:
            linhas.append(f"#{it.numero_item} {it.softsystem_descricao or it.descricao_fornecedor}: nota {esperado:g}, contado {it.qtd_contada:g} ({'falta' if dif < 0 else 'sobra'} {abs(dif):g})")
    entrada.status = "contada"
    entrada.divergencia_aprovada_por = _usuario(current_user)
    entrada.divergencia_justificativa = payload.justificativa.strip()
    _registrar_evento(db, entrada.id, _usuario(current_user), "divergencia_aprovada",
                      f"Justificativa: {payload.justificativa.strip()}\n" + "\n".join(linhas))
    await db.commit()
    return {"success": True, "status": "contada", "divergencias": linhas}


@router.put("/entradas/{entrada_id}/precificacao")
async def salvar_precificacao(
    entrada_id: int,
    payload: PrecificacaoPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Grava margem/preço escolhidos, vínculos e vencimentos - recalcula tudo no servidor."""
    try:
        entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
        if entrada.status in ("fechada", "enviada_softsystem", "cancelada"):
            raise HTTPException(status_code=400, detail=f"Entrada {entrada.status} não pode mais ser alterada.")

        editaveis = ("margem_lucro_pct", "preco_venda_final", "softsystem_prod_codigo", "softsystem_descricao",
                     "softsystem_grupo", "softsystem_subgrupo", "vinculo_metodo", "produto_modelo_codigo",
                     "preco_mercado_min", "preco_mercado_med", "preco_mercado_max", "preco_mercado_resumo",
                     "concorrentes", "softsystem_status", "fator_conversao")
        por_id = {i.id: i for i in entrada.itens}
        mudancas = {int(p["item_id"]): p for p in payload.itens if p.get("item_id") is not None}
        if payload.despesas_extras is not None:
            entrada.despesas_extras_json = json.dumps(payload.despesas_extras, ensure_ascii=False)
        if payload.tipo_rateio:
            entrada.tipo_rateio_frete = payload.tipo_rateio

        itens_calc = []
        for it in sorted(entrada.itens, key=lambda x: x.numero_item):
            base = json.loads(it.calculo_json) if it.calculo_json else {}
            m = mudancas.get(it.id, {})
            for k in editaveis:
                if k in m:
                    base[k] = m[k]
            if "fator_conversao" in m and entrada.status in ("aguardando_contagem", "contagem_divergente"):
                it.fator_conversao = _safe_float(m["fator_conversao"], 1.0) or 1.0
            base["item_id"] = it.id
            itens_calc.append(base)

        nota = json.loads(entrada.nota_json) if entrada.nota_json else {"totais": {}}
        params = await _parametros_loja(db, current_user.tenant_id, entrada.empresa)
        calc = ComprasCustoService.calcular(
            itens_calc, nota.get("totais") or {}, params, entrada.valor_frete_cte or 0.0, entrada.valor_icms_cte or 0.0,
            json.loads(entrada.despesas_extras_json or "[]"), entrada.tipo_rateio_frete or "valor",
        )
        for c in calc["itens"]:
            it = por_id[c["item_id"]]
            it.softsystem_prod_codigo = str(c.get("softsystem_prod_codigo")) if c.get("softsystem_prod_codigo") is not None else None
            it.softsystem_descricao = c.get("softsystem_descricao")
            it.softsystem_grupo = c.get("softsystem_grupo")
            it.softsystem_subgrupo = c.get("softsystem_subgrupo")
            it.vinculo_metodo = c.get("vinculo_metodo")
            it.produto_modelo_codigo = str(c.get("produto_modelo_codigo")) if c.get("produto_modelo_codigo") is not None else None
            _aplicar_calculo_no_item(it, c)

        if payload.parcelas is not None:
            entrada.parcelas_json = json.dumps(payload.parcelas, ensure_ascii=False)
        if payload.parcelas_cte is not None:
            entrada.parcelas_cte_json = json.dumps(payload.parcelas_cte, ensure_ascii=False)
        _registrar_evento(db, entrada.id, _usuario(current_user), "precificacao", "Preços/margens/vencimentos atualizados.")
        await db.commit()
        return {"success": True, "calculo": calc}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[SALVAR_PRECIFICACAO] Erro na precificação da entrada #{entrada_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao salvar precificação: {e}")


# --------------------------------------------------------------------------- lançamento no Softsystem
# Pedido do usuário em 14/10/2026 ("preciso que o lançamento vá para lá... atualizar tudo"). Ver
# app/services/softsystem_compra_writer.py. Chave de segurança no .env do servidor:
#   SOFTSYSTEM_COMPRAS_MODO = desligado (padrão) | teste | producao
#   SOFTSYSTEM_COMPRAS_DB_TESTE = caminho da cópia de teste (modo teste grava SÓ nela)
def _modo_lancamento() -> str:
    modo = (settings.SOFTSYSTEM_COMPRAS_MODO or "desligado").strip().lower()
    return modo if modo in ("desligado", "teste", "producao") else "desligado"


def _operador_softsystem(u: User) -> str:
    # o Softsystem usa o primeiro nome em maiúsculas como operador (ex.: EDUARDO, FERNANDO)
    return ((u.nome or "OMINICHANNEL").strip().split() or ["OMINICHANNEL"])[0].upper()


async def _lancar_no_softsystem(db: AsyncSession, entrada: ComprasEntrada, current_user: User) -> Dict[str, Any]:
    from app.services.softsystem_compra_writer import montar_plano, lancar_compra, LancamentoErro

    modo = _modo_lancamento()
    if modo == "desligado":
        return {"lancado": False, "modo": modo,
                "mensagem": "O lançamento automático no Softsystem ainda não foi liberado neste servidor."}
    db_teste = settings.SOFTSYSTEM_COMPRAS_DB_TESTE if modo == "teste" else None
    if modo == "teste" and not db_teste:
        return {"lancado": False, "modo": modo, "mensagem": "Modo teste sem a cópia do banco configurada (SOFTSYSTEM_COMPRAS_DB_TESTE)."}

    entrada_d = {
        "id": entrada.id, "chave_acesso": entrada.chave_acesso, "numero_nf": entrada.numero_nf, "serie": entrada.serie,
        "data_emissao": entrada.data_emissao.isoformat() if entrada.data_emissao else None,
        "fornecedor_cnpj": entrada.fornecedor_cnpj, "fornecedor_nome": entrada.fornecedor_nome,
        "valor_total_nota": entrada.valor_total_nota, "nota": json.loads(entrada.nota_json or "{}"),
        "valor_frete_cte": entrada.valor_frete_cte or 0.0,
        # entradas antigas não guardavam o CT-e inteiro - monta o mínimo com o que tem
        "cte": json.loads(entrada.cte_json) if entrada.cte_json else ({
            "chave_acesso": entrada.cte_chave, "numero_cte": entrada.cte_numero,
            "transportadora": {"cnpj": entrada.transportadora_cnpj, "razao_social": entrada.transportadora_nome},
        } if (entrada.valor_frete_cte or 0) > 0 else None),
    }
    itens_d = []
    for it in entrada.itens:
        d = {c: getattr(it, c) for c in (
            "numero_item", "softsystem_prod_codigo", "codigo_fornecedor", "descricao_fornecedor", "quantidade",
            "fator_conversao", "qtd_contada", "valor_total", "preco_venda_final", "ncm", "cfop", "v_ipi", "v_icms_st",
            "id", "produto_modelo_codigo")}
        d["calculo"] = json.loads(it.calculo_json) if it.calculo_json else {}
        d["cadastro_novo"] = json.loads(it.cadastro_novo_json) if it.cadastro_novo_json else None
        itens_d.append(d)
    plano = montar_plano(entrada_d, itens_d, json.loads(entrada.parcelas_json or "[]"), _operador_softsystem(current_user),
                         json.loads(entrada.parcelas_cte_json or "[]"))
    usuario = _usuario(current_user)
    try:
        r = await asyncio.to_thread(lancar_compra, entrada.empresa, plano, db_teste)
    except LancamentoErro as e:
        _registrar_evento(db, entrada.id, usuario, "lancamento_recusado", str(e))
        await db.commit()
        return {"lancado": False, "modo": modo, "mensagem": str(e)}
    except Exception as e:
        logger.error(f"[SOFTSYSTEM] Falha ao lançar a entrada #{entrada.id}: {e}", exc_info=True)
        _registrar_evento(db, entrada.id, usuario, "lancamento_falhou", f"Erro no Softsystem (nada foi gravado): {e}")
        await db.commit()
        return {"lancado": False, "modo": modo, "mensagem": f"Erro ao gravar no Softsystem - nada foi gravado, tente de novo. ({e})"}

    extras = []
    criados = r.get("produtos_criados") or {}
    if criados:
        extras.append(f"{len(criados)} produto(s) novo(s) cadastrado(s): " + ", ".join(str(c) for c in criados.values()))
        if modo == "producao":  # o item passa a apontar para o produto criado
            for it in entrada.itens:
                if it.id in criados:
                    it.softsystem_prod_codigo = str(criados[it.id])
                    it.softsystem_descricao = (json.loads(it.cadastro_novo_json or "{}").get("descricao") or "")[:255] or it.softsystem_descricao
                    it.vinculo_metodo = "cadastro_novo"
    if r.get("fornecedor_criado"):
        extras.append(f"fornecedor cadastrado no Softsystem (código {r['fornecedor']})")
    if r.get("transportadora_criada"):
        extras.append(f"transportadora cadastrada no Softsystem (código {r['transportadora']})")
    if r.get("cte_lancado"):
        extras.append(f"frete do CT-e {entrada.cte_numero} lançado no contas a pagar da transportadora")
    elif r.get("cte_ja_existia"):
        extras.append(f"o CT-e {entrada.cte_numero} já estava no contas a pagar - não foi duplicado")
    extra_txt = (" " + "; ".join(extras) + ".") if extras else ""
    if modo == "producao":
        entrada.status = "enviada_softsystem"
        entrada.softsystem_codcompra = r["codcompra"]
        _registrar_evento(db, entrada.id, usuario, "lancada_softsystem",
                          f"Lançada no Softsystem: compra {r['codcompra']} (loja {r['loja']}).{extra_txt}")
        msg = f"Lançada no Softsystem: compra {r['codcompra']}.{extra_txt}"
        arq = await _arquivar_na_pasta(db, entrada, usuario)
        if arq:
            msg += " " + arq
    else:
        _registrar_evento(db, entrada.id, usuario, "lancamento_teste",
                          f"TESTE: lançada na cópia de teste do Softsystem como compra {r['codcompra']} (produção não foi alterada).{extra_txt}")
        msg = f"TESTE: lançada na cópia de teste como compra {r['codcompra']}. O Softsystem de verdade não foi alterado.{extra_txt}"
    await db.commit()
    return {"lancado": True, "modo": modo, "codcompra": r["codcompra"], "mensagem": msg}


async def _arquivar_na_pasta(db: AsyncSession, entrada: ComprasEntrada, usuario: str) -> Optional[str]:
    """Via da nota (XML + DANFE, e o CT-e) na pasta ANO/MÊS/FORNECEDOR/N.F da loja - pedido de
    15/10/2026. Falha aqui nunca desfaz o lançamento: registra e o botão tenta de novo."""
    from app.services.nota_arquivo_service import arquivar_nota
    nota = json.loads(entrada.nota_json or "{}")
    try:
        r = await asyncio.to_thread(arquivar_nota, entrada.empresa, entrada.chave_acesso, entrada.numero_nf,
                                    nota.get("fornecedor") or {"razao_social": entrada.fornecedor_nome},
                                    entrada.cte_chave, entrada.cte_numero, None, entrada.pasta_notas)
    except Exception as e:
        logger.warning(f"[ARQUIVO] Entrada #{entrada.id}: {e}")
        _registrar_evento(db, entrada.id, usuario, "arquivo_falhou", f"Não deu para salvar a via na pasta de notas: {e}")
        await db.commit()
        return f"Atenção: a via (XML/DANFE) não foi salva na pasta de notas ({e}) - use \"Salvar na pasta\" para tentar de novo."
    if not r.get("arquivado"):
        return None
    _registrar_evento(db, entrada.id, usuario, "arquivada_pasta",
                      "XML e DANFE salvos em NOTAS FISCAIS- FORNECEDORES\\" + r["pasta"] + ("" if r["gravados"] else " (já estavam lá)"))
    await db.commit()
    return "Via salva em NOTAS FISCAIS- FORNECEDORES\\" + r["pasta"] + "."


@router.post("/entradas/{entrada_id}/arquivar-pasta")
async def arquivar_entrada_pasta(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Salva (de novo) XML + DANFE da nota na pasta de notas de fornecedor."""
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status != "enviada_softsystem":
        raise HTTPException(status_code=400, detail="A via vai para a pasta depois que a nota é lançada no Softsystem.")
    msg = await _arquivar_na_pasta(db, entrada, _usuario(current_user))
    if not msg:
        raise HTTPException(status_code=400, detail="Pasta de notas desta loja não configurada.")
    if msg.startswith("Atenção"):
        raise HTTPException(status_code=502, detail=msg)
    return {"success": True, "mensagem": msg}


@router.post("/entradas/{entrada_id}/lancar-softsystem")
async def lancar_entrada_softsystem(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Lança (ou tenta de novo) a entrada fechada no Softsystem."""
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status != "fechada":
        raise HTTPException(status_code=400, detail="Só entradas fechadas (e ainda não lançadas) vão para o Softsystem.")
    r = await _lancar_no_softsystem(db, entrada, current_user)
    if not r["lancado"]:
        raise HTTPException(status_code=400, detail=r["mensagem"])
    return {"success": True, **r}


# ------------------------------------------------- etapa 4: estoque real + localização (pós-lançamento)
# Pedido do usuário em 15/10/2026: depois de lançar a nota, a pessoa confere o estoque REAL do
# produto na prateleira (não só o que chegou) e informa onde ele fica guardado. A localização vai
# para ESTOQUE.LOCALIZACAO (Localização 1). Estoque diferente do Softsystem vira Ajuste de Estoque -
# gravado na hora quando é administrador; de outro usuário fica registrado aguardando o administrador
# aplicar (mesma regra da tela de Acerto de Estoque, por causa do controle de perdas).
# 15/10/2026 (2ª rodada): o Guardião do Softsystem NÃO replica estoque nem localização entre os dois
# bancos (cada um só tem a ESTOQUE da sua loja) - pedido do usuário: "a quantidade no estoque e a
# localização têm que ir para os dois sistemas". Então a tela mostra as duas lojas: o estoque real é
# digitado para cada uma (cada CNPJ tem o seu - vira ajuste no banco da própria loja) e a localização
# é gravada nos DOIS bancos. Em modo teste só existe a cópia da Servweld: a Centro-Oeste fica de fora.
LOJAS_AUDITORIA = ("servweld", "centrooeste")


class AuditoriaItemPayload(BaseModel):
    item_id: int
    estoque_fisico: Optional[float] = None          # compatibilidade: estoque da loja da própria nota
    estoque_servweld: Optional[float] = None
    estoque_centrooeste: Optional[float] = None
    localizacao: Optional[str] = None


class AuditoriaPayload(BaseModel):
    itens: List[AuditoriaItemPayload]


def _entrada_lancada(entrada: ComprasEntrada) -> bool:
    if entrada.status == "enviada_softsystem":
        return True
    return entrada.status == "fechada" and _modo_lancamento() == "teste" and any(
        ev.acao == "lancamento_teste" for ev in entrada.eventos)


@router.get("/entradas/{entrada_id}/auditoria")
async def obter_auditoria_entrada(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    codigos = sorted({it.softsystem_prod_codigo for it in entrada.itens if it.softsystem_prod_codigo})
    locais: Dict[str, Dict[int, Dict[str, Any]]] = {e: {} for e in LOJAS_AUDITORIA}
    erros = []
    if codigos:
        for emp in LOJAS_AUDITORIA:
            try:
                locais[emp] = await asyncio.to_thread(SoftsystemService.localizacao_estoque, emp, codigos)
            except Exception as e:
                erros.append(f"Softsystem da {NOME_LOJA.get(emp, emp)} indisponível agora: {e}")
    itens = []
    for it in sorted(entrada.itens, key=lambda x: x.numero_item):
        cod = (it.softsystem_prod_codigo or "").strip()
        por_loja = {emp: ((locais[emp].get(int(cod)) if cod.isdigit() else None) or {}) for emp in LOJAS_AUDITORIA}
        propria = por_loja[entrada.empresa]
        auditoria = {}
        for ev in entrada.eventos:  # último estoque contado de cada loja fica no evento
            if ev.item_id == it.id and ev.acao == "auditoria_item":
                try:
                    auditoria = json.loads(ev.detalhe or "{}")
                except ValueError:
                    pass
        itens.append({
            "item_id": it.id, "numero_item": it.numero_item, "codproduto": it.softsystem_prod_codigo,
            "descricao": it.softsystem_descricao or it.descricao_fornecedor,
            "qtd_recebida": it.qtd_contada if it.qtd_contada is not None else round(it.quantidade * (it.fator_conversao or 1.0), 4),
            "estoque_softsystem": propria.get("estoque"), "localizacao_softsystem": propria.get("localizacao"),
            "lojas": {emp: {"estoque": por_loja[emp].get("estoque"), "localizacao": por_loja[emp].get("localizacao"),
                            "estoque_auditado": auditoria.get(emp)} for emp in LOJAS_AUDITORIA},
            "estoque_auditado": it.estoque_auditado, "localizacao": it.localizacao_estoque,
            "auditado_por": it.auditado_por, "auditado_em": it.auditado_em.isoformat() if it.auditado_em else None,
        })
    return {"success": True, "liberada": _entrada_lancada(entrada), "modo": _modo_lancamento(), "empresa": entrada.empresa,
            "lojas": [{"empresa": e, "nome": NOME_LOJA.get(e, e)} for e in LOJAS_AUDITORIA],
            "pode_ajustar_estoque": current_user.role == UserRole.ADMIN, "erro": " · ".join(erros) or None, "itens": itens}


NOME_LOJA = {"servweld": "Servweld", "centrooeste": "Centro-Oeste"}


@router.post("/entradas/{entrada_id}/auditoria")
async def salvar_auditoria_entrada(entrada_id: int, payload: AuditoriaPayload, db: AsyncSession = Depends(get_db),
                                   current_user: User = Depends(get_current_user)):
    from app.services.softsystem_compra_writer import lancar_ajuste, gravar_localizacao, LancamentoErro

    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if not _entrada_lancada(entrada):
        raise HTTPException(status_code=400, detail="Primeiro lance a nota no Softsystem - a auditoria de estoque e localização vem depois.")
    modo = _modo_lancamento()
    por_id = {it.id: it for it in entrada.itens}
    usuario = _usuario(current_user)
    admin = current_user.role == UserRole.ADMIN
    agora = datetime.utcnow()

    def destino(emp: str) -> Optional[str]:
        """None = produção; caminho = cópia de teste; '' = pular (Centro-Oeste não tem cópia de teste)."""
        if modo != "teste":
            return None
        return settings.SOFTSYSTEM_COMPRAS_DB_TESTE if emp == "servweld" else ""

    locais: Dict[int, str] = {}
    fisicos: Dict[str, Dict[int, float]] = {e: {} for e in LOJAS_AUDITORIA}
    for p in payload.itens:
        it = por_id.get(p.item_id)
        if not it or not (it.softsystem_prod_codigo or "").isdigit():
            continue
        cod = int(it.softsystem_prod_codigo)
        if p.localizacao is not None and p.localizacao.strip():
            novo_loc = p.localizacao.strip().upper()[:60]
            if novo_loc != (it.localizacao_estoque or ""):
                it.localizacao_estoque = novo_loc
                locais[cod] = novo_loc
        contagem = {"servweld": p.estoque_servweld, "centrooeste": p.estoque_centrooeste}
        if p.estoque_fisico is not None and contagem.get(entrada.empresa) is None:
            contagem[entrada.empresa] = p.estoque_fisico
        registro = {}
        for emp, q in contagem.items():
            if q is None:
                continue
            if q < 0:
                raise HTTPException(status_code=400, detail=f"Estoque negativo no item {it.numero_item}.")
            fisicos[emp][cod] = q
            registro[emp] = q
        if contagem.get(entrada.empresa) is not None:
            it.estoque_auditado = contagem[entrada.empresa]
        if registro:
            _registrar_evento(db, entrada.id, usuario, "auditoria_item", json.dumps(registro), it.id)
        if registro or p.localizacao:
            it.auditado_por = usuario
            it.auditado_em = agora

    msgs = []
    try:
        if locais:
            gravadas = []
            for emp in LOJAS_AUDITORIA:
                d = destino(emp)
                if d == "":
                    continue
                r = await asyncio.to_thread(gravar_localizacao, emp, locais, _operador_softsystem(current_user), d)
                gravadas.append(f"{NOME_LOJA[emp]} ({len(r['gravados'])})")
            msgs.append("Localização gravada no Softsystem: " + ", ".join(gravadas) + ".")
            _registrar_evento(db, entrada.id, usuario, "localizacao",
                              "Localização (Servweld e Centro-Oeste): " + ", ".join(f"{c} = {l}" for c, l in locais.items()))
        for emp in LOJAS_AUDITORIA:
            if not fisicos[emp]:
                continue
            if not admin:
                _registrar_evento(db, entrada.id, usuario, "auditoria_estoque_pendente",
                                  f"Estoque contado na {NOME_LOJA[emp]} (aguardando administrador aplicar): "
                                  + ", ".join(f"{c} = {q:g}" for c, q in fisicos[emp].items()))
                msgs.append(f"Estoque da {NOME_LOJA[emp]} registrado - o administrador aplica o ajuste se houver diferença.")
                continue
            d = destino(emp)
            if d == "":
                msgs.append(f"{NOME_LOJA[emp]}: sem cópia de teste - estoque não gravado.")
                continue
            r = await asyncio.to_thread(
                lancar_ajuste, emp, [{"codproduto": c, "quantidade_fisica": q} for c, q in fisicos[emp].items()],
                _operador_softsystem(current_user), f"Auditoria pós-entrada NF {entrada.numero_nf} (entrada #{entrada.id})", d)
            msgs.append(f"{NOME_LOJA[emp]}: " + (r["mensagem"] if r.get("codajuste") else "estoque já batia com o Softsystem."))
            difs = [i for i in r.get("itens", []) if abs(i.get("diferenca") or 0) > 0.0001]
            _registrar_evento(db, entrada.id, usuario, "auditoria_estoque",
                              f"{NOME_LOJA[emp]} - " + (f"Ajuste {r['codajuste']}: " if r.get("codajuste") else "Sem diferença: ")
                              + ", ".join(f"{i['codproduto']} {i['antes']:g}->{i['depois']:g}" for i in (difs or r.get("itens", []))))
    except LancamentoErro as e:
        await db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[SOFTSYSTEM] Falha na auditoria da entrada #{entrada.id}: {e}", exc_info=True)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Erro ao gravar no Softsystem: {e}")
    await db.commit()
    if modo == "teste" and msgs:
        msgs.insert(0, "TESTE (cópia do banco):")
    return {"success": True, "mensagem": " ".join(msgs) or "Nada para gravar."}


class PrecoPosLancamentoPayload(BaseModel):
    itens: List[Dict[str, Any]]  # {item_id, preco_venda_final, margem_lucro_pct?}


@router.put("/entradas/{entrada_id}/preco-softsystem")
async def ajustar_preco_pos_lancamento(entrada_id: int, payload: PrecoPosLancamentoPayload, db: AsyncSession = Depends(get_db),
                                       current_user: User = Depends(get_current_user)):
    """Preço de venda ajustado DEPOIS do lançamento (15/10/2026): grava na entrada e no cadastro do
    produto no Softsystem (PRODUTOS.PRECO)."""
    from app.services.softsystem_compra_writer import atualizar_preco_venda, LancamentoErro
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if not _entrada_lancada(entrada):
        raise HTTPException(status_code=400, detail="Antes do lançamento o preço é salvo pela precificação normal.")
    modo = _modo_lancamento()
    if modo == "desligado":
        raise HTTPException(status_code=400, detail="Gravação no Softsystem desligada neste servidor.")
    por_id = {it.id: it for it in entrada.itens}
    precos: Dict[int, float] = {}
    detalhes = []
    for p in payload.itens:
        it = por_id.get(int(p.get("item_id") or 0))
        novo = float(p.get("preco_venda_final") or 0)
        if not it or not (it.softsystem_prod_codigo or "").isdigit() or novo <= 0:
            continue
        if abs(novo - (it.preco_venda_final or 0)) < 0.005:
            continue
        detalhes.append(f"{it.softsystem_prod_codigo}: {it.preco_venda_final or 0:.2f} -> {novo:.2f}")
        it.preco_venda_final = round(novo, 2)
        if p.get("margem_lucro_pct") is not None:
            it.margem_lucro_pct = float(p["margem_lucro_pct"])
        calc = json.loads(it.calculo_json) if it.calculo_json else {}
        calc["preco_venda_final"] = it.preco_venda_final
        it.calculo_json = json.dumps(calc, ensure_ascii=False, default=str)
        precos[int(it.softsystem_prod_codigo)] = it.preco_venda_final
    if not precos:
        return {"success": True, "mensagem": "Nenhum preço mudou."}
    try:
        await asyncio.to_thread(atualizar_preco_venda, entrada.empresa, precos, _operador_softsystem(current_user),
                                settings.SOFTSYSTEM_COMPRAS_DB_TESTE if modo == "teste" else None)
    except LancamentoErro as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[SOFTSYSTEM] Falha ao atualizar preço da entrada #{entrada.id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Erro ao gravar no Softsystem - nada foi gravado. ({e})")
    _registrar_evento(db, entrada.id, _usuario(current_user), "preco_alterado",
                      ("TESTE: " if modo == "teste" else "") + "Preço de venda atualizado no Softsystem: " + ", ".join(detalhes))
    await db.commit()
    return {"success": True, "mensagem": ("TESTE (cópia): " if modo == "teste" else "")
            + f"Preço atualizado no Softsystem em {len(precos)} produto(s)."}


@router.post("/entradas/{entrada_id}/fechar")
async def fechar_entrada(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Fecha a entrada depois da contagem. A gravação no Softsystem (compra, itens, contas a pagar,
    estoque pela quantidade contada e preço) é a próxima etapa - fica com status 'fechada' até lá.
    """
    try:
        entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
        if entrada.status != "contada":
            raise HTTPException(status_code=400, detail="Só é possível fechar depois que a contagem física for concluída (ou a divergência aprovada).")

        pendencias = []
        for it in entrada.itens:
            if not it.softsystem_prod_codigo:
                cad = json.loads(it.cadastro_novo_json) if it.cadastro_novo_json else {}
                if not cad.get("confirmado"):
                    pendencias.append(f"Item {it.numero_item} é produto novo: confirme o cadastro dele (botão \"Cadastro do produto novo\")."
                                      if it.produto_modelo_codigo or cad else f"Item {it.numero_item} sem produto vinculado nem modelo para cadastro.")
            if not it.preco_venda_final or it.preco_venda_final <= 0:
                pendencias.append(f"Item {it.numero_item} sem preço de venda.")
        nota = json.loads(entrada.nota_json or "{}")
        sem_cobranca_padroes = ["GARANTIA", "REMESSA", "TROCA", "BONIFICA", "CONSERTO", "DEVOLU", "RETORNO", "DEMONSTRA", "AMOSTRA", "BRINDE"]
        cfops_sem_cobranca = {
            "5949", "6949", "5910", "6910", "5911", "6911", "5912", "6912",
            "5913", "6913", "5914", "6914", "5915", "6915", "5916", "6916",
            "5927", "6927", "5928", "6928", "5944", "6944", "5945", "6945"
        }
        nat_op = (nota.get("natureza_operacao") or "").upper()
        info_ad = (nota.get("informacoes_complementares") or "").upper()
        cfops_itens = {re.sub(r"\D", "", str(it.cfop or "")) for it in entrada.itens if it.cfop}
        eh_sem_cobranca = (
            any(p in nat_op for p in sem_cobranca_padroes)
            or any(p in info_ad for p in sem_cobranca_padroes)
            or bool(cfops_itens and all(c in cfops_sem_cobranca for c in cfops_itens))
            or (entrada.valor_total_nota or 0) == 0
        )

        parcelas = json.loads(entrada.parcelas_json or "[]")
        soma = round(sum(float(p.get("valor") or 0) for p in parcelas), 2)
        if parcelas and abs(soma - (entrada.valor_total_nota or 0)) > 0.05:
            pendencias.append(f"Parcelas somam R$ {soma:.2f}, mas a nota é de R$ {entrada.valor_total_nota:.2f}.")
        if not parcelas and not eh_sem_cobranca:
            pendencias.append("Informe os vencimentos (contas a pagar) do fornecedor.")
        if (entrada.valor_frete_cte or 0) > 0:
            parcelas_cte = json.loads(entrada.parcelas_cte_json or "[]")
            soma_cte = round(sum(float(p.get("valor") or 0) for p in parcelas_cte), 2)
            if not parcelas_cte:
                pendencias.append(f"Informe o vencimento do frete do CT-e {entrada.cte_numero or ''} (transportadora).")
            elif abs(soma_cte - entrada.valor_frete_cte) > 0.05:
                pendencias.append(f"Vencimentos do frete somam R$ {soma_cte:.2f}, mas o CT-e é de R$ {entrada.valor_frete_cte:.2f}.")
        if pendencias:
            raise HTTPException(status_code=400, detail=" ".join(pendencias))

        usuario = _usuario(current_user)
        entrada.status = "fechada"
        entrada.fechada_em = datetime.utcnow()
        entrada.fechada_por = usuario
        _registrar_evento(db, entrada.id, usuario, "fechada", "Entrada fechada - aguardando envio ao Softsystem.")
        await db.commit()

        # lança no Softsystem na hora (se liberado) - se der problema, a entrada fica 'fechada' e o
        # botão "Lançar no Softsystem" tenta de novo
        lancamento = await _lancar_no_softsystem(db, entrada, current_user)

        notificacoes = []
        try:
            itens_gatilho = [{
                "ean": it.ean, "descricao_fornecedor": it.descricao_fornecedor,
                "softsystem_prod_codigo": it.softsystem_prod_codigo,
            } for it in entrada.itens]
            notificacoes = await BalcaoEsperaService.processar_gatilho_entrada_compra(
                db=db, tenant_id=current_user.tenant_id, empresa=entrada.empresa,
                itens_entrada=itens_gatilho, numero_nf=entrada.numero_nf, compra_id=entrada.id,
            )
        except Exception as e_balcao:
            logger.warning(f"[BALCAO] Erro ao processar gatilho do balcão na entrada #{entrada.id}: {e_balcao}")

        return {"success": True, "status": entrada.status, "lancamento": lancamento,
                "clientes_notificados": len(notificacoes), "detalhes_notificacoes": notificacoes}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[FECHAR_ENTRADA] Erro ao fechar entrada #{entrada_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao fechar entrada: {e}")


@router.post("/entradas/{entrada_id}/cancelar")
async def cancelar_entrada(entrada_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_admin_user)):
    entrada = await _carregar_entrada(db, current_user.tenant_id, entrada_id)
    if entrada.status == "enviada_softsystem":
        raise HTTPException(status_code=400, detail="Entrada já enviada ao Softsystem - cancele por lá.")
    entrada.status = "cancelada"
    _registrar_evento(db, entrada.id, _usuario(current_user), "cancelada", "Entrada cancelada.")
    await db.commit()
    if entrada.pasta_notas:  # pasta criada na importação: some se continuar vazia
        from app.services.nota_arquivo_service import remover_pasta_vazia
        try:
            await asyncio.to_thread(remover_pasta_vazia, entrada.empresa, entrada.pasta_notas)
        except Exception as e:
            logger.warning(f"[ARQUIVO] Cancelamento #{entrada.id}: {e}")
    return {"success": True}


# ============================================================ 6. Fila do Balcão ("Avise-me quando Chegar")
@router.get("/balcao-espera")
async def listar_balcao_espera(
    empresa: Optional[str] = None,
    status: Optional[str] = None,
    busca: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(BalcaoFilaEspera).where(BalcaoFilaEspera.tenant_id == current_user.tenant_id)
    if empresa and empresa != "todas":
        stmt = stmt.where(BalcaoFilaEspera.empresa == empresa.lower())
    if status and status != "todos":
        stmt = stmt.where(BalcaoFilaEspera.status == status.lower())
    if busca:
        termo = f"%{busca.strip()}%"
        stmt = stmt.where(
            (BalcaoFilaEspera.cliente_nome.ilike(termo)) |
            (BalcaoFilaEspera.cliente_telefone.ilike(termo)) |
            (BalcaoFilaEspera.produto_nome.ilike(termo)) |
            (BalcaoFilaEspera.produto_codigo.ilike(termo)) |
            (BalcaoFilaEspera.produto_ean.ilike(termo))
        )
    res = await db.execute(stmt.order_by(desc(BalcaoFilaEspera.criado_em)))
    demandas = res.scalars().all()
    return {"success": True, "total": len(demandas), "demandas": demandas}


@router.post("/balcao-espera")
async def criar_balcao_espera(payload: BalcaoDemandaCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = await BalcaoEsperaService.cadastrar_demanda(
        db=db,
        tenant_id=current_user.tenant_id,
        empresa=payload.empresa,
        cliente_nome=payload.cliente_nome,
        cliente_telefone=payload.cliente_telefone,
        produto_nome=payload.produto_nome,
        atendente_nome=_usuario(current_user),
        produto_codigo=payload.produto_codigo,
        produto_ean=payload.produto_ean,
        quantidade_desejada=payload.quantidade_desejada,
        cliente_documento=payload.cliente_documento,
        observacao=payload.observacao,
    )
    return {"success": True, "demanda": item}


@router.post("/balcao-espera/{demanda_id}/notificar")
async def notificar_balcao_espera(demanda_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await BalcaoEsperaService.notificar_cliente(
        db=db, demanda_id=demanda_id, origem_aviso=f"Disparo manual realizado por {_usuario(current_user)}"
    )


@router.patch("/balcao-espera/{demanda_id}/status")
async def atualizar_status_balcao_espera(
    demanda_id: int,
    status: str = Query(..., pattern="^(aguardando|notificado|convertido|cancelado)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    res = await db.execute(select(BalcaoFilaEspera).where(
        BalcaoFilaEspera.id == demanda_id, BalcaoFilaEspera.tenant_id == current_user.tenant_id
    ))
    demanda = res.scalar_one_or_none()
    if not demanda:
        raise HTTPException(status_code=404, detail="Demanda não encontrada")
    demanda.status = status
    demanda.historico_auditoria = BalcaoEsperaService._adicionar_log_auditoria(
        demanda.historico_auditoria, f"Status alterado para '{status.upper()}' por {_usuario(current_user)}."
    )
    await db.commit()
    return {"success": True, "demanda": demanda}


# ============================================================ 7. Pedidos de Compra por Fabricante / Telecontrol
class PedidoItemIn(BaseModel):
    referencia: str
    descricao: str
    quantidade: float = 1.0
    unidade: str = "UN"
    preco_estimado: Optional[float] = None
    softsystem_codproduto: Optional[int] = None
    balcao_espera_id: Optional[int] = None
    observacao: Optional[str] = None


class PedidoCriarIn(BaseModel):
    empresa: str = "servweld"
    fabricante_nome: str
    fornecedor_cnpj: Optional[str] = None
    fornecedor_email: Optional[str] = None
    fornecedor_whatsapp: Optional[str] = None
    contato_nome: Optional[str] = None
    observacao: Optional[str] = None


class ProdutoDiretoIn(BaseModel):
    empresa: str = "servweld"
    descricao: str
    modelo_codigo: int
    unidade: str = "UN"
    ncm: str
    codgrupo: int
    codsubgrupo: int
    codsubgruponivel2: Optional[int] = None
    codsubgruponivel3: Optional[int] = None
    codmarca: Optional[int] = None
    marca_nova: Optional[str] = None
    referencia: Optional[str] = None
    peso: Optional[float] = None
    preco_venda: Optional[float] = None
    preco_custo: Optional[float] = None


@router.get("/pedidos")
async def listar_pedidos(
    empresa: Optional[str] = None,
    status: Optional[str] = None,
    fabricante: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem
    stmt = select(ComprasPedido).where(ComprasPedido.tenant_id == current_user.tenant_id)
    if empresa and empresa != "todas":
        stmt = stmt.where(ComprasPedido.empresa == empresa.lower())
    if status and status != "todos":
        stmt = stmt.where(ComprasPedido.status == status.lower())
    if fabricante:
        stmt = stmt.where(ComprasPedido.fabricante_nome.ilike(f"%{fabricante.strip()}%"))
    
    res = await db.execute(stmt.options(selectinload(ComprasPedido.itens)).order_by(desc(ComprasPedido.criado_em)))
    pedidos = res.scalars().all()
    
    return {
        "success": True,
        "total": len(pedidos),
        "pedidos": [
            {
                "id": p.id,
                "empresa": p.empresa,
                "fabricante_nome": p.fabricante_nome,
                "fornecedor_cnpj": p.fornecedor_cnpj,
                "fornecedor_email": p.fornecedor_email,
                "fornecedor_whatsapp": p.fornecedor_whatsapp,
                "contato_nome": p.contato_nome,
                "status": p.status,
                "observacao": p.observacao,
                "criado_em": p.criado_em,
                "criado_por": p.criado_por,
                "fechado_em": p.fechado_em,
                "fechado_por": p.fechado_por,
                "total_itens": len(p.itens),
                "total_pecas": sum(it.quantidade for it in p.itens)
            } for p in pedidos
        ]
    }


@router.post("/pedidos")
async def criar_ou_obter_pedido(
    payload: PedidoCriarIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido
    empresa = payload.empresa.lower()
    fab_nome = payload.fabricante_nome.strip()
    
    # Regra: se já tem pedido em aberto do mesmo fabricante na mesma empresa, avisa e retorna o existente
    stmt = select(ComprasPedido).where(
        ComprasPedido.tenant_id == current_user.tenant_id,
        ComprasPedido.empresa == empresa,
        ComprasPedido.fabricante_nome.ilike(fab_nome),
        ComprasPedido.status == "aberto"
    ).options(selectinload(ComprasPedido.itens))
    res = await db.execute(stmt)
    aberto = res.scalar_one_or_none()
    
    if aberto:
        return {
            "success": True,
            "ja_existia": True,
            "mensagem": f"Já existe um pedido aberto para '{aberto.fabricante_nome}' (Nº {aberto.id}). Continue lançando nele!",
            "pedido": aberto
        }

    novo = ComprasPedido(
        tenant_id=current_user.tenant_id,
        empresa=empresa,
        fabricante_nome=fab_nome,
        fornecedor_cnpj=payload.fornecedor_cnpj,
        fornecedor_email=payload.fornecedor_email,
        fornecedor_whatsapp=payload.fornecedor_whatsapp,
        contato_nome=payload.contato_nome,
        observacao=payload.observacao,
        status="aberto",
        criado_em=datetime.utcnow(),
        criado_por=_usuario(current_user)
    )
    db.add(novo)
    await db.commit()
    await db.refresh(novo)
    
    # Recarrega itens
    res = await db.execute(select(ComprasPedido).where(ComprasPedido.id == novo.id).options(selectinload(ComprasPedido.itens)))
    return {"success": True, "ja_existia": False, "pedido": res.scalar_one()}


@router.get("/pedidos/{pedido_id}")
async def obter_detalhe_pedido(
    pedido_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem
    res = await db.execute(
        select(ComprasPedido)
        .where(ComprasPedido.id == pedido_id, ComprasPedido.tenant_id == current_user.tenant_id)
        .options(selectinload(ComprasPedido.itens))
    )
    pedido = res.scalar_one_or_none()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return {"success": True, "pedido": pedido}


@router.post("/pedidos/{pedido_id}/itens")
async def adicionar_item_pedido(
    pedido_id: int,
    item_in: PedidoItemIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem, BalcaoFilaEspera
    res = await db.execute(
        select(ComprasPedido).where(ComprasPedido.id == pedido_id, ComprasPedido.tenant_id == current_user.tenant_id)
    )
    pedido = res.scalar_one_or_none()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    if pedido.status != "aberto":
        raise HTTPException(status_code=400, detail="Este pedido já está fechado ou cancelado.")

    item = ComprasPedidoItem(
        pedido_id=pedido.id,
        referencia=item_in.referencia.strip(),
        descricao=item_in.descricao.strip(),
        quantidade=float(item_in.quantidade),
        unidade=item_in.unidade.strip().upper(),
        preco_estimado=item_in.preco_estimado,
        softsystem_codproduto=item_in.softsystem_codproduto,
        balcao_espera_id=item_in.balcao_espera_id,
        observacao=item_in.observacao,
        criado_em=datetime.utcnow()
    )
    db.add(item)

    # Se veio de uma demanda do balcão, atualiza o histórico da demanda
    if item_in.balcao_espera_id:
        b_res = await db.execute(select(BalcaoFilaEspera).where(BalcaoFilaEspera.id == item_in.balcao_espera_id))
        demanda = b_res.scalar_one_or_none()
        if demanda:
            demanda.historico_auditoria = BalcaoEsperaService._adicionar_log_auditoria(
                demanda.historico_auditoria,
                f"Item incluído no Pedido de Compra #{pedido.id} ({pedido.fabricante_nome}) por {_usuario(current_user)}."
            )

    await db.commit()
    await db.refresh(item)
    return {"success": True, "item": item}


@router.delete("/pedidos/{pedido_id}/itens/{item_id}")
async def remover_item_pedido(
    pedido_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem
    res = await db.execute(
        select(ComprasPedidoItem).join(ComprasPedido).where(
            ComprasPedidoItem.id == item_id,
            ComprasPedido.id == pedido_id,
            ComprasPedido.tenant_id == current_user.tenant_id
        )
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    await db.delete(item)
    await db.commit()
    return {"success": True}


@router.get("/pedidos/{pedido_id}/sugestoes-balcao")
async def buscar_sugestoes_balcao(
    pedido_id: int,
    termo: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Localiza pedidos de clientes na fila de espera do balcão que:
    1) Sejam do mesmo fabricante do pedido, OU
    2) Tenham similaridade de nome/tipo com o termo informado ou com os itens já lançados no pedido.
    """
    from app.models.models import ComprasPedido, ComprasPedidoItem, BalcaoFilaEspera
    from app.services.compras_pedido_service import ComprasPedidoService
    
    res = await db.execute(
        select(ComprasPedido).where(ComprasPedido.id == pedido_id, ComprasPedido.tenant_id == current_user.tenant_id)
        .options(selectinload(ComprasPedido.itens))
    )
    pedido = res.scalar_one_or_none()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    # Busca todas as demandas 'aguardando' da empresa
    stmt = select(BalcaoFilaEspera).where(
        BalcaoFilaEspera.tenant_id == current_user.tenant_id,
        BalcaoFilaEspera.empresa == pedido.empresa,
        BalcaoFilaEspera.status == "aguardando"
    )
    d_res = await db.execute(stmt)
    todas_aguardando = d_res.scalars().all()

    sugestoes = []
    termos_pedido = [it.descricao for it in pedido.itens]
    if termo:
        termos_pedido.append(termo)

    for dem in todas_aguardando:
        motivo = None
        # Mesma menção de fabricante na observação ou produto
        if pedido.fabricante_nome.lower() in (dem.produto_nome or "").lower() or pedido.fabricante_nome.lower() in (dem.observacao or "").lower():
            motivo = f"Mesmo fabricante ({pedido.fabricante_nome})"
        else:
            # Testa similaridade com itens do pedido
            for t_item in termos_pedido:
                if ComprasPedidoService.verificar_similaridade(t_item, dem.produto_nome):
                    motivo = f"Similar ao item do pedido: '{t_item}'"
                    break

        if motivo:
            sugestoes.append({
                "demanda_id": dem.id,
                "cliente_nome": dem.cliente_nome,
                "cliente_telefone": dem.cliente_telefone,
                "produto_nome": dem.produto_nome,
                "produto_codigo": dem.produto_codigo,
                "quantidade_desejada": dem.quantidade_desejada,
                "observacao": dem.observacao,
                "criado_em": dem.criado_em,
                "motivo_sugestao": motivo
            })

    return {"success": True, "sugestoes": sugestoes}


@router.get("/pedidos/{pedido_id}/exportar-csv")
async def exportar_pedido_csv(
    pedido_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem
    from app.services.compras_pedido_service import ComprasPedidoService

    res = await db.execute(
        select(ComprasPedido).where(ComprasPedido.id == pedido_id, ComprasPedido.tenant_id == current_user.tenant_id)
        .options(selectinload(ComprasPedido.itens))
    )
    pedido = res.scalar_one_or_none()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    itens_dict = [
        {"referencia": it.referencia, "quantidade": it.quantidade}
        for it in pedido.itens
    ]
    arquivos = ComprasPedidoService.gerar_csv_telecontrol(itens_dict, limite_linhas=500)
    return {"success": True, "arquivos": arquivos}


@router.get("/pedidos/{pedido_id}/exportar-pdf")
async def exportar_pedido_pdf(
    pedido_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem
    from app.services.compras_pedido_service import ComprasPedidoService
    from fastapi.responses import Response

    res = await db.execute(
        select(ComprasPedido).where(ComprasPedido.id == pedido_id, ComprasPedido.tenant_id == current_user.tenant_id)
        .options(selectinload(ComprasPedido.itens))
    )
    pedido = res.scalar_one_or_none()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    p_dict = {
        "id": pedido.id,
        "empresa": pedido.empresa,
        "fabricante_nome": pedido.fabricante_nome,
        "contato_nome": pedido.contato_nome,
        "fornecedor_email": pedido.fornecedor_email,
        "fornecedor_whatsapp": pedido.fornecedor_whatsapp,
        "status": pedido.status,
        "observacao": pedido.observacao,
        "criado_em": pedido.criado_em
    }
    itens_dict = [
        {"referencia": it.referencia, "descricao": it.descricao, "quantidade": it.quantidade, "unidade": it.unidade}
        for it in pedido.itens
    ]

    pdf_bytes = ComprasPedidoService.gerar_pdf_pedido(p_dict, itens_dict)
    nome_arq = f"pedido_{pedido.id:05d}_{pedido.fabricante_nome.replace(' ', '_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"}
    )


@router.post("/pedidos/{pedido_id}/fechar")
async def fechar_pedido(
    pedido_id: int,
    enviar_whatsapp: bool = False,
    enviar_email: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.models.models import ComprasPedido, ComprasPedidoItem
    res = await db.execute(
        select(ComprasPedido).where(ComprasPedido.id == pedido_id, ComprasPedido.tenant_id == current_user.tenant_id)
        .options(selectinload(ComprasPedido.itens))
    )
    pedido = res.scalar_one_or_none()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")

    pedido.status = "fechado"
    pedido.fechado_em = datetime.utcnow()
    pedido.fechado_por = _usuario(current_user)

    # Disparo de WhatsApp se solicitado e tiver telefone
    if enviar_whatsapp and pedido.fornecedor_whatsapp:
        try:
            from app.services.evolution_service import evolution_service
            clean_phone = re.sub(r"\D", "", pedido.fornecedor_whatsapp)
            if len(clean_phone) in (10, 11) and not clean_phone.startswith("55"):
                clean_phone = f"55{clean_phone}"
            
            nome_loja = "Servweld" if pedido.empresa == "servweld" else "Centro Oeste"
            msg = (
                f"Olá! Segue fechamento do nosso *Pedido de Compra Nº {pedido.id:05d}* ({nome_loja}).\n\n"
                f"Fabricante: *{pedido.fabricante_nome}*\n"
                f"Total de itens: *{len(pedido.itens)}*\n"
                f"Total de peças: *{sum(it.quantidade for it in pedido.itens):.0f}*\n\n"
                f"Por favor, confirmar o recebimento e prazo de faturamento/entrega."
            )
            await evolution_service.send_text_message("instancia_vendas", clean_phone, msg)
            pedido.enviado_whatsapp_em = datetime.utcnow()
        except Exception as e:
            logger.warning(f"[PEDIDO] Erro ao enviar whatsapp ao fornecedor: {e}")

    await db.commit()
    return {"success": True, "pedido": pedido}


@router.post("/cadastrar-produto-direto")
async def cadastrar_produto_direto_endpoint(
    payload: ProdutoDiretoIn,
    current_user: User = Depends(get_current_user)
):
    """Cria um novo produto diretamente no Softsystem a partir do modelo selecionado."""
    from app.services.softsystem_compra_writer import cadastrar_produto_direto, LancamentoErro
    from app.services.cadastro_produto_service import arvore, validar_cadastro

    empresa = payload.empresa.lower()
    arv = arvore(empresa)
    cad_dict = payload.model_dump()
    
    erros = validar_cadastro(arv, cad_dict)
    if erros:
        raise HTTPException(status_code=400, detail=" ".join(erros))

    try:
        cod_criado = await asyncio.to_thread(
            cadastrar_produto_direto,
            empresa=empresa,
            cad=cad_dict,
            operador=_usuario(current_user)
        )
        return {"success": True, "codproduto": cod_criado, "descricao": payload.descricao}
    except LancamentoErro as le:
        raise HTTPException(status_code=400, detail=str(le))
    except Exception as e:
        logger.error(f"[CADASTRO_DIRETO] Erro ao cadastrar produto: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao gravar no Softsystem: {e}")

