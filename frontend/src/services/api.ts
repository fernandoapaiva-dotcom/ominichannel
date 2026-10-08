const getApiBase = () => {
  return `/api/v1`;
};

export async function apiFetch(endpoint: string, options: RequestInit = {}) {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBase()}${endpoint}`, {
      ...options,
      headers,
    });
  } catch (err: any) {
    throw new Error(`Falha ao conectar com o servidor backend (${getApiBase()}). Verifique se o servidor está ativo.`);
  }

  if (response.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('Sessão expirada');
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    let errMsg = 'Erro ao comunicar com o servidor';
    if (typeof errData.detail === 'string') {
      errMsg = errData.detail;
    } else if (Array.isArray(errData.detail)) {
      errMsg = errData.detail.map((e: any) => e.msg || JSON.stringify(e)).join(', ');
    } else if (errData.detail) {
      errMsg = JSON.stringify(errData.detail);
    }
    throw new Error(errMsg);
  }

  return response.json();
}

// Arquivos acima disto sobem em partes (ver apiUploadChunked): um POST único de vários MB estourava o tempo
// quando o servidor estava ocupado e, antes do ajuste do nginx, era recusado por passar de 1 MB.
export const CHUNKED_UPLOAD_THRESHOLD_BYTES = 1.5 * 1024 * 1024;
const UPLOAD_CHUNK_BYTES = 1024 * 1024;

class FatalUploadError extends Error {}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Achado em produção em 05/10/2026: fetch() não tem timeout nenhum por padrão - numa conexão
// instável (ex.: internet lenta/oscilando da loja), uma parte do upload podia travar a conexão
// sem nunca falhar nem ter sucesso, e o navegador ficava esperando pra sempre ("carregando..."
// infinito) - a lógica de nova tentativa nunca disparava porque a Promise nunca resolvia nem
// rejeitava. Timeout força a falha depois de um tempo razoável, pra entrar no circuito de retry.
const UPLOAD_REQUEST_TIMEOUT_MS = 60000;

async function authorizedPost(endpoint: string, body: BodyInit, isJson: boolean, timeoutMs = UPLOAD_REQUEST_TIMEOUT_MS): Promise<Response> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (isJson) headers['Content-Type'] = 'application/json';
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${getApiBase()}${endpoint}`, { method: 'POST', headers, body, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  const errData = await response.json().catch(() => ({}));
  if (typeof errData.detail === 'string') return errData.detail;
  return fallback;
}

/**
 * Envia um arquivo grande em partes de 1 MB para `${endpointBase}/chunk` e depois pede a montagem/envio em
 * `${endpointBase}/complete`. Cada parte tem nova tentativa própria (até 5x, com espera crescente): se a
 * conexão oscilar ou o servidor demorar, só aquela parte é repetida, não o arquivo inteiro. Reenviar uma
 * parte é seguro (o servidor sobrescreve). O passo final só repete em falha de rede/502/503, nunca em 504,
 * para não mandar o mesmo arquivo duas vezes ao cliente.
 */
// 32 caracteres hexadecimais (0-9a-f) - o backend exige esse formato exato pro upload_id
// (_UPLOAD_ID_RE em conversations.py). Achado em produção em 05/10/2026: em navegadores sem
// crypto.randomUUID (ou fora de contexto seguro), o uploadId caía no modo alternativo
// `${Date.now()}${Math.random()}`, que inclui um PONTO decimal do Math.random() - não é hex
// válido, o backend recusava com "upload_id inválido" e o PDF nunca saía do lugar. Gera os 32
// dígitos hex na mão, sem depender de nenhuma API que possa faltar.
function randomHex32(): string {
  if (crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '');
  let s = '';
  for (let i = 0; i < 32; i++) s += Math.floor(Math.random() * 16).toString(16);
  return s;
}

// Quantas partes sobem AO MESMO TEMPO. Achado em produção em 05/10/2026: subir uma parte de
// cada vez, esperando a anterior terminar pra só então começar a próxima, multiplicava o atraso
// de ida-e-volta de cada requisição (TLS, Cloudflare Tunnel, etc.) pelo número de partes - num
// arquivo de 10 MB (10 partes) isso significava 10 round-trips sequenciais. Com isso,
// CHUNK_CONCURRENCY partes sobem em paralelo, cada "trabalhador" pega a próxima parte livre assim
// que termina a sua - pedido explícito do usuário ("tem que ser 1000x mais rápido").
const CHUNK_CONCURRENCY = 4;

