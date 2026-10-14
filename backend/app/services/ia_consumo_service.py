"""
Observador de consumo de IA (14/10/2026) - pedido do usuário depois da auditoria de tokens:
"precisamos criar no sistema um observador de tokens, ele mostra onde consome mais e viabiliza o custo".

Como funciona: em vez de mexer em cada uma das ~20 funções que chamam o Gemini, `instalar()` embrulha
o próprio `generate_content` da biblioteca google-genai. TODA chamada (backend, treino do RAG, catálogo
das vistas explodidas...) passa a gravar em `ia_consumo`: de onde veio (função + quem chamou), modelo,
tokens de entrada / saída / "raciocínio" (thinking), se deu erro, tempo e custo em US$ pela tabela de
preços de `ia_consumo_config` (editável no painel Admin > Consumo de IA).

Regras de segurança:
- o observador NUNCA derruba a chamada da IA: qualquer falha dele é engolida;
- a gravação é feita por uma thread própria, em lote, com sqlite3 puro (não trava o event loop nem
  depende da sessão async do backend);
- processos curtos (scripts) gravam o que faltou ao sair (atexit).

A "origem" é descoberta pela pilha de chamadas. Quando a chamada vai para outra thread
(asyncio.to_thread(client.models.generate_content, ...)) a pilha se perde, então o acesso a
`client.models` (que acontece ainda no código que chamou) guarda a origem num ContextVar, que o
to_thread copia para a thread.
"""
import atexit
import contextvars
import functools
import json
import logging
import os
import queue
import sqlite3
import sys
import threading
import time
from datetime import datetime

logger = logging.getLogger("ia_consumo")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ESTE_ARQUIVO = os.path.abspath(__file__)

# Preço por 1 milhão de tokens, em US$ (fontes na auditoria de 14/10/2026 - conferir em ai.google.dev/pricing).
# "Raciocínio" (thinking) é cobrado como saída. Modelo desconhecido usa o "padrao".
PRECOS_PADRAO = {
    "cotacao_dolar": 5.50,
    "orcamento_mensal_brl": 0,
    "modelos": {
        "gemini-3.6-flash": {"entrada": 0.75, "saida": 3.75},
        "gemini-3.1-flash-lite": {"entrada": 0.25, "saida": 1.50},
        "gemini-2.5-flash": {"entrada": 0.30, "saida": 2.50},
        "padrao": {"entrada": 0.75, "saida": 3.75},
    },
}

# função que chama a IA -> (nome no painel, grupo). Quem chama pelo portal do técnico vira "Copiloto Técnico".
ROTULOS = {
    "evaluate_department_routing": ("Roteamento de setor", "Atendimento WhatsApp"),
    "generate_rag_response": ("Resposta com base no RAG", "Atendimento WhatsApp"),
    "generate_concierge_response": ("Concierge (resposta da IA)", "Atendimento WhatsApp"),
    "process_audio_message": ("Transcrição de áudio", "Atendimento WhatsApp"),
    "process_image_message": ("Leitura de imagem", "Atendimento WhatsApp"),
    "process_document_message": ("Leitura de documento", "Atendimento WhatsApp"),
    "generate_onboarding_summary": ("Resumo de onboarding", "Atendimento WhatsApp"),
    "summarize_conversation_for_transfer": ("Resumo na transferência", "Atendimento WhatsApp"),
    "classify_store_info_intent": ("Classificação: dados da loja", "Atendimento WhatsApp"),
    "generate_suggested_reply": ("Sugestão de resposta", "Atendente (painel)"),
    "generate_copilot_consultation": ("Copiloto do atendente", "Atendente (painel)"),
    "generate_customer_diagnostic_report": ("Laudo / orçamento ao cliente", "O.S. e laudos"),
    "generate_internal_diagnostic_note": ("Nota técnica interna", "O.S. e laudos"),
    "sem_conserto_motivo": ("Motivo de sem conserto", "O.S. e laudos"),
    "classify_confirmation_intent": ("Classificação de confirmação", "O.S. e laudos"),
    "analyze_bench_media": ("Foto / vídeo da bancada", "Copiloto Técnico"),
    "chat_ai_rule_copilot": ("Assistente de automações", "Admin e testes"),
    "diagnose_hallucination_endpoint": ("Diagnóstico de alucinação", "Admin e testes"),
    "test_integration_connection": ("Teste da chave da IA", "Admin e testes"),
    "chat_with_rag_trainer": ("Assistente de treino do RAG", "Treino e catálogo"),
    "extrair_pecas": ("Catálogo: vistas explodidas", "Treino e catálogo"),
    "ocr_with_gemini": ("OCR de PDF escaneado", "Treino e catálogo"),
}
GRUPOS_TREINO = {"Treino e catálogo"}  # gasto único (o resto é recorrente, do dia a dia)


