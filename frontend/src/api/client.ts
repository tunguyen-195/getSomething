let csrfToken: string | null = null;

export const SUMMARY_TYPES = ['brief', 'detailed', 'investigation', 'forensic'] as const;
export type SummaryType = (typeof SUMMARY_TYPES)[number];
export type SummaryLengthMode = 'auto' | 'manual';
export const INVESTIGATION_SCENARIOS = [
  'auto',
  'general',
  'financial_asset',
  'coordination_planning',
  'threat_coercion',
  'goods_transport',
  'public_administration',
  'incident_conflict',
] as const;
export type InvestigationScenario = (typeof INVESTIGATION_SCENARIOS)[number];
export const DEFAULT_SUMMARY_TYPE: SummaryType = 'detailed';
export const DEFAULT_INTERACTIVE_SUMMARY_TYPE: SummaryType = 'investigation';
export const DEFAULT_SUMMARY_MIN_LENGTH = 50;
export const DEFAULT_SUMMARY_MAX_LENGTH = 200;
export const DEFAULT_INVESTIGATION_SUMMARY_MIN_LENGTH = 120;
export const DEFAULT_INVESTIGATION_SUMMARY_MAX_LENGTH = 400;
export const DEFAULT_MULTI_SUMMARY_MIN_LENGTH = 100;
export const DEFAULT_MULTI_SUMMARY_MAX_LENGTH = 400;
export const SUMMARY_USER_PROMPT_MAX_LENGTH = 2000;

export function normalizeSummaryUserPrompt(value: string | null | undefined): string | undefined {
  const normalized = value?.trim() ?? '';
  if (!normalized) return undefined;
  if (Array.from(normalized).length > SUMMARY_USER_PROMPT_MAX_LENGTH) {
    throw new Error(`Summary prompt must not exceed ${SUMMARY_USER_PROMPT_MAX_LENGTH} characters`);
  }
  return normalized;
}

export interface SummaryDialogOptions {
  model_name: string;
  summary_type: SummaryType;
  user_prompt?: string;
  include_context_analysis: boolean;
  min_length: number;
  max_length: number;
  length_mode: SummaryLengthMode;
  investigation_scenario: InvestigationScenario;
}

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

  let response = await fetch(input, {
    ...init,
    headers,
    credentials: 'include',
  });

  if (response.status === 403 && unsafeMethods.has(method)) {
    const payload = await response.clone().json().catch(() => null);
    const detail = typeof payload?.detail === 'string' ? payload.detail : '';
    if (detail === 'CSRF validation failed') {
      csrfToken = null;
      headers.set('X-CSRF-Token', await getCsrfToken());
      response = await fetch(input, {
        ...init,
        headers,
        credentials: 'include',
      });
    }
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
