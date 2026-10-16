"""
Arquivo das notas de fornecedor na pasta da loja - pedido do usuário em 15/10/2026: "quando der
entrada na nota fiscal quero que salve uma via na pasta Z:\\Documentos\\NOTAS FISCAIS- FORNECEDORES
igual está lá: ANO / MÊS / NOME DO FORNECEDOR / Nº DA NOTA, XML e DANFE".

Padrão estudado na pasta (Z: = \\\\SRV-SERVWELD\\Users\\Administrator\\My Drive, montada na VM em
/mnt/softsystem_drive):
  2026/09 - SETEMBRO/BARBOSA SOLDAS/N.F 108.179/35260809132546000170550010001081791901081798.xml
                                              /N.F 108.179.pdf   (DANFE)
- o MÊS é o da ENTRADA (a NF 108.179 foi emitida em agosto e está em setembro);
- a pasta do mês já existente é reaproveitada pelo número ("07 -JULHO" também vale);
- o NOME DO FORNECEDOR é o que a loja já usa: o CNPJ sai da chave no nome dos XMLs antigos, então o
  mesmo fornecedor cai sempre na mesma pasta ("BARBOSA SOLDAS"); fornecedor novo usa o nome fantasia;
- número da nota com ponto de milhar a partir de 6 dígitos ("N.F 108.179", "N.F 34920");
- CT-e da transportadora vai junto, na pasta da nota (XML + DACTE);
- nunca sobrescreve: arquivo que já existe (alguém salvou à mão) fica como está.
"""
import json
import logging
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger("nota_arquivo")

MESES = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO",
         "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
_RX_CHAVE = re.compile(r"(\d{44})")
# O índice CNPJ -> pasta do fornecedor exige PERCORRER anos de pastas no Google Drive do servidor
# (CIFS) - e varrer pasta grande por lá travou a VM em 15/10/2026. Então: fica salvo em disco
# (sobrevive aos reinícios do backend), é refeito no máximo 1x por semana em segundo plano e cada
# nota arquivada já entra nele na hora (sem varrer nada).
_INDICE_TTL_S = 7 * 24 * 3600
_ARQ_INDICE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data",
                           "indice_fornecedores_notas.json")
_indice: Dict[str, tuple] = {}
_trava = threading.Lock()
_reconstruindo = set()


def _ler_indice_disco(base: str):
    try:
        with open(_ARQ_INDICE, encoding="utf-8") as f:
            d = json.load(f).get(base)
        return (float(d["quando"]), dict(d["mapa"])) if d else None
    except Exception:
        return None


def _gravar_indice_disco(base: str, quando: float, mapa: Dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(_ARQ_INDICE), exist_ok=True)
        tudo = {}
        if os.path.exists(_ARQ_INDICE):
            with open(_ARQ_INDICE, encoding="utf-8") as f:
                tudo = json.load(f)
        tudo[base] = {"quando": quando, "mapa": mapa}
        tmp = _ARQ_INDICE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tudo, f, ensure_ascii=False)
        os.replace(tmp, _ARQ_INDICE)
    except Exception as e:
        logger.warning(f"[ARQUIVO] Não gravei o índice de fornecedores: {e}")


def lembrar_fornecedor(base: str, cnpj: str, pasta_fornecedor: str) -> None:
    """Nota arquivada: o CNPJ passa a apontar para a pasta usada (sem varrer nada)."""
    with _trava:
        hit = _indice.get(base) or _ler_indice_disco(base) or (time.time(), {})
        mapa = dict(hit[1])
        if mapa.get(cnpj) == pasta_fornecedor:
            return
        mapa[cnpj] = pasta_fornecedor
        _indice[base] = (hit[0], mapa)
        _gravar_indice_disco(base, hit[0], mapa)


def pasta_base(empresa: str) -> str:
    return (settings.NOTAS_FORNECEDORES_DIR_SERVWELD if empresa == "servweld"
            else settings.NOTAS_FORNECEDORES_DIR_CENTROOESTE) or ""


def _limpo(nome: str) -> str:
    """Nome válido de pasta no Windows, em maiúsculas."""
    t = re.sub(r'[\\/:*?"<>|]+', " ", nome or "").upper()
    return re.sub(r"\s+", " ", t).strip(" .")[:60]


def nome_numero(numero: str) -> str:
    n = str(int(re.sub(r"\D", "", str(numero)) or 0))
    return f"N.F {int(n):,}".replace(",", ".") if len(n) >= 6 else f"N.F {n}"


def nome_fornecedor_novo(fornecedor: Dict[str, Any]) -> str:
    fant = (fornecedor or {}).get("nome_fantasia") or ""
    if fant.strip():
        return _limpo(fant)
    razao = (fornecedor or {}).get("razao_social") or "FORNECEDOR"
    razao = re.sub(r"\b(LTDA|EIRELI|ME|EPP|S\.?\s?A\.?|S/A|COMERCIO|INDUSTRIA|E)\b\.?", " ", razao.upper())
    return _limpo(" ".join(razao.split()[:3])) or "FORNECEDOR"


