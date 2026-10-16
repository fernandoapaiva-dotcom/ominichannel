import json
import logging
import re
import statistics
from typing import Dict, Any, Optional, List

import httpx

from app.core.config import settings

logger = logging.getLogger("market_price_service")

# 15/10/2026: o Google desligou o gemini-2.5-flash ("no longer available") - pesquisa de concorrentes e
# textos do site davam HTTP 404. gemini-3.6-flash é o mesmo modelo do resto do sistema e aceita busca no Google.
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"


def _extrair_json(texto: str) -> Optional[Dict[str, Any]]:
    """Com a busca do Google ligada o Gemini não aceita resposta em modo JSON - extrai do texto."""
    limpo = re.sub(r"```(?:json)?", "", texto or "").strip()
    inicio, fim = limpo.find("{"), limpo.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        return json.loads(limpo[inicio:fim + 1])
    except json.JSONDecodeError:
        return None


class MarketPriceService:
    @staticmethod
    async def pesquisar_preco_mercado(descricao: str, ean: Optional[str] = None, ncm: Optional[str] = None,
                                      api_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Pesquisa concorrentes reais (Google Search via Gemini) vendendo o mesmo produto no Brasil
        e devolve a lista (loja, preço, link) + mínimo/mediana/máximo. Os links vêm das fontes
        que o Google efetivamente consultou (groundingMetadata), não de memória do modelo.
        `api_key` é a chave do tenant (Configurações); sem ela cai na do .env.
        """
        api_key = api_key or settings.GEMINI_API_KEY
        if not api_key:
            return {"min": None, "med": None, "max": None, "concorrentes": [], "fonte": "sem_api_key"}

        prompt = f"""Pesquise no Google o preço de venda atual, no Brasil, deste produto de solda/ferramentas/EPI:
- Descrição: {descricao}
- EAN: {ean or 'não informado'}
- NCM: {ncm or 'não informado'}

Procure o MESMO produto (mesma marca, modelo e medida) em lojas online brasileiras (lojas de solda,
ferramentas, Mercado Livre, Amazon, Leroy Merlin, distribuidores). Ignore itens diferentes, kits
ou usados. Preço à vista, por unidade, em reais.

Responda SOMENTE com um JSON neste formato, sem texto fora dele:
{{"concorrentes": [{{"loja": "nome da loja", "preco": 123.45, "url": "link da página do produto", "observacao": "ex: frete grátis, à vista no pix"}}],
  "resumo": "uma frase sobre a faixa de preço encontrada"}}
Se não encontrar o mesmo produto, devolva "concorrentes": [].
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.1},
        }
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(GEMINI_URL, params={"key": api_key}, json=payload)
            if res.status_code != 200:
                logger.warning(f"Gemini preço de mercado HTTP {res.status_code}: {res.text[:200]}")
                return {"min": None, "med": None, "max": None, "concorrentes": [], "fonte": "indisponivel"}
            data = res.json()
        except Exception as e:
            logger.warning(f"Erro na pesquisa de preço de mercado para '{descricao}': {e}")
            return {"min": None, "med": None, "max": None, "concorrentes": [], "fonte": "indisponivel"}

        cand = (data.get("candidates") or [{}])[0]
        texto = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
        parsed = _extrair_json(texto) or {}

        fontes: List[Dict[str, str]] = []
        for chunk in (cand.get("groundingMetadata") or {}).get("groundingChunks", []) or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                fontes.append({"titulo": web.get("title", ""), "url": web["uri"]})

        concorrentes = []
        for c in parsed.get("concorrentes") or []:
            try:
                preco = float(str(c.get("preco")).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if preco <= 0:
                continue
            concorrentes.append({
                "loja": str(c.get("loja") or "").strip()[:80],
                "preco": round(preco, 2),
                "url": str(c.get("url") or "").strip(),
                "observacao": str(c.get("observacao") or "").strip()[:120],
            })
        concorrentes.sort(key=lambda c: c["preco"])

        # Descarta preços absurdos (outro produto, kit) - fora de 3x / 1/3 da mediana
        if len(concorrentes) >= 3:
            med = statistics.median(c["preco"] for c in concorrentes)
            concorrentes = [c for c in concorrentes if med / 3 <= c["preco"] <= med * 3]

        precos = [c["preco"] for c in concorrentes]
        return {
            "min": min(precos) if precos else None,
            "med": round(statistics.median(precos), 2) if precos else None,
            "max": max(precos) if precos else None,
            "concorrentes": concorrentes,
            "fontes": fontes[:10],
            "resumo": parsed.get("resumo") or ("Nenhum concorrente com o mesmo produto encontrado." if not precos else ""),
            "fonte": "google_search",
        }
