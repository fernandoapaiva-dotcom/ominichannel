"""
Catálogo do site - etapas 5 (imagens, vídeos, PDFs) e 6 (e-commerce) da entrada de nota (15/10/2026).

/catalogo/...        administração no OminiChannel (login): fotos com fundo branco + marca d'água,
                     PDFs técnicos, vídeos do YouTube, textos da aba "Para Lojas Web" (gravados também
                     no Softsystem) e a marcação "publicar no site".
/public/site/...     leitura PÚBLICA (sem login) para o site da Hostinger, no mesmo formato que o site
                     servsolda_site já usava. Só devolve produtos marcados para o site; nunca custo.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, oauth2_scheme
from app.models.models import CatalogoMidia, CatalogoProduto, User
from app.services import catalogo_imagem_service as img
from app.services import catalogo_service as cat
from app.services.settings_service import settings_service
from app.services.softsystem_service import SoftsystemService

logger = logging.getLogger("catalogo_api")
router = APIRouter(prefix="/catalogo", tags=["Catálogo do site"])
public_router = APIRouter(prefix="/public/site", tags=["Site público"])

EMPRESAS = ("servweld", "centrooeste")


async def get_ator(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    """Atendente/admin (token do painel) OU técnico (token do Portal do Técnico) - o app Foto
    (/foto-os) aceita os dois logins; aqui vira um objeto com tenant_id e nome."""
    from types import SimpleNamespace
    from app.core.security import get_current_technician
    try:
        return await get_current_user(token=token, db=db)
    except HTTPException:
        tec = await get_current_technician(token=token, db=db)
        return SimpleNamespace(id=None, tenant_id=tec.tenant_id, nome=getattr(tec, "nome", None) or "Técnico", login=None, role=None)


def _empresa(e: str) -> str:
    """Catálogo ÚNICO (pedido do usuário em 15/10/2026): os produtos são os mesmos nos dois bancos
    (o Guardião do Softsystem replica o cadastro), então fotos, textos e site valem para as duas
    lojas - tudo fica guardado no catálogo da loja do site, venha a tela de qual empresa vier."""
    if e not in EMPRESAS:
        raise HTTPException(status_code=400, detail="Empresa inválida")
    return settings.SITE_EMPRESA


def _usuario(u: User) -> str:
    return (getattr(u, "nome", None) or getattr(u, "login", None) or "usuário")[:100]


def _modo_db() -> Optional[str]:
    """None = produção; caminho = cópia de teste; '' = gravação no Softsystem desligada."""
    modo = (settings.SOFTSYSTEM_COMPRAS_MODO or "desligado").strip().lower()
    if modo == "producao":
        return None
    if modo == "teste":
        return settings.SOFTSYSTEM_COMPRAS_DB_TESTE or ""
    return ""


async def _registro(db: AsyncSession, tenant_id: int, empresa: str, cod: int, criar: bool = False) -> Optional[CatalogoProduto]:
    r = await db.execute(select(CatalogoProduto).where(
        CatalogoProduto.tenant_id == tenant_id, CatalogoProduto.empresa == empresa, CatalogoProduto.codproduto == cod))
    reg = r.scalar_one_or_none()
    if not reg and criar:
        reg = CatalogoProduto(tenant_id=tenant_id, empresa=empresa, codproduto=cod, atualizado_em=datetime.utcnow())
        db.add(reg)
        await db.flush()
    return reg


async def _midias(db: AsyncSession, tenant_id: int, empresa: str, cod: int) -> List[CatalogoMidia]:
    r = await db.execute(select(CatalogoMidia).where(
        CatalogoMidia.tenant_id == tenant_id, CatalogoMidia.empresa == empresa, CatalogoMidia.codproduto == cod
    ).order_by(CatalogoMidia.ordem, CatalogoMidia.id))
    return list(r.scalars().all())


def _midia_dict(m: CatalogoMidia) -> Dict[str, Any]:
    return {"id": m.id, "tipo": m.tipo, "arquivo": m.arquivo, "miniatura": m.miniatura or m.arquivo, "original": m.original,
            "titulo": m.titulo, "ordem": m.ordem, "origem": m.origem, "url_origem": m.url_origem,
            "fundo_removido": m.fundo_removido, "criado_por": m.criado_por, "softsystem_codimagem": m.softsystem_codimagem,
            "criado_em": m.criado_em.isoformat() if m.criado_em else None}


def _pasta_softsystem(empresa: str) -> str:
    return settings.SOFTSYSTEM_IMAGENS_DIR_SERVWELD if empresa == "servweld" else settings.SOFTSYSTEM_IMAGENS_DIR_CENTROOESTE


# A pasta "Arquivos" do Softsystem fica no SRV-SERVWELD (CIFS - a de My Drive é o Google Drive
# sincronizado no servidor) e tem MILHARES de arquivos (fotos de O.S., orçamentos...). Listar essas
# pastas inteiras travou a VM várias vezes em 15/10/2026 (engasgo de CIFS -> soft lockup; a 1ª queda
# veio 9 min depois de ligar as miniaturas). Então NUNCA lista a pasta: os números das fotos vêm do
# banco (PRODUTOSIMAGENS) e só se confere se AQUELE arquivo existe ("Produto {cod} {numero}.jpg").
_EXTENSOES_FOTO = (".jpg", ".JPG", ".jpeg", ".png")


def _numeros_fotos(cods: List[int], so_ativas: bool) -> Dict[int, set]:
    """{cod: números de foto} somando os dois bancos (o da Centro-Oeste tem fotos próprias)."""
    res: Dict[int, set] = {int(c): set() for c in cods}
    if not cods:
        return res
    marcas = ", ".join("?" for _ in cods)
    filtro = " AND COALESCE(EXCLUIDO, 'F') <> 'T'" if so_ativas else ""
    for emp in ("servweld", "centrooeste"):
        try:
            for c, n in SoftsystemService._consultar(
                    emp, f"SELECT CODPRODUTO, CODIMAGEM FROM PRODUTOSIMAGENS WHERE CODPRODUTO IN ({marcas}){filtro}",
                    tuple(int(x) for x in cods)):
                res.setdefault(int(c), set()).add(int(n))
        except Exception as e:
            logger.warning(f"[CATALOGO] Fotos do Softsystem ({emp}) indisponíveis: {e}")
    return res


def _fotos_por_numeros(cod: int, numeros) -> List[tuple]:
    """[(pasta, nome)] conferindo arquivo a arquivo (stat) nas pastas das duas lojas - sem listar pasta."""
    pastas = [p for p in (settings.SOFTSYSTEM_IMAGENS_DIR_SERVWELD, settings.SOFTSYSTEM_IMAGENS_DIR_CENTROOESTE) if p]
    res = []
    for n in sorted(numeros):
        achou = None
        for pasta in pastas:
            for ext in _EXTENSOES_FOTO:
                nome = f"Produto {int(cod)} {int(n)}{ext}"
                try:
                    if os.path.isfile(os.path.join(pasta, nome)):
                        achou = (pasta, nome)
                        break
                except OSError:
                    continue
            if achou:
                break
        if achou:
            res.append(achou)
    return res


def _fotos_softsystem(empresa: str, cod: int, so_ativas: bool = False) -> List[tuple]:
    """[(pasta, nome)] das fotos do produto (as excluídas entram quando so_ativas=False - dá para
    trazer de volta pelo "Importar fotos do Softsystem")."""
    return _fotos_por_numeros(cod, _numeros_fotos([cod], so_ativas).get(int(cod), set()))


def _codimagem_do_nome(nome: Optional[str]) -> Optional[int]:
    m = re.match(r"^Produto \d+ (\d+)\.", nome or "")
    return int(m.group(1)) if m else None


def _serializar(reg: Optional[CatalogoProduto], web_soft: Dict[str, Any]) -> Dict[str, Any]:
    if reg:
        return {
            "publicar_site": reg.publicar_site, "destaque": reg.destaque, "titulo_web": reg.titulo_web,
            "descricao_web": reg.descricao_web, "especificacoes": json.loads(reg.especificacoes_json or "[]"),
            "videos": json.loads(reg.videos_json or "[]"), "keywords": reg.keywords, "dica": reg.dica,
            "material": reg.material, "cor": reg.cor, "garantia": reg.garantia, "frete_gratis": reg.frete_gratis,
            "nunca_mostra_preco": reg.nunca_mostra_preco, "desconto_web_pct": reg.desconto_web_pct,
            "atualizado_por": reg.atualizado_por, "atualizado_em": reg.atualizado_em.isoformat() if reg.atualizado_em else None,
            "softsystem_sincronizado_em": reg.softsystem_sincronizado_em.isoformat() if reg.softsystem_sincronizado_em else None,
            "softsystem_erro": reg.softsystem_erro, "novo": False,
        }
    # ainda não está no catálogo: pré-preenche com o que já existe no Softsystem (aba Para Lojas Web)
    return {
        "publicar_site": bool(web_soft.get("mostrar_na_web")), "destaque": False, "titulo_web": web_soft.get("titulo_web"),
        "descricao_web": web_soft.get("descricao_web"), "especificacoes": [],
        "videos": [{"titulo": "", "url": v, "youtube_id": cat.youtube_id(v)} for v in web_soft.get("videos") or []],
        "keywords": web_soft.get("keywords"), "dica": web_soft.get("dica"), "material": web_soft.get("material"),
        "cor": web_soft.get("cor"), "garantia": None, "frete_gratis": bool(web_soft.get("frete_gratis")),
        "nunca_mostra_preco": bool(web_soft.get("nunca_mostra_preco")), "desconto_web_pct": web_soft.get("desconto_web_pct"),
        "novo": True,
    }


# ================================================================== administração
@router.get("/produto/{cod}")
async def obter_produto(cod: int, empresa: str = Query("servweld"), db: AsyncSession = Depends(get_db),
                        current_user=Depends(get_ator)):
    emp = _empresa(empresa)
    try:
        sw = (await asyncio.to_thread(cat.produtos_softsystem, emp, [cod], False)).get(cod)
        web_soft = await asyncio.to_thread(cat.produtosweb_softsystem, emp, cod)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")
    if not sw:
        raise HTTPException(status_code=404, detail=f"Produto {cod} não existe no Softsystem.")
    reg = await _registro(db, current_user.tenant_id, emp, cod)
    midias = await _midias(db, current_user.tenant_id, emp, cod)
    fotos_soft = [n for _, n in await asyncio.to_thread(_fotos_softsystem, emp, cod)]
    return {"success": True, "softsystem": sw, "catalogo": _serializar(reg, web_soft),
            "midias": [_midia_dict(m) for m in midias], "fotos_softsystem": fotos_soft,
            "pasta_softsystem_configurada": any(p and os.path.isdir(p) for p in (settings.SOFTSYSTEM_IMAGENS_DIR_SERVWELD, settings.SOFTSYSTEM_IMAGENS_DIR_CENTROOESTE))}


class CatalogoPayload(BaseModel):
    publicar_site: bool = False
    destaque: bool = False
    titulo_web: Optional[str] = None
    descricao_web: Optional[str] = None
    especificacoes: List[Dict[str, Any]] = []
    videos: List[Dict[str, Any]] = []
    keywords: Optional[str] = None
    dica: Optional[str] = None
    material: Optional[str] = None
    cor: Optional[str] = None
    garantia: Optional[str] = None
    frete_gratis: bool = False
    nunca_mostra_preco: bool = False
    desconto_web_pct: Optional[float] = None


@router.put("/produto/{cod}")
async def salvar_produto(cod: int, payload: CatalogoPayload, empresa: str = Query("servweld"),
                         db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    emp = _empresa(empresa)
    videos = []
    for v in payload.videos:
        url = (v.get("url") or "").strip()
        if not url:
            continue
        yid = cat.youtube_id(url)
        if not yid:
            raise HTTPException(status_code=400, detail=f"Link de vídeo inválido (precisa ser do YouTube): {url}")
        videos.append({"titulo": (v.get("titulo") or "").strip()[:150], "url": f"https://www.youtube.com/watch?v={yid}", "youtube_id": yid})
    specs = [{"nome": str(s.get("nome") or "").strip()[:80], "valor": str(s.get("valor") or "").strip()[:200]}
             for s in payload.especificacoes if str(s.get("nome") or "").strip() and str(s.get("valor") or "").strip()]
    if payload.desconto_web_pct is not None and not (0 <= payload.desconto_web_pct <= 90):
        raise HTTPException(status_code=400, detail="Desconto web precisa ficar entre 0 e 90%.")
    if payload.publicar_site:
        midias = await _midias(db, current_user.tenant_id, emp, cod)
        if not any(m.tipo == "imagem" for m in midias):
            raise HTTPException(status_code=400, detail="Para publicar no site, cadastre pelo menos uma foto.")

    reg = await _registro(db, current_user.tenant_id, emp, cod, criar=True)
    for campo in ("publicar_site", "destaque", "titulo_web", "descricao_web", "keywords", "dica", "material", "cor",
                  "garantia", "frete_gratis", "nunca_mostra_preco", "desconto_web_pct"):
        val = getattr(payload, campo)
        setattr(reg, campo, val.strip() if isinstance(val, str) else val)
    reg.especificacoes_json = json.dumps(specs, ensure_ascii=False)
    reg.videos_json = json.dumps(videos, ensure_ascii=False)
    reg.atualizado_em = datetime.utcnow()
    reg.atualizado_por = _usuario(current_user)

    # aba "Para Lojas Web" do Softsystem (respeita o modo de gravação do servidor)
    destino = _modo_db()
    aviso = None
    if destino == "":
        aviso = "Gravação no Softsystem desligada neste servidor - salvo só no OminiChannel."
    else:
        try:
            dados = {**payload.dict(), "titulo_web": reg.titulo_web, "descricao_web": reg.descricao_web}
            await asyncio.to_thread(cat.gravar_web_softsystem, emp, cod, dados, [v["url"] for v in videos], destino)
            reg.softsystem_sincronizado_em = datetime.utcnow()
            reg.softsystem_erro = None
        except Exception as e:
            logger.error(f"[CATALOGO] Falha ao gravar PRODUTOSWEB do {cod}: {e}", exc_info=True)
            reg.softsystem_erro = str(e)[:500]
            aviso = f"Salvo no OminiChannel, mas não foi para o Softsystem agora ({e})."
    await db.commit()
    _cache_site.clear()
    return {"success": True, "aviso": aviso, "teste": destino not in (None, "")}


@router.post("/produto/{cod}/imagens")
async def enviar_imagens(cod: int, empresa: str = Form("servweld"), links: str = Form(""), remover_fundo: bool = Form(True),
                         modo: str = Form("local"), arquivos: List[UploadFile] = File(default=[]), db: AsyncSession = Depends(get_db),
                         current_user=Depends(get_ator)):
    """Fotos por upload e/ou links (um por linha): fundo branco + marca d'água Servsolda."""
    emp = _empresa(empresa)
    entradas = []
    for a in arquivos[:10]:
        dados = await a.read()
        if len(dados) > img.MAX_BYTES:
            raise HTTPException(status_code=400, detail=f"{a.filename}: arquivo maior que 15 MB.")
        entradas.append(("upload", a.filename, dados))
    for url in [l.strip() for l in (links or "").splitlines() if l.strip()][:10]:
        try:
            dados, _ = await asyncio.to_thread(img.baixar, url, ("image/",))
        except img.ImagemErro as e:
            raise HTTPException(status_code=400, detail=f"{url[:80]}: {e}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Não deu para baixar {url[:80]}: {e}")
        entradas.append(("link", url, dados))
    if not entradas:
        raise HTTPException(status_code=400, detail="Envie pelo menos uma foto ou um link.")
    return await _gravar_fotos(db, current_user, emp, cod, entradas, remover_fundo, ia=(modo == "ia"))


