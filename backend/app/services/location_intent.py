"""
Interpretação de localização nas mensagens do cliente (regras, sem IA).

Duas situações opostas que o sistema precisa distinguir:
  - STORE_LOCATION:    o cliente PEDE a localização/endereço da loja -> o sistema envia a da loja.
  - CUSTOMER_LOCATION: o cliente ENVIA a própria localização (pin do WhatsApp ou link do Maps),
                       normalmente pra gente ir até o local fazer uma visita -> o sistema NÃO
                       pode responder com a localização da loja; trata como local de visita.

Antes disto a decisão era uma lista de frases fixas: ~metade dos jeitos comuns de pedir a loja
("Onde é a loja de vocês?", "Vocês ficam onde?", "endereço por favor", "manda o pin") caía em NONE,
e o texto que o sistema gera para o pin do cliente ("Localização Compartilhada pelo Cliente")
casava com "localiza" + "compartilha" e era lido como PEDIDO da loja.
"""
import re
import unicodedata
from typing import Tuple

STORE_LOCATION = "STORE_LOCATION"
STORE_HOURS = "STORE_HOURS"
CUSTOMER_LOCATION = "CUSTOMER_LOCATION"
NONE = "NONE"

# Texto que o próprio webhook gera quando o cliente compartilha um pin (ver receive_evolution_webhook).
PIN_MARKER = "localizacao recebida do cliente"

MAPS_LINK = re.compile(
    r"(maps\.app\.goo\.gl|goo\.gl/maps|google\.[a-z.]{2,6}/maps|maps\.google\.|waze\.com/ul|maps\.apple\.com)",
    re.I,
)


