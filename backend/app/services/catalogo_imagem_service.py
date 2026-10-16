"""
Tratamento das fotos do catálogo (etapa 5 da entrada de nota - pedido do usuário em 15/10/2026:
"imagens (upload ou links), remover fundo e deixar branco, marca d'água Servsolda").

Pipeline de cada foto:
  1. abre (corrige rotação do celular pelo EXIF);
  2. fundo: se a borda da foto já é branca (foto de fornecedor), não mexe; senão remove o fundo com
     um modelo U2-Net/ISNet (onnxruntime, roda na própria VM - sem custo por foto) e põe fundo BRANCO;
  3. recorta as sobras, centraliza num quadrado 1200x1200 com margem;
  4. aplica a marca d'água Servsolda (logo oficial de app/assets/logos) no canto inferior direito;
  5. grava JPEG + miniatura 400px.
A VM tem 2 núcleos: o modelo roda com 1 thread, uma foto por vez (trava global), e é descarregado
da memória depois de 10 min parado.

Downloads por link: só http/https, só endereço público (bloqueia rede interna - SSRF), até 15 MB.
"""
import io
import ipaddress
import logging
import os
import socket
import threading
import time
import uuid
from typing import Optional, Tuple
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger("catalogo_imagem")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOADS_DIR = os.path.join(_BACKEND_DIR, "uploads")
# Modelos de remoção de fundo (os mesmos do projeto rembg). Medido na VM (2 núcleos) em 15/10/2026:
# isnet-general-use (1024 px) recorta muito bem mas leva ~40 s por foto - lento demais para a tela;
# silueta (U2-Net 320 px, 43 MB) leva poucos segundos. Troca pela variável CATALOGO_MODELO_FUNDO.
MODELOS = {
    "silueta": {"tam": 320, "media": (0.485, 0.456, 0.406), "desvio": (0.229, 0.224, 0.225), "max1": True},
    "isnet-general-use": {"tam": 1024, "media": (0.5, 0.5, 0.5), "desvio": (1.0, 1.0, 1.0), "max1": False},
}
MODELO_NOME = os.getenv("CATALOGO_MODELO_FUNDO", "silueta")
if MODELO_NOME not in MODELOS:
    MODELO_NOME = "silueta"
MODELO_PATH = os.path.join(_BACKEND_DIR, "models", f"{MODELO_NOME}.onnx")
MODELO_URL = f"https://github.com/danielgatis/rembg/releases/download/v0.0.0/{MODELO_NOME}.onnx"
LOGO_PATH = os.path.join(_BACKEND_DIR, "app", "assets", "logos", "servsolda.png")

LADO = 1200
LADO_MINI = 400
MARGEM = 0.07          # sobra em volta do produto
LOGO_LARGURA = 0.28    # largura da marca d'água em relação à foto
LOGO_OPACIDADE = 0.55
MAX_BYTES = 15 * 1024 * 1024

_trava = threading.Lock()
_sessao = None
_ultimo_uso = 0.0
_logo_cache: Optional[Image.Image] = None


class ImagemErro(Exception):
    pass


