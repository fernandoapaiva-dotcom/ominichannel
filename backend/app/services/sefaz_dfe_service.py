"""
Busca de NF-e / CT-e na SEFAZ (Ambiente Nacional) com o certificado A1 da loja.

- NFeDistribuicaoDFe (NT 2014.002): consulta pela chave (consChNFe) ou pelo NSU (consNSU).
  Sem a manifestação do destinatário a SEFAZ devolve só o resumo (resNFe), sem os produtos.
- NFeRecepcaoEvento4: registra a "Ciência da Operação" (evento 210210), que libera o XML
  completo. É um evento fiscal oficial em nome da loja (só "ciência" - não confirma nem recusa a
  nota). Desde 14/10/2026 é registrado AUTOMATICAMENTE quando a busca só traz o resumo (pedido do
  usuário: "preciso que seja imediato, não consigo dar sequência rápido no lançamento").
- CTeDistribuicaoDFe: só aceita NSU (não tem consulta por chave) - o NSU vem da tabela
  DOCUMENTOSDESTINADOS do Softsystem, que já sincroniza os documentos destinados.

A SEFAZ bloqueia o CNPJ por 1 hora ("656 - consumo indevido") quando repete consultas, por
isso: todo XML obtido vai para o cache local e nunca é consultado de novo, e há travas em memória:
  - antes da Ciência: a mesma chave só é consultada de novo depois de 1 hora (sem a Ciência a
    resposta seria o mesmo resumo);
  - depois da Ciência: poucas re-consultas com espaçamento crescente (RETENTATIVAS_APOS_CIENCIA_S)
    - o XML costuma sair em segundos/minutos depois do evento;
  - teto de consultas por chave (consChNFe) por CNPJ por hora (LIMITE_CONSCH_POR_HORA).
"""
import base64
import gzip
import hashlib
import logging
import os
import re
import secrets
import ssl
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12

from app.core.config import settings
from app.services.nfe_xml_service import CNPJ_POR_EMPRESA, strip_tag

logger = logging.getLogger("sefaz_dfe_service")

UF_CODIGO_DF = "53"  # as duas lojas são do DF

URL_NFE_DIST = {
    1: "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
    2: "https://hom1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx",
}
URL_NFE_EVENTO = {
    1: "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
    2: "https://hom1.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx",
}
URL_CTE_DIST = {
    1: "https://www1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx",
    2: "https://hom1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx",
}

NS_NFE = "http://www.portalfiscal.inf.br/nfe"
NS_CTE = "http://www.portalfiscal.inf.br/cte"
NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"

# Trava contra consumo indevido: chave -> timestamp da última consulta; CNPJ -> bloqueado até
_ultima_consulta_chave: Dict[str, float] = {}
_cnpj_bloqueado_ate: Dict[str, float] = {}
INTERVALO_MINIMO_MESMA_CHAVE_S = 60 * 60

# Depois da Ciência: espera mínima antes de cada nova consulta da chave (1ª, 2ª, ...). Soma ~38 min;
# esgotou, volta pra regra de 1 hora (aí o caminho é importar o XML).
RETENTATIVAS_APOS_CIENCIA_S = [4, 40, 90, 240, 600, 1200]
_ciencia_registrada_em: Dict[str, float] = {}
_consultas_apos_ciencia: Dict[str, int] = {}
# consChNFe por CNPJ na última hora (a SEFAZ limita consulta por chave; fica abaixo com folga)
LIMITE_CONSCH_POR_HORA = 18
_consch_por_cnpj: Dict[str, list] = {}


class SefazErro(Exception):
    pass


class SefazAguarde(SefazErro):
    """Ainda não pode consultar de novo sem arriscar bloqueio - `segundos` até poder."""
    def __init__(self, mensagem: str, segundos: float):
        super().__init__(mensagem)
        self.segundos = max(1, int(segundos))


def _pasta_certificados() -> str:
    return settings.NFE_CERT_DIR


def _arquivos_cert(empresa: str) -> Tuple[str, str]:
    base = os.path.join(_pasta_certificados(), empresa)
    return f"{base}.pfx", f"{base}.senha"


def _gravar_privado(caminho: str, conteudo: bytes):
    """Grava com permissão só do dono (600) - o .pfx e a senha nunca ficam legíveis por outros usuários."""
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(conteudo)