async def _chave_ia(db: AsyncSession, tenant_id: int) -> Optional[str]:
    decrypted = await settings_service.get_tenant_decrypted_settings(db, tenant_id)
    return decrypted.get("gemini_api_key") or settings.GEMINI_API_KEY


async def _tratar(db, tenant_id: int, emp: str, cod: int, dados: bytes, remover_fundo: bool, ia: bool):
    """(jpg, mini, fundo_removido, usou_ia, aviso). Com IA: foto de venda; se a IA falhar, cai no
    tratamento local (fundo branco + marca d'água) e avisa."""
    if ia:
        try:
            sw = (await asyncio.to_thread(cat.produtos_softsystem, emp, [cod])).get(cod) or {}
            venda = await asyncio.wait_for(asyncio.to_thread(
                img.foto_venda_ia, dados, await _chave_ia(db, tenant_id), sw.get("descricao") or ""), timeout=90)
            jpg, mini, _ = await asyncio.to_thread(img.processar, venda, True, True)  # fundo da IA não é branco puro
            return jpg, mini, True, True, None
        except Exception as e:
            logger.warning(f"[CATALOGO] Foto de venda pela IA falhou ({cod}): {e}")
            jpg, mini, rem = await asyncio.to_thread(img.processar, dados, remover_fundo)
            return jpg, mini, rem, False, f"IA indisponível agora ({str(e)[:80]}) - usei o fundo branco automático"
    jpg, mini, rem = await asyncio.to_thread(img.processar, dados, remover_fundo)
    return jpg, mini, rem, False, None


