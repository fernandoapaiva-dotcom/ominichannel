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
"""
import argparse
import asyncio
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
from app.services.parts_vision_service import PALAVRAS_VISTA, VisaoDoc, VisaoPeca, extrair_pecas  # noqa: E402
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


async def processar(caminho, marca, modelo, fname, doc_id, mostrar=False) -> str:
    titulo = " / ".join(p for p in (marca, modelo, fname) if p)
    with open(caminho, "rb") as f:
        dados = f.read()
    status, pecas, detalhe = await extrair_pecas(dados, titulo, settings.GEMINI_API_KEY)

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
    logger.info(f"[VISTA] {titulo}: {status} - {len(pecas)} peça(s)")
    if mostrar:
        for p in pecas[:8]:
            print(f"      {p['item'] or '-':>4} | {p['codigo']:<16} | {p['part_number'] or '':<14} | {p['descricao'][:60]}")
        if len(pecas) > 8:
            print(f"      ... +{len(pecas) - 8} peças")
    return status


async def preparar():
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[VisaoDoc.__table__, VisaoPeca.__table__, PartsCatalogItem.__table__]))


async def teste(n: int):
    await preparar()
    lista = await candidatos(set())
    print(f"{len(lista)} vista(s) explodida(s) a ler. Testando {min(n, len(lista))}:")
    for c in lista[:n]:
        print(f"\n  >> {c[1]} / {c[3]}")
        await processar(*c, mostrar=True)


async def loop():
    await preparar()
    tentados_hoje: set = set()
    dia = _agora_brt().date()
    while True:
        if _agora_brt().date() != dia:  # novo dia: os que deram erro podem ser tentados de novo
            dia, tentados_hoje = _agora_brt().date(), set()
        if not na_janela():
            await asyncio.sleep(600)
            continue
        lista = await candidatos(tentados_hoje)
        if not lista:
            await asyncio.sleep(3600)
            continue
        logger.info(f"[JANELA LIVRE] {len(lista)} vista(s) explodida(s) na fila")
        cont = {"ok": 0, "sem_tabela": 0, "erro": 0, "grande": 0}
        for c in lista:
            if not na_janela():
                logger.info(f"[JANELA] Horário comercial começou - parei; {cont}")
                break
            tentados_hoje.add(c[4])
            try:
                cont[await processar(*c)] += 1
            except Exception as e:
                cont["erro"] += 1
                logger.error(f"[ERRO] {c[3]}: {e}")
            await asyncio.sleep(2)
        else:
            logger.info(f"[FILA] Rodada concluída: {cont}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", type=int, default=0, help="lê N PDFs agora (fora da janela) e mostra as peças")
    args = ap.parse_args()
    asyncio.run(teste(args.teste) if args.teste else loop())
