"""
Estado (em memória) do envio em andamento da abertura de O.S. para um cliente.

A sequência de abertura (saudação, recebimento, termos e, por último, o pedido de "responda SIM")
leva ~70-90s por causa do ritmo de digitação entre as mensagens. O cliente costuma responder no
meio ("Boa tarde", "Ok", "Sim"). Sem este controle, essas respostas caíam no tratamento normal:
o sistema repetia "Só para eu confirmar certinho..." e, quando o cliente já tinha dito "Sim" e
recebido "Perfeito! ... o PDF", o pedido de confirmação ("Muito importante...") ainda chegava DEPOIS.

Regras (aplicadas em webhooks.py e os_handler_ingest.py):
  - enquanto o pedido de SIM ainda não saiu, resposta ambígua do cliente é ignorada em silêncio;
  - "Sim" só vale antes do pedido se o cliente já recebeu TODOS os termos (info_done) - aí o pedido
    fica dispensado (skip_prompt);
  - "Não" é tratado normalmente e o pedido deixa de ser enviado (a conversa já não está pendente).
Processo único (pm2 fork_mode), então um dict em memória basta.
"""
import time
from typing import Dict, Optional

_STATE: Dict[int, dict] = {}
_MAX_AGE_SECONDS = 600  # segurança: estado esquecido (ex.: falha no meio) não bloqueia nada por mais que isso


def start(conversation_id: int) -> dict:
    state = {"started_at": time.time(), "info_done": False, "skip_prompt": False}
    _STATE[conversation_id] = state
    return state


def get(conversation_id: int) -> Optional[dict]:
    state = _STATE.get(conversation_id)
    if state and (time.time() - state["started_at"]) > _MAX_AGE_SECONDS:
        _STATE.pop(conversation_id, None)
        return None
    return state


def finish(conversation_id: int, state: dict) -> None:
    if _STATE.get(conversation_id) is state:
        _STATE.pop(conversation_id, None)