def normalize(text: str) -> str:
    """minúsculas, sem acento, abreviações de chat expandidas, pontuação virando espaço."""
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"\b(vcs|vcss|vces)\b", "voces", t)
    t = re.sub(r"\b(vc|voce)\b", "voce", t)
    t = re.sub(r"\b(pfv|pf|pfvr|pls|plz|por favor|porfavor)\b", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# --- o cliente falando da PRÓPRIA localização/endereço (nunca é pedido da loja) ---
_OWN = re.compile(
    r"\b(minha|meu|meus|minhas)\s+(localizacao|rua|bairro|cidade|casa|endereco|obra|empresa|oficina|loja)\b"
    r"|\b(estou|to|tou)\s+(em|no|na|aqui|perto)\b|\b(sou de|moro em|moro no|moro na)\b"
    r"|\b(aqui em|aqui no|aqui na|aqui perto|aqui onde|manda aqui)\b"
    r"|\b(vou|vou te|vou lhe)\s+(mandar|enviar|passar|compartilhar)\s+(a\s+)?(minha|localizacao|o\s+local)\b"
    r"|\bentregam\s+(na|no|em)\b"
)

# --- contexto que torna "endereço/local" uma pergunta sobre o cliente/pedido, não sobre a loja ---
_OWN_CONTEXT = re.compile(
    r"\b(meu|minha|meus|minhas|entrega|entregar|cobranca|instalacao|obra|pedido|orcamento|nota fiscal|boleto|frete)\b"
)

# Pedido inequívoco da loja, mesmo quando o cliente também fala de si ("moro no Guará, onde ficam vocês?").
_STRONG_STORE = re.compile(
    r"\b(onde|aonde)\b.*\b(loja|servweld|servsolda|assistencia|empresa|oficina|laboratorio)\b"
    r"|\bonde\s+voces?\s+(ficam|estao|moram)\b|\bonde\s+(ficam|estao|moram)\s+voces\b|\bvoces?\s+ficam\s+onde\b|\bcade\s+(voces|a\s+loja)\b"
    r"|\b(endereco|localizacao|local|rua)\s+(da|de)\s+(loja|voces|servweld|servsolda|assistencia|empresa)\b"
)

_PLACE = r"(loja|voces|servweld|servsolda|assistencia|empresa|oficina|laboratorio|deposito|escritorio|sede|matriz|filial)"
_LOCWORD = r"(endereco|localizacao|localizador|localizacoes|mapa|maps|gps|pin|local|rua|ponto de referencia)"
_ASK = (r"(manda|mande|mandar|envia|envie|enviar|passa|passe|passar|me da|pode|poderia|consegue|tem como|"
        r"gostaria|queria|quero|preciso|cade|qual|quais|compartilha|compartilhe|informa|informe|saber)")

_BARE = {
    "endereco", "localizacao", "localizador", "mapa", "maps", "gps", "pin", "local", "onde fica", "onde e",
    "como chegar", "onde", "aonde", "localizacao da loja", "endereco da loja", "onde fica a loja",
}

_STORE_PATTERNS = [
    # localização/endereço + (pedido) + (a loja): "manda a localização", "endereço de vocês", "manda o pin"
    re.compile(rf"\b{_LOCWORD}\b.*\b{_PLACE}\b"),
    re.compile(rf"\b{_PLACE}\b.*\b{_LOCWORD}\b"),
    re.compile(rf"\b{_ASK}\b.*\b{_LOCWORD}\b"),
    re.compile(rf"\b{_LOCWORD}\b.*\b{_ASK}\b"),
    # onde fica / onde é / onde estão + a loja
    re.compile(rf"\b(onde|aonde)\b.*\b{_PLACE}\b"),
    re.compile(r"\b(onde|aonde)\s+(fica|ficam)\b"),
    re.compile(r"\bcade\s+(voces|a\s+loja)\b"),
    # vocês ficam onde / vocês estão localizados / vocês ficam no guará
    re.compile(r"\bvoces?\s+(ficam|se localizam|moram|estao localizados|estao onde|estao situados)\b"),
    re.compile(r"\bonde\s+(voces?|vcs)\s+(ficam|estao|moram|atendem)\b"),
    # como chego aí
    re.compile(r"\bcomo\b.*\b(chego|chegar|ir|vou|faco pra chegar|fazer pra chegar)\b.*\b(ai|la|loja|ate voces|ate a loja|ate ai)\b"),
    # onde levo / entrego / deixo o equipamento
    re.compile(r"\bonde\b.*\b(levo|entrego|deixo|posso levar|posso entregar|posso deixar|devo levar|devo entregar|levar)\b"),
]

# perguntas sobre o STATUS de algo ("onde está minha máquina", "onde fica o orçamento") não são pedido da loja
_STATUS_QUESTION = re.compile(
    r"\b(onde|aonde)\s+(esta|estao|ta|fica|ficou|foi)\b.*\b(meu|minha|meus|minhas|equipamento|maquina|orcamento|pedido|nota|encomenda|peca|pecas|cabo|tocha)\b"
)

_HOURS = re.compile(
    r"\b(horario de (funcionamento|atendimento)|horario da loja|horario de voces|que horas (abre|abrem|fecha|fecham)|"
    r"ate que horas|abre (sabado|hoje|amanha|domingo)|abrem (sabado|hoje|amanha|domingo)|estao abertos|esta aberto|"
    r"funciona (sabado|domingo|hoje)|qual o horario)\b"
)


def is_customer_location(text: str, is_location_pin: bool = False) -> bool:
    """O cliente ENVIOU uma localização: pin do WhatsApp ou link do Maps/Waze."""
    if is_location_pin:
        return True
    n = normalize(text)
    return PIN_MARKER in n or "localizacao compartilhada pelo cliente" in n or bool(MAPS_LINK.search(text or ""))


def store_location_request(text: str) -> bool:
    """O cliente está PEDINDO a localização/endereço da loja."""
    n = normalize(text)
    if len(n) < 3:
        return False
    if _OWN.search(n) and not _STRONG_STORE.search(n):
        return False
    if _STATUS_QUESTION.search(n):
        return False
    if n in _BARE:
        return True
    if _OWN_CONTEXT.search(n) and not re.search(rf"\b{_PLACE}\b", n):
        return False
    return any(p.search(n) for p in _STORE_PATTERNS)


def rule_intent(text: str, is_location_pin: bool = False) -> Tuple[str, bool]:
    """
    Decide só com regras. Retorna (intenção, definitiva): definitiva=True quando não vale a pena
    perguntar a uma IA (pin/link do cliente, ou o cliente falando da própria localização).
    """
    if is_customer_location(text, is_location_pin):
        return CUSTOMER_LOCATION, True
    n = normalize(text)
    if _OWN.search(n) and not _STRONG_STORE.search(n):
        return NONE, True
    if store_location_request(text):
        return STORE_LOCATION, False
    if _HOURS.search(n) or (re.search(r"\b(horario|expediente)\b", n) and re.search(r"\b(qual|atendimento|funcionamento|loja)\b", n)):
        return STORE_HOURS, False
    return NONE, False
