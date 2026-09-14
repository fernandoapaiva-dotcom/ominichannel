/**
 * Spelling and Typo Corrector Engine for Brazilian Portuguese (pt-BR)
 * Designed for real-time chat correction and pre-send sanitization.
 */

// Multi-word phrase replacements (checked first)
export const PHRASE_REPLACEMENTS: Record<string, string> = {
  'comcerteza': 'com certeza',
  'concerteza': 'com certeza',
  'derrepente': 'de repente',
  'de repete': 'de repente',
  'apartir': 'a partir',
  'porisso': 'por isso',
  'bomdia': 'bom dia',
  'boatarde': 'boa tarde',
  'boanoite': 'boa noite',
  'ate logo': 'até logo',
  'ate mais': 'até mais',
  'ate breve': 'até breve',
  'por favor': 'por favor',
  'porfavor': 'por favor',
  'a mais ou menos': 'mais ou menos',
  'pra mim fazer': 'para eu fazer',
  'para mim fazer': 'para eu fazer',
  'fazem anos': 'faz anos',
  'fazem meses': 'faz meses',
  'fazem dias': 'faz dias',
  'houveram problemas': 'houve problemas',
  'houveram duvidas': 'houve dúvidas',
  'deu certo': 'deu certo'
};

// Word-level replacements (normalized lowercase keys)
export const WORD_REPLACEMENTS: Record<string, string> = {
  // Common informal abbreviations
  'vc': 'você',
  'vcs': 'vocês',
  'tb': 'também',
  'tbm': 'também',
  'pq': 'porque',
  'oq': 'o que',
  'kd': 'cadê',
  'td': 'tudo',
  'tds': 'todos',
  'blz': 'beleza',
  'vlw': 'valeu',
  'flw': 'falou',
  'cmg': 'comigo',
  'ctg': 'contigo',
  'pfv': 'por favor',
  'pls': 'por favor',
  'porfa': 'por favor',
  'msg': 'mensagem',
  'msgs': 'mensagens',
  'zap': 'WhatsApp',
  'whats': 'WhatsApp',
  'wpp': 'WhatsApp',
  'obg': 'obrigado',
  'obgd': 'obrigado',
  'obgda': 'obrigada',
  'brigado': 'obrigado',
  'brigada': 'obrigada',
  'dnada': 'de nada',

  // Common phonetic / spelling mistakes
  'senho': 'senhor',
  'senhorr': 'senhor',
  'menas': 'menos',
  'seje': 'seja',
  'esteje': 'esteja',
  'poblema': 'problema',
  'pobrema': 'problema',
  'probrema': 'problema',
  'poblemas': 'problemas',
  'probremas': 'problemas',
  'fais': 'faz',
  'geito': 'jeito',
  'excessao': 'exceção',
  'excessão': 'exceção',
  'escessao': 'exceção',
  'escecao': 'exceção',
  'enxergar': 'enxergar',
  'enchergar': 'enxergar',
  'mecher': 'mexer',
  'meche': 'mexe',
  'paralizar': 'paralisar',
  'analizar': 'analisar',
  'analize': 'análise',
  'pesquiza': 'pesquisa',

  // Missing accents - Technical, Equipment & Parts
  'substituidos': 'substituídos',
  'substituido': 'substituído',
  'substituida': 'substituída',
  'substituidas': 'substituídas',
  'maquina': 'máquina',
  'maquinas': 'máquinas',
  'equipamento': 'equipamento',
  'equipamentos': 'equipamentos',
  'eletrica': 'elétrica',
  'eletricas': 'elétricas',
  'eletrico': 'elétrico',
  'eletricos': 'elétricos',
  'eletronica': 'eletrônica',
  'eletronicas': 'eletrônicas',
  'eletronico': 'eletrônico',
  'eletronicos': 'eletrônicos',
  'mecanica': 'mecânica',
  'mecanicas': 'mecânicas',
  'mecanico': 'mecânico',
  'mecanicos': 'mecânicos',
  'tecnico': 'técnico',
  'tecnica': 'técnica',
  'tecnicos': 'técnicos',
  'tecnicas': 'técnicas',
  'peca': 'peça',
  'pecas': 'peças',
  'orcamento': 'orçamento',
  'orcamentos': 'orçamentos',
  'servico': 'serviço',
  'servicos': 'serviços',
  'laboratorio': 'laboratório',
  'laboratorios': 'laboratórios',
  'modulo': 'módulo',
  'modulos': 'módulos',
  'codigo': 'código',
  'codigos': 'códigos',
  'numero': 'número',
  'numeros': 'números',
  'revisao': 'revisão',
  'revisoes': 'revisões',
  'manutencao': 'manutenção',
  'manutencoes': 'manutenções',
  'calibracao': 'calibração',
  'calibracoes': 'calibrações',
  'garantia': 'garantia',
  'garantias': 'garantias',
  'conserto': 'conserto',
  'consertos': 'consertos',
  'valvula': 'válvula',
  'valvulas': 'válvulas',
  'fusivel': 'fusível',
  'fusiveis': 'fusíveis',
  'bateria': 'bateria',
  'baterias': 'baterias',

  // Missing accents - Common verbs & auxiliary words
  'nao': 'não',
  'sao': 'são',
  'estao': 'estão',
  'irao': 'irão',
  'sera': 'será',
  'serao': 'serão',
  'esta': 'está',
  'estara': 'estará',
  'estarao': 'estarão',
  'tambem': 'também',
  'alguem': 'alguém',
  'ninguem': 'ninguém',
  'ate': 'até',
  'ja': 'já',
  'so': 'só',
  'la': 'lá',
  'ca': 'cá',
  'eh': 'é',
  'ta': 'está',
  'to': 'estou',
  'pra': 'para',
  'pro': 'para o',
  'pros': 'para os',
  'pras': 'para as',
  'concluido': 'concluído',
  'concluida': 'concluída',
  'concluidos': 'concluídos',
  'concluidas': 'concluídas',
  'valido': 'válido',
  'valida': 'válida',
  'validos': 'válidos',
  'validas': 'válidas',
  'invalido': 'inválido',
  'invalida': 'inválida',

  // Missing accents - Business & Communication
  'atencao': 'atenção',
  'posicao': 'posição',
  'posicoes': 'posições',
  'autorizacao': 'autorização',
  'autorizacoes': 'autorizações',
  'solucao': 'solução',
  'solucoes': 'soluções',
  'avaliacao': 'avaliação',
  'avaliacoes': 'avaliações',
  'confirmacao': 'confirmação',
  'confirmacoes': 'confirmações',
  'informacao': 'informação',
  'informacoes': 'informações',
  'condicao': 'condição',
  'condicoes': 'condições',
  'situacao': 'situação',
  'situacoes': 'situações',
  'solicitacao': 'solicitação',
  'solicitacoes': 'solicitações',
  'opcao': 'opção',
  'opcoes': 'opções',
  'direcao': 'direção',
  'disposicao': 'disposição',
  'comunicacao': 'comunicação',
  'declaracao': 'declaração',
  'preco': 'preço',
  'precos': 'preços',
  'duvida': 'dúvida',
  'duvidas': 'dúvidas',
  'horario': 'horário',
  'horarios': 'horários',
  'periodo': 'período',
  'periodos': 'períodos',
  'proximo': 'próximo',
  'proxima': 'próxima',
  'proximos': 'próximos',
  'proximas': 'próximas',
  'ultimo': 'último',
  'ultima': 'última',
  'ultimos': 'últimos',
  'ultimas': 'últimas',
  'facil': 'fácil',
  'faceis': 'fáceis',
  'dificil': 'difícil',
  'dificeis': 'difíceis',
  'possivel': 'possível',
  'possiveis': 'possíveis',
  'impossivel': 'impossível',
  'impossiveis': 'impossíveis',
  'disponivel': 'disponível',
  'disponiveis': 'disponíveis',
  'responsavel': 'responsável',
  'responsaveis': 'responsáveis',
  'util': 'útil',
  'uteis': 'úteis',
  'inutil': 'inútil',
  'inuteis': 'inúteis',
  'rapido': 'rápido',
  'rapida': 'rapida',
  'rapidos': 'rápidos',
  'rapidas': 'rápidas',
  'otimo': 'ótimo',
  'otima': 'ótima',
  'otimos': 'ótimos',
  'otimas': 'ótimas',
  'pessimo': 'péssimo',
  'pessima': 'péssima',
  'publico': 'público',
  'pagina': 'página',
  'paginas': 'páginas',
  'gerencia': 'gerência',
  'exito': 'êxito',
  'inicio': 'início',
  'previo': 'prévio',
  'previa': 'prévia',
  'criterio': 'critério',
  'criterios': 'critérios',
  'historico': 'histórico',
  'historicos': 'históricos',
  'politica': 'política',
  'politicas': 'políticas'
};

