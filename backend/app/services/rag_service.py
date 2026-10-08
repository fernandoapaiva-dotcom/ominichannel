import os
import logging
from typing import Optional

logger = logging.getLogger("rag_service")

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> list:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

class RAGService:
    """
    `import chromadb` alone costs ~63MB of RAM (measured on this server - its own
    dependency tree, before anything is even instantiated), and creating the client loads
    a local sentence-transformer embedding model on top of that. This service is a
    module-level singleton imported at app startup (via the RAG router), so both costs
    used to be paid on every boot even with zero documents in the knowledge base. Both the
    import and the client creation are deferred to the first real call via
    _ensure_client(), called at the top of every public method.
    """
    def __init__(self):
        self.client = None
        self.collection = None
        # Cache em memória (por tenant) de 1 metadado representativo por DOCUMENTO (não por
        # chunk) - ver _get_doc_index(). Achado em produção em 08/10/2026: uma pergunta técnica
        # com número de modelo (ex: "esquema da LHN 240") levou 181 SEGUNDOS pra responder depois
        # que a base cresceu hoje (OCR + ~900 documentos novos da ESAB) - _rank_docs_by_model_number
        # escaneava TODOS os chunks do acervo inteiro (dezenas de milhares) a cada pergunta, sem
        # cache nenhum. Técnico reclamou direto: "nem sabemos se está funcionando".
        self._doc_index_cache: dict = {}
        self._doc_index_cache_at: dict = {}
        self._DOC_INDEX_TTL_SECONDS = 600
        # Cache em memória (global, fundamentos não variam por tenant na prática - só ~15
        # documentos fixos) dos chunks de categoria_geral=True usados por
        # _fundamentos_candidates(). Achado em produção em 08/10/2026, durante a verificação do
        # fix acima: MESMO com _get_doc_index já em cache, uma busca ainda levava ~9s porque
        # collection.get(where={"categoria_geral": True}) escaneava o acervo inteiro (70 mil+
        # chunks) do zero TODA chamada (são só 54 chunks de resultado, mas o filtro de metadado
        # não é indexado - o custo é proporcional ao total de chunks, não ao resultado). Mesmo
        # padrão de cache do índice de documentos, só que guardando os chunks inteiros (poucas
        # dezenas, não pesa memória).
        self._fundamentos_cache: Optional[list] = None
        self._fundamentos_cache_at: float = 0
        self._FUNDAMENTOS_TTL_SECONDS = 600

    def _ensure_client(self):
        if self.collection is not None:
            return
        import chromadb
        persist_dir = os.path.join(os.getcwd(), "chroma_data")
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection("tenant_knowledge_base")

    def _chroma_call(self, fn, *args, retries: int = 3, delay: float = 0.5, **kwargs):
        """
        Tenta de novo em caso de erro transitório do chromadb - achado em produção em
        08/10/2026: a ingestão em massa dos documentos da ESAB (processo separado, rodando por
        horas) escreve no MESMO acervo que o backend lê a cada pergunta de usuário - essa
        leitura+escrita concorrente derruba "chromadb.errors.InternalError: Error executing
        plan: Internal error: Error finding id" de vez em quando (lock/concorrência no motor
        rust+sqlite), mesmo durante perguntas reais de técnico (visto nos logs de produção). Não
        é um erro permanente - a mesma leitura, tentada de novo um instante depois, quase sempre
        funciona.
        """
        import time
        last_err = None
        for attempt in range(retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(delay)
        raise last_err

    async def add_document(
        self,
        tenant_id: int,
        doc_id: str,
        content: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """Adds or updates document chunks in the local vector DB for a tenant with scope metadata"""
        try:
            self._ensure_client()
            meta = metadata or {}
            meta["tenant_id"] = int(tenant_id)
            meta["scope"] = str(meta.get("scope", "geral"))
            meta["department_id"] = int(meta.get("department_id") or 0)
            meta["department_name"] = str(meta.get("department_name") or "Geral")
            meta["titulo"] = str(meta.get("titulo") or "Documento RAG")
            meta["filename"] = str(meta.get("filename") or "")
            meta["criado_em"] = str(meta.get("criado_em") or os.environ.get("CURRENT_TIME", ""))
            meta["parent_doc_id"] = str(doc_id)

            if len(content) > 1500:
                chunks = chunk_text(content, chunk_size=1500, overlap=200)
                chunk_ids = [f"t{tenant_id}_{doc_id}_c{i}" for i in range(len(chunks))]
                chunk_metas = []
                for i in range(len(chunks)):
                    c_meta = dict(meta)
                    c_meta["chunk_index"] = i
                    c_meta["total_chunks"] = len(chunks)
                    chunk_metas.append(c_meta)
                self.collection.upsert(
                    documents=chunks,
                    ids=chunk_ids,
                    metadatas=chunk_metas
                )
            else:
                self.collection.upsert(
                    documents=[content],
                    ids=[f"t{tenant_id}_{doc_id}"],
                    metadatas=[meta]
                )
            # Invalida o cache de _get_doc_index pra esse tenant - sem isso, um documento
            # ingerido agora (ex: pelo vigia de pasta) só apareceria na busca-por-nome depois de
            # até 10min (TTL do cache).
            self._doc_index_cache.pop(int(tenant_id), None)
            self._doc_index_cache_at.pop(int(tenant_id), None)
            # Idem pro cache de fundamentos, caso o documento novo seja ele mesmo um fundamento
            # (categoria_geral=True) - sem isso, um fundamento recém-ingerido só entraria na
            # busca depois de até 10min.
            if meta.get("categoria_geral"):
                self._fundamentos_cache = None
            return True
        except Exception as e:
            logger.error(f"Error adding document to RAG vector store: {e}")
            return False

    def _scoped_meta(self, meta: dict, department_id: Optional[int]) -> bool:
        m_scope = meta.get("scope", "geral")
        m_dept_id = meta.get("department_id", 0)
        return m_scope == "geral" or m_dept_id == 0 or (department_id and int(m_dept_id) == int(department_id))

    # Palavras genéricas demais (tipo de documento, ação pedida, equipamento no geral) pra contar
    # como sinal de modelo - "manda o ESQUEMA da LHN 240" não pode fazer ESQUEMA bater em quase
    # todo arquivo da base só por aparecer no título de muita coisa. Só o nome/código realmente
    # distintivo do modelo (ex: "LHN", "Superbantam", "240") deve contar.
    _GENERIC_WORDS = {
        "manual", "esquema", "esquemas", "eletrico", "elétrico", "eletrica", "elétrica",
        "diagrama", "diagramas", "documento", "documentos", "arquivo", "arquivos", "peca",
        "peça", "pecas", "peças", "catalogo", "catálogo", "instrucao", "instrução", "instrucoes",
        "instruções", "equipamento", "equipamentos", "maquina", "máquina", "maquinas", "máquinas",
        "solda", "soldagem", "corte", "tecnico", "técnico", "tecnica", "técnica", "pdf", "favor",
        "pode", "mandar", "manda", "enviar", "envia", "quero", "preciso", "sobre", "para", "com",
        "uma", "este", "esta", "esse", "essa", "modelo", "numero", "número", "reparo", "defeito",
        "teste", "roteiro", "calibracao", "calibração", "transformacao", "transformação",
        # Nome de CATEGORIA de equipamento (não de modelo específico) - achado em produção em
        # 07/10/2026: "como funciona um inversor" batia "inversor" contra o nome de QUALQUER
        # manual de marca de inversor (ex: BREMEN), escopando a busca pro manual errado em vez de
        # cair na busca geral/fundamentos. Categoria nunca deve contar como sinal de modelo.
        "inversor", "inversores", "retificador", "retificadores", "transformador",
        "transformadores", "spotter", "repuxadeira", "repuxadeiras", "carregador", "carregadores",
        "regulador", "reguladores", "plasma", "tartaruga", "alimentador", "alimentadores",
        "ponteadeira", "ponteadeiras", "bateria", "baterias", "funciona", "funcionamento",
        "entender", "entenda", "explica", "explique", "diferenca", "diferença", "fundamentos",
        "arquitetura", "componente", "componentes", "principio", "princípio", "geral", "gerais",
    }

    def _get_doc_index(self, tenant_id: int) -> list:
        """
        1 metadado representativo por DOCUMENTO (parent_doc_id), não por chunk - cacheado em
        memória por _DOC_INDEX_TTL_SECONDS (10min). O scan paginado completo do acervo (caro,
        181s medido em produção com o acervo de hoje) só roda quando o cache expira ou ainda não
        existe, não a cada pergunta. Novo documento ingerido fica até 10min sem aparecer na
        busca-por-nome (_rank_docs_by_model_number) - aceitável, a busca semântica normal já
        enxerga ele antes disso; add_document() também invalida o cache direto, então uma
        ingestão feita por este mesmo processo já atualiza na hora.
        """
        import time
        now = time.time()
        cached_at = self._doc_index_cache_at.get(tenant_id, 0)
        if now - cached_at < self._DOC_INDEX_TTL_SECONDS and tenant_id in self._doc_index_cache:
            return self._doc_index_cache[tenant_id]

        t0 = time.time()
        all_metas: list = []
        offset = 0
        batch = 2000
        while True:
            page = self._chroma_call(self.collection.get, where={"tenant_id": int(tenant_id)}, include=["metadatas"], limit=batch, offset=offset)
            page_metas = page.get("metadatas", [])
            if not page_metas:
                break
            all_metas.extend(page_metas)
            offset += batch

        seen_docs = {}
        for meta in all_metas:
            pdoc_id = meta.get("parent_doc_id", "")
            if pdoc_id and pdoc_id not in seen_docs:
                seen_docs[pdoc_id] = meta

        doc_list = list(seen_docs.values())
        self._doc_index_cache[tenant_id] = doc_list
        self._doc_index_cache_at[tenant_id] = now
        logger.info(f"[RAG] _get_doc_index: reconstruído cache de {len(doc_list)} documentos (de {len(all_metas)} chunks) em {time.time()-t0:.1f}s")
        return doc_list

    def _rank_docs_by_model_number(self, tenant_id: int, query: str, department_id: Optional[int]):
        """
        Acha, pelo NOME do arquivo (não pelo conteúdo), quais documentos batem o modelo pedido -
        número (ex: "240" em "LHN 240") OU palavra distintiva (ex: "Superbantam", quando o modelo
        não tem número) - busca por embedding sozinha falha aqui porque diagramas/esquemas
        costumam ser imagem dentro do PDF (sem texto extraível pra comparar por similaridade
        semântica), e código/nome de modelo não é algo que embedding semântico distingue bem de
        um modelo parecido (achado em produção em 07/10/2026 - pedido "esquema elétrico da LHN
        240" devolvia conteúdo do manual da LHN 220: mesma família, número diferente). Usado
        tanto por find_document() (pra saber qual ARQUIVO reenviar) quanto por search_context()
        (pra saber de qual DOCUMENTO tirar o trecho de texto da resposta) - mesmo problema, mesma
        causa raiz.
        Retorna lista de (overlap, is_narrow, total_chunks, meta) ordenada da melhor pra pior.
        """
        import re
        query_numbers = set(re.findall(r'\d+', query))
        query_words = {
            w for w in re.findall(r'[a-zA-ZÀ-ÿ]+', query.lower())
            if len(w) >= 5 and w not in self._GENERIC_WORDS
        }
        if not query_numbers and not query_words:
            return []

        # Documentos de propósito estreito (calibração, roteiro de teste) quase nunca têm o
        # esquema elétrico/diagrama completo - quando empatam no número do modelo com o
        # manual de verdade, o manual deve ganhar. Achado em produção em 07/10/2026: pedido
        # "esquema elétrico da LHN 240" sempre devolvia "CALIBRACAO LHN 240 ESAB.pdf" (387
        # caracteres) em vez de "LHN_240i_pt_rev1.pdf" (64mil+ caracteres, o manual real) -
        # os dois batiam "240" igual, e o desempate antigo pegava sempre o primeiro indexado.
        NARROW_PURPOSE_WORDS = ("calibracao", "calibração", "roteiro", "instrucao", "instrução", "transformacao", "transformação")

        seen_docs = {}
        for meta in self._get_doc_index(tenant_id):
            if not self._scoped_meta(meta, department_id):
                continue
            pdoc_id = meta.get("parent_doc_id", "")
            name_text = meta.get("filename", "") + " " + meta.get("titulo", "") + " " + meta.get("modelo", "")
            name_numbers = set(re.findall(r'\d+', name_text))
            name_words = {w for w in re.findall(r'[a-zA-ZÀ-ÿ]+', name_text.lower()) if len(w) >= 5}
            # Número de modelo pesa mais que palavra (mais específico/confiável) - duas ocorrências
            # equivalentes de "overlap" pra cada número batido, uma só pra cada palavra batida.
            overlap = 2 * len(query_numbers & name_numbers) + len(query_words & name_words)
            if overlap > 0:
                is_narrow = any(w in name_text.lower() for w in NARROW_PURPOSE_WORDS)
                total_chunks = int(meta.get("total_chunks") or 1)
                seen_docs[pdoc_id] = (overlap, 0 if not is_narrow else 1, total_chunks, meta)

        return sorted(seen_docs.values(), key=lambda x: (-x[0], x[1], -x[2]))

    def _fundamentos_candidates(self, tenant_id: int, query: str, limit: int):
        """
        Acha os trechos mais relevantes entre os documentos de FUNDAMENTOS (conhecimento geral
        de categoria, sem marca/modelo - ver ingest_fundamentos.py) por sobreposição de palavras
        com a pergunta, em vez de confiar só na busca semântica achando sozinha - achado em
        produção em 07/10/2026: numa base de 70 mil+ chunks de manual real, o documento de
        fundamentos (ex: "Fontes de Solda INVERSORAS") perdia pra manuais reais no ranking
        semântico pra perguntas tipo "como funciona um inversor", mesmo sendo exatamente sobre o
        assunto - a densidade de palavras-chave num manual real de 60 mil caracteres é maior que
        num documento de fundamentos de 6 mil. Como só existem ~15 documentos de fundamentos
        (poucas dezenas de chunks no total), escanear todos e pontuar por palavra é rápido e
        garante que eles apareçam quando forem de fato relevantes - sem pontuação positiva (score
        0), não entra, pra não forçar fundamentos irrelevantes numa pergunta sem nada a ver.
        """
        import re
        # Achado em produção em 07/10/2026: sem filtrar palavra de função (como/que/para/com...),
        # QUALQUER chunk que compartilhasse só essas palavras comuns já pontuava > 0 e podia
        # "ganhar" por coincidência, em vez do documento de fundamentos realmente relevante pro
        # assunto perguntado (ex: pergunta sobre "inversor" devolvendo o de "corte plasma").
        STOPWORDS = {
            "que", "como", "para", "com", "por", "sem", "dos", "das", "uma", "uns", "uma", "este",
            "esta", "esse", "essa", "isso", "isto", "aquele", "aquela", "mas", "ela", "ele",
            "eles", "elas", "meu", "minha", "seu", "sua", "nao", "não", "sim", "tem", "tenho",
            "tem", "ser", "ter", "foi", "são", "sao", "está", "esta", "estao", "estão", "onde",
            "quando", "qual", "quais", "porque", "pois", "ainda", "muito", "mais", "menos",
        }
        import time
        now = time.time()
        if self._fundamentos_cache is not None and (now - self._fundamentos_cache_at) < self._FUNDAMENTOS_TTL_SECONDS:
            docs, metas = self._fundamentos_cache
        else:
            got = self._chroma_call(self.collection.get, where={"categoria_geral": True}, include=["documents", "metadatas"])
            docs = got.get("documents", [])
            metas = got.get("metadatas", [])
            self._fundamentos_cache = (docs, metas)
            self._fundamentos_cache_at = now

        def _stems(text: str) -> set:
            # Radical bem simples (6 primeiros caracteres) - sem isso, "inversor" (pergunta) não
            # batia com "inversoras"/"inversão" (texto do documento) por serem strings diferentes,
            # mesmo sendo claramente a mesma palavra-base em português (achado em produção em
            # 07/10/2026).
            return {w[:6] for w in re.findall(r'\w+', text.lower()) if len(w) > 2 and w.lower() not in STOPWORDS}

        query_stems = _stems(query)

        # Pontua por DOCUMENTO inteiro (soma de todos os chunks), não por chunk isolado - um
        # documento ERRADO que só cita o assunto de passagem numa única frase (ex: o doc de
        # "Corte Plasma" cita "inversor"/"IGBT" na comparação de arquitetura) não pode vencer o
        # documento certo só porque, por acaso, essa frase caiu toda no mesmo chunk.
        by_doc: dict = {}
        for doc, meta in zip(docs, metas):
            if int(meta.get("tenant_id", 0)) != int(tenant_id):
                continue
            pdoc_id = meta.get("parent_doc_id", "")
            doc_stems = _stems(doc)
            score = len(query_stems & doc_stems)
            entry = by_doc.setdefault(pdoc_id, {"total": 0, "chunks": []})
            entry["total"] += score
            entry["chunks"].append((score, meta.get("chunk_index", 0), doc, meta))

        ranked_docs_local = sorted(by_doc.values(), key=lambda e: -e["total"])
        out = []
        for entry in ranked_docs_local:
            if entry["total"] <= 0 or len(out) >= limit:
                break
            best_chunk = sorted(entry["chunks"], key=lambda c: (-c[0], c[1]))[0]
            out.append((best_chunk[2], best_chunk[3]))
        return out[:limit]

    async def search_context(
        self,
        tenant_id: int,
        query: str,
        department_id: Optional[int] = None,
        top_k: int = 5,
        max_total_chars: int = 7000
    ) -> str:
        """
        Searches tenant documents by semantic similarity with token-safe length capping.
        Includes BOTH Geral (company-wide) knowledge and department-specific knowledge.

        Achado em produção em 07/10/2026: técnico perguntou sobre um modelo específico e a IA
        "alucinou" um componente que a máquina não tem - a busca semântica solta de antes (sem
        filtro algum) trazia trechos de manuais de modelos PARECIDOS mas diferentes. A primeira
        correção (só reordenar os top-K já trazidos pela busca semântica) não bastou: o manual
        certo muitas vezes nem ENTRA nos top-K semânticos pra começo de conversa (embedding não
        destingue bem "240" de "220"), então reordenar um pool que já não tinha o documento
        certo não ajuda. Agora, quando o pedido tem número de modelo: (1) acha o(s) documento(s)
        certo(s) pelo NOME do arquivo primeiro (_rank_docs_by_model_number, mesma lógica do
        find_document), (2) faz a busca semântica ESCOPADA só dentro desses documentos - garante
        que o trecho retornado é do modelo certo, não só "parecido". Sem número no pedido, cai
        na busca semântica geral de sempre. Cada trecho vem com "[Fonte: ...]" na frente, pra IA
        conseguir citar de qual manual tirou a informação e perceber se está misturando modelos.
        """
        import re
        try:
            self._ensure_client()
            ranked_docs = self._rank_docs_by_model_number(tenant_id, query, department_id)

            if ranked_docs:
                # Só os 1-2 documentos que melhor batem o modelo pedido - busca TODOS os chunks
                # deles (collection.get, filtro exato por parent_doc_id) e escolhe os mais
                # relevantes por sobreposição de palavras com a pergunta, em vez de usar
                # collection.query (busca semântica) escopada - achado em produção em 07/10/2026:
                # query() com where "$in" nesse acervo de 70 mil+ chunks sempre dava "too many SQL
                # variables" (erro do próprio chromadb/sqlite); get() com filtro exato funciona
                # numa boa, e dentro de só 1-2 documentos já identificados pelo nome a ordenação
                # por palavra-chave é suficiente - não precisa de embedding aqui.
                best_doc_ids = [meta.get("parent_doc_id") for _ov, _nw, _ch, meta in ranked_docs[:2]]
                # "$in" (mesmo só com 1-2 valores) dá "too many SQL variables" nesse acervo de 70
                # mil+ chunks (achado em produção em 07/10/2026, no chromadb/sqlite desta versão) -
                # uma chamada por doc_id com filtro de igualdade simples (comprovadamente ok,
                # usado em _rank_docs_by_model_number) contorna o problema.
                chunk_docs: list = []
                chunk_metas: list = []
                for doc_id in best_doc_ids:
                    got = self._chroma_call(self.collection.get, where={"parent_doc_id": doc_id}, include=["documents", "metadatas"])
                    chunk_docs.extend(got.get("documents", []))
                    chunk_metas.extend(got.get("metadatas", []))
                query_words_set = {w.lower() for w in re.findall(r'\w+', query) if len(w) > 2}
                scored = []
                for doc, meta in zip(chunk_docs, chunk_metas):
                    doc_words = set(re.findall(r'\w+', doc.lower()))
                    score = len(query_words_set & doc_words)
                    scored.append((score, meta.get("chunk_index", 0), doc, meta))
                scored.sort(key=lambda x: (-x[0], x[1]))
                # Reserva 1-2 vagas no top_k pra contexto GERAL (busca semântica solta, sem
                # escopar por documento) - pedido do usuário em 07/10/2026 ("entenda o
                # funcionamento do começo ao fim... como um engenheiro"): sem isso, uma pergunta
                # tipo "por que o IGBT da LHN 240 pode estar queimando?" ficava só com trechos do
                # manual específico da LHN 240 e perdia o documento de fundamentos sobre como
                # IGBT/inversor funciona em geral - as duas coisas juntas respondem melhor.
                general_slots = min(2, top_k - 1) if top_k > 1 else 0
                specific_slots = top_k - general_slots
                docs = [d for _s, _ci, d, _m in scored[:specific_slots]]
                metas = [m for _s, _ci, _d, m in scored[:specific_slots]]
                if general_slots:
                    for gd, gm in self._fundamentos_candidates(tenant_id, query, general_slots):
                        docs.append(gd)
                        metas.append(gm)
            else:
                # Garante 1 vaga pra fundamentos (se relevante) mesmo sem modelo identificado na
                # pergunta - ver _fundamentos_candidates: busca semântica solta entre 70 mil+
                # chunks reais costuma deixar o documento de fundamentos de fora do top_k.
                fundamentos = self._fundamentos_candidates(tenant_id, query, 1)
                fund_doc_ids = {m.get("parent_doc_id") for _d, m in fundamentos}
                results = self._chroma_call(
                    self.collection.query,
                    query_texts=[query],
                    n_results=top_k,
                    where={"tenant_id": int(tenant_id)}
                )
                docs = [d for d in results.get("documents", [[]])[0]]
                metas = [m for m in results.get("metadatas", [[]])[0]]
                if fundamentos:
                    keep = top_k - len(fundamentos)
                    docs = [d for d, m in zip(docs, metas) if m.get("parent_doc_id") not in fund_doc_ids][:max(keep, 0)]
                    metas = [m for m in metas if m.get("parent_doc_id") not in fund_doc_ids][:max(keep, 0)]
                    for fd, fm in fundamentos:
                        docs.append(fd)
                        metas.append(fm)

            if not docs:
                return ""

            filtered_docs = []
            total_chars = 0
            for doc, meta in zip(docs, metas):
                if not self._scoped_meta(meta, department_id):
                    continue
                if len(doc) > 2500:
                    # Extract keyword-relevant snippets rather than full huge file
                    query_words = [w.lower() for w in query.split() if len(w) > 2 and w.lower() not in ["para", "com", "uma", "como", "qual", "onde"]]
                    snippets = []
                    doc_lower = doc.lower()
                    for qw in query_words:
                        idx = doc_lower.find(qw)
                        if idx != -1:
                            start = max(0, idx - 400)
                            end = min(len(doc), idx + 1200)
                            snippets.append(doc[start:end])
                    excerpt = "\n[...]\n".join(snippets[:3]) if snippets else doc[:1500]
                else:
                    excerpt = doc

                titulo = meta.get("titulo") or meta.get("filename") or "documento sem título"
                tagged = f"[Fonte: {titulo}]\n{excerpt}"

                if total_chars + len(tagged) > max_total_chars:
                    remaining = max_total_chars - total_chars
                    if remaining > 300:
                        filtered_docs.append(tagged[:remaining] + "\n[...]")
                    break
                filtered_docs.append(tagged)
                total_chars += len(tagged)

            return "\n---\n".join(filtered_docs)
        except Exception as e:
            logger.error(f"Error searching RAG vector store: {e}")
            return ""

    async def find_document(
        self,
        tenant_id: int,
        query: str,
        department_id: Optional[int] = None,
        top_k: int = 10
    ) -> list:
        """
        Encontra o arquivo original pra reenviar ao técnico. Ver _rank_docs_by_model_number()
        pra lógica de desambiguação por modelo. Só cai pra busca semântica (texto do conteúdo)
        se nenhum nome bater.
        """
        try:
            self._ensure_client()
            ranked = self._rank_docs_by_model_number(tenant_id, query, department_id)
            if ranked:
                return [
                    {
                        "titulo": meta.get("titulo", ""),
                        "filename": meta.get("filename", ""),
                        "source_path": meta.get("source_path"),
                        "parent_doc_id": meta.get("parent_doc_id", "")
                    }
                    for _overlap, _narrow, _chunks, meta in ranked[:top_k]
                    if meta.get("source_path")
                ]

            # Fallback: sem número no pedido, ou nenhum nome de arquivo bateu - busca semântica normal.
            results = self._chroma_call(
                self.collection.query,
                query_texts=[query],
                n_results=top_k,
                where={"tenant_id": int(tenant_id)}
            )
            metas = results.get("metadatas", [[]])[0]
            out = []
            for meta in metas:
                if self._scoped_meta(meta, department_id) and meta.get("source_path"):
                    out.append({
                        "titulo": meta.get("titulo", ""),
                        "filename": meta.get("filename", ""),
                        "source_path": meta.get("source_path"),
                        "parent_doc_id": meta.get("parent_doc_id", "")
                    })
            return out
        except Exception as e:
            logger.error(f"Error finding document in RAG vector store: {e}")
            return []

    async def list_documents(self, tenant_id: int) -> list:
        """Lists all RAG documents index metadata for a tenant"""
        try:
            self._ensure_client()
            res = self.collection.get(
                where={"tenant_id": int(tenant_id)},
                include=["metadatas", "documents"]
            )
            ids = res.get("ids", [])
            metas = res.get("metadatas", [])
            docs = res.get("documents", [])

            output = []
            for d_id, meta, doc in zip(ids, metas, docs):
                output.append({
                    "id": d_id.replace(f"t{tenant_id}_", ""),
                    "full_id": d_id,
                    "titulo": meta.get("titulo", "Sem Título"),
                    "scope": meta.get("scope", "geral"),
                    "department_id": meta.get("department_id", 0),
                    "department_name": meta.get("department_name", "Geral"),
                    "filename": meta.get("filename", ""),
                    "snippet": doc[:150] + ("..." if len(doc) > 150 else "")
                })
            return output
        except Exception as e:
            logger.error(f"Error listing RAG documents: {e}")
            return []

    async def delete_document(self, tenant_id: int, doc_id: str) -> bool:
        """Deletes a document from ChromaDB vector store"""
        try:
            self._ensure_client()
            full_id = doc_id if doc_id.startswith(f"t{tenant_id}_") else f"t{tenant_id}_{doc_id}"
            self.collection.delete(ids=[full_id])
            return True
        except Exception as e:
            logger.error(f"Error deleting RAG document {doc_id}: {e}")
            return False

rag_service = RAGService()


async def start_rag_index_warmer_loop(tenant_ids: Optional[list] = None, interval_seconds: int = 480):
    """
    Reconstrói _get_doc_index() (cache de metadados usado em _rank_docs_by_model_number, ver
    comentário no __init__) PROATIVAMENTE em segundo plano, antes do cache expirar sozinho -
    achado em produção em 08/10/2026: mesmo com o cache, a reconstrução em si leva ~90s num
    acervo deste tamanho; sem esse aquecimento, o PRIMEIRO técnico a perguntar algo com número de
    modelo depois de cada expiração (a cada 10min) ainda pegaria essa demora na cara. Rodando a
    cada 8min (menor que o TTL de 10min do cache), o cache nunca chega a expirar de verdade na
    frente de um usuário real - a reconstrução sempre acontece aqui, em background, não na
    resposta de ninguém.
    """
    import asyncio
    tenant_ids = tenant_ids or [1]
    logger.info(f"[RAG] Aquecedor de cache de índice iniciado (tenants={tenant_ids}, a cada {interval_seconds}s)")
    while True:
        for tid in tenant_ids:
            try:
                rag_service._ensure_client()
                await asyncio.to_thread(rag_service._get_doc_index, tid)
                # Mesmo achado de 08/10/2026, pra um segundo gargalo descoberto depois deste
                # primeiro fix: _fundamentos_candidates também escaneava o acervo inteiro sem
                # cache (~3s por pergunta, toda pergunta). Aquece aqui também.
                await asyncio.to_thread(rag_service._fundamentos_candidates, tid, "solda inversor", 1)
            except Exception as e:
                logger.error(f"[RAG] Erro aquecendo cache de índice pro tenant {tid}: {e}")
            try:
                # Aquece o modelo de embedding (carregado sob demanda no primeiro
                # collection.query() do processo) - sem isso, a PRIMEIRA pergunta real depois de
                # cada restart do backend pagaria esse custo na cara do usuário.
                await asyncio.to_thread(
                    rag_service._chroma_call, rag_service.collection.query, query_texts=["aquecimento"], n_results=1
                )
            except Exception as e:
                logger.error(f"[RAG] Erro aquecendo embedding: {e}")
        await asyncio.sleep(interval_seconds)
