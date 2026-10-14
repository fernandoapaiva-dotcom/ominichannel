"""
Lê as VISTAS EXPLODIDAS (tabela de peças em imagem) com o Gemini e põe as peças no catálogo do
bibliotecário do Copiloto - ver app/services/parts_vision_service.py. Pedido do usuário em 13/10/2026,
depois de terminar o treino da Balmer: "vamos programar a segunda parte... deixar rodando na
madrugada".

Roda como processo de fundo no PM2 e só trabalha na MESMA janela do treino do RAG (18h às 7h50 em
dia útil; dia inteiro no fim de semana/feriado) - fora dela fica esperando. Um PDF por vez. Cada PDF
lido fica registrado (catalogo_visao_docs) e não é lido de novo; os que deram erro são tentados de
novo na noite seguinte. Vista explodida nova que chegar na pasta entra sozinha na próxima rodada.

    pm2 start venv/bin/python3 --name catalogo-vistas --cwd /home/administrator/ominichannel/backend -- scripts/catalogo_vistas_explodidas.py
    pm2 save

Teste (lê N PDFs agora, fora da janela, e mostra o que achou):
    venv/bin/python scripts/catalogo_vistas_explodidas.py --teste 3

Custo x qualidade (14/10/2026 - "quero baratear mas sem perder a qualidade do ensino"):
    venv/bin/python scripts/catalogo_vistas_explodidas.py --comparar 5
relê 5 PDFs já lidos com cada configuração de parts_vision_service.CONFIGS, compara as peças com as
da 1ª leitura (completa) e APROVA a mais barata que concordar tanto quanto a própria completa relida
(mínimo 98%, ou a variação natural da completa). A madrugada passa a usar a aprovada; resultado
suspeito em PDF é relido na completa. Teto de gasto por noite (--teto R$) e parada quando o crédito
acaba (o PDF não é marcado e entra de novo quando houver crédito).
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, time as dtime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.models.models import PartsCatalogItem  # noqa: E402
from app.services.librarian_service import norm  # noqa: E402
from app.services.os_board_followup_service import _FERIADOS_NACIONAIS  # noqa: E402
from app.services import ia_consumo_service as obs  # noqa: E402
from app.services.parts_vision_service import (  # noqa: E402
    CONFIGS, MIN_CONCORDANCIA, ORDEM_CONFIGS, PALAVRAS_VISTA, VisaoDoc, VisaoPeca, _texto_do_pdf, extrair_pecas,
    ler_vista, motivo_suspeito, norm_codigo,
)
from scripts.ingest_rag_docs import doc_id_for_path, iter_target_files  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
for ruidoso in ("httpx", "google_genai", "google", "urllib3"):
    logging.getLogger(ruidoso).setLevel(logging.WARNING)
logger = logging.getLogger("catalogo_vistas")

ROOTS = [
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/DOC. TÉCNICOS",
    "/mnt/softsystem_drive/Documentos/ASSISTENCIA/ONDA DE CIRCUITO",
]
TENANT_ID = 1
INICIO_PROTEGIDO, FIM_PROTEGIDO = dtime(7, 50), dtime(18, 0)
CONFIG_PADRAO = {"modo": "completo", "teto_noite_brl": 15.0}


def ler_config() -> dict:
    """Configuração aprovada + teto por noite (guardada em ia_consumo_config, chave 'catalogo_vistas')."""
    cfg = dict(CONFIG_PADRAO)
    try:
        con = obs._conectar()
        row = con.execute("SELECT valor FROM ia_consumo_config WHERE chave = 'catalogo_vistas'").fetchone()
        con.close()
        if row:
            cfg.update(json.loads(row[0]))
    except Exception as e:
        logger.warning(f"[CONFIG] usando a padrão: {e}")
    if cfg.get("modo") not in CONFIGS:
        cfg["modo"] = "completo"
    return cfg


def salvar_config(cfg: dict) -> None:
    con = obs._conectar()
    con.execute("INSERT OR REPLACE INTO ia_consumo_config (chave, valor) VALUES ('catalogo_vistas', ?)", (json.dumps(cfg, ensure_ascii=False),))
    con.commit()
    con.close()


def _agora_brt() -> datetime:
    return datetime.utcnow() - timedelta(hours=3)


def na_janela() -> bool:
    """Mesma regra do treino do RAG (scripts/watch_rag_docs.py): só não roda em dia útil das 7h50 às 18h."""
    agora = _agora_brt()
    dia_util = agora.weekday() < 5 and agora.strftime("%Y-%m-%d") not in _FERIADOS_NACIONAIS
    return not (dia_util and INICIO_PROTEGIDO <= agora.time() < FIM_PROTEGIDO)


async def _com_retentativa(fn):
    """SQLite compartilhado com o backend: tenta de novo se o banco estiver ocupado."""
    for tentativa in range(6):
        try:
            return await fn()
        except Exception as e:
            if "locked" in str(e).lower() and tentativa < 5:
                await asyncio.sleep(1 + tentativa)
                continue
            raise


async def candidatos(tentados_hoje: set) -> list:
    async with AsyncSessionLocal() as db:
        feitos = set((await db.execute(select(VisaoDoc.parent_doc_id).where(VisaoDoc.status.in_(("ok", "sem_tabela", "grande"))))).scalars().all())
        # Já tem tabela de peças lida do TEXTO (3+ peças): não precisa ler por imagem
        com_texto = set((await db.execute(
            select(PartsCatalogItem.parent_doc_id).where(PartsCatalogItem.tenant_id == TENANT_ID)
            .group_by(PartsCatalogItem.parent_doc_id).having(func.count(PartsCatalogItem.id) >= 3)
        )).scalars().all())
    lista = await asyncio.to_thread(lambda: list(iter_target_files(ROOTS)))
    out = []
    for caminho, marca, modelo, fname in lista:
        if not fname.lower().endswith(".pdf"):
            continue
        nome = norm(f"{modelo} {fname}")
        if not any(p in nome for p in PALAVRAS_VISTA):
            continue
        doc_id = doc_id_for_path(caminho)
        if doc_id in feitos or doc_id in com_texto or doc_id in tentados_hoje:
            continue
        out.append((caminho, marca, modelo, fname, doc_id))
    return out


async def processar(caminho, marca, modelo, fname, doc_id, mostrar=False, nome_config="completo") -> tuple:
    """(status, custo_brl). 'sem_credito' não grava nada (o PDF fica para depois)."""
    titulo = " / ".join(p for p in (marca, modelo, fname) if p)
    with open(caminho, "rb") as f:
        dados = f.read()
    status, pecas, detalhe, custo = await extrair_pecas(dados, titulo, settings.GEMINI_API_KEY, nome_config)
    if status == "sem_credito":
        logger.warning(f"[SEM CRÉDITO] {titulo}: {detalhe}")
        return status, custo

    async def gravar():
        async with AsyncSessionLocal() as db:
            await db.execute(delete(VisaoPeca).where(VisaoPeca.parent_doc_id == doc_id))
            await db.execute(delete(PartsCatalogItem).where(PartsCatalogItem.parent_doc_id == doc_id))
            comum = dict(tenant_id=TENANT_ID, parent_doc_id=doc_id, titulo=titulo[:255], filename=fname[:255],
                         marca=marca or None, source_path=caminho)
            for p in pecas:
                campos = dict(comum, item=p["item"], codigo=p["codigo"], part_number=p["part_number"],
                              descricao=p["descricao"], descricao_norm=norm(p["descricao"])[:255])
                db.add(VisaoPeca(**campos))
                db.add(PartsCatalogItem(**campos))
            reg = (await db.execute(select(VisaoDoc).where(VisaoDoc.parent_doc_id == doc_id))).scalar_one_or_none()
            if not reg:
                reg = VisaoDoc(parent_doc_id=doc_id, filename=fname[:255], status=status)
                db.add(reg)
            reg.status, reg.n_pecas, reg.detalhe, reg.processado_em = status, len(pecas), detalhe, datetime.utcnow()
            await db.commit()

    await _com_retentativa(gravar)
    logger.info(f"[VISTA] {titulo}: {status} - {len(pecas)} peça(s) - {detalhe} - R$ {custo:.3f}")
    if mostrar:
        for p in pecas[:8]:
            print(f"      {p['item'] or '-':>4} | {p['codigo']:<16} | {p['part_number'] or '':<14} | {p['descricao'][:60]}")
        if len(pecas) > 8:
            print(f"      ... +{len(pecas) - 8} peças")
    return status, custo


async def preparar():
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[VisaoDoc.__table__, VisaoPeca.__table__, PartsCatalogItem.__table__]))


async def teste(n: int):
    await preparar()
    lista = await candidatos(set())
    print(f"{len(lista)} vista(s) explodida(s) a ler. Testando {min(n, len(lista))}:")
    modo = ler_config()["modo"]
    for c in lista[:n]:
        print(f"\n  >> {c[1]} / {c[3]}  (configuração: {modo})")
        await processar(*c, mostrar=True, nome_config=modo)


async def comparar(n: int):
    """Relê N PDFs já lidos (na completa) com cada configuração e aprova a mais barata que mantém a qualidade."""
    await preparar()
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(
            select(VisaoPeca.parent_doc_id, VisaoPeca.marca, VisaoPeca.source_path, VisaoPeca.titulo, func.count(VisaoPeca.id))
            .group_by(VisaoPeca.parent_doc_id).having(func.count(VisaoPeca.id).between(8, 150))
        )).all()
        refs = {}
        for d in docs:
            refs[d[0]] = (await db.execute(select(VisaoPeca.codigo).where(VisaoPeca.parent_doc_id == d[0]))).scalars().all()
    # variedade: um PDF por marca primeiro; se houver menos marcas que N (a 1ª noite leu quase só Balmer),
    # completa com outros PDFs, de tamanhos variados
    existentes = [d for d in sorted(docs, key=lambda d: d[0]) if os.path.exists(d[2] or "")]
    escolhidos, marcas = [], set()
    for d in existentes:
        if d[1] not in marcas:
            escolhidos.append(d)
            marcas.add(d[1])
    resto = sorted((d for d in existentes if d not in escolhidos), key=lambda d: d[4])  # por nº de peças
    faltam = min(n - len(escolhidos), len(resto))
    if faltam > 0:  # espalhados do menor ao maior
        passo = len(resto) / faltam
        escolhidos += [resto[int(i * passo + passo / 2)] for i in range(faltam)]
    escolhidos = escolhidos[:n]
    if not escolhidos:
        print("Nenhum PDF já lido para comparar.")
        return
    print(f"Comparando {len(escolhidos)} PDF(s) já lidos ({', '.join(str(d[1]) for d in escolhidos)}) "
          f"em {len(ORDEM_CONFIGS)} configurações...\n")
    res = {nome: {"bate": 0, "base": 0, "custo": 0.0, "suspeitos": 0, "lidos": 0} for nome in ORDEM_CONFIGS}
    for doc_id, marca, caminho, titulo, _ in escolhidos:
        with open(caminho, "rb") as f:
            dados = f.read()
        texto = _texto_do_pdf(dados)
        ref = {norm_codigo(c) for c in refs[doc_id]}
        print(f"  >> {titulo[:90]}  ({len(ref)} peças na 1ª leitura)")
        for nome in ORDEM_CONFIGS:
            r = await ler_vista(dados, titulo, settings.GEMINI_API_KEY, nome)
            if r["status"] == "sem_credito":
                print("\n!! Crédito da IA esgotado - recarregue no Google AI Studio e rode de novo. Nada foi alterado.")
                return
            cand = {norm_codigo(p["codigo"]) for p in r["pecas"]}
            bate, base = len(ref & cand), max(len(ref), len(cand))
            susp = motivo_suspeito(r["pecas"], texto) if nome != "completo" else None
            acc = res[nome]
            acc["bate"] += bate
            acc["base"] += base
            acc["custo"] += r["custo_brl"]
            acc["lidos"] += 1
            acc["suspeitos"] += 1 if (susp or r["status"] == "erro") else 0
            print(f"     {nome:<15} {bate:>3}/{base:<3} peças batem  R$ {r['custo_brl']:.4f}"
                  + (f"  ERRO: {r['erro'][:80]}" if r["status"] == "erro" else "")
                  + (f"  (seria relido: {susp})" if susp else ""))
    custo_completo = res["completo"]["custo"] / max(1, res["completo"]["lidos"])
    conc_completo = res["completo"]["bate"] / max(1, res["completo"]["base"])
    # A completa relida também varia um pouco: a barata precisa concordar tanto quanto ela (e nunca menos de 90%)
    exigido = max(0.90, min(MIN_CONCORDANCIA, conc_completo - 0.01))
    print(f"\nA própria configuração completa, relida, concorda {conc_completo:.1%} com a 1ª leitura -> exigido: {exigido:.1%}\n")
    print(f"  {'configuração':<15} {'concordância':>12} {'R$/PDF':>9} {'relidos':>8} {'R$/PDF real*':>13}")
    aprovadas, resumo = [], {}
    for nome in ORDEM_CONFIGS:
        a = res[nome]
        conc = a["bate"] / max(1, a["base"])
        taxa = a["suspeitos"] / max(1, a["lidos"])
        efetivo = a["custo"] / max(1, a["lidos"]) + (taxa * custo_completo if nome != "completo" else 0)
        ok = nome == "completo" or conc >= exigido
        resumo[nome] = {"concordancia": round(conc, 4), "custo_pdf_brl": round(efetivo, 4), "relidos": round(taxa, 3), "aprovada": ok}
        if ok:
            aprovadas.append((efetivo, nome))
        print(f"  {nome:<15} {conc:>11.1%} {a['custo'] / max(1, a['lidos']):>9.4f} {taxa:>7.0%} {efetivo:>13.4f}  "
              f"{'APROVADA' if ok else 'reprovada'}")
    print("  * custo real = leitura + releitura na completa quando o resultado é suspeito")
    efetivo, escolhida = min(aprovadas)
    cfg = ler_config()
    cfg.update(modo=escolhida, comparacao={"em": datetime.utcnow().isoformat(timespec="seconds"), "pdfs": len(escolhidos),
                                           "exigido": exigido, "resultado": resumo})
    salvar_config(cfg)
    restantes = len(await candidatos(set()))
    print(f"\n>> Configuração aprovada para a madrugada: {escolhida.upper()} ({CONFIGS[escolhida]['modelo']})")
    print(f">> Faltam {restantes} vista(s) explodida(s): estimativa de R$ {restantes * efetivo:.2f} para terminar "
          f"(R$ {efetivo:.3f} por PDF; teto por noite R$ {cfg['teto_noite_brl']:.2f})")


def _noite() -> str:
    """Identifica a noite: o gasto da madrugada conta para o dia em que ela começou."""
    agora = _agora_brt()
    return (agora.date() - timedelta(days=1 if agora.time() < INICIO_PROTEGIDO else 0)).isoformat()


async def loop():
    await preparar()
    tentados_hoje: set = set()
    dia = _agora_brt().date()
    noite, gasto_noite = _noite(), 0.0
    while True:
        if _agora_brt().date() != dia:  # novo dia: os que deram erro podem ser tentados de novo
            dia, tentados_hoje = _agora_brt().date(), set()
        if _noite() != noite:
            noite, gasto_noite = _noite(), 0.0
        if not na_janela():
            await asyncio.sleep(600)
            continue
        cfg = ler_config()
        if gasto_noite >= cfg["teto_noite_brl"]:
            await asyncio.sleep(600)
            continue
        lista = await candidatos(tentados_hoje)
        if not lista:
            await asyncio.sleep(3600)
            continue
        logger.info(f"[JANELA LIVRE] {len(lista)} vista(s) explodida(s) na fila - configuração {cfg['modo']}, "
                    f"gasto da noite R$ {gasto_noite:.2f} de R$ {cfg['teto_noite_brl']:.2f}")
        cont = {"ok": 0, "sem_tabela": 0, "erro": 0, "grande": 0, "sem_credito": 0}
        pausa = 2
        for c in lista:
            if not na_janela():
                logger.info(f"[JANELA] Horário comercial começou - parei; {cont}")
                break
            if gasto_noite >= cfg["teto_noite_brl"]:
                logger.info(f"[TETO] Gasto da noite chegou a R$ {gasto_noite:.2f} - continuo na próxima noite; {cont}")
                break
            tentados_hoje.add(c[4])
            try:
                status, custo = await processar(*c, nome_config=cfg["modo"])
            except Exception as e:
                cont["erro"] += 1
                logger.error(f"[ERRO] {c[3]}: {e}")
                continue
            gasto_noite += custo
            cont[status] += 1
            if status == "sem_credito":
                tentados_hoje.discard(c[4])  # não foi lido: entra de novo quando houver crédito
                logger.warning(f"[SEM CRÉDITO] Crédito da IA esgotado - parei, tento de novo em 1 hora; {cont}")
                pausa = 3600
                break
            await asyncio.sleep(2)
        else:
            logger.info(f"[FILA] Rodada concluída: {cont}")
        await asyncio.sleep(pausa)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", type=int, default=0, help="lê N PDFs agora (fora da janela) e mostra as peças")
    ap.add_argument("--comparar", type=int, default=0, help="compara as configurações em N PDFs já lidos e aprova a mais barata sem perder qualidade")
    ap.add_argument("--teto", type=float, default=None, help="define o gasto máximo por noite, em R$")
    args = ap.parse_args()
    if args.teto is not None:
        _cfg = ler_config()
        _cfg["teto_noite_brl"] = args.teto
        salvar_config(_cfg)
        print(f"Teto por noite: R$ {args.teto:.2f}")
    elif args.comparar:
        asyncio.run(comparar(args.comparar))
    else:
        asyncio.run(teste(args.teste) if args.teste else loop())
