import xml.etree.ElementTree as ET
import os
import re
from typing import Dict, Any, List, Optional
import logging

from app.core.config import settings

logger = logging.getLogger("nfe_xml_service")

# CNPJs das lojas (EMPRESA.CGC de cada banco do Softsystem)
CNPJ_SERVWELD = "11504286000169"       # Servweld (Lucro Presumido) - EMPRESA.CGC loja 1
CNPJ_CENTROOESTE = "54804458000122"    # Centro Oeste (Simples Nacional) - EMPRESA.CGC loja 2
CNPJ_POR_EMPRESA = {"servweld": CNPJ_SERVWELD, "centrooeste": CNPJ_CENTROOESTE}
EMPRESA_POR_CNPJ = {v: k for k, v in CNPJ_POR_EMPRESA.items()}

UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"
}


def clean_cnpj(val: Optional[str]) -> str:
    if not val:
        return ""
    return re.sub(r"\D", "", val)


def strip_tag(tag: str) -> str:
    """Remove namespace XML para facilitar a navegação."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


# Helpers de navegação sem namespace. `path` aceita "a/b/c".
def _child(parent: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    if parent is None:
        return None
    for c in parent:
        if strip_tag(c.tag) == name:
            return c
    return None


def _children(parent: Optional[ET.Element], name: str) -> List[ET.Element]:
    if parent is None:
        return []
    return [c for c in parent if strip_tag(c.tag) == name]


def _find(parent: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    el = parent
    for part in path.split("/"):
        el = _child(el, part)
        if el is None:
            return None
    return el


def _t(parent: Optional[ET.Element], path: str, default: str = "") -> str:
    el = _find(parent, path)
    return el.text.strip() if el is not None and el.text else default


def _n(parent: Optional[ET.Element], path: str, default: float = 0.0) -> float:
    txt = _t(parent, path)
    try:
        return float(txt) if txt else default
    except ValueError:
        return default


def _first_child(parent: Optional[ET.Element]) -> Optional[ET.Element]:
    """ICMS, IPI, PIS e COFINS têm um único subgrupo cujo nome varia (ICMS00, ICMSSN102, PISAliq...)."""
    if parent is None:
        return None
    for c in parent:
        return c
    return None


def _find_root(root: ET.Element, name: str) -> Optional[ET.Element]:
    for elem in root.iter():
        if strip_tag(elem.tag) == name:
            return elem
    return None


def _cadastro_emitente(emit: Optional[ET.Element]) -> Dict[str, Any]:
    """Dados do emitente (fornecedor/transportadora) para cadastrá-lo no Softsystem se faltar."""
    ender = _child(emit, "enderEmit")
    fone = re.sub(r"\D", "", _t(ender, "fone"))
    return {
        "cnpj": clean_cnpj(_t(emit, "CNPJ") or _t(emit, "CPF")),
        "razao_social": _t(emit, "xNome"),
        "nome_fantasia": _t(emit, "xFant"),
        "ie": _t(emit, "IE"),
        "logradouro": " ".join(x for x in (_t(ender, "xLgr"), _t(ender, "nro")) if x),
        "bairro": _t(ender, "xBairro"),
        "cidade": _t(ender, "xMun"),
        "cod_ibge": _t(ender, "cMun"),
        "uf": _t(ender, "UF"),
        "cep": re.sub(r"\D", "", _t(ender, "CEP")),
        "ddd": fone[:2] if len(fone) >= 10 else "",
        "fone": fone[2:] if len(fone) >= 10 else fone,
    }


def empresa_por_cnpj(cnpj: str) -> Optional[str]:
    return EMPRESA_POR_CNPJ.get(clean_cnpj(cnpj))


class NfeXmlService:
    @staticmethod
    def parse_xml_content(xml_bytes_or_str: bytes | str) -> Dict[str, Any]:
        """
        Interpreta o XML da NF-e (layout 4.00) ou CT-e (layout 4.00) e extrai
        todos os dados comerciais, fiscais, de itens e de cobrança.
        """
        if isinstance(xml_bytes_or_str, str):
            xml_bytes = xml_bytes_or_str.encode("utf-8")
        else:
            xml_bytes = xml_bytes_or_str

        root = ET.fromstring(xml_bytes.strip())

        # CT-e primeiro: ele cita as notas transportadas em infDoc/infNFe, então procurar
        # infNFe antes confundiria um CT-e com NF-e.
        inf_cte = _find_root(root, "infCte")
        if inf_cte is not None:
            data = NfeXmlService._parse_cte(inf_cte)
            data["protocolo"] = _t(_find_root(root, "infProt"), "nProt") or None
            return data

        inf_nfe = _find_root(root, "infNFe")
        if inf_nfe is not None:
            data = NfeXmlService._parse_nfe(inf_nfe)
            data["protocolo"] = _t(_find_root(root, "infProt"), "nProt") or None
            return data

        if _find_root(root, "resNFe") is not None:
            raise ValueError(
                "A SEFAZ devolveu só o resumo desta NF-e (sem os produtos). "
                "É preciso registrar a 'Ciência da Operação' para liberar o XML completo."
            )
        raise ValueError("O XML fornecido não é uma NF-e nem um CT-e válido da SEFAZ.")

    @staticmethod
    def validar_chave(chave: str) -> str:
        """Limpa e confere o dígito verificador (módulo 11) da chave de acesso."""
        chave_clean = re.sub(r"\D", "", chave or "")
        if len(chave_clean) != 44:
            raise ValueError(f"A chave de acesso deve ter exatamente 44 dígitos (recebido: {len(chave_clean)}).")
        pesos = [2, 3, 4, 5, 6, 7, 8, 9]
        soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(chave_clean[:43])))
        resto = soma % 11
        dv = 0 if resto in (0, 1) else 11 - resto
        if dv != int(chave_clean[43]):
            raise ValueError("Chave de acesso inválida: o dígito verificador não confere. Confira se algum número foi digitado errado.")
        return chave_clean

    @staticmethod
    def decodificar_chave_acesso(chave: str) -> Dict[str, Any]:
        """
        Decodifica a chave de acesso de 44 dígitos da NF-e (mod 55) ou CT-e (mod 57).
        """
        chave_clean = NfeXmlService.validar_chave(chave)

        uf_codigo = chave_clean[0:2]
        aamm = chave_clean[2:6]
        cnpj_emitente = chave_clean[6:20]
        modelo = chave_clean[20:22]
        serie = chave_clean[22:25]
        numero_doc = chave_clean[25:34]

        tipo_doc, tipo_desc = "NFE", "Nota Fiscal Eletrônica (NF-e)"
        if modelo == "57":
            tipo_doc, tipo_desc = "CTE", "Conhecimento de Transporte (CT-e)"
        elif modelo == "65":
            tipo_doc, tipo_desc = "NFCE", "Nota Fiscal de Consumidor (NFC-e)"

        return {
            "chave_acesso": chave_clean,
            "chave_formatada": " ".join(chave_clean[i:i + 4] for i in range(0, 44, 4)),
            "tipo_documento": tipo_doc,
            "descricao_tipo": tipo_desc,
            "uf_origem": UF_POR_CODIGO.get(uf_codigo, "BR"),
            "uf_codigo": uf_codigo,
            "mes_ano": f"{aamm[2:4]}/20{aamm[0:2]}",
            "cnpj_emitente": cnpj_emitente,
            "cnpj_emitente_formatado": f"{cnpj_emitente[:2]}.{cnpj_emitente[2:5]}.{cnpj_emitente[5:8]}/{cnpj_emitente[8:12]}-{cnpj_emitente[12:]}",
            "modelo": modelo,
            "serie": str(int(serie)),
            "numero_documento": str(int(numero_doc)),
            "digito_verificador": chave_clean[43],
        }

    @staticmethod
    def localizar_xml_local(chave: str) -> Optional[str]:
        """
        Procura o XML pela chave nas pastas onde o Softsystem salva as notas (ele só salva
        o XML do fornecedor depois que a entrada é lançada) e no cache local onde guardamos
        o que já foi baixado da SEFAZ. Retorna o caminho do arquivo ou None.
        """
        pastas = [p.strip() for p in (settings.NFE_XML_DIRS or "").split(";") if p.strip()]
        pastas.append(settings.NFE_XML_CACHE_DIR)
        nomes = (f"{chave}.xml", f"{chave}-procNFe.xml", f"{chave}-nfe.xml", f"{chave}-procCTe.xml", f"{chave}-cte.xml")
        for pasta in pastas:
            for nome in nomes:
                caminho = os.path.join(pasta, nome)
                try:
                    if os.path.isfile(caminho):
                        return caminho
                except OSError as e:
                    # Pasta de rede fora do ar não pode travar a busca - segue para a próxima
                    logger.warning(f"Pasta de XML inacessível ({pasta}): {e}")
                    break
        return None

    @staticmethod
    def salvar_xml_cache(chave: str, xml_bytes: bytes) -> str:
        os.makedirs(settings.NFE_XML_CACHE_DIR, exist_ok=True)
        caminho = os.path.join(settings.NFE_XML_CACHE_DIR, f"{chave}.xml")
        with open(caminho, "wb") as fh:
            fh.write(xml_bytes)
        return caminho

    @staticmethod
    def _parse_item_impostos(imposto: Optional[ET.Element]) -> Dict[str, Any]:
        icms = _first_child(_child(imposto, "ICMS"))
        ipi = _child(imposto, "IPI")
        ipi_trib = _child(ipi, "IPITrib")
        ipi_grupo = ipi_trib if ipi_trib is not None else _child(ipi, "IPINT")
        pis = _first_child(_child(imposto, "PIS"))
        cofins = _first_child(_child(imposto, "COFINS"))
        ibscbs = _child(imposto, "IBSCBS")
        g_ibscbs = _child(ibscbs, "gIBSCBS")

        return {
            "origem": _t(icms, "orig"),
            "cst_icms": _t(icms, "CST"),
            "csosn": _t(icms, "CSOSN"),
            "v_bc_icms": _n(icms, "vBC"),
            "p_icms": _n(icms, "pICMS"),
            "v_icms": _n(icms, "vICMS"),
            "p_red_bc": _n(icms, "pRedBC"),
            "p_mva_st": _n(icms, "pMVAST"),
            "v_bc_st": _n(icms, "vBCST"),
            "p_icms_st": _n(icms, "pICMSST"),
            "v_icms_st": _n(icms, "vICMSST"),
            "v_fcp_st": _n(icms, "vFCPST"),
            # ST retida anteriormente (CST 60 / CSOSN 500) - já pago na cadeia, não gera custo extra
            "v_icms_st_ret": _n(icms, "vICMSSTRet"),
            # Crédito do Simples destacado pelo fornecedor optante (CSOSN 101/201)
            "p_cred_sn": _n(icms, "pCredSN"),
            "v_cred_icms_sn": _n(icms, "vCredICMSSN"),
            "cst_ipi": _t(ipi_grupo, "CST"),
            "p_ipi": _n(ipi_trib, "pIPI"),
            "v_ipi": _n(ipi_trib, "vIPI"),
            "cst_pis": _t(pis, "CST"),
            "p_pis": _n(pis, "pPIS"),
            "v_pis": _n(pis, "vPIS"),
            "cst_cofins": _t(cofins, "CST"),
            "p_cofins": _n(cofins, "pCOFINS"),
            "v_cofins": _n(cofins, "vCOFINS"),
            # Reforma tributária (NT 2025.002) - em 2026 é destaque informativo (CBS 0,9% / IBS 0,1%)
            "cst_ibscbs": _t(ibscbs, "CST"),
            "c_class_trib": _t(ibscbs, "cClassTrib"),
            "v_ibs": _n(g_ibscbs, "vIBS"),
            "v_cbs": _n(g_ibscbs, "gCBS/vCBS"),
            "p_cbs": _n(g_ibscbs, "gCBS/pCBS"),
            "p_ibs_uf": _n(g_ibscbs, "gIBSUF/pIBSUF"),
        }

    @staticmethod
    def _parse_nfe(inf_nfe: ET.Element) -> Dict[str, Any]:
        chave_acesso = re.sub(r"^NFe", "", inf_nfe.attrib.get("Id", "")).strip()

        ide = _child(inf_nfe, "ide")
        emit = _child(inf_nfe, "emit")
        dest = _child(inf_nfe, "dest")
        transp = _child(inf_nfe, "transp")
        total = _child(inf_nfe, "total")
        cobr = _child(inf_nfe, "cobr")
        pag = _child(inf_nfe, "pag")

        ender_emit = _child(emit, "enderEmit")
        endereco_forn = f"{_t(ender_emit, 'xLgr')}, {_t(ender_emit, 'nro')} - {_t(ender_emit, 'xBairro')}" if ender_emit is not None else ""

        dest_cnpj = clean_cnpj(_t(dest, "CNPJ") or _t(dest, "CPF"))
        dest_nome = _t(dest, "xNome")
        empresa_destino = empresa_por_cnpj(dest_cnpj)
        if not empresa_destino:
            nome_up = dest_nome.upper()
            empresa_destino = "centrooeste" if ("CENTRO" in nome_up and "OESTE" in nome_up) else "servweld"

        transporta = _child(transp, "transporta")
        vols = _children(transp, "vol")

        icms_tot = _child(total, "ICMSTot")
        ibscbs_tot = _child(total, "IBSCBSTot")

        itens: List[Dict[str, Any]] = []
        for det in _children(inf_nfe, "det"):
            prod = _child(det, "prod")
            c_ean = _t(prod, "cEAN")
            if c_ean.upper() == "SEM GTIN":
                c_ean = ""
            c_ean_trib = _t(prod, "cEANTrib")
            if c_ean_trib.upper() == "SEM GTIN":
                c_ean_trib = ""
            item = {
                "numero_item": int(det.attrib.get("nItem", len(itens) + 1)),
                "codigo_fornecedor": _t(prod, "cProd"),
                "ean": c_ean or c_ean_trib,
                "descricao_fornecedor": _t(prod, "xProd"),
                "ncm": _t(prod, "NCM"),
                "cest": _t(prod, "CEST"),
                "cfop": _t(prod, "CFOP"),
                "unidade": _t(prod, "uCom"),
                "quantidade": _n(prod, "qCom", 1.0),
                "valor_unitario": _n(prod, "vUnCom"),
                "valor_total": _n(prod, "vProd"),
                "unidade_tributavel": _t(prod, "uTrib"),
                "quantidade_tributavel": _n(prod, "qTrib", 0.0),
                "valor_frete_item": _n(prod, "vFrete"),
                "valor_seguro_item": _n(prod, "vSeg"),
                "valor_desconto_item": _n(prod, "vDesc"),
                "valor_outras_desp_item": _n(prod, "vOutro"),
                "pedido_compra": _t(prod, "xPed"),
                "info_adicional": _t(det, "infAdProd"),
            }
            item.update(NfeXmlService._parse_item_impostos(_child(det, "imposto")))
            itens.append(item)

        # Cobrança: duplicatas com vencimento (quando o fornecedor informa)
        duplicatas = []
        for dup in _children(cobr, "dup"):
            duplicatas.append({
                "numero": _t(dup, "nDup"),
                "vencimento": _t(dup, "dVenc"),
                "valor": _n(dup, "vDup"),
            })
        formas_pagamento = [
            {"tipo": _t(dp, "tPag"), "valor": _n(dp, "vPag"), "indicador": _t(dp, "indPag")}
            for dp in _children(pag, "detPag")
        ]

        return {
            "tipo_documento": "NFE",
            "chave_acesso": chave_acesso,
            "numero_nf": _t(ide, "nNF"),
            "serie": _t(ide, "serie"),
            "data_emissao": _t(ide, "dhEmi") or _t(ide, "dEmi"),
            "natureza_operacao": _t(ide, "natOp"),
            "tipo_operacao": _t(ide, "tpNF"),  # 0 = entrada, 1 = saída (do ponto de vista do emitente)
            "empresa_destino": empresa_destino,
            "fornecedor": {
                "cnpj": clean_cnpj(_t(emit, "CNPJ") or _t(emit, "CPF")),
                "razao_social": _t(emit, "xNome"),
                "nome_fantasia": _t(emit, "xFant"),
                "ie": _t(emit, "IE"),
                "crt": _t(emit, "CRT"),  # 1 = Simples Nacional, 2 = Simples excesso, 3 = Regime normal
                "endereco": endereco_forn,
                "cidade": _t(ender_emit, "xMun"),
                "uf": _t(ender_emit, "UF"),
                "telefone": _t(ender_emit, "fone"),
                "cadastro": _cadastro_emitente(emit),
            },
            "destinatario": {
                "cnpj": dest_cnpj,
                "razao_social": dest_nome,
                "uf": _t(dest, "enderDest/UF"),
            },
            "transportadora": {
                "cnpj": clean_cnpj(_t(transporta, "CNPJ") or _t(transporta, "CPF")),
                "razao_social": _t(transporta, "xNome"),
                # 0 = por conta do emitente (CIF), 1 = destinatário (FOB), 2 = terceiros, 9 = sem frete
                "modalidade_frete": _t(transp, "modFrete"),
            },
            "volumes": {
                "quantidade": sum(_n(v, "qVol") for v in vols),
                "peso_liquido": sum(_n(v, "pesoL") for v in vols),
                "peso_bruto": sum(_n(v, "pesoB") for v in vols),
            },
            "totais": {
                "valor_produtos": _n(icms_tot, "vProd"),
                "valor_frete": _n(icms_tot, "vFrete"),
                "valor_seguro": _n(icms_tot, "vSeg"),
                "valor_desconto": _n(icms_tot, "vDesc"),
                "valor_outras_despesas": _n(icms_tot, "vOutro"),
                "valor_bc_icms": _n(icms_tot, "vBC"),
                "valor_icms": _n(icms_tot, "vICMS"),
                "valor_bc_st": _n(icms_tot, "vBCST"),
                "valor_st": _n(icms_tot, "vST"),
                "valor_fcp_st": _n(icms_tot, "vFCPST"),
                "valor_ipi": _n(icms_tot, "vIPI"),
                "valor_pis": _n(icms_tot, "vPIS"),
                "valor_cofins": _n(icms_tot, "vCOFINS"),
                "valor_ibs": _n(ibscbs_tot, "gIBS/vIBS"),
                "valor_cbs": _n(ibscbs_tot, "gCBS/vCBS"),
                "valor_total_nf": _n(icms_tot, "vNF"),
            },
            "fatura": {
                "numero": _t(cobr, "fat/nFat"),
                "valor_original": _n(cobr, "fat/vOrig"),
                "valor_desconto": _n(cobr, "fat/vDesc"),
                "valor_liquido": _n(cobr, "fat/vLiq"),
            },
            "duplicatas": duplicatas,
            "formas_pagamento": formas_pagamento,
            "informacoes_complementares": _t(inf_nfe, "infAdic/infCpl"),
            "itens": itens,
        }

    @staticmethod
    def _parse_cte(inf_cte: ET.Element) -> Dict[str, Any]:
        """Interpreta Conhecimento de Transporte Eletrônico (CT-e)."""
        chave_acesso = re.sub(r"^CTe", "", inf_cte.attrib.get("Id", "")).strip()

        ide = _child(inf_cte, "ide")
        emit = _child(inf_cte, "emit")
        v_prest = _child(inf_cte, "vPrest")
        imp_icms = _first_child(_find(inf_cte, "imp/ICMS"))

        # Tomador do serviço (quem paga o frete): toma3 aponta para um dos participantes,
        # toma4 traz o próprio tomador.
        papeis = {"0": "rem", "1": "exped", "2": "receb", "3": "dest"}
        toma3 = _child(ide, "toma3")
        toma4 = _child(ide, "toma4")
        tomador_cnpj = ""
        if toma3 is not None:
            papel = papeis.get(_t(toma3, "toma"))
            if papel:
                part = _child(inf_cte, papel)
                tomador_cnpj = clean_cnpj(_t(part, "CNPJ") or _t(part, "CPF"))
        elif toma4 is not None:
            tomador_cnpj = clean_cnpj(_t(toma4, "CNPJ") or _t(toma4, "CPF"))

        chaves_nfe = [
            _t(inf_nfe, "chave")
            for inf_nfe in _children(_find(inf_cte, "infCTeNorm/infDoc"), "infNFe")
            if _t(inf_nfe, "chave")
        ]
        componentes = [
            {"nome": _t(c, "xNome"), "valor": _n(c, "vComp")}
            for c in _children(v_prest, "Comp")
        ]
        # cobrança do frete (quando a transportadora informa a fatura/duplicatas no CT-e)
        cobr = _find(inf_cte, "infCTeNorm/cobr")
        duplicatas = [
            {"numero": _t(d, "nDup"), "vencimento": _t(d, "dVenc"), "valor": _n(d, "vDup")}
            for d in _children(cobr, "dup")
        ]
        observacoes = " ".join(
            x for x in [_t(inf_cte, "compl/xObs")] + [_t(o, "xTexto") for o in _children(_child(inf_cte, "compl"), "ObsCont")] if x
        )

        return {
            "tipo_documento": "CTE",
            "chave_acesso": chave_acesso,
            "numero_cte": _t(ide, "nCT"),
            "serie": _t(ide, "serie"),
            "data_emissao": _t(ide, "dhEmi"),
            "cfop": _t(ide, "CFOP"),
            "uf_inicio": _t(ide, "UFIni"),
            "uf_fim": _t(ide, "UFFim"),
            "transportadora": {
                "cnpj": clean_cnpj(_t(emit, "CNPJ")),
                "razao_social": _t(emit, "xNome"),
                "ie": _t(emit, "IE"),
                "uf": _t(emit, "enderEmit/UF"),
                "cadastro": _cadastro_emitente(emit),
            },
            "remetente_cnpj": clean_cnpj(_t(inf_cte, "rem/CNPJ")),
            "destinatario_cnpj": clean_cnpj(_t(inf_cte, "dest/CNPJ")),
            "tomador_cnpj": tomador_cnpj,
            "empresa_tomadora": empresa_por_cnpj(tomador_cnpj),
            "valor_frete_total": _n(v_prest, "vTPrest"),
            "valor_a_receber": _n(v_prest, "vRec"),
            "componentes": componentes,
            "icms": {
                "cst": _t(imp_icms, "CST"),
                "v_bc": _n(imp_icms, "vBC"),
                "p_icms": _n(imp_icms, "pICMS"),
                "v_icms": _n(imp_icms, "vICMS"),
            },
            "valor_carga": _n(inf_cte, "infCTeNorm/infCarga/vCarga"),
            "chaves_nfe": chaves_nfe,
            "fatura": {"numero": _t(cobr, "fat/nFat"), "valor_liquido": _n(cobr, "fat/vLiq")},
            "duplicatas": duplicatas,
            "informacoes_complementares": observacoes,
        }