class SefazService:
    # ------------------------------------------------------------------ certificado
    @staticmethod
    def _cert_config(empresa: str) -> Tuple[str, str]:
        """
        Certificado enviado pela tela (pasta NFE_CERT_DIR, senha criptografada com a chave do
        servidor) tem prioridade; o .env (NFE_CERT_*_PATH/_SENHA) fica como alternativa.
        """
        from app.core.security import decrypt_data

        pfx, arq_senha = _arquivos_cert(empresa)
        if os.path.isfile(pfx) and os.path.isfile(arq_senha):
            with open(arq_senha, "r", encoding="utf-8") as fh:
                return pfx, decrypt_data(fh.read().strip())
        if empresa == "centrooeste":
            return settings.NFE_CERT_CENTROOESTE_PATH, settings.NFE_CERT_CENTROOESTE_SENHA
        return settings.NFE_CERT_SERVWELD_PATH, settings.NFE_CERT_SERVWELD_SENHA

    @staticmethod
    def _dados_cert(cert) -> Dict[str, Any]:
        from cryptography.x509.oid import NameOID

        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        cn = cn_attrs[0].value if cn_attrs else ""
        # e-CNPJ ICP-Brasil: CN = "RAZAO SOCIAL:12345678000199"
        m = re.search(r"(\d{14})", cn)
        validade = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
        return {
            "titular": cn.split(":")[0].strip() if cn else "",
            "cnpj": m.group(1) if m else "",
            "validade": validade.isoformat(),
            "dias_restantes": (validade - datetime.now(timezone.utc)).days,
        }

    @staticmethod
    def salvar_certificado(empresa: str, pfx_bytes: bytes, senha: str) -> Dict[str, Any]:
        """Valida o .pfx (senha, validade, CNPJ da loja) e guarda no servidor."""
        from app.core.security import encrypt_data

        try:
            chave, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode("utf-8"))
        except ValueError:
            raise SefazErro("Senha incorreta ou arquivo não é um certificado .pfx válido.")
        if chave is None or cert is None:
            raise SefazErro("O arquivo .pfx não contém a chave privada e o certificado.")
        dados = SefazService._dados_cert(cert)
        if dados["dias_restantes"] < 0:
            raise SefazErro(f"Este certificado venceu em {dados['validade'][:10]}.")
        cnpj_loja = CNPJ_POR_EMPRESA[empresa]
        if dados["cnpj"] and dados["cnpj"] != cnpj_loja:
            raise SefazErro(
                f"Este certificado é do CNPJ {dados['cnpj']} ({dados['titular']}), mas a loja escolhida é o CNPJ {cnpj_loja}. "
                "Confira se não trocou o arquivo das lojas."
            )
        os.makedirs(_pasta_certificados(), mode=0o700, exist_ok=True)
        pfx, arq_senha = _arquivos_cert(empresa)
        _gravar_privado(pfx, pfx_bytes)
        _gravar_privado(arq_senha, encrypt_data(senha).encode("utf-8"))
        logger.info(f"Certificado A1 da {empresa} atualizado: {dados['titular']} até {dados['validade'][:10]}")
        return dados

    @staticmethod
    def info_certificado(empresa: str) -> Dict[str, Any]:
        """Situação do certificado da loja para a tela (nunca devolve a senha)."""
        caminho, senha = SefazService._cert_config(empresa)
        if not caminho or not os.path.isfile(caminho):
            return {"configurado": False}
        try:
            with open(caminho, "rb") as fh:
                _, cert, _ = pkcs12.load_key_and_certificates(fh.read(), (senha or "").encode("utf-8"))
            return {"configurado": True, **SefazService._dados_cert(cert)}
        except Exception:
            return {"configurado": False, "erro": "Certificado salvo, mas a senha não abre o arquivo - envie de novo."}

    @staticmethod
    def certificado_configurado(empresa: str) -> bool:
        caminho, senha = SefazService._cert_config(empresa)
        return bool(caminho and senha and os.path.isfile(caminho))

    @staticmethod
    def _carregar_pfx(empresa: str):
        caminho, senha = SefazService._cert_config(empresa)
        if not caminho or not senha:
            raise SefazErro(
                f"Certificado digital da {empresa.upper()} não configurado no servidor "
                f"(NFE_CERT_{empresa.upper()}_PATH / _SENHA no .env)."
            )
        with open(caminho, "rb") as fh:
            chave, cert, _ = pkcs12.load_key_and_certificates(fh.read(), senha.encode("utf-8"))
        if chave is None or cert is None:
            raise SefazErro("O arquivo .pfx não contém a chave privada e o certificado.")
        validade = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)
        if validade < datetime.now(timezone.utc):
            raise SefazErro(f"O certificado digital da {empresa.upper()} venceu em {validade:%d/%m/%Y}.")
        return chave, cert

    @staticmethod
    def _ssl_context(chave, cert) -> ssl.SSLContext:
        """
        Contexto TLS com o certificado do cliente (autenticação mútua exigida pela SEFAZ).
        A chave vai para um arquivo temporário já cifrado com senha aleatória e é apagada logo
        depois de carregada - nunca fica em disco em texto puro.

        A cadeia dos servidores da SEFAZ é ICP-Brasil, que não está no repositório padrão do
        Python; sem um bundle próprio (NFE_SEFAZ_CA_BUNDLE) a verificação do servidor fica
        desligada, como fazem as bibliotecas de NF-e em geral.
        """
        ca_bundle = os.getenv("NFE_SEFAZ_CA_BUNDLE", "")
        if ca_bundle:
            ctx = ssl.create_default_context(cafile=ca_bundle)
        else:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        senha_tmp = secrets.token_urlsafe(24).encode()
        key_pem = chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(senha_tmp),
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        fd, caminho = tempfile.mkstemp(suffix=".pem")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(cert_pem + key_pem)
            ctx.load_cert_chain(caminho, password=senha_tmp)
        finally:
            try:
                os.remove(caminho)
            except OSError:
                pass
        return ctx

    # ------------------------------------------------------------------ transporte
    @staticmethod
    def _soap(url: str, body_xml: str, ctx: ssl.SSLContext) -> ET.Element:
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
            f"<soap12:Body>{body_xml}</soap12:Body></soap12:Envelope>"
        )
        try:
            with httpx.Client(verify=ctx, timeout=30.0) as client:
                res = client.post(
                    url,
                    content=envelope.encode("utf-8"),
                    headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                )
        except httpx.HTTPError as e:
            raise SefazErro(f"Não foi possível falar com a SEFAZ: {e}")
        if res.status_code != 200:
            raise SefazErro(f"SEFAZ respondeu HTTP {res.status_code}: {res.text[:300]}")
        return ET.fromstring(res.content)

    @staticmethod
    def _find(root: ET.Element, name: str) -> Optional[ET.Element]:
        for el in root.iter():
            if strip_tag(el.tag) == name:
                return el
        return None

    @staticmethod
    def _text(root: Optional[ET.Element], name: str) -> str:
        if root is None:
            return ""
        el = SefazService._find(root, name)
        return el.text.strip() if el is not None and el.text else ""

    @staticmethod
    def _checar_trava(cnpj: str, chave: str):
        agora = time.time()
        bloqueio = _cnpj_bloqueado_ate.get(cnpj, 0)
        if bloqueio > agora:
            minutos = int((bloqueio - agora) / 60) + 1
            raise SefazErro(
                f"A SEFAZ bloqueou temporariamente as consultas deste CNPJ por excesso de pedidos. "
                f"Tente de novo em ~{minutos} min (ou importe o XML manualmente)."
            )
        espera = SefazService.segundos_ate_poder_consultar(chave)
        if espera > 0:
            if chave in _ciencia_registrada_em:
                raise SefazAguarde(
                    f"Ciência registrada - aguardando a SEFAZ liberar o XML (nova tentativa em ~{espera} s).", espera
                )
            raise SefazAguarde(
                "Esta chave já foi consultada na SEFAZ há menos de 1 hora sem trazer o XML completo. "
                "Para não bloquear o CNPJ, aguarde ou importe o arquivo XML.", espera
            )

    @staticmethod
    def segundos_ate_poder_consultar(chave: str) -> int:
        """0 = pode consultar agora; senão quantos segundos faltam (trava por chave)."""
        agora = time.time()
        ultima = _ultima_consulta_chave.get(chave, 0)
        ciencia = _ciencia_registrada_em.get(chave)
        if ciencia:
            n = _consultas_apos_ciencia.get(chave, 0)
            if n < len(RETENTATIVAS_APOS_CIENCIA_S):
                base = max(ciencia, ultima if ultima > ciencia else ciencia)
                return max(0, int(base + RETENTATIVAS_APOS_CIENCIA_S[n] - agora + 0.999))
        if ultima and agora - ultima < INTERVALO_MINIMO_MESMA_CHAVE_S:
            return int(ultima + INTERVALO_MINIMO_MESMA_CHAVE_S - agora) + 1
        return 0

    @staticmethod
    def tentativas_apos_ciencia_restantes(chave: str) -> int:
        if chave not in _ciencia_registrada_em:
            return 0
        return max(0, len(RETENTATIVAS_APOS_CIENCIA_S) - _consultas_apos_ciencia.get(chave, 0))

    @staticmethod
    def ciencia_registrada(chave: str) -> bool:
        return chave in _ciencia_registrada_em

    @staticmethod
    def _checar_limite_consch(cnpj: str):
        agora = time.time()
        janela = [t for t in _consch_por_cnpj.get(cnpj, []) if agora - t < 3600]
        _consch_por_cnpj[cnpj] = janela
        if len(janela) >= LIMITE_CONSCH_POR_HORA:
            espera = janela[0] + 3600 - agora
            raise SefazAguarde(
                f"Muitas consultas por chave na SEFAZ na última hora - para não bloquear o CNPJ, a próxima "
                f"sai em ~{int(espera / 60) + 1} min (ou importe o XML).", espera
            )

    @staticmethod
    def _registrar_resposta(cnpj: str, chave: str, c_stat: str):
        _ultima_consulta_chave[chave] = time.time()
        if chave in _ciencia_registrada_em:
            _consultas_apos_ciencia[chave] = _consultas_apos_ciencia.get(chave, 0) + 1
        if c_stat == "656":
            _cnpj_bloqueado_ate[cnpj] = time.time() + 60 * 60

    # ------------------------------------------------------------------ distribuição
    @staticmethod
    def _nsu(nsu: str) -> str:
        # O Softsystem guarda o NSU de CT-e com prefixo "T" (ex: T00000000003043)
        return re.sub(r"\D", "", nsu).zfill(15)

    @staticmethod
    def _extrair_docs(ret: ET.Element) -> list:
        docs = []
        for el in ret.iter():
            if strip_tag(el.tag) != "docZip" or not el.text:
                continue
            conteudo = gzip.decompress(base64.b64decode(el.text))
            docs.append({
                "nsu": el.attrib.get("NSU", ""),
                "schema": el.attrib.get("schema", ""),
                "xml": conteudo,
            })
        return docs

    @staticmethod
    def _resultado_distribuicao(ret: ET.Element, chave: str) -> Dict[str, Any]:
        c_stat = SefazService._text(ret, "cStat")
        x_motivo = SefazService._text(ret, "xMotivo")
        resultado: Dict[str, Any] = {"cStat": c_stat, "xMotivo": x_motivo, "xml": None, "resumo": None}
        for doc in SefazService._extrair_docs(ret):
            schema = doc["schema"]
            if schema.startswith("procNFe") or schema.startswith("procCTe") or schema.startswith("cteProc"):
                resultado["xml"] = doc["xml"]
                resultado["nsu"] = doc["nsu"]
            elif schema.startswith("resNFe") and resultado["xml"] is None:
                res = ET.fromstring(doc["xml"])
                resultado["resumo"] = {
                    "chave": SefazService._text(res, "chNFe") or chave,
                    "emitente_cnpj": SefazService._text(res, "CNPJ"),
                    "emitente_nome": SefazService._text(res, "xNome"),
                    "data_emissao": SefazService._text(res, "dhEmi"),
                    "valor_total": float(SefazService._text(res, "vNF") or 0),
                    # 1 = autorizada, 2 = denegada, 3 = cancelada
                    "situacao": SefazService._text(res, "cSitNFe"),
                }
                resultado["nsu"] = doc["nsu"]
        return resultado

    @staticmethod
    def consultar_nfe(chave: str, empresa: str, nsu: Optional[str] = None) -> Dict[str, Any]:
        """
        Busca a NF-e na SEFAZ. Se `nsu` vier (do DOCUMENTOSDESTINADOS do Softsystem) usa
        consNSU, senão consChNFe. Retorna {cStat, xMotivo, xml (bytes|None), resumo (dict|None)}.
        """
        cnpj = CNPJ_POR_EMPRESA[empresa]
        SefazService._checar_trava(cnpj, chave)
        # depois da Ciência o XML completo entra com um NSU NOVO - consultar o NSU antigo devolveria
        # o mesmo resumo, então a re-consulta é sempre pela chave
        if chave in _ciencia_registrada_em:
            nsu = None
        if not nsu:
            SefazService._checar_limite_consch(cnpj)
        chave_priv, cert = SefazService._carregar_pfx(empresa)
        ctx = SefazService._ssl_context(chave_priv, cert)

        if nsu:
            consulta = f"<consNSU><NSU>{SefazService._nsu(nsu)}</NSU></consNSU>"
        else:
            consulta = f"<consChNFe><chNFe>{chave}</chNFe></consChNFe>"
        body = (
            '<nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">'
            "<nfeDadosMsg>"
            f'<distDFeInt xmlns="{NS_NFE}" versao="1.01">'
            f"<tpAmb>{settings.NFE_AMBIENTE}</tpAmb><cUFAutor>{UF_CODIGO_DF}</cUFAutor>"
            f"<CNPJ>{cnpj}</CNPJ>{consulta}</distDFeInt>"
            "</nfeDadosMsg></nfeDistDFeInteresse>"
        )
        if not nsu:
            _consch_por_cnpj.setdefault(cnpj, []).append(time.time())
        root = SefazService._soap(URL_NFE_DIST[settings.NFE_AMBIENTE], body, ctx)
        ret = SefazService._find(root, "retDistDFeInt")
        if ret is None:
            raise SefazErro("Resposta inesperada da SEFAZ (sem retDistDFeInt).")
        resultado = SefazService._resultado_distribuicao(ret, chave)
        SefazService._registrar_resposta(cnpj, chave, resultado["cStat"])
        logger.info(f"DistDFe NF-e {chave} ({empresa}): {resultado['cStat']} {resultado['xMotivo']}")
        return resultado

    @staticmethod
    def consultar_cte(chave: str, empresa: str, nsu: str) -> Dict[str, Any]:
        """CT-e só sai por NSU (o Ambiente Nacional do CT-e não tem consulta por chave)."""
        cnpj = CNPJ_POR_EMPRESA[empresa]
        SefazService._checar_trava(cnpj, chave)
        chave_priv, cert = SefazService._carregar_pfx(empresa)
        ctx = SefazService._ssl_context(chave_priv, cert)
        body = (
            '<cteDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe">'
            "<cteDadosMsg>"
            f'<distDFeInt xmlns="{NS_CTE}" versao="1.00">'
            f"<tpAmb>{settings.NFE_AMBIENTE}</tpAmb><cUFAutor>{UF_CODIGO_DF}</cUFAutor>"
            f"<CNPJ>{cnpj}</CNPJ><consNSU><NSU>{SefazService._nsu(nsu)}</NSU></consNSU></distDFeInt>"
            "</cteDadosMsg></cteDistDFeInteresse>"
        )
        root = SefazService._soap(URL_CTE_DIST[settings.NFE_AMBIENTE], body, ctx)
        ret = SefazService._find(root, "retDistDFeInt")
        if ret is None:
            raise SefazErro("Resposta inesperada da SEFAZ do CT-e (sem retDistDFeInt).")
        resultado = SefazService._resultado_distribuicao(ret, chave)
        SefazService._registrar_resposta(cnpj, chave, resultado["cStat"])
        logger.info(f"DistDFe CT-e {chave} ({empresa}): {resultado['cStat']} {resultado['xMotivo']}")
        return resultado

    # ------------------------------------------------------------------ manifestação
    @staticmethod
    def _assinar_inf_evento(inf_evento_c14n: str, id_evento: str, chave_priv, cert) -> str:
        """
        Assinatura XML-DSig enveloped (RSA-SHA1, C14N 1.0) exigida pela SEFAZ.
        `inf_evento_c14n` já vem na forma canônica (montado por nós, sem espaços, com o
        namespace herdado declarado), então o digest é calculado direto sobre ele.
        """
        digest = base64.b64encode(hashlib.sha1(inf_evento_c14n.encode("utf-8")).digest()).decode()
        signed_info = (
            f'<SignedInfo xmlns="{NS_DSIG}">'
            '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"></CanonicalizationMethod>'
            '<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"></SignatureMethod>'
            f'<Reference URI="#{id_evento}">'
            "<Transforms>"
            '<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"></Transform>'
            '<Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"></Transform>'
            "</Transforms>"
            '<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"></DigestMethod>'
            f"<DigestValue>{digest}</DigestValue>"
            "</Reference></SignedInfo>"
        )
        assinatura = base64.b64encode(
            chave_priv.sign(signed_info.encode("utf-8"), padding.PKCS1v15(), hashes.SHA1())
        ).decode()
        cert_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
        return (
            f'<Signature xmlns="{NS_DSIG}">{signed_info}'
            f"<SignatureValue>{assinatura}</SignatureValue>"
            f"<KeyInfo><X509Data><X509Certificate>{cert_b64}</X509Certificate></X509Data></KeyInfo>"
            "</Signature>"
        )

    @staticmethod
    def manifestar_ciencia(chave: str, empresa: str) -> Dict[str, Any]:
        """Registra o evento 210210 - Ciência da Operação. Duplicidade (573) conta como sucesso."""
        return SefazService.manifestar(chave, empresa, "ciencia")

    @staticmethod
    def manifestar(chave: str, empresa: str, tipo: str = "ciencia") -> Dict[str, Any]:
        """
        Manifestação do destinatário que libera o XML completo:
          ciencia     210210 "Ciencia da Operacao"    - só até 10 dias da emissão (cStat 596 depois)
          confirmacao 210200 "Confirmacao da Operacao" - até 180 dias; declara que a mercadoria
                      foi RECEBIDA (15/10/2026: nota da ESAB de 02/10 já fora do prazo da Ciência).
        """
        cnpj = CNPJ_POR_EMPRESA[empresa]
        chave_priv, cert = SefazService._carregar_pfx(empresa)
        ctx = SefazService._ssl_context(chave_priv, cert)

        tp_evento, desc_evento = {"ciencia": ("210210", "Ciencia da Operacao"),
                                  "confirmacao": ("210200", "Confirmacao da Operacao")}[tipo]
        n_seq = "1"
        id_evento = f"ID{tp_evento}{chave}{n_seq.zfill(2)}"
        dh_evento = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%dT%H:%M:%S-03:00")
        inf_evento = (
            f'<infEvento xmlns="{NS_NFE}" Id="{id_evento}">'
            f"<cOrgao>91</cOrgao><tpAmb>{settings.NFE_AMBIENTE}</tpAmb><CNPJ>{cnpj}</CNPJ>"
            f"<chNFe>{chave}</chNFe><dhEvento>{dh_evento}</dhEvento><tpEvento>{tp_evento}</tpEvento>"
            f"<nSeqEvento>{n_seq}</nSeqEvento><verEvento>1.00</verEvento>"
            f'<detEvento versao="1.00"><descEvento>{desc_evento}</descEvento></detEvento>'
            "</infEvento>"
        )
        signature = SefazService._assinar_inf_evento(inf_evento, id_evento, chave_priv, cert)
        # Dentro do <evento> o namespace já é herdado do envEvento - a forma serializada sem o
        # xmlns repetido é equivalente à canônica usada no digest.
        inf_evento_doc = inf_evento.replace(f' xmlns="{NS_NFE}"', "", 1)
        id_lote = str(int(time.time() * 1000))[-15:]
        body = (
            '<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4">'
            f'<envEvento xmlns="{NS_NFE}" versao="1.00"><idLote>{id_lote}</idLote>'
            f'<evento versao="1.00">{inf_evento_doc}{signature}</evento>'
            "</envEvento></nfeDadosMsg>"
        )
        root = SefazService._soap(URL_NFE_EVENTO[settings.NFE_AMBIENTE], body, ctx)
        ret_evento = SefazService._find(root, "retEvento")
        c_stat = SefazService._text(ret_evento, "cStat") if ret_evento is not None else SefazService._text(root, "cStat")
        x_motivo = SefazService._text(ret_evento, "xMotivo") if ret_evento is not None else SefazService._text(root, "xMotivo")
        sucesso = c_stat in ("135", "136", "573")
        if sucesso and chave not in _ciencia_registrada_em:
            # abre a janela de re-consultas rápidas (RETENTATIVAS_APOS_CIENCIA_S)
            _ciencia_registrada_em[chave] = time.time()
            _consultas_apos_ciencia[chave] = 0
        logger.info(f"Manifestação {desc_evento} {chave} ({empresa}): {c_stat} {x_motivo}")
        return {
            "sucesso": sucesso,
            "cStat": c_stat,
            "xMotivo": x_motivo,
            "protocolo": SefazService._text(ret_evento, "nProt") if ret_evento is not None else "",
        }