async def _gravar_fotos(db, current_user, emp, cod, entradas, remover_fundo, ia: bool = False) -> Dict[str, Any]:
    existentes = await _midias(db, current_user.tenant_id, emp, cod)
    ordem = max([m.ordem for m in existentes] + [0])
    novas, erros = [], []
    for origem, nome, dados in entradas:
        try:
            jpg, mini, removido, usou_ia, aviso = await _tratar(db, current_user.tenant_id, emp, cod, dados, remover_fundo, ia)
        except img.ImagemErro as e:
            erros.append(f"{nome}: {e}")
            continue
        if aviso:
            erros.append(f"{nome}: {aviso}")
        ext = "png" if dados[:4] == b"\x89PNG" else "jpg"
        m = CatalogoMidia(
            tenant_id=current_user.tenant_id, empresa=emp, codproduto=cod, tipo="imagem",
            arquivo=await asyncio.to_thread(img.salvar, emp, cod, jpg, "jpg"),
            miniatura=await asyncio.to_thread(img.salvar, emp, cod, mini, "jpg"),
            original=await asyncio.to_thread(img.salvar, emp, cod, dados, ext),
            titulo="Foto de venda (IA)" if usou_ia else None, ordem=(ordem := ordem + 1), origem=origem, url_origem=nome[:1000] if origem != "upload" else None,
            fundo_removido=removido, criado_em=datetime.utcnow(), criado_por=_usuario(current_user),
        )
        if origem == "softsystem":
            m.softsystem_codimagem = _codimagem_do_nome(nome)  # já está no Softsystem
        else:
            destino = _modo_db()
            if destino != "":
                try:
                    m.softsystem_codimagem = await asyncio.to_thread(cat.gravar_foto_softsystem, cod, jpg, destino)
                except Exception as e:
                    logger.error(f"[CATALOGO] Foto do {cod} não foi para o Softsystem: {e}", exc_info=True)
                    erros.append(f"{nome}: foto salva no catálogo, mas não foi para o Softsystem agora ({str(e)[:80]})")
        db.add(m)
        novas.append(m)
    await db.commit()
    # foto nova do OminiChannel vira A foto do produto no Softsystem: as antigas que não estão no
    # catálogo saem da frente nos dois bancos (ver aposentar_fotos_antigas)
    if any(m.origem != "softsystem" and m.softsystem_codimagem for m in novas) and _modo_db() != "":
        manter = {x.softsystem_codimagem for x in await _midias(db, current_user.tenant_id, emp, cod) if x.softsystem_codimagem}
        try:
            await asyncio.to_thread(cat.aposentar_fotos_antigas, cod, manter, _modo_db())
        except Exception as e:
            logger.warning(f"[CATALOGO] Fotos antigas do {cod} não retiradas: {e}")
            erros.append(f"as fotos antigas do Softsystem não foram retiradas agora ({str(e)[:60]})")
    _cache_site.clear()
    return {"success": True, "midias": [_midia_dict(m) for m in novas], "erros": erros}


