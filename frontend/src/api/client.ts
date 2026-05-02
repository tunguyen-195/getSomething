let csrfToken: string | null = null;

const unsafeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const API_BASE_URL = typeof window !== 'undefined' && (window as any).API_BASE_URL ? (window as any).API_BASE_URL : '';
const CSRF_COOKIE_NAME = 'csrf_token';

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${name}=`;
  const value = document.cookie
    .split(';')
    .map(part => part.trim())
    .find(part => part.startsWith(prefix));
  return value ? decodeURIComponent(value.slice(prefix.length)) : null;
}

async function responseDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.clone().json();
    return typeof body?.detail === 'string' ? body.detail : null;
  } catch {
    return null;
  }
}

export async function getCsrfToken(forceRefresh = false): Promise<string> {
  const cookieToken = readCookie(CSRF_COOKIE_NAME);
  if (!forceRefresh && cookieToken) {
    csrfToken = cookieToken;
    return csrfToken;
  }
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
  const shouldAttachCsrf = unsafeMethods.has(method);

  if (shouldAttachCsrf) {
    headers.set('X-CSRF-Token', await getCsrfToken());
  }

  let response = await fetch(input, {
    ...init,
    headers,
    credentials: 'include',
  });

  if (shouldAttachCsrf && response.status === 403 && (await responseDetail(response)) === 'CSRF validation failed') {
    csrfToken = null;
    headers.set('X-CSRF-Token', await getCsrfToken(true));
    response = await fetch(input, {
      ...init,
      headers,
      credentials: 'include',
    });
  }

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