# ------------------------------------------------------------------ download seguro
def _host_publico(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def baixar(url: str, tipos_aceitos: Tuple[str, ...] = ("image/",)) -> Tuple[bytes, str]:
    """Baixa um arquivo de um link público. Devolve (bytes, content-type)."""
    import httpx
    atual = url.strip()
    for _ in range(4):  # segue até 3 redirecionamentos, conferindo cada destino
        p = urlparse(atual)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ImagemErro("O link precisa começar com http:// ou https://")
        if not _host_publico(p.hostname):
            raise ImagemErro("Esse link aponta para um endereço interno - não é permitido.")
        with httpx.Client(timeout=20.0, follow_redirects=False, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept": "image/avif,image/webp,image/*,application/pdf,*/*;q=0.8", "Referer": f"{p.scheme}://{p.hostname}/",
        }) as cli:
            with cli.stream("GET", atual) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    atual = str(httpx.URL(atual).join(r.headers["location"]))
                    continue
                if r.status_code != 200:
                    raise ImagemErro(f"O site respondeu {r.status_code} ao baixar o arquivo.")
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                dados = bytearray()
                for bloco in r.iter_bytes():
                    dados.extend(bloco)
                    if len(dados) > MAX_BYTES:
                        raise ImagemErro("Arquivo maior que 15 MB.")
                if not any(ctype.startswith(t) for t in tipos_aceitos) and not _parece(bytes(dados), tipos_aceitos):
                    raise ImagemErro(f"O link não é de {'uma imagem' if 'image/' in tipos_aceitos else 'um PDF'} (veio {ctype or 'desconhecido'}).")
                return bytes(dados), ctype
    raise ImagemErro("Redirecionamentos demais no link.")


def _parece(dados: bytes, tipos: Tuple[str, ...]) -> bool:
    if "application/pdf" in tipos and dados[:5] == b"%PDF-":
        return True
    if "image/" in tipos:
        try:
            Image.open(io.BytesIO(dados)).verify()
            return True
        except Exception:
            return False
    return False


# ------------------------------------------------------------------ remoção de fundo
def _carregar_modelo():
    global _sessao
    if _sessao is not None:
        return _sessao
    if not os.path.exists(MODELO_PATH):
        os.makedirs(os.path.dirname(MODELO_PATH), exist_ok=True)
        logger.info(f"[IMAGEM] Baixando o modelo de remoção de fundo {MODELO_NOME} (uma vez só)...")
        import httpx
        tmp = MODELO_PATH + ".baixando"
        with httpx.stream("GET", MODELO_URL, follow_redirects=True, timeout=300.0) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for bloco in r.iter_bytes():
                    f.write(bloco)
        os.replace(tmp, MODELO_PATH)
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    _sessao = ort.InferenceSession(MODELO_PATH, sess_options=opts, providers=["CPUExecutionProvider"])
    threading.Thread(target=_descarregar_quando_parado, daemon=True).start()
    return _sessao


def _descarregar_quando_parado():
    global _sessao
    while True:
        time.sleep(60)
        with _trava:
            if _sessao is not None and time.time() - _ultimo_uso > 600:
                _sessao = None
                logger.info("[IMAGEM] Modelo de remoção de fundo descarregado (parado há 10 min).")
                return


def _mascara(img: Image.Image) -> Image.Image:
    """Máscara (L, 0-255) do produto (mesma normalização do rembg para cada modelo)."""
    global _ultimo_uso
    sessao = _carregar_modelo()
    _ultimo_uso = time.time()
    cfg = MODELOS[MODELO_NOME]
    rgb = img.convert("RGB").resize((cfg["tam"], cfg["tam"]), Image.LANCZOS)
    x = np.asarray(rgb).astype(np.float32)
    x = x / max(float(x.max()), 1e-6) if cfg["max1"] else x / 255.0
    x = (x - np.array(cfg["media"], dtype=np.float32)) / np.array(cfg["desvio"], dtype=np.float32)
    x = x.transpose(2, 0, 1)[None, ...].astype(np.float32)
    saida = sessao.run(None, {sessao.get_inputs()[0].name: x})[0][0, 0]
    mn, mx = float(saida.min()), float(saida.max())
    m = (saida - mn) / (mx - mn + 1e-8)
    mask = Image.fromarray((m * 255).astype(np.uint8), "L").resize(img.size, Image.LANCZOS)
    return mask


def fundo_ja_branco(img: Image.Image) -> bool:
    """Borda da foto (moldura de 3%) quase toda branca -> foto de catálogo, não precisa remover fundo."""
    rgb = np.asarray(img.convert("RGB").resize((300, 300)))
    b = 9
    borda = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3), rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    return float((borda.min(axis=1) > 232).mean()) >= 0.92