@router.post("/produto/{cod}/retirar-fotos-softsystem")
async def retirar_fotos_softsystem(cod: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_ator)):
    """"A foto do Softsystem não é deste material": tira (EXCLUIDO='T', nos dois bancos) as fotos do
    produto que não são do catálogo do OminiChannel. O arquivo fica na pasta (dá para voltar)."""
    destino = _modo_db()
    if destino == "":
        raise HTTPException(status_code=400, detail="Gravação no Softsystem desligada neste servidor.")
    emp = settings.SITE_EMPRESA
    manter = {m.softsystem_codimagem for m in await _midias(db, current_user.tenant_id, emp, cod)
              if m.softsystem_codimagem and m.origem != "softsystem"}
    try:
        feitas = await asyncio.to_thread(cat.aposentar_fotos_antigas, cod, manter, destino)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao gravar no Softsystem: {e}")
    # a foto do Softsystem que estava no catálogo (importada) também sai
    for m in await _midias(db, current_user.tenant_id, emp, cod):
        if m.origem == "softsystem" and m.tipo == "imagem":
            for c in (m.arquivo, m.miniatura, m.original):
                await asyncio.to_thread(img.apagar, c)
            await db.delete(m)
    await db.commit()
    _cache_site.clear()
    logger.info(f"[CATALOGO] Fotos do Softsystem retiradas do {cod} por {_usuario(current_user)}: {feitas}")
    total = sum(len(v) for v in feitas.values())
    return {"success": True, "retiradas": feitas, "mensagem": f"{total} foto(s) retirada(s) do Softsystem." if total else "Nenhuma foto para retirar."}


