"""
Estado (em memória) do envio em andamento da abertura de O.S. para um cliente.

A sequência de abertura (saudação, recebimento, termos e, por último, o pedido de "responda SIM")
leva ~70-90s por causa do ritmo de digitação entre as mensagens. O cliente costuma responder no
meio ("Boa tarde", "Ok", "Sim"). Sem este controle, essas respostas caíam no tratamento normal:
o sistema repetia "Só para eu confirmar certinho..." e, quando o cliente já tinha dito "Sim" e
recebido "Perfeito! ... o PDF", o pedido de confirmação ("Muito importante...") ainda chegava DEPOIS.

Regras (aplicadas em webhooks.py e os_handler_ingest.py):
  - enquanto o pedido de SIM ainda não saiu, resposta ambígua do cliente é ignorada em silêncio;
  - um "Sim" claro vale como a confirmação, sempre UMA só: se veio depois dos termos (info_done) o pedido
    de SIM fica dispensado (skip_prompt); se veio no meio dos termos, é guardado (early_yes) e, assim que
    o último termo sai, o PDF é liberado sem pedir de novo;
  - "Não" é tratado normalmente e o pedido deixa de ser enviado (a conversa já não está pendente).
Processo único (pm2 fork_mode), então um dict em memória basta.
"""
import time
from typing import Dict, Optional

_STATE: Dict[int, dict] = {}
_MAX_AGE_SECONDS = 600  # segurança: estado esquecido (ex.: falha no meio) não bloqueia nada por mais que isso


def start(conversation_id: int) -> dict:
    state = {"started_at": time.time(), "info_done": False, "skip_prompt": False, "early_yes": False}
    _STATE[conversation_id] = state
    return state


def get(conversation_id: int) -> Optional[dict]:
    state = _STATE.get(conversation_id)
    if state and (time.time() - state["started_at"]) > _MAX_AGE_SECONDS:
        _STATE.pop(conversation_id, None)
        return None
    return state


_CONFIRMED: Dict[int, float] = {}


def mark_confirmed(conversation_id: int) -> None:
    """O cliente acabou de confirmar a leitura das condições (o PDF foi/está sendo liberado)."""
    _CONFIRMED[conversation_id] = time.time()


def confirmed_recently(conversation_id: int, within_seconds: int = 300) -> bool:
    """
    Uma O.S. do mesmo atendimento que chega DEPOIS do "Sim" não tem mais confirmação pendente para
    entrar: como o cliente já confirmou nesta visita, o PDF dela sai direto (senão ficava sem enviar).
    """
    ts = _CONFIRMED.get(conversation_id)
    return bool(ts and (time.time() - ts) <= within_seconds)


def finish(conversation_id: int, state: dict) -> None:
    if _STATE.get(conversation_id) is state:
        _STATE.pop(conversation_id, None)
