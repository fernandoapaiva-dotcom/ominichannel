// Cliente HTTP do Portal do Técnico - espelha apiFetch (services/api.ts) mas com chave de sessão própria
// (tech_token), isolada do login administrativo, pra um técnico e um atendente poderem estar logados no
// mesmo navegador/celular sem um derrubar a sessão do outro.
const getApiBase = () => `/api/v1/technician-portal`;

export async function techApiFetch(endpoint: string, options: RequestInit = {}) {
  const token = localStorage.getItem('tech_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${getApiBase()}${endpoint}`, { ...options, headers });
  } catch (err: any) {
    throw new Error('Falha ao conectar com o servidor. Verifique sua internet.');
  }

  if (response.status === 401) {
    localStorage.removeItem('tech_token');
    window.location.href = '/tecnico';
    throw new Error('Sessão expirada');
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    let errMsg = 'Erro ao comunicar com o servidor';
    if (typeof errData.detail === 'string') errMsg = errData.detail;
    else if (errData.detail) errMsg = JSON.stringify(errData.detail);
    throw new Error(errMsg);
  }

  return response.json();
}

// Espelha apiUpload (services/api.ts) mas com a sessão do técnico (tech_token) - usado pra subir
// foto de O.S. direto pela câmera do app do técnico (ver OsDetailModal em TechBoard.tsx).
export async function techApiUpload(endpoint: string, formData: FormData) {
  const token = localStorage.getItem('tech_token');
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${getApiBase()}${endpoint}`, { method: 'POST', headers, body: formData });
  } catch (err: any) {
    throw new Error('Falha ao conectar com o servidor. Verifique sua internet.');
  }

  if (response.status === 401) {
    localStorage.removeItem('tech_token');
    window.location.href = '/tecnico';
    throw new Error('Sessão expirada');
  }

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    let errMsg = 'Erro ao comunicar com o servidor';
    if (typeof errData.detail === 'string') errMsg = errData.detail;
    else if (errData.detail) errMsg = JSON.stringify(errData.detail);
    throw new Error(errMsg);
  }

  return response.json();
}