class LocalizacaoPayload(BaseModel):
    localizacao: str


@router.get("/app/localizacao/{cod}")
async def ver_localizacao(cod: int, current_user=Depends(get_ator)):
    """Localização e estoque do produto nas duas lojas (app Foto)."""
    return {"success": True, "lojas": await asyncio.to_thread(cat.localizacao_produto, cod)}


@router.put("/app/localizacao/{cod}")
async def gravar_localizacao_app(cod: int, payload: LocalizacaoPayload, current_user=Depends(get_ator)):
    """Estoquista fotografando a peça já grava onde ela fica: Localização 1 nos DOIS bancos (pedido de
    15/10/2026 - o Guardião não replica localização). Em teste só na cópia da Servweld."""
    from app.services.softsystem_compra_writer import gravar_localizacao
    loc = (payload.localizacao or "").strip().upper()[:60]
    if not loc:
        raise HTTPException(status_code=400, detail="Digite a localização.")
    destino = _modo_db()
    if destino == "":
        raise HTTPException(status_code=400, detail="Gravação no Softsystem desligada neste servidor.")
    operador = (_usuario(current_user).split() or ["OMINICHANNEL"])[0].upper()[:20]
    feitas, sem_estoque = [], []
    for emp in (("servweld",) if destino else ("servweld", "centrooeste")):
        try:
            r = await asyncio.to_thread(gravar_localizacao, emp, {cod: loc}, operador, destino if emp == "servweld" else None)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erro ao gravar no Softsystem ({emp}): {e}")
        (feitas if r["gravados"] else sem_estoque).append({"servweld": "Servweld", "centrooeste": "Centro-Oeste"}[emp])
    logger.info(f"[CATALOGO] Localização do {cod} = {loc} por {operador} (app Foto): {feitas}")
    msg = f"Localização {loc} gravada: {', '.join(feitas) or 'nenhuma loja'}."
    if sem_estoque:
        msg += f" Sem cadastro de estoque em: {', '.join(sem_estoque)}."
    return {"success": True, "mensagem": msg, "lojas": await asyncio.to_thread(cat.localizacao_produto, cod)}


@router.post("/produto/{cod}/importar-softsystem")
async def importar_fotos_softsystem(cod: int, empresa: str = Query("servweld"), remover_fundo: bool = Query(False),
                                    db: AsyncSession = Depends(get_db), current_user=Depends(get_ator)):
    """Traz as fotos que o produto já tem no Softsystem (pasta Arquivos) para o catálogo."""
    emp = _empresa(empresa)
    achadas = await asyncio.to_thread(_fotos_softsystem, emp, cod)
    if not achadas:
        raise HTTPException(status_code=404, detail="Nenhuma foto deste produto nas pastas do Softsystem.")
    ja_cat = await _midias(db, current_user.tenant_id, emp, cod)
    ja = {m.url_origem for m in ja_cat if m.origem == "softsystem"} | {f"Produto {cod} {m.softsystem_codimagem}.jpg" for m in ja_cat if m.softsystem_codimagem}
    entradas = []
    for pasta, n in achadas:
        if n in ja:
            continue
        with open(os.path.join(pasta, n), "rb") as f:
            entradas.append(("softsystem", n, f.read()))
    if not entradas:
        return {"success": True, "midias": [], "erros": [], "mensagem": "As fotos do Softsystem já foram importadas."}
    return await _gravar_fotos(db, current_user, emp, cod, entradas, remover_fundo)


@router.post("/produto/{cod}/pdfs")
async def enviar_pdf(cod: int, empresa: str = Form("servweld"), titulo: str = Form(""), link: str = Form(""),
                     arquivo: Optional[UploadFile] = File(default=None), db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """Manual / ficha técnica em PDF: upload ou link (o arquivo é baixado e guardado aqui - link externo quebra)."""
    emp = _empresa(empresa)
    if arquivo is not None:
        dados = await arquivo.read()
        nome = arquivo.filename or "manual.pdf"
        origem, url = "upload", None
    elif link.strip():
        try:
            dados, _ = await asyncio.to_thread(img.baixar, link.strip(), ("application/pdf",))
        except img.ImagemErro as e:
            raise HTTPException(status_code=400, detail=str(e))
        nome, origem, url = link.strip().rsplit("/", 1)[-1][:120], "link", link.strip()[:1000]
    else:
        raise HTTPException(status_code=400, detail="Envie o PDF ou o link dele.")
    if dados[:5] != b"%PDF-":
        raise HTTPException(status_code=400, detail="O arquivo não é um PDF.")
    if len(dados) > img.MAX_BYTES:
        raise HTTPException(status_code=400, detail="PDF maior que 15 MB.")
    existentes = await _midias(db, current_user.tenant_id, emp, cod)
    m = CatalogoMidia(
        tenant_id=current_user.tenant_id, empresa=emp, codproduto=cod, tipo="pdf",
        arquivo=await asyncio.to_thread(img.salvar, emp, cod, dados, "pdf"),
        titulo=(titulo.strip() or re.sub(r"\.pdf$", "", nome, flags=re.I) or "Ficha técnica")[:200],
        ordem=max([x.ordem for x in existentes] + [0]) + 1, origem=origem, url_origem=url,
        criado_em=datetime.utcnow(), criado_por=_usuario(current_user),
    )
    db.add(m)
    await db.commit()
    _cache_site.clear()
    return {"success": True, "midia": _midia_dict(m)}


@router.delete("/midia/{midia_id}")
async def apagar_midia(midia_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_ator)):
    m = await db.get(CatalogoMidia, midia_id)
    if not m or m.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if m.softsystem_codimagem and m.origem != "softsystem" and _modo_db() != "":
        try:
            await asyncio.to_thread(cat.excluir_foto_softsystem, m.codproduto, m.softsystem_codimagem, _modo_db())
        except Exception as e:
            logger.error(f"[CATALOGO] Foto {m.softsystem_codimagem} não marcada como excluída no Softsystem: {e}")
            raise HTTPException(status_code=502, detail=f"Não deu para tirar a foto do Softsystem agora - tente de novo. ({e})")
    for caminho in (m.arquivo, m.miniatura, m.original):
        await asyncio.to_thread(img.apagar, caminho)
    await db.delete(m)
    await db.commit()
    _cache_site.clear()
    return {"success": True}


