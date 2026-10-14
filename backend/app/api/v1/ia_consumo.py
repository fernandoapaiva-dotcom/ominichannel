"""
Painel "Consumo de IA" (Admin) - lê o que o observador (app/services/ia_consumo_service.py) gravou:
quanto se gasta hoje / no mês / projeção, por dia, por função e por modelo, separando o TREINO (gasto
único: catálogo das vistas explodidas, OCR) do USO do dia a dia (Copiloto, laudos, WhatsApp).
Montado dentro do router de /settings (ver o fim de settings.py).
"""
import asyncio
import calendar
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_admin_user
from app.models.models import User
from app.services import ia_consumo_service as obs

router = APIRouter(prefix="/ia-consumo")

_DIA_BRT = "date(criado_em, '-3 hours')"


def _resumo(dias: int) -> dict:
    con = obs._conectar()
    try:
        precos = obs.ler_precos(con)
        cot = float(precos.get("cotacao_dolar") or obs.PRECOS_PADRAO["cotacao_dolar"])
        agora = datetime.utcnow() - timedelta(hours=3)
        hoje = agora.strftime("%Y-%m-%d")
        ini_mes = agora.strftime("%Y-%m-01")
        ini_periodo = (agora - timedelta(days=dias - 1)).strftime("%Y-%m-%d")

        def treino(origem, chamadores):
            return obs.rotulo(origem, chamadores)[1] in obs.GRUPOS_TREINO

        # Uma linha por (dia, origem, chamadores, modelo) desde o início do mês ou do período (o que vier antes)
        desde = min(ini_mes, ini_periodo)
        linhas = con.execute(
            f"SELECT {_DIA_BRT} AS dia, origem, chamadores, modelo, COUNT(*), SUM(1 - ok), SUM(tok_entrada),"
            f" SUM(tok_saida), SUM(tok_pensamento), SUM(custo_usd) FROM ia_consumo WHERE {_DIA_BRT} >= ?"
            " GROUP BY dia, origem, chamadores, modelo", (desde,)).fetchall()
        primeiro = con.execute("SELECT MIN(criado_em) FROM ia_consumo").fetchone()[0]
        erros = con.execute(
            "SELECT criado_em, origem, chamadores, modelo, erro FROM ia_consumo WHERE ok = 0 ORDER BY id DESC LIMIT 15"
        ).fetchall()
    finally:
        con.close()

    def vazio():
        return {"chamadas": 0, "erros": 0, "tok_entrada": 0, "tok_saida": 0, "tok_pensamento": 0, "custo_brl": 0.0}

    def soma(alvo, ch, er, te, ts, tp, usd):
        alvo["chamadas"] += ch
        alvo["erros"] += er or 0
        alvo["tok_entrada"] += te or 0
        alvo["tok_saida"] += ts or 0
        alvo["tok_pensamento"] += tp or 0
        alvo["custo_brl"] += (usd or 0) * cot

    tot_hoje, tot_mes = vazio(), vazio()
    mes_rec, mes_treino = vazio(), vazio()
    por_dia = {(agora - timedelta(days=i)).strftime("%Y-%m-%d"): {"recorrente": vazio(), "treino": vazio()} for i in range(dias)}
    por_funcao, por_modelo = defaultdict(vazio), defaultdict(vazio)
    for dia, origem, chamadores, modelo, ch, er, te, ts, tp, usd in linhas:
        valores = (ch, er, te, ts, tp, usd)
        eh_treino = treino(origem, chamadores)
        if dia == hoje:
            soma(tot_hoje, *valores)
        if dia >= ini_mes:
            soma(tot_mes, *valores)
            soma(mes_treino if eh_treino else mes_rec, *valores)
        if dia >= ini_periodo:
            if dia in por_dia:
                soma(por_dia[dia]["treino" if eh_treino else "recorrente"], *valores)
            nome, grupo = obs.rotulo(origem, chamadores)
            soma(por_funcao[(nome, grupo)], *valores)
            soma(por_modelo[modelo or "?"], *valores)

    # Projeção do mês: uso recorrente na média dos dias já passados + o treino que já aconteceu
    dias_mes = calendar.monthrange(agora.year, agora.month)[1]
    dias_passados = agora.day
    if primeiro:
        inicio_obs = (datetime.fromisoformat(primeiro) - timedelta(hours=3)).date()
        if inicio_obs.strftime("%Y-%m") == agora.strftime("%Y-%m"):
            dias_passados = (agora.date() - inicio_obs).days + 1
    media_rec_dia = mes_rec["custo_brl"] / max(1, dias_passados)
    projecao = mes_treino["custo_brl"] + mes_rec["custo_brl"] + media_rec_dia * (dias_mes - agora.day)

    funcoes = []
    for (nome, grupo), v in por_funcao.items():
        ok = max(1, v["chamadas"] - v["erros"])
        funcoes.append(dict(v, nome=nome, grupo=grupo, tipo="treino" if grupo in obs.GRUPOS_TREINO else "recorrente",
                            custo_medio_brl=v["custo_brl"] / ok,
                            tokens_medio=(v["tok_entrada"] + v["tok_saida"] + v["tok_pensamento"]) / ok))
    funcoes.sort(key=lambda f: -f["custo_brl"])

    return {
        "cotacao_dolar": cot,
        "orcamento_mensal_brl": float(precos.get("orcamento_mensal_brl") or 0),
        "observando_desde": primeiro,
        "dias": dias,
        "hoje": tot_hoje,
        "mes": tot_mes,
        "mes_recorrente": mes_rec,
        "mes_treino": mes_treino,
        "media_recorrente_dia_brl": media_rec_dia,
        "projecao_mes_brl": projecao,
        "projecao_recorrente_mes_brl": media_rec_dia * dias_mes,
        "por_dia": [{"dia": d, **v} for d, v in sorted(por_dia.items())],
        "por_funcao": funcoes,
        "por_modelo": sorted(({"modelo": m, **v} for m, v in por_modelo.items()), key=lambda x: -x["custo_brl"]),
        "ultimos_erros": [
            {"quando": q, "funcao": obs.rotulo(o, c)[0], "modelo": m, "erro": e} for q, o, c, m, e in erros
        ],
    }


@router.get("/resumo")
async def resumo_consumo(dias: int = Query(30, ge=1, le=120), admin_user: User = Depends(get_admin_user)):
    return await asyncio.to_thread(_resumo, dias)


@router.get("/precos")
async def ler_precos(admin_user: User = Depends(get_admin_user)):
    return await asyncio.to_thread(obs.ler_precos, None)


@router.post("/precos")
async def salvar_precos(payload: dict, recalcular: bool = Query(False), admin_user: User = Depends(get_admin_user)):
    try:
        modelos = {
            str(nome).strip(): {"entrada": float(p["entrada"]), "saida": float(p["saida"])}
            for nome, p in (payload.get("modelos") or {}).items() if str(nome).strip()
        }
        valor = {
            "cotacao_dolar": float(payload.get("cotacao_dolar") or 0),
            "orcamento_mensal_brl": float(payload.get("orcamento_mensal_brl") or 0),
            "modelos": modelos,
        }
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Preços inválidos")
    if valor["cotacao_dolar"] <= 0 or not modelos:
        raise HTTPException(status_code=400, detail="Informe a cotação do dólar e ao menos um modelo")
    modelos.setdefault("padrao", obs.PRECOS_PADRAO["modelos"]["padrao"])
    await asyncio.to_thread(obs.salvar_precos, valor)
    if recalcular:  # "aplicar também ao que já foi gasto"
        await asyncio.to_thread(obs.recalcular_historico, valor)
    return valor