# ------------------------------------------------------------------ montagem final
def _logo() -> Optional[Image.Image]:
    """Logo oficial sem o fundo branco (vira transparente), recortado nas bordas."""
    global _logo_cache
    if _logo_cache is None and os.path.exists(LOGO_PATH):
        lg = Image.open(LOGO_PATH).convert("RGBA")
        a = np.asarray(lg).astype(np.int16)
        claro = a[..., :3].min(axis=2)
        alpha = np.clip((250 - claro) * 6, 0, 255).astype(np.uint8)  # branco -> transparente, com borda suave
        a = a.astype(np.uint8)
        a[..., 3] = np.minimum(a[..., 3], alpha)
        lg = Image.fromarray(a, "RGBA")
        bbox = lg.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
        _logo_cache = lg.crop(bbox) if bbox else lg
    return _logo_cache


def processar(dados: bytes, remover_fundo: bool = True, forcar_recorte: bool = False) -> Tuple[bytes, bytes, bool]:
    """bytes da foto -> (jpeg 1200, miniatura 400, fundo_removido).
    forcar_recorte: recorta o produto mesmo que o fundo pareça branco - a IA devolve um fundo cinza
    MUITO claro (não #FFFFFF) que passava por "já branco" e virava um quadrado visível na foto final
    (visto em 15/10/2026 no bico 1570)."""
    global _ultimo_uso
    try:
        img = Image.open(io.BytesIO(dados))
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception:
        raise ImagemErro("Arquivo de imagem inválido ou corrompido.")
    if img.width < 120 or img.height < 120:
        raise ImagemErro("Imagem pequena demais (mínimo 120x120).")
    if max(img.size) > 4000:
        img.thumbnail((4000, 4000))
    img = img.convert("RGBA")

    removido = False
    if remover_fundo and (forcar_recorte or not fundo_ja_branco(img)):
        with _trava:
            mask = _mascara(img)
            _ultimo_uso = time.time()
        alpha = Image.fromarray(np.minimum(np.asarray(img.getchannel("A")), np.asarray(mask)), "L")
        img.putalpha(alpha)
        removido = True

    if not removido:
        # fundo "quase branco" (cinza claríssimo de foto de catálogo) vira branco puro - senão aparece
        # o contorno da foto original sobre o branco da tela
        arr = np.asarray(img).copy()
        claro = arr[..., :3].min(axis=2) > 232
        arr[claro, :3] = 255
        img = Image.fromarray(arr, "RGBA")

    # recorte do conteúdo: transparência (fundo removido) ou o que não é branco
    if removido:
        bbox = img.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    else:
        cinza = np.asarray(img.convert("L"))
        conteudo = Image.fromarray(((cinza < 235) * 255).astype(np.uint8), "L")
        bbox = conteudo.getbbox()
    if bbox:
        img = img.crop(bbox)

    util = int(LADO * (1 - 2 * MARGEM))
    escala = min(util / img.width, util / img.height, 3.0)  # amplia foto pequena até 3x, reduz a grande
    img = img.resize((max(1, round(img.width * escala)), max(1, round(img.height * escala))), Image.LANCZOS)
    tela = Image.new("RGBA", (LADO, LADO), (255, 255, 255, 255))
    tela.alpha_composite(img, ((LADO - img.width) // 2, (LADO - img.height) // 2))

    lg = _logo()
    if lg is not None:
        larg = int(LADO * LOGO_LARGURA)
        lg2 = lg.resize((larg, max(1, int(lg.height * larg / lg.width))), Image.LANCZOS)
        a = np.asarray(lg2).copy()
        a[..., 3] = (a[..., 3].astype(np.float32) * LOGO_OPACIDADE).astype(np.uint8)
        lg2 = Image.fromarray(a, "RGBA")
        m = int(LADO * 0.025)
        tela.alpha_composite(lg2, (LADO - lg2.width - m, LADO - lg2.height - m))

    final = tela.convert("RGB")
    out = io.BytesIO()
    final.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    mini = final.copy()
    mini.thumbnail((LADO_MINI, LADO_MINI), Image.LANCZOS)
    out_m = io.BytesIO()
    mini.save(out_m, "JPEG", quality=82, optimize=True)
    return out.getvalue(), out_m.getvalue(), removido


def salvar(empresa: str, codproduto: int, conteudo: bytes, extensao: str) -> str:
    """Grava em uploads/catalogo/{empresa}/{codproduto}/ e devolve o caminho público (/uploads/...)."""
    pasta = os.path.join(UPLOADS_DIR, "catalogo", empresa, str(int(codproduto)))
    os.makedirs(pasta, exist_ok=True)
    nome = f"{uuid.uuid4().hex[:16]}.{extensao}"
    with open(os.path.join(pasta, nome), "wb") as f:
        f.write(conteudo)
    return f"/uploads/catalogo/{empresa}/{int(codproduto)}/{nome}"


# ------------------------------------------------------------------ foto de venda pela IA
# Pedido do usuário em 15/10/2026: foto tirada no celular (bancada, mão, chão...) vira FOTO DE VENDA
# de e-commerce. Modelo de imagem do Gemini (testado na VM com foto real de O.S.: tirou fundo, mão e
# chão, fundo branco com sombra suave, máquina idêntica). Depois passa pelo processar() normal
# (enquadra 1200x1200 + marca d'água Servsolda). A pessoa vê o resultado e pode voltar para a versão
# sem IA (o original fica guardado).
MODELO_FOTO_IA = os.getenv("CATALOGO_MODELO_FOTO_IA", "gemini-3.1-flash-image")
PROMPT_FOTO_IA = (
    "Transforme esta foto em uma FOTO PROFISSIONAL DE E-COMMERCE: fundo branco puro (#FFFFFF), iluminação de "
    "estúdio suave e uniforme, sombra leve e natural apenas embaixo do produto, produto inteiro, centralizado e nítido. "
    "NÃO altere o produto: mantenha exatamente o mesmo formato, cores, textos, marcas, rótulos, etiquetas, conectores, "
    "parafusos, medidas e proporções. Não adicione nem remova peças. Não adicione texto, logotipo nem marca d'água. "
    "Remova mãos, mesa, chão e objetos que não fazem parte do produto."
)


def foto_venda_ia(dados: bytes, api_key: Optional[str], descricao: str = "") -> bytes:
    """Foto do celular -> foto de venda (bytes da imagem devolvida pelo modelo)."""
    if not api_key:
        raise ImagemErro("Chave da IA (Gemini) não configurada.")
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(dados)))
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=90)
    except Exception:
        raise ImagemErro("Arquivo de imagem inválido ou corrompido.")
    from google import genai
    from app.services.ia_consumo_service import instalar
    instalar()  # tokens/custo vão para o painel Admin > Consumo de IA
    cli = genai.Client(api_key=api_key)
    prompt = PROMPT_FOTO_IA + (f" Produto: {descricao}." if descricao else "")
    resp = cli.models.generate_content(
        model=MODELO_FOTO_IA,
        contents=[prompt, genai.types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")],
        config=genai.types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    for cand in resp.candidates or []:
        for p in ((cand.content.parts if cand.content else None) or []):
            if getattr(p, "inline_data", None) and p.inline_data.data:
                return p.inline_data.data
    raise ImagemErro("A IA não devolveu imagem (tente outra foto ou use a versão sem IA).")


def apagar(caminho_publico: Optional[str]) -> None:
    if not caminho_publico or not caminho_publico.startswith("/uploads/catalogo/"):
        return
    real = os.path.normpath(os.path.join(UPLOADS_DIR, caminho_publico[len("/uploads/"):]))
    if real.startswith(os.path.join(UPLOADS_DIR, "catalogo")) and os.path.isfile(real):
        os.remove(real)