@router.post("/midia/{midia_id}/reprocessar")
async def reprocessar_midia(midia_id: int, modo: str = Query("local"), db: AsyncSession = Depends(get_db),
                            current_user=Depends(get_ator)):
    """Refaz a foto a partir do ORIGINAL guardado: modo=ia (foto de venda) ou local (sem IA - só
    fundo branco + marca d'água). Usado quando a versão da IA não agradou."""
    m = await db.get(CatalogoMidia, midia_id)
    if not m or m.tenant_id != current_user.tenant_id or m.tipo != "imagem":
        raise HTTPException(status_code=404, detail="Foto não encontrada")
    if not m.original or not m.original.startswith("/uploads/catalogo/"):
        raise HTTPException(status_code=400, detail="Esta foto não tem o original guardado.")
    with open(os.path.join(img.UPLOADS_DIR, m.original[len("/uploads/"):]), "rb") as f:
        dados = f.read()
    try:
        jpg, mini, rem, usou_ia, aviso = await _tratar(db, current_user.tenant_id, m.empresa, m.codproduto, dados, True, modo == "ia")
    except img.ImagemErro as e:
        raise HTTPException(status_code=400, detail=str(e))
    antigos = (m.arquivo, m.miniatura)
    m.arquivo = await asyncio.to_thread(img.salvar, m.empresa, m.codproduto, jpg, "jpg")
    m.miniatura = await asyncio.to_thread(img.salvar, m.empresa, m.codproduto, mini, "jpg")
    m.fundo_removido = rem
    m.titulo = "Foto de venda (IA)" if usou_ia else None
    if m.softsystem_codimagem and m.origem != "softsystem" and _modo_db() is None:
        try:
            await asyncio.to_thread(cat._gravar_arquivo_foto, m.codproduto, m.softsystem_codimagem, jpg)
        except Exception as e:
            aviso = (aviso + " · " if aviso else "") + f"o arquivo no Softsystem não foi trocado agora ({str(e)[:60]})"
    await db.commit()
    for c in antigos:
        await asyncio.to_thread(img.apagar, c)
    _cache_site.clear()
    return {"success": True, "midia": _midia_dict(m), "aviso": aviso}


@router.get("/app/buscar")
async def buscar_para_foto(q: str = Query(..., min_length=2), empresa: str = Query("servweld"),
                           db: AsyncSession = Depends(get_db), current_user=Depends(get_ator)):
    """Busca do app Foto: código Softsystem, código do FORNECEDOR (de-para das compras), referência
    do fabricante, EAN ou descrição - e quantas fotos o produto já tem."""
    emp = _empresa(empresa)
    try:
        achados = await asyncio.to_thread(cat.buscar_para_foto, emp, q.strip())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Softsystem: {e}")
    cods = [p["codigo"] for p in achados]
    fotos: Dict[int, List[CatalogoMidia]] = {}
    if cods:
        res = await db.execute(select(CatalogoMidia).where(
            CatalogoMidia.tenant_id == current_user.tenant_id, CatalogoMidia.empresa == emp,
            CatalogoMidia.tipo == "imagem", CatalogoMidia.codproduto.in_(cods)).order_by(CatalogoMidia.ordem, CatalogoMidia.id))
        for m in res.scalars():
            fotos.setdefault(m.codproduto, []).append(m)
    return {"success": True, "produtos": [{
        **p, "fotos": len(fotos.get(p["codigo"], [])),
        "capa": (fotos[p["codigo"]][0].miniatura if fotos.get(p["codigo"]) else None),
    } for p in achados]}


class OrdemPayload(BaseModel):
    ids: List[int]


@router.put("/produto/{cod}/ordem")
async def ordenar_midias(cod: int, payload: OrdemPayload, empresa: str = Query("servweld"), db: AsyncSession = Depends(get_db),
                         current_user=Depends(get_ator)):
    """A primeira foto é a capa no site."""
    emp = _empresa(empresa)
    por_id = {m.id: m for m in await _midias(db, current_user.tenant_id, emp, cod)}
    for i, mid in enumerate(payload.ids, start=1):
        if mid in por_id:
            por_id[mid].ordem = i
    await db.commit()
    _cache_site.clear()
    return {"success": True}


