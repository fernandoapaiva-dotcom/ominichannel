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
