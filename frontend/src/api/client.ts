let csrfToken: string | null = null;

const unsafeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';

export async function getCsrfToken(): Promise<string> {
  if (csrfToken) return csrfToken;
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/csrf`, {
    credentials: 'include',
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch CSRF token: ${response.status}`);
  }
  const data = await response.json();
  csrfToken = data.csrf_token;
  return csrfToken as string;
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers || {});

  if (unsafeMethods.has(method)) {
    headers.set('X-CSRF-Token', await getCsrfToken());
  }

  const response = await fetch(input, {
    ...init,
    headers,
    credentials: 'include',
  });

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:required'));
  }
  if (response.status === 429) {
    window.dispatchEvent(new CustomEvent('api:rate-limited'));
  }
  return response;
}

export async function login(username: string, password: string) {
  const token = await getCsrfToken();
  const response = await apiFetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': token,
    },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new Error('Invalid credentials');
  }
  return response.json();
}

export async function logout() {
  await apiFetch(`${API_BASE_URL}/api/v1/auth/logout`, { method: 'POST' });
  csrfToken = null;
}

export async function getCurrentUser() {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/auth/me`);
  if (!response.ok) return null;
  return response.json();
}
