const getApiBase = () => {
  const host = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';
  return `http://${host}:8000/api/v1`;
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
    throw new Error(errData.detail || 'Erro ao comunicar com o servidor');
  }

  return response.json();
}

export async function apiUpload(endpoint: string, formData: FormData) {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {};

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBase()}${endpoint}`, {
      method: 'POST',
      headers,
      body: formData
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
    throw new Error(errData.detail || 'Erro ao enviar arquivo');
  }

  return response.json();
}
