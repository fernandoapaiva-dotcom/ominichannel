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

async function authorizedPost(endpoint: string, body: BodyInit, isJson: boolean): Promise<Response> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (isJson) headers['Content-Type'] = 'application/json';
  return fetch(`${getApiBase()}${endpoint}`, { method: 'POST', headers, body });
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
export async function apiUploadChunked(
  endpointBase: string,
  file: File,
  caption?: string,
  onProgress?: (sent: number, total: number) => void
) {
  const uploadId = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}${Math.random()}`).replace(/-/g, '').padEnd(32, '0').slice(0, 32).toLowerCase();
  const total = Math.max(1, Math.ceil(file.size / UPLOAD_CHUNK_BYTES));
  const CHUNK_DELAYS_MS = [0, 1500, 3000, 6000, 10000];

  for (let index = 0; index < total; index++) {
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
    if (onProgress) onProgress(index + 1, total);
  }

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
      response = await fetch(`${getApiBase()}${endpoint}`, {
        method: 'POST',
        headers,
        body: formData
      });
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
