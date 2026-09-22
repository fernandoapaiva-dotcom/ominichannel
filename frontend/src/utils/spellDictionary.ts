/**
 * Dicionário real de pt-BR - complementa o WORD_REPLACEMENTS de spellingCorrector.ts, que só
 * cobre uma lista fixa de erros/abreviações conhecidos manualmente.
 *
 * Antes, só quem estivesse naquela lista fixa era sublinhado - qualquer erro de digitação
 * novo passava batido. Agora, se a palavra não está na lista curada, consultamos as 150 mil
 * palavras pt-BR mais comuns (lista de frequência derivada de legendas reais, então já vem
 * com as conjugações do dia a dia - não é só a forma "de dicionário"/infinitivo, o que evita
 * o problema antigo de marcar verbo corretamente conjugado como erro).
 *
 * Testamos usar um dicionário Hunspell completo (o mesmo formato do LibreOffice/Firefox) via
 * a lib `nspell`, mas montar a árvore de afixos do português levava minutos e travava a aba -
 * inviável pra rodar no navegador do atendente. Uma lista plana de palavras é só um Set, monta
 * na hora e cobre o vocabulário do dia a dia muito bem.
 *
 * Carregado sob demanda (só quando a tela de conversa abre), porque o arquivo tem ~1,3MB (uns
 * 640KB comprimido) - não vale a pena baixar isso no carregamento inicial do app.
 */

import { WORD_REPLACEMENTS } from './spellingCorrector';

let wordSet: Set<string> | null = null;
let loadingPromise: Promise<void> | null = null;

/** Começa a baixar a lista de palavras em segundo plano; pode ser chamado várias vezes. */
export function preloadSpellDictionary(): void {
  if (wordSet || loadingPromise) return;
  loadingPromise = (async () => {
    try {
      const res = await fetch('/dict/pt-br-words.txt');
      if (!res.ok) throw new Error('lista de palavras indisponível');
      const text = await res.text();
      const set = new Set<string>();
      for (const line of text.split('\n')) {
        const w = line.trim();
        if (w) set.add(w);
      }
      wordSet = set;
    } catch (err) {
      console.warn('Não foi possível carregar o dicionário pt-BR para correção ortográfica:', err);
    }
  })();
}

export function isSpellDictionaryReady(): boolean {
  return !!wordSet;
}

// Só analisa tokens puramente alfabéticos (com acentuação pt-BR) - nomes de modelo, códigos
// de O.S., números de telefone etc. já saem de cara.
const PURE_WORD_RE = /^[a-zàáâãçéêíïóôõöúü]+$/i;
const ALPHABET = 'abcdefghijklmnopqrstuvwxyzàáâãçéêíïóôõöúü'.split('');

// Termos do dia a dia da loja/app que uma lista genérica de frequência não conhece bem e a
// gente não quer sublinhar como erro. Vai crescendo conforme aparecerem falsos positivos reais.
const DOMAIN_ALLOWLIST = new Set([
  'whatsapp', 'app', 'pix', 'email', 'link', 'site', 'status', 'login', 'ok',
  'inversor', 'retificador', 'boxer', 'softsystem', 'servweld', 'servsolda'
]);

function isKnown(word: string): boolean {
  if (!wordSet) return true; // dicionário ainda não carregou - não flagra nada por enquanto
  return wordSet.has(word) || DOMAIN_ALLOWLIST.has(word);
}

/** Gera todas as variações a 1 edição de distância (Norvig-style), filtra só as conhecidas. */
function knownEdits1(word: string): Set<string> {
  const result = new Set<string>();
  const splits: Array<[string, string]> = [];
  for (let i = 0; i <= word.length; i++) splits.push([word.slice(0, i), word.slice(i)]);

  for (const [l, r] of splits) {
    if (r.length > 0) {
      const del = l + r.slice(1);
      if (isKnown(del)) result.add(del);
    }
    if (r.length > 1) {
      const transpose = l + r[1] + r[0] + r.slice(2);
      if (isKnown(transpose)) result.add(transpose);
    }
    if (r.length > 0) {
      for (const c of ALPHABET) {
        const replace = l + c + r.slice(1);
        if (isKnown(replace)) result.add(replace);
      }
    }
    for (const c of ALPHABET) {
      const insert = l + c + r;
      if (isKnown(insert)) result.add(insert);
    }
  }
  return result;
}