/**
 * Preserves the casing of the original word when applying the replacement.
 * - ALL CAPS: SUBSTUIDOS -> SUBSTITUÍDOS
 * - Title Case: Substituidos -> Substituídos
 * - lowercase: substituidos -> substituídos
 */
export function preserveCase(original: string, replacement: string): string {
  if (!original || !replacement) return replacement;

  // ALL UPPERCASE
  if (original === original.toUpperCase() && original !== original.toLowerCase()) {
    return replacement.toUpperCase();
  }

  // Title Case (First letter capitalized)
  if (original[0] === original[0].toUpperCase() && original[0] !== original[0].toLowerCase()) {
    return replacement[0].toUpperCase() + replacement.slice(1);
  }

  // Lowercase
  return replacement.toLowerCase();
}

/**
 * Checks if a single word has a correction.
 * Returns the corrected word if found, or original word if not.
 */
export function correctSingleWord(word: string): { corrected: string; wasChanged: boolean } {
  if (!word || word.length < 2) return { corrected: word, wasChanged: false };

  // Remove trailing punctuation for matching
  const match = word.match(/^([^\w\sáàâãéèêíïóôõöúçñ]*)([\wáàâãéèêíïóôõöúçñ]+)([^\w\sáàâãéèêíïóôõöúçñ]*)$/i);
  if (!match) return { corrected: word, wasChanged: false };

  const [, leadingPunct, coreWord, trailingPunct] = match;
  const lowerCore = coreWord.toLowerCase();

  const replacement = WORD_REPLACEMENTS[lowerCore];
  if (replacement && replacement.toLowerCase() !== lowerCore) {
    const casedReplacement = preserveCase(coreWord, replacement);
    return {
      corrected: `${leadingPunct}${casedReplacement}${trailingPunct}`,
      wasChanged: true
    };
  }

  return { corrected: word, wasChanged: false };
}