def indice_fornecedores(base: str) -> Dict[str, str]:
    """{cnpj: nome da pasta do fornecedor} lido dos XMLs já arquivados (os 3 anos mais recentes; vale
    o nome mais recente). Usa o índice salvo em disco; se passou de 7 dias, refaz em SEGUNDO PLANO e
    devolve o que já tem (a tela nunca espera a varredura). Só varre na hora se nunca foi feito."""
    with _trava:
        hit = _indice.get(base)
        if not hit:
            hit = _ler_indice_disco(base)
            if hit:
                _indice[base] = hit
    if hit:
        if time.time() - hit[0] > _INDICE_TTL_S and base not in _reconstruindo:
            _reconstruindo.add(base)
            threading.Thread(target=_reconstruir_indice, args=(base,), daemon=True).start()
        return hit[1]
    return _reconstruir_indice(base)


def _reconstruir_indice(base: str) -> Dict[str, str]:
    try:
        return _varrer_indice(base)
    finally:
        _reconstruindo.discard(base)


def _varrer_indice(base: str) -> Dict[str, str]:
    mapa: Dict[str, tuple] = {}
    try:
        anos = sorted((a for a in os.listdir(base) if re.fullmatch(r"\d{4}", a)), reverse=True)[:3]
    except OSError as e:
        logger.warning(f"[ARQUIVO] Pasta de notas inacessível ({base}): {e}")
        return {}
    for ano in anos:
        pa = os.path.join(base, ano)
        for mes in _listar(pa):
            m = re.match(r"(\d{1,2})", mes)
            if not m:
                continue
            ordem = int(ano) * 100 + int(m.group(1))
            pm = os.path.join(pa, mes)
            for forn in _listar(pm):
                pf = os.path.join(pm, forn)
                if not os.path.isdir(pf):
                    continue
                for nota in _listar(pf):
                    alvo = os.path.join(pf, nota)
                    nomes = _listar(alvo) if os.path.isdir(alvo) else [nota]
                    for arq in nomes:
                        k = _RX_CHAVE.search(arq)
                        if k and arq.lower().endswith(".xml") and k.group(1)[20:22] == "55":
                            cnpj = k.group(1)[6:20]
                            if cnpj not in mapa or mapa[cnpj][0] < ordem:
                                mapa[cnpj] = (ordem, forn)
                            break
    res = {c: v[1] for c, v in mapa.items()}
    agora = time.time()
    with _trava:
        anterior = (_indice.get(base) or (0, {}))[1]
        res = {**anterior, **res}  # mantém o que foi aprendido no arquivamento
        _indice[base] = (agora, res)
        _gravar_indice_disco(base, agora, res)
    logger.info(f"[ARQUIVO] Índice de fornecedores da pasta de notas: {len(res)} CNPJs.")
    return res


def _listar(p: str):
    try:
        return sorted(os.listdir(p))
    except OSError:
        return []


def pasta_do_mes(base: str, quando: datetime) -> str:
    pa = os.path.join(base, f"{quando.year}")
    _mkdirs(pa)
    for nome in _listar(pa):
        m = re.match(r"\s*(\d{1,2})\s*-", nome)
        if m and int(m.group(1)) == quando.month and os.path.isdir(os.path.join(pa, nome)):
            return os.path.join(pa, nome)
    p = os.path.join(pa, f"{quando.month:02d} - {MESES[quando.month - 1]}")
    _mkdirs(p)
    return p


def _com_retentativa(fn, *args):
    """Z: é o Google Drive para computador do SRV-SERVWELD: enquanto ele sincroniza uma pasta
    recém-criada, recusa gravações por alguns segundos ("Permission denied" intermitente - visto em
    15/10/2026 na NF 164.158). Tenta de novo com espera crescente antes de desistir."""
    for tentativa in range(5):
        try:
            return fn(*args)
        except PermissionError:
            if tentativa == 4:
                raise
            time.sleep(2 * (tentativa + 1))


def _mkdirs(p: str) -> None:
    _com_retentativa(lambda: os.makedirs(p, exist_ok=True))


def _gravar_se_nao_existe(caminho: str, dados: bytes) -> bool:
    if os.path.exists(caminho):
        return False

    def _gravar():
        tmp = caminho + ".tmp"
        with open(tmp, "wb") as f:
            f.write(dados)
        os.replace(tmp, caminho)
    _com_retentativa(_gravar)
    return True


def _pdf_danfe(xml: bytes) -> bytes:
    from brazilfiscalreport.danfe import Danfe
    pdf = Danfe(xml=xml.decode("utf-8", "replace"))
    return bytes(pdf.output())


def _pdf_dacte(xml: bytes) -> Optional[bytes]:
    try:
        from brazilfiscalreport.dacte import Dacte
        return bytes(Dacte(xml=xml.decode("utf-8", "replace")).output())
    except Exception as e:  # DACTE é bônus: falhar não impede arquivar a nota
        logger.warning(f"[ARQUIVO] DACTE não gerado: {e}")
        return None