/** Todas as variações cruas a 1 edição (sem checar se são conhecidas) - usado como ponte pra
 * a busca de distância 2. Precisa gerar os 4 tipos de edição (apagar/trocar/trocar posição/
 * inserir), senão erros como "cofaternização" (faltam DUAS letras diferentes, "n" e "r") nunca
 * encontram "confraternização": só apagar/transpor não alcança um typo que precisa de inserção. */
function rawEdits1(word: string): string[] {
  const result: string[] = [];
  const splits: Array<[string, string]> = [];
  for (let i = 0; i <= word.length; i++) splits.push([word.slice(0, i), word.slice(i)]);
  for (const [l, r] of splits) {
    if (r.length > 0) result.push(l + r.slice(1));
    if (r.length > 1) result.push(l + r[1] + r[0] + r.slice(2));
    if (r.length > 0) for (const c of ALPHABET) result.push(l + c + r.slice(1));
    for (const c of ALPHABET) result.push(l + c + r);
  }
  return result;
}

// Busca de distância 2 é bem mais cara (testamos: ~500ms pra uma palavra de 14 letras) -
// guardamos o resultado por palavra pra nunca refazer a mesma conta duas vezes na mesma sessão.
const deepSuggestCache = new Map<string, string | undefined>();

/** Consulta só a lista de palavras (não a curada de WORD_REPLACEMENTS - isso é feito por quem
 * chama esta função antes, em getSpellIssue). Retorna undefined enquanto ainda não carregou.
 *
 * `deep`: também tenta achar sugestão a 2 edições de distância quando a de 1 não encontra nada
 * (~500ms no pior caso) - só vale a pena numa ação pontual do usuário (menu de botão direito),
 * nunca a cada tecla digitada (por isso o sublinhado, que recalcula a cada tecla, usa deep=false
 * e só sinaliza "está errado" sem gastar tempo achando a sugestão perfeita). */
export function checkWordAgainstDictionary(
  word: string,
  options: { deep?: boolean } = {}
): { misspelled: boolean; suggestion?: string } | undefined {
  if (!wordSet) return undefined;
  if (!word || word.length < 3) return { misspelled: false };
  if (!PURE_WORD_RE.test(word)) return { misspelled: false };
  // Nomes próprios/marcas: se a palavra começa com maiúscula (e não é tudo maiúsculo por
  // ênfase digitada), não arriscamos marcar como erro.
  const firstIsUpper = word[0] !== word[0].toLowerCase();
  const isAllCaps = word === word.toUpperCase();
  if (firstIsUpper && !isAllCaps) return { misspelled: false };

  const lower = word.toLowerCase();
  if (isKnown(lower)) return { misspelled: false };

  const candidates = knownEdits1(lower);
  if (candidates.size > 0) {
    const best = [...candidates].sort((a, b) => Math.abs(a.length - lower.length) - Math.abs(b.length - lower.length))[0];
    return { misspelled: true, suggestion: best };
  }

  if (!options.deep) return { misspelled: true };

  if (deepSuggestCache.has(lower)) {
    return { misspelled: true, suggestion: deepSuggestCache.get(lower) };
  }
  const deepCandidates = new Set<string>();
  for (const bridge of new Set(rawEdits1(lower))) {
    for (const cand of knownEdits1(bridge)) deepCandidates.add(cand);
  }
  const best = deepCandidates.size > 0
    ? [...deepCandidates].sort((a, b) => Math.abs(a.length - lower.length) - Math.abs(b.length - lower.length))[0]
    : undefined;
  deepSuggestCache.set(lower, best);
  return { misspelled: true, suggestion: best };
}

/**
 * Combina os dois níveis de checagem: primeiro a lista curada (instantânea, sem depender do
 * dicionário ter carregado - cobre abreviações tipo "vc"/"blz" que não são bem "erros" pro
 * dicionário formal), depois a lista de palavras pt-BR pra pegar qualquer outro erro de
 * digitação. É o que a caixa de digitar (sublinhado) e o menu de botão direito usam.
 */
export function getSpellIssue(word: string, options: { deep?: boolean } = {}): { flagged: boolean; suggestion?: string } {
  if (!word) return { flagged: false };
  const curated = WORD_REPLACEMENTS[word.toLowerCase()];
  if (curated && curated.toLowerCase() !== word.toLowerCase()) {
    return { flagged: true, suggestion: curated };
  }
  const fromDict = checkWordAgainstDictionary(word, options);
  if (fromDict?.misspelled) {
    return { flagged: true, suggestion: fromDict.suggestion };
  }
  return { flagged: false };
}