@router.post("/produto/{cod}/gerar-textos")
async def gerar_textos(cod: int, empresa: str = Query("servweld"), db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """IA pesquisa o produto e sugere título, descrição, ficha técnica e palavras-chave (a pessoa revisa)."""
    emp = _empresa(empresa)
    sw = (await asyncio.to_thread(cat.produtos_softsystem, emp, [cod])).get(cod)
    if not sw:
        raise HTTPException(status_code=404, detail="Produto não existe no Softsystem.")
    decrypted = await settings_service.get_tenant_decrypted_settings(db, current_user.tenant_id)
    try:
        return {"success": True, "sugestao": await cat.gerar_textos_ia(sw, decrypted.get("gemini_api_key") or settings.GEMINI_API_KEY,
                                                                      current_user.tenant_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _codimagens_ativas(cods: List[int]) -> Dict[int, set]:
    """{cod: números de foto NÃO excluídos} nos dois bancos (foto retirada fica com o arquivo na
    pasta, mas não pode mais aparecer nas telas)."""
    return _numeros_fotos(cods, True)


def _miniatura_softsystem(empresa: str, cod: int, ativas: Optional[set] = None) -> Optional[Dict[str, str]]:
    """Miniatura (400 px) e foto ampliada (1200 px) da 1ª foto ATIVA do produto nas pastas do
    Softsystem, geradas uma vez por número de foto em uploads/catalogo_cache (foto trocada = arquivo
    novo; a tela não lê a pasta de rede a cada visita)."""
    fotos = _fotos_por_numeros(cod, ativas) if ativas is not None else _fotos_softsystem(empresa, cod, True)
    if not fotos:
        return None
    pasta, nome = fotos[0]
    n = _codimagem_do_nome(nome) or 0
    base = os.path.join(img.UPLOADS_DIR, "catalogo_cache", empresa)
    mini, grande = f"{int(cod)}_{n}.jpg", f"{int(cod)}_{n}_g.jpg"
    if not (os.path.exists(os.path.join(base, mini)) and os.path.exists(os.path.join(base, grande))):
        from PIL import Image, ImageOps
        try:
            with Image.open(os.path.join(pasta, nome)) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                os.makedirs(base, exist_ok=True)
                g = im.copy()
                g.thumbnail((1200, 1200))
                g.save(os.path.join(base, grande), "JPEG", quality=85)
                im.thumbnail((400, 400))
                im.save(os.path.join(base, mini), "JPEG", quality=80)
        except Exception as e:
            logger.warning(f"[CATALOGO] Miniatura do Softsystem {cod}: {e}")
            return None
    return {"miniatura": f"/uploads/catalogo_cache/{empresa}/{mini}", "foto": f"/uploads/catalogo_cache/{empresa}/{grande}"}


@router.get("/fotos")
async def fotos_produtos(cods: str = Query(..., description="códigos separados por vírgula"), empresa: str = Query("servweld"),
                         db: AsyncSession = Depends(get_db), current_user=Depends(get_ator)):
    """Foto de cada produto para mostrar nas telas da entrada (lançamento, contagem, preço):
    capa do catálogo do site; sem ela, a foto que já está no Softsystem. {cod: {miniatura, foto, origem}}."""
    emp = _empresa(empresa)
    codigos = sorted({int(c) for c in re.findall(r"\d+", cods)})[:100]
    if not codigos:
        return {"success": True, "fotos": {}}
    midias = list((await db.execute(select(CatalogoMidia).where(
        CatalogoMidia.tenant_id == current_user.tenant_id, CatalogoMidia.empresa == emp,
        CatalogoMidia.tipo == "imagem", CatalogoMidia.codproduto.in_(codigos)
    ).order_by(CatalogoMidia.ordem, CatalogoMidia.id))).scalars().all())
    res: Dict[str, Any] = {}
    for m in midias:
        res.setdefault(str(m.codproduto), {"miniatura": m.miniatura or m.arquivo, "foto": m.arquivo, "origem": "catalogo"})
    faltam = [c for c in codigos if str(c) not in res]

    def _do_softsystem():
        out = {}
        ativas = _codimagens_ativas(faltam)
        for c in faltam:
            u = _miniatura_softsystem(emp, c, ativas.get(int(c), set()))
            if u:
                out[str(c)] = {**u, "origem": "softsystem"}
        return out
    if faltam:
        res.update(await asyncio.to_thread(_do_softsystem))
    return {"success": True, "fotos": res}


@router.get("/produtos")
async def listar_catalogo(empresa: str = Query("servweld"), so_publicados: bool = Query(False), db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """Produtos já trabalhados no catálogo, com o que falta para ficarem completos."""
    emp = _empresa(empresa)
    q = select(CatalogoProduto).where(CatalogoProduto.tenant_id == current_user.tenant_id, CatalogoProduto.empresa == emp)
    if so_publicados:
        q = q.where(CatalogoProduto.publicar_site.is_(True))
    regs = list((await db.execute(q.order_by(CatalogoProduto.atualizado_em.desc()).limit(500))).scalars().all())
    midias = list((await db.execute(select(CatalogoMidia).where(
        CatalogoMidia.tenant_id == current_user.tenant_id, CatalogoMidia.empresa == emp))).scalars().all())
    por_prod: Dict[int, List[CatalogoMidia]] = {}
    for m in midias:
        por_prod.setdefault(m.codproduto, []).append(m)
    try:
        sws = await asyncio.to_thread(cat.produtos_softsystem, emp, [r.codproduto for r in regs]) if regs else {}
    except Exception:
        sws = {}
    out = []
    for r in regs:
        ms = sorted(por_prod.get(r.codproduto, []), key=lambda m: (m.ordem, m.id))
        fotos = [m for m in ms if m.tipo == "imagem"]
        sw = sws.get(r.codproduto) or {}
        falta = [t for t, ok in (("foto", bool(fotos)), ("descrição", bool(r.descricao_web)),
                                 ("ficha técnica", r.especificacoes_json not in (None, "", "[]"))) if not ok]
        out.append({"codproduto": r.codproduto, "descricao": sw.get("descricao") or r.titulo_web, "titulo_web": r.titulo_web,
                    "publicar_site": r.publicar_site, "destaque": r.destaque, "capa": (fotos[0].miniatura or fotos[0].arquivo) if fotos else None,
                    "fotos": len(fotos), "pdfs": sum(1 for m in ms if m.tipo == "pdf"), "videos": len(json.loads(r.videos_json or "[]")),
                    "preco": sw.get("preco"), "estoque": sw.get("estoque"), "falta": falta, "softsystem_erro": r.softsystem_erro,
                    "atualizado_por": r.atualizado_por, "atualizado_em": r.atualizado_em.isoformat() if r.atualizado_em else None})
    return {"success": True, "produtos": out}


# ================================================================== site público (sem login)
_cache_site: Dict[str, tuple] = {}
_CACHE_SITE_S = 120


async def _dados_site(db: AsyncSession) -> Dict[str, Any]:
    """Tudo o que o site precisa, montado uma vez a cada 2 min (o Softsystem não é consultado a cada visita)."""
    hit = _cache_site.get("tudo")
    if hit and time.time() - hit[0] < _CACHE_SITE_S:
        return hit[1]
    emp, tenant = settings.SITE_EMPRESA, settings.SITE_TENANT_ID
    regs = list((await db.execute(select(CatalogoProduto).where(
        CatalogoProduto.tenant_id == tenant, CatalogoProduto.empresa == emp, CatalogoProduto.publicar_site.is_(True)))).scalars().all())
    midias = list((await db.execute(select(CatalogoMidia).where(
        CatalogoMidia.tenant_id == tenant, CatalogoMidia.empresa == emp))).scalars().all())
    por_prod: Dict[int, List[CatalogoMidia]] = {}
    for m in midias:
        por_prod.setdefault(m.codproduto, []).append(m)
    sws = await asyncio.to_thread(cat.produtos_softsystem, emp, [r.codproduto for r in regs]) if regs else {}

    from app.services.cadastro_produto_service import arvore
    arv = await asyncio.to_thread(arvore, emp)
    nomes: Dict[str, str] = {}
    for g in arv["grupos"]:
        nomes[cat.secao_id(g["codigo"])] = g["nome"].title()
        for s in g.get("subgrupos", []):
            nomes[cat.secao_id(g["codigo"], s["codigo"])] = s["nome"].title()

    produtos = []
    for r in regs:
        sw = sws.get(r.codproduto)
        if not sw or sw.get("inativo") or sw.get("codgrupo") is None:
            continue
        produtos.append(cat.produto_site(r, sw, por_prod.get(r.codproduto, []), settings.SITE_PUBLIC_BASE_URL, nomes))

    # menu: só grupos/subgrupos que têm produto publicado; imagem da seção = capa do 1º produto
    usados_sub = {p["sectionId"] for p in produtos}
    usados_grupo = {re.match(r"g\d+", s).group(0) for s in usados_sub}
    capa = {}
    for p in produtos:
        fotos = json.loads(p["images"])
        if fotos:
            capa.setdefault(p["sectionId"], fotos[0])
            capa.setdefault(re.match(r"g\d+", p["sectionId"]).group(0), fotos[0])
    secoes = []
    for i, g in enumerate(sorted(arv["grupos"], key=lambda x: x["nome"])):
        gid = cat.secao_id(g["codigo"])
        if gid not in usados_grupo:
            continue
        secoes.append({"id": gid, "name": nomes[gid], "image": capa.get(gid), "icon": None, "order": i, "active": True, "parentId": None})
        for j, s in enumerate(g.get("subgrupos", [])):
            sid = cat.secao_id(g["codigo"], s["codigo"])
            if sid in usados_sub and sid != gid:
                secoes.append({"id": sid, "name": nomes[sid], "image": capa.get(sid), "icon": None, "order": j, "active": True, "parentId": gid})
    dados = {"produtos": produtos, "secoes": secoes}
    _cache_site["tudo"] = (time.time(), dados)
    return dados


def _sem_acento(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c)).lower()


@public_router.get("/sections")
async def site_secoes(db: AsyncSession = Depends(get_db)):
    return (await _dados_site(db))["secoes"]


@public_router.get("/products")
async def site_produtos(sectionId: Optional[str] = None, search: Optional[str] = None, status: Optional[str] = None,
                        minPrice: Optional[float] = None, maxPrice: Optional[float] = None, limit: int = Query(200, le=500),
                        db: AsyncSession = Depends(get_db)):
    lista = (await _dados_site(db))["produtos"]
    if sectionId:
        lista = [p for p in lista if p["sectionId"] == sectionId or p["sectionId"].startswith(sectionId + "s")]
    if status:
        lista = [p for p in lista if p["status"] == status.upper()]
    if search:
        termos = _sem_acento(search).split()
        lista = [p for p in lista if all(t in _sem_acento(f"{p['name']} {p['sku']} {p['brand']} {p['ean']}") for t in termos)]
    if minPrice is not None:
        lista = [p for p in lista if p["price"] >= minPrice]
    if maxPrice is not None:
        lista = [p for p in lista if p["price"] <= maxPrice]
    return lista[:limit]


@public_router.get("/products/{sku}")
async def site_produto(sku: str, db: AsyncSession = Depends(get_db)):
    p = next((x for x in (await _dados_site(db))["produtos"] if x["sku"] == sku), None)
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return p