def rotulo(origem: str, chamadores: str) -> tuple:
    func = (origem or "").rsplit(".", 1)[-1]
    nome, grupo = ROTULOS.get(func, (func or "desconhecido", "Outros"))
    if "technician_portal" in (chamadores or "") and grupo not in GRUPOS_TREINO:
        grupo = "Copiloto Técnico"
        if func == "generate_concierge_response":
            nome = "Pergunta ao Copiloto"
        elif func == "process_audio_message":
            nome = "Áudio do técnico (transcrição)"
    if "os_report_autodraft" in (chamadores or ""):
        nome += " (automático)"
    return nome, grupo


# ----------------------------------------------------------------------------------------- origem

_ORIGEM: contextvars.ContextVar = contextvars.ContextVar("ia_consumo_origem", default=None)


def _origem_da_pilha(frame) -> tuple | None:
    """(origem, chamadores): 1ª função do projeto na pilha + módulos do projeto acima dela."""
    achados = []
    while frame is not None and len(achados) < 12:
        fn = frame.f_code.co_filename
        if fn.startswith(_BACKEND_DIR) and os.sep + "venv" + os.sep not in fn and os.path.abspath(fn) != _ESTE_ARQUIVO:
            mod = os.path.splitext(os.path.relpath(fn, _BACKEND_DIR))[0].replace(os.sep, ".")
            achados.append((mod, frame.f_code.co_name))
        frame = frame.f_back
    if not achados:
        return None
    mod0, func0 = achados[0]
    chamadores = []
    for mod, func in achados[1:]:
        if mod != mod0 and f"{mod}.{func}" not in chamadores:
            chamadores.append(f"{mod}.{func}")
    return f"{mod0}.{func0}", " < ".join(chamadores[:4])


# ----------------------------------------------------------------------------------------- preços

_precos_cache = {"em": 0.0, "valor": PRECOS_PADRAO}


def _db_path() -> str:
    from app.core.config import settings
    url = settings.DATABASE_URL
    caminho = url.split(":///", 1)[1] if ":///" in url else "omini_channel.db"
    return caminho if os.path.isabs(caminho) else os.path.abspath(caminho)


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=30)
    con.execute(
        "CREATE TABLE IF NOT EXISTS ia_consumo ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT NOT NULL, origem TEXT, chamadores TEXT,"
        " modelo TEXT, chave TEXT, processo TEXT, ok INTEGER, erro TEXT,"
        " tok_entrada INTEGER DEFAULT 0, tok_saida INTEGER DEFAULT 0, tok_pensamento INTEGER DEFAULT 0,"
        " tok_cache INTEGER DEFAULT 0, ms INTEGER, custo_usd REAL DEFAULT 0)"
    )
    con.execute("CREATE INDEX IF NOT EXISTS ix_ia_consumo_criado_em ON ia_consumo (criado_em)")
    con.execute("CREATE TABLE IF NOT EXISTS ia_consumo_config (chave TEXT PRIMARY KEY, valor TEXT)")
    return con


def ler_precos(con: sqlite3.Connection | None = None) -> dict:
    if con is None and time.time() - _precos_cache["em"] < 300:
        return _precos_cache["valor"]
    fechar = con is None
    try:
        con = con or _conectar()
        row = con.execute("SELECT valor FROM ia_consumo_config WHERE chave = 'precos'").fetchone()
        valor = json.loads(row[0]) if row else PRECOS_PADRAO
    except Exception:
        valor = _precos_cache["valor"]
    finally:
        if fechar and con is not None:
            con.close()
    _precos_cache.update(em=time.time(), valor=valor)
    return valor