/**
 * Scans the full text and applies multi-word phrase corrections and individual word corrections.
 */
export function correctFullText(text: string): {
  text: string;
  changesCount: number;
  lastCorrection?: { from: string; to: string };
} {
  if (!text || !text.trim()) {
    return { text, changesCount: 0 };
  }

  let result = text;
  let changesCount = 0;
  let lastCorrection: { from: string; to: string } | undefined;

  // 1. Multi-word phrase replacements
  for (const [phrase, rep] of Object.entries(PHRASE_REPLACEMENTS)) {
    const regex = new RegExp(`\\b${phrase}\\b`, 'gi');
    if (regex.test(result)) {
      result = result.replace(regex, (match) => {
        changesCount++;
        const cased = preserveCase(match, rep);
        lastCorrection = { from: match, to: cased };
        return cased;
      });
    }
  }

  // 2. Individual word replacements
  const wordRegex = /\b[a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ]+\b/g;
  result = result.replace(wordRegex, (match) => {
    const lower = match.toLowerCase();
    const rep = WORD_REPLACEMENTS[lower];
    if (rep && rep.toLowerCase() !== lower) {
      changesCount++;
      const cased = preserveCase(match, rep);
      lastCorrection = { from: match, to: cased };
      return cased;
    }
    return match;
  });

  return {
    text: result,
    changesCount,
    lastCorrection
  };
}

/**
 * Inspects the text currently typed in a textarea before a given cursor position
 * (e.g. triggered when user hits Space or Punctuation).
 * If the word immediately before the trigger character was misspelled, it corrects it in place.
 */
export function correctLastWordBeforeCursor(
  text: string,
  cursorPos: number
): {
  newText: string;
  newCursor: number;
  correctedWord?: { from: string; to: string };
} {
  if (cursorPos <= 0 || cursorPos > text.length) {
    return { newText: text, newCursor: cursorPos };
  }

  // Slice text up to the cursor
  const textBefore = text.slice(0, cursorPos);
  const textAfter = text.slice(cursorPos);

  // Find the word right before the cursor (may end with a space or punctuation)
  const match = textBefore.match(/([a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ]+)([\s.,!?;:]+)$/);
  if (!match) {
    return { newText: text, newCursor: cursorPos };
  }

  const [fullMatch, rawWord, trailingDelim] = match;
  const lower = rawWord.toLowerCase();

  const rep = WORD_REPLACEMENTS[lower];
  if (rep && rep.toLowerCase() !== lower) {
    const casedRep = preserveCase(rawWord, rep);
    const startIndex = cursorPos - fullMatch.length;
    const replacementWithDelim = `${casedRep}${trailingDelim}`;
    const newText = text.slice(0, startIndex) + replacementWithDelim + textAfter;
    const newCursor = startIndex + replacementWithDelim.length;

    return {
      newText,
      newCursor,
      correctedWord: { from: rawWord, to: casedRep }
    };
  }

  return { newText: text, newCursor: cursorPos };
}
