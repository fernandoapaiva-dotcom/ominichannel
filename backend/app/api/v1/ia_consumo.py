"""
Painel "Consumo de IA" (Admin) - lê o que o observador (app/services/ia_consumo_service.py) gravou:
quanto se gasta hoje / no mês / projeção, por dia, por função e por modelo, separando o TREINO (gasto
único: catálogo das vistas explodidas, OCR) do USO do dia a dia (Copiloto, laudos, WhatsApp).
Montado dentro do router de /settings (ver o fim de settings.py).
"""
import asyncio
import calendar
import json
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_admin_user
from app.models.models import User
from app.services import ia_consumo_service as obs

router = APIRouter(prefix="/ia-consumo")

_DIA_BRT = "date(criado_em, '-3 hours')"

# Gasto ANTES do observador existir (14/10/2026), lido do gráfico "Custo da conta de faturamento" do
# Google AI Studio (dias no fuso dos EUA; valores das barras aproximados, total = R$ 27,29 informado).
# Editável no painel (Histórico do AI Studio). Saldo informado pelo usuário: R$ 148,09 após a recarga.
HISTORICO_INICIAL = {
    "2026-10-06": 2.35, "2026-10-07": 5.40, "2026-10-08": 2.25, "2026-10-09": 0.80,
    "2026-10-10": 1.90, "2026-10-11": 0.30, "2026-10-12": 0.15, "2026-10-13": 14.14,
}
SALDO_INICIAL = {"valor_brl": 148.09, "em": "2026-10-14T12:00:00"}


def _config(con, chave: str):
    row = con.execute("SELECT valor FROM ia_consumo_config WHERE chave = ?", (chave,)).fetchone()
    return json.loads(row[0]) if row else None


def _set_config(con, chave: str, valor) -> None:
    con.execute("INSERT OR REPLACE INTO ia_consumo_config (chave, valor) VALUES (?, ?)", (chave, json.dumps(valor)))


def _conectar_com_historico():
    con = obs._conectar()
    con.execute("CREATE TABLE IF NOT EXISTS ia_consumo_historico (dia TEXT PRIMARY KEY, custo_brl REAL NOT NULL, fonte TEXT)")
    if _config(con, "historico_semeado") is None:  # 1ª vez: já entra com o passado do AI Studio e o saldo
        con.executemany("INSERT OR IGNORE INTO ia_consumo_historico (dia, custo_brl, fonte) VALUES (?, ?, ?)",
                        [(d, v, "AI Studio (gráfico, aproximado)") for d, v in HISTORICO_INICIAL.items()])
        if _config(con, "saldo") is None:
            _set_config(con, "saldo", SALDO_INICIAL)
        _set_config(con, "historico_semeado", True)
        con.commit()
    return con


def _resumo(dias: int) -> dict:
    con = _conectar_com_historico()
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
        historico = con.execute("SELECT dia, custo_brl FROM ia_consumo_historico WHERE dia >= ?", (desde,)).fetchall()
        saldo = _config(con, "saldo")
        gasto_desde_saldo = 0.0
        if saldo:
            gasto_desde_saldo = (con.execute("SELECT SUM(custo_usd) FROM ia_consumo WHERE criado_em >= ?",
                                             (saldo["em"],)).fetchone()[0] or 0) * cot
        sete_dias = (datetime.utcnow() - timedelta(days=7)).isoformat(timespec="seconds")
        gasto_7d = (con.execute("SELECT SUM(custo_usd) FROM ia_consumo WHERE criado_em >= ?", (sete_dias,)).fetchone()[0] or 0) * cot
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
    por_dia = {(agora - timedelta(days=i)).strftime("%Y-%m-%d"): {"recorrente": vazio(), "treino": vazio(), "historico_brl": 0.0}
               for i in range(dias)}
    mes_historico = 0.0
    for dia, custo in historico:  # gasto de antes do observador (AI Studio): só o total do dia
        if dia >= ini_mes:
            mes_historico += custo
        if dia in por_dia:
            por_dia[dia]["historico_brl"] += custo
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
    projecao = mes_historico + mes_treino["custo_brl"] + mes_rec["custo_brl"] + media_rec_dia * (dias_mes - agora.day)

    # Saldo: o Google não tem API do saldo pré-pago - o usuário informa o saldo do AI Studio e o painel
    # desconta, em tempo real, o que o observador viu gastar desde então
    saldo_info = None
    if saldo:
        estimado = float(saldo["valor_brl"]) - gasto_desde_saldo
        dias_obs = 7
        if primeiro:
            dias_obs = max(1, min(7, (datetime.utcnow() - datetime.fromisoformat(primeiro)).total_seconds() / 86400))
        media_total_dia = gasto_7d / dias_obs
        saldo_info = {
            "informado_brl": float(saldo["valor_brl"]), "informado_em": saldo["em"], "gasto_desde_brl": gasto_desde_saldo,
            "estimado_brl": estimado,
            "dias_no_ritmo_atual": (estimado / media_total_dia) if media_total_dia > 0.01 else None,
            "dias_no_dia_a_dia": (estimado / media_rec_dia) if media_rec_dia > 0.01 else None,
        }

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
        "mes": dict(tot_mes, custo_brl=tot_mes["custo_brl"] + mes_historico),
        "mes_historico_brl": mes_historico,
        "saldo": saldo_info,
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


@router.post("/saldo")
async def informar_saldo(payload: dict, admin_user: User = Depends(get_admin_user)):
    """Saldo atual mostrado no Google AI Studio (Faturamento) - a partir dele o painel desconta o gasto em tempo real."""
    try:
        valor = float(payload.get("valor_brl"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Informe o saldo em R$")

    def _salvar():
        con = _conectar_com_historico()
        try:
            _set_config(con, "saldo", {"valor_brl": valor, "em": datetime.utcnow().isoformat(timespec="seconds")})
            con.commit()
        finally:
            con.close()
    await asyncio.to_thread(_salvar)
    return {"ok": True}


@router.get("/historico")
async def listar_historico(admin_user: User = Depends(get_admin_user)):
    def _ler():
        con = _conectar_com_historico()
        try:
            return [{"dia": d, "custo_brl": c, "fonte": f} for d, c, f in
                    con.execute("SELECT dia, custo_brl, fonte FROM ia_consumo_historico ORDER BY dia").fetchall()]
        finally:
            con.close()
    return await asyncio.to_thread(_ler)


@router.post("/historico")
async def salvar_historico(payload: dict, admin_user: User = Depends(get_admin_user)):
    """Lança/corrige o gasto de um dia anterior ao observador (valor do AI Studio)."""
    try:
        dia = datetime.strptime(str(payload.get("dia")), "%Y-%m-%d").strftime("%Y-%m-%d")
        custo = float(payload.get("custo_brl"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Informe o dia (AAAA-MM-DD) e o valor em R$")

    def _salvar():
        con = _conectar_com_historico()
        try:
            con.execute("INSERT OR REPLACE INTO ia_consumo_historico (dia, custo_brl, fonte) VALUES (?, ?, 'AI Studio (lançado no painel)')",
                        (dia, custo))
            con.commit()
        finally:
            con.close()
    await asyncio.to_thread(_salvar)
    return {"ok": True}


@router.delete("/historico/{dia}")
async def apagar_historico(dia: str, admin_user: User = Depends(get_admin_user)):
    def _apagar():
        con = _conectar_com_historico()
        try:
            con.execute("DELETE FROM ia_consumo_historico WHERE dia = ?", (dia,))
            con.commit()
        finally:
            con.close()
    await asyncio.to_thread(_apagar)
    return {"ok": True}