def preparar_pasta(empresa: str, chave: str, numero_nf: str, fornecedor: Dict[str, Any],
                   quando: Optional[datetime] = None) -> Optional[str]:
    """Cria a pasta ANO/MÊS/FORNECEDOR/N.F já na IMPORTAÇÃO da nota (pedido do usuário em 15/10/2026):
    até o lançamento o Google Drive do servidor já sincronizou e a pasta está pronta. Devolve o
    caminho relativo à pasta de notas (guardado na entrada) ou None se a loja não tem pasta."""
    base = pasta_base(empresa)
    if not base:
        return None
    if not os.path.isdir(base):
        raise OSError(f"Pasta de notas inacessível: {base}")
    nome_forn = indice_fornecedores(base).get(chave[6:20]) or nome_fornecedor_novo(fornecedor)
    quando = quando or (datetime.utcnow() - timedelta(hours=3))
    pasta = os.path.join(pasta_do_mes(base, quando), nome_forn, nome_numero(numero_nf))
    _mkdirs(pasta)
    return os.path.relpath(pasta, base)


def remover_pasta_vazia(empresa: str, pasta_rel: Optional[str]) -> bool:
    """Entrada cancelada: apaga a pasta da nota SÓ se continuar vazia (nunca apaga arquivo de ninguém);
    a do fornecedor também sai se ficou vazia por causa disso."""
    base = pasta_base(empresa)
    if not base or not pasta_rel or ".." in pasta_rel.replace("\\", "/").split("/"):
        return False
    pasta = os.path.join(base, pasta_rel)
    try:
        if os.path.isdir(pasta) and not os.listdir(pasta):
            os.rmdir(pasta)
            forn = os.path.dirname(pasta)
            if os.path.isdir(forn) and not os.listdir(forn):
                os.rmdir(forn)
            return True
    except OSError as e:
        logger.warning(f"[ARQUIVO] Não removi {pasta_rel}: {e}")
    return False


def arquivar_nota(empresa: str, chave: str, numero_nf: str, fornecedor: Dict[str, Any],
                  cte_chave: Optional[str] = None, cte_numero: Optional[str] = None,
                  quando: Optional[datetime] = None, pasta_rel: Optional[str] = None) -> Dict[str, Any]:
    """Salva XML + DANFE (e CT-e) na pasta de notas da loja. Devolve a pasta e o que foi gravado."""
    from app.services.nfe_xml_service import NfeXmlService
    base = pasta_base(empresa)
    if not base:
        return {"arquivado": False, "motivo": "Pasta de notas desta loja não configurada."}
    if not os.path.isdir(base):
        raise OSError(f"Pasta de notas inacessível: {base}")
    caminho_xml = NfeXmlService.localizar_xml_local(chave)
    if not caminho_xml:
        raise FileNotFoundError("XML da nota não encontrado no OminiChannel.")
    with open(caminho_xml, "rb") as f:
        xml = f.read()

    if pasta_rel and ".." not in pasta_rel.replace("\\", "/").split("/"):
        pasta = os.path.join(base, pasta_rel)  # criada na importação da nota
    else:
        pasta = os.path.join(base, preparar_pasta(empresa, chave, numero_nf, fornecedor, quando))
    _mkdirs(pasta)

    gravados = []
    if _gravar_se_nao_existe(os.path.join(pasta, f"{chave}.xml"), xml):
        gravados.append(f"{chave}.xml")
    danfe = os.path.join(pasta, f"{nome_numero(numero_nf)}.pdf")
    if not os.path.exists(danfe) and _gravar_se_nao_existe(danfe, _pdf_danfe(xml)):
        gravados.append(os.path.basename(danfe))

    if cte_chave:
        cx = NfeXmlService.localizar_xml_local(cte_chave)
        if cx:
            with open(cx, "rb") as f:
                xml_cte = f.read()
            if _gravar_se_nao_existe(os.path.join(pasta, f"{cte_chave}.xml"), xml_cte):
                gravados.append(f"{cte_chave}.xml")
            dacte_nome = os.path.join(pasta, f"CT-e {cte_numero or cte_chave[25:34].lstrip('0')}.pdf")
            if not os.path.exists(dacte_nome):
                pdf = _pdf_dacte(xml_cte)
                if pdf and _gravar_se_nao_existe(dacte_nome, pdf):
                    gravados.append(os.path.basename(dacte_nome))

    lembrar_fornecedor(base, chave[6:20], os.path.basename(os.path.dirname(pasta)))
    rel = os.path.relpath(pasta, base).replace("/", "\\")
    logger.info(f"[ARQUIVO] NF {numero_nf} arquivada em {rel}: {gravados or 'já estava lá'}")
    return {"arquivado": True, "pasta": rel, "gravados": gravados}