def salvar_precos(valor: dict) -> None:
    con = _conectar()
    try:
        con.execute("INSERT OR REPLACE INTO ia_consumo_config (chave, valor) VALUES ('precos', ?)", (json.dumps(valor),))
        con.commit()
    finally:
        con.close()
    _precos_cache.update(em=time.time(), valor=valor)


def recalcular_historico(valor: dict) -> int:
    """Refaz o custo de TODOS os registros com a tabela de preços nova (ex.: preço conferido na fatura)."""
    con = _conectar()
    try:
        modelos = [r[0] for r in con.execute("SELECT DISTINCT modelo FROM ia_consumo").fetchall()]
        n = 0
        for m in modelos:
            p = preco_do_modelo(valor, m or "")
            n += con.execute(
                "UPDATE ia_consumo SET custo_usd = (tok_entrada * ? + (tok_saida + tok_pensamento) * ?) / 1000000.0"
                " WHERE ok = 1 AND modelo IS ?", (float(p.get("entrada", 0)), float(p.get("saida", 0)), m)).rowcount
        con.commit()
        return n
    finally:
        con.close()


def preco_do_modelo(precos: dict, modelo: str) -> dict:
    tabela = precos.get("modelos") or PRECOS_PADRAO["modelos"]
    modelo = (modelo or "").replace("models/", "")
    if modelo in tabela:
        return tabela[modelo]
    candidatos = [k for k in tabela if k != "padrao" and modelo.startswith(k)]
    if candidatos:
        return tabela[max(candidatos, key=len)]
    return tabela.get("padrao") or PRECOS_PADRAO["modelos"]["padrao"]


def custo_usd(precos: dict, modelo: str, entrada: int, saida: int, pensamento: int) -> float:
    p = preco_do_modelo(precos, modelo)
    return (entrada * float(p.get("entrada", 0)) + (saida + pensamento) * float(p.get("saida", 0))) / 1_000_000


# ----------------------------------------------------------------------------------------- gravação

_fila: queue.SimpleQueue = queue.SimpleQueue()
_thread = None
_trava = threading.Lock()