export async function apiUploadChunked(
  endpointBase: string,
  file: File,
  caption?: string,
  onProgress?: (sent: number, total: number) => void
) {
  const uploadId = randomHex32().toLowerCase();
  const total = Math.max(1, Math.ceil(file.size / UPLOAD_CHUNK_BYTES));
  const CHUNK_DELAYS_MS = [0, 1500, 3000, 6000, 10000];
  let sentCount = 0;

  const uploadOneChunk = async (index: number) => {
    const blob = file.slice(index * UPLOAD_CHUNK_BYTES, (index + 1) * UPLOAD_CHUNK_BYTES);
    let done = false;
    let lastError = 'Falha de conexão ao enviar o arquivo.';
    for (let attempt = 0; attempt < CHUNK_DELAYS_MS.length && !done; attempt++) {
      if (CHUNK_DELAYS_MS[attempt] > 0) await sleep(CHUNK_DELAYS_MS[attempt]);
      const form = new FormData();
      form.append('upload_id', uploadId);
      form.append('index', String(index));
      form.append('total', String(total));
      form.append('chunk', blob, 'parte');
      try {
        const response = await authorizedPost(`${endpointBase}/chunk`, form, false);
        if (response.status === 401) {
          localStorage.removeItem('token');
          window.location.href = '/login';
          throw new FatalUploadError('Sessão expirada');
        }
        if (response.ok) {
          done = true;
        } else if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
          throw new FatalUploadError(await readErrorDetail(response, 'Erro ao enviar arquivo'));
        } else {
          lastError = await readErrorDetail(response, `Servidor ocupado (${response.status})`);
        }
      } catch (err: any) {
        if (err instanceof FatalUploadError) throw err;
        lastError = 'Falha de conexão ao enviar o arquivo.';
      }
    }
    if (!done) throw new Error(lastError);
    sentCount++;
    if (onProgress) onProgress(sentCount, total);
  };

  // Pool simples: N "trabalhadores" rodando ao mesmo tempo, cada um pega o próximo índice livre
  // assim que termina o seu - pára todo mundo no primeiro erro definitivo (sessão expirada, parte
  // rejeitada de vez), mas deixa os já em andamento terminarem antes de propagar o erro.
  let nextIndex = 0;
  let firstError: any = null;
  const worker = async () => {
    while (!firstError) {
      const myIndex = nextIndex++;
      if (myIndex >= total) return;
      try {
        await uploadOneChunk(myIndex);
      } catch (err) {
        if (!firstError) firstError = err;
        return;
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(CHUNK_CONCURRENCY, total) }, () => worker()));
  if (firstError) throw firstError;

  const completeBody = JSON.stringify({
    upload_id: uploadId,
    total,
    filename: file.name,
    content_type: file.type || null,
    caption: caption || null,
  });
  let response: Response | null = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) await sleep(3000);
    try {
      response = await authorizedPost(`${endpointBase}/complete`, completeBody, true);
    } catch {
      response = null;
      continue;
    }
    if (response.status === 502 || response.status === 503) continue;
    break;
  }
  if (!response) throw new Error('Falha ao conectar com o servidor backend. Verifique se o servidor está ativo.');
  if (response.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('Sessão expirada');
  }
  if (!response.ok) {
    throw new Error(await readErrorDetail(response, 'Erro ao enviar arquivo'));
  }
  return response.json();
}

export async function apiUpload(endpoint: string, formData: FormData) {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {};

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // Até 3 tentativas para falhas que não chegaram a ser processadas (rede caiu, 502/503 do proxy).
  // Erro de validação, sessão ou arquivo grande demais não adianta repetir.
  const RETRY_DELAYS_MS = [0, 1500, 4000];
  let response: Response | null = null;
  let lastNetworkError = false;
  for (let attempt = 0; attempt < RETRY_DELAYS_MS.length; attempt++) {
    if (RETRY_DELAYS_MS[attempt] > 0) {
      await new Promise(resolve => setTimeout(resolve, RETRY_DELAYS_MS[attempt]));
    }
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), UPLOAD_REQUEST_TIMEOUT_MS);
      try {
        response = await fetch(`${getApiBase()}${endpoint}`, {
          method: 'POST',
          headers,
          body: formData,
          signal: controller.signal
        });
      } finally {
        clearTimeout(timeoutId);
      }
      lastNetworkError = false;
    } catch (err: any) {
      response = null;
      lastNetworkError = true;
      continue;
    }
    if (response.status === 502 || response.status === 503) {
      continue;
    }
    break;
  }

  if (!response || lastNetworkError) {
    throw new Error(`Falha ao conectar com o servidor backend (${getApiBase()}). Verifique se o servidor está ativo.`);
  }

  if (response.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('Sessão expirada');
  }

  if (response.status === 413) {
    throw new Error('Arquivo grande demais para o servidor.');
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.detail || 'Erro ao enviar arquivo');
  }

  return response.json();
}