def _gravar_lote(lote: list) -> None:
    con = _conectar()
    try:
        precos = ler_precos(con)
        linhas = []
        for r in lote:
            r["custo_usd"] = custo_usd(precos, r["modelo"], r["tok_entrada"], r["tok_saida"], r["tok_pensamento"]) if r["ok"] else 0.0
            linhas.append((r["criado_em"], r["origem"], r["chamadores"], r["modelo"], r["chave"], r["processo"], r["ok"],
                           r["erro"], r["tok_entrada"], r["tok_saida"], r["tok_pensamento"], r["tok_cache"], r["ms"], r["custo_usd"]))
        con.executemany(
            "INSERT INTO ia_consumo (criado_em, origem, chamadores, modelo, chave, processo, ok, erro, tok_entrada,"
            " tok_saida, tok_pensamento, tok_cache, ms, custo_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
        con.commit()
    finally:
        con.close()


def _esvaziar(espera: float) -> None:
    lote = []
    try:
        lote.append(_fila.get(timeout=espera))
        while len(lote) < 500:
            lote.append(_fila.get_nowait())
    except queue.Empty:
        pass
    if not lote:
        return
    for tentativa in range(5):
        try:
            _gravar_lote(lote)
            return
        except Exception as e:
            if tentativa == 4:
                logger.warning(f"[IA CONSUMO] {len(lote)} registro(s) perdidos: {e}")
            time.sleep(1 + tentativa)


def _gravador() -> None:
    while True:
        try:
            _esvaziar(5)
            time.sleep(2)
        except Exception:
            time.sleep(5)


def _final() -> None:
    try:
        while not _fila.empty():
            _esvaziar(0.1)
    except Exception:
        pass


def _enfileirar(registro: dict) -> None:
    global _thread
    _fila.put(registro)
    if _thread is None:
        with _trava:
            if _thread is None:
                _thread = threading.Thread(target=_gravador, name="ia-consumo", daemon=True)
                _thread.start()
                atexit.register(_final)


def _registrar(models_obj, args, kwargs, origem, resposta, erro, t0) -> None:
    try:
        modelo = kwargs.get("model") or (args[0] if args else "") or ""
        api = getattr(models_obj, "_api_client", None)
        chave = str(getattr(api, "api_key", "") or "")
        uso = getattr(resposta, "usage_metadata", None)

        def n(campo):
            try:
                return int(getattr(uso, campo, 0) or 0)
            except Exception:
                return 0

        texto_erro = None
        if erro is not None:
            texto_erro = f"{type(erro).__name__}: {erro}"[:300]
        _enfileirar({
            "criado_em": datetime.utcnow().isoformat(timespec="seconds"),
            "origem": (origem or ("desconhecido", ""))[0],
            "chamadores": (origem or ("", ""))[1],
            "modelo": str(modelo).replace("models/", "")[:60],
            "chave": ("…" + chave[-4:]) if chave else "",
            "processo": (os.environ.get("name") or os.path.basename(sys.argv[0] if sys.argv and sys.argv[0] else "python"))[:60],  # PM2 põe o nome do processo em $name
            "ok": 1 if erro is None else 0,
            "erro": texto_erro,
            "tok_entrada": n("prompt_token_count") + n("tool_use_prompt_token_count"),
            "tok_saida": n("candidates_token_count"),
            "tok_pensamento": n("thoughts_token_count"),
            "tok_cache": n("cached_content_token_count"),
            "ms": int((time.monotonic() - t0) * 1000),
        })
    except Exception:
        pass


def _origem_atual(frame):
    try:
        return _origem_da_pilha(frame) or _ORIGEM.get()
    except Exception:
        return None


# ----------------------------------------------------------------------------------------- instalação

_instalado = False


def instalar() -> None:
    """Liga o observador neste processo. Pode ser chamado várias vezes (só instala uma)."""
    global _instalado
    if _instalado:
        return
    try:
        from google.genai import client as g_client, models as g_models
    except Exception as e:
        logger.warning(f"[IA CONSUMO] google-genai indisponível, observador desligado: {e}")
        return

    def embrulha_sync(orig):
        @functools.wraps(orig)
        def generate_content(self, *args, **kwargs):
            origem, t0 = _origem_atual(sys._getframe(1)), time.monotonic()
            try:
                resposta = orig(self, *args, **kwargs)
            except BaseException as e:
                _registrar(self, args, kwargs, origem, None, e, t0)
                raise
            _registrar(self, args, kwargs, origem, resposta, None, t0)
            return resposta
        generate_content._ia_consumo = True
        return generate_content

    def embrulha_async(orig):
        @functools.wraps(orig)
        async def generate_content(self, *args, **kwargs):
            origem, t0 = _origem_atual(sys._getframe(1)), time.monotonic()
            try:
                resposta = await orig(self, *args, **kwargs)
            except BaseException as e:
                _registrar(self, args, kwargs, origem, None, e, t0)
                raise
            _registrar(self, args, kwargs, origem, resposta, None, t0)
            return resposta
        generate_content._ia_consumo = True
        return generate_content

    def models_com_origem(prop):
        def getter(self):
            try:
                o = _origem_da_pilha(sys._getframe(1))
                if o:
                    _ORIGEM.set(o)
            except Exception:
                pass
            return prop.fget(self)
        return property(getter)

    if not getattr(g_models.Models.generate_content, "_ia_consumo", False):
        g_models.Models.generate_content = embrulha_sync(g_models.Models.generate_content)
    if not getattr(g_models.AsyncModels.generate_content, "_ia_consumo", False):
        g_models.AsyncModels.generate_content = embrulha_async(g_models.AsyncModels.generate_content)
    for cls in (g_client.Client, g_client.AsyncClient):
        prop = cls.__dict__.get("models")
        if isinstance(prop, property):
            cls.models = models_com_origem(prop)
    _instalado = True
    logger.info("[IA CONSUMO] observador de tokens ligado")
