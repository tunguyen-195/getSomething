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
/**
 * Batch summaries use the same semantic allow-list as single-file summaries.
 * Keeping this alias instead of a second list prevents the UI from silently
 * dropping investigation/forensic results returned by newer API versions.
 */
export type AudioBatchSummaryType = SummaryType;
export const DEFAULT_BATCH_SUMMARY_TYPE: AudioBatchSummaryType = 'detailed';
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

export const AUDIO_BATCH_STATUSES = [
  'created',
  'queued',
  'processing',
  'partially_succeeded',
  'succeeded',
  'failed',
  'cancel_requested',
  'cancelled',
] as const;
export type AudioBatchStatus = (typeof AUDIO_BATCH_STATUSES)[number];
export const AUDIO_BATCH_MAX_FILES = 20;
export const AUDIO_BATCH_MAX_FILE_BYTES = 100_000_000;
export const AUDIO_BATCH_MAX_TOTAL_BYTES = 1_000_000_000;

export const AUDIO_BATCH_ITEM_STATUSES = [
  'uploaded',
  'queued',
  'transcribing',
  'transcribed',
  'failed',
  'cancel_requested',
  'cancelled',
] as const;
export type AudioBatchItemStatus = (typeof AUDIO_BATCH_ITEM_STATUSES)[number];

export interface SafeApiErrorEnvelope {
  code: string;
  message: string;
  retryable?: boolean;
}

export interface AudioBatchItem {
  id: number;
  position: number;
  task_id: string;
  audio_id: number;
  original_filename: string;
  status: AudioBatchItemStatus;
  error_code: string | null;
  celery_task_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AudioBatchResponse {
  id: string;
  case_id: number;
  status: AudioBatchStatus;
  requested_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  total_size_bytes: number;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  items: AudioBatchItem[];
}

export interface CreateAudioBatchInput {
  files: File[];
  caseId: string;
  idempotencyKey: string;
}

export interface BatchTranscriptionOptions {
  task_ids: string[];
  language?: string;
  enable_diarization?: boolean;
  diarization_method?: string;
  fast_mode?: boolean;
}

export interface AudioBatchAcceptedResponse {
  batch_id: string;
  status: AudioBatchStatus;
}

export interface AudioBatchSummaryRequest {
  task_ids: string[];
  model_name?: string | null;
  summary_type: AudioBatchSummaryType;
  /** Request independent outputs for one or more semantic summary modes. */
  summary_types?: AudioBatchSummaryType[];
  min_length: number;
  max_length: number;
  length_mode: SummaryLengthMode;
  user_prompt?: string;
}

export type AudioBatchSummaryStatus =
  | 'queued'
  | 'processing'
  | 'partially_succeeded'
  | 'succeeded'
  | 'failed'
  | 'cancel_requested'
  | 'cancelled';

export interface AudioBatchSummaryJob {
  batch_id: string;
  summary_job_id: string;
  status: AudioBatchSummaryStatus;
  summary: string | null;
  /** Type of the legacy/single result, when the server returns one. */
  summary_type?: AudioBatchSummaryType;
  /**
   * New multi-result projection. Each type is persisted independently; the
   * root `summary` remains as a backwards-compatible legacy projection.
   */
  summary_results?: AudioBatchSummaryResult[];
  /** Alias accepted during rolling upgrades. */
  summaries?: Record<string, string | AudioBatchSummaryResult | null>;
  /** Single-file projection alias used by the v2 task result endpoint. */
  summary_variants?: Record<string, string | AudioBatchSummaryResult | null>;
  source_manifest: Array<{
    position: number;
    task_id: string;
    filename: string;
  }>;
  user_prompt_applied: boolean;
  error: SafeApiErrorEnvelope | null;
}

export interface AudioBatchSummaryResult {
  summary_type: AudioBatchSummaryType;
  summary: string | null;
  summary_model?: string | null;
  runtime?: {
    prompt_version?: string | null;
    summary_generation?: string | null;
    provider?: string | null;
    llm_call_count?: number | null;
    availability_attempts?: number | null;
    user_prompt_applied?: boolean | null;
  } | null;
  status?: AudioBatchSummaryStatus;
  error?: SafeApiErrorEnvelope | null;
}

export interface AudioBatchResumeRecord {
  batch_id: string;
  summary_job_id?: string;
  selected_task_ids?: string[];
}

const AUDIO_BATCH_TERMINAL_STATUSES = new Set<AudioBatchStatus>([
  'partially_succeeded',
  'succeeded',
  'failed',
  'cancelled',
]);
const AUDIO_BATCH_SUMMARY_TERMINAL_STATUSES = new Set<AudioBatchSummaryStatus>([
  'partially_succeeded',
  'succeeded',
  'failed',
  'cancelled',
]);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SAFE_ERROR_CODE_PATTERN = /^[A-Z0-9_]{1,80}$/;

export function isAudioBatchTerminal(status: AudioBatchStatus): boolean {
  return AUDIO_BATCH_TERMINAL_STATUSES.has(status);
}

export function isAudioBatchProcessing(status: AudioBatchStatus): boolean {
  return status === 'queued' || status === 'processing' || status === 'cancel_requested';
}

export function isAudioBatchSummaryTerminal(status: AudioBatchSummaryStatus): boolean {
  return AUDIO_BATCH_SUMMARY_TERMINAL_STATUSES.has(status);
}

export function audioBatchResumeStorageKey(userId: string | number, caseId: string | number): string {
  return `stt:audio-batch:v1:${encodeURIComponent(String(userId))}:${encodeURIComponent(String(caseId))}`;
}

export function parseAudioBatchResumeRecord(value: string | null): AudioBatchResumeRecord | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object') return null;
    const record = parsed as Record<string, unknown>;
    if (typeof record.batch_id !== 'string' || !UUID_PATTERN.test(record.batch_id)) return null;
    if (record.summary_job_id !== undefined
      && (typeof record.summary_job_id !== 'string' || !UUID_PATTERN.test(record.summary_job_id))) {
      return null;
    }
    const selectedTaskIds = record.selected_task_ids;
    if (selectedTaskIds !== undefined
      && (!Array.isArray(selectedTaskIds)
        || selectedTaskIds.length > AUDIO_BATCH_MAX_FILES
        || selectedTaskIds.some(taskId => typeof taskId !== 'string' || !taskId || taskId.length > 255)
        || new Set(selectedTaskIds).size !== selectedTaskIds.length)) {
      return null;
    }
    return {
      batch_id: record.batch_id,
      ...(typeof record.summary_job_id === 'string' ? { summary_job_id: record.summary_job_id } : {}),
      ...(Array.isArray(selectedTaskIds) ? { selected_task_ids: selectedTaskIds as string[] } : {}),
    };
  } catch {
    return null;
  }
}

export function orderTaskIdsByBatch(batch: AudioBatchResponse, taskIds: string[]): string[] {
  const requested = new Set(taskIds);
  return batch.items
    .filter(item => requested.has(item.task_id))
    .map(item => item.task_id);
}

export class AudioBatchApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;

  constructor(status: number, code = 'BATCH_REQUEST_FAILED', retryable = status >= 500) {
    super('Không thể hoàn tất yêu cầu xử lý nhiều file.');
    this.name = 'AudioBatchApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
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

function batchErrorCode(payload: unknown): { code?: string; retryable?: boolean } {
  if (!payload || typeof payload !== 'object') return {};
  const outer = payload as Record<string, unknown>;
  const detail = outer.detail && typeof outer.detail === 'object'
    ? outer.detail as Record<string, unknown>
    : outer;
  const code = typeof detail.code === 'string' && /^[A-Z0-9_]{1,80}$/.test(detail.code)
    ? detail.code
    : undefined;
  return { code, retryable: typeof detail.retryable === 'boolean' ? detail.retryable : undefined };
}

async function readBatchResponse<T>(response: Response): Promise<T> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const safeError = batchErrorCode(payload);
    throw new AudioBatchApiError(response.status, safeError.code, safeError.retryable);
  }
  if (!payload || typeof payload !== 'object') {
    throw new AudioBatchApiError(response.status, 'INVALID_BATCH_RESPONSE', false);
  }
  return payload as T;
}

function requireAudioBatchResponse(payload: AudioBatchResponse, expectedBatchId?: string): AudioBatchResponse {
  if (!UUID_PATTERN.test(payload.id)
    || (expectedBatchId !== undefined && payload.id !== expectedBatchId)
    || !AUDIO_BATCH_STATUSES.includes(payload.status)
    || !Array.isArray(payload.items)
    || !Number.isInteger(payload.requested_count)
    || payload.requested_count < 1
    || payload.requested_count > AUDIO_BATCH_MAX_FILES
    || payload.items.length !== payload.requested_count
    || !Number.isInteger(payload.completed_count)
    || !Number.isInteger(payload.failed_count)
    || !Number.isInteger(payload.cancelled_count)
    || payload.completed_count < 0
    || payload.failed_count < 0
    || payload.cancelled_count < 0
    || payload.completed_count + payload.failed_count + payload.cancelled_count > payload.requested_count) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_RESPONSE', false);
  }
  const positions = payload.items.map(item => item.position);
  const taskIds = payload.items.map(item => item.task_id);
  const validItems = payload.items.every((item, index) => (
    item.position === index
    && typeof item.task_id === 'string'
    && item.task_id.length > 0
    && typeof item.original_filename === 'string'
    && (item.error_code === null || SAFE_ERROR_CODE_PATTERN.test(item.error_code))
    && AUDIO_BATCH_ITEM_STATUSES.includes(item.status)
  ));
  if (!validItems
    || positions.some((position, index) => position !== index)
    || new Set(taskIds).size !== taskIds.length) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_RESPONSE', false);
  }
  return payload;
}

function requireAudioBatchSummaryJob(
  payload: AudioBatchSummaryJob,
  expectedBatchId: string,
  expectedSummaryJobId?: string,
): AudioBatchSummaryJob {
  const validStatus = ['queued', 'processing', 'partially_succeeded', 'succeeded', 'failed', 'cancel_requested', 'cancelled']
    .includes(payload.status);
  if (!UUID_PATTERN.test(payload.batch_id)
    || payload.batch_id !== expectedBatchId
    || !UUID_PATTERN.test(payload.summary_job_id)
    || (expectedSummaryJobId !== undefined && payload.summary_job_id !== expectedSummaryJobId)
    || !validStatus) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_SUMMARY_RESPONSE', false);
  }
  if (payload.status === 'succeeded'
    && (typeof payload.summary !== 'string' || payload.summary.trim().length === 0)
    && (!Array.isArray(payload.summary_results)
      || !payload.summary_results.some(result => (
        typeof result?.summary === 'string' && result.summary.trim().length > 0
      )))) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_SUMMARY_RESPONSE', false);
  }
  if (payload.summary_type !== undefined && !SUMMARY_TYPES.includes(payload.summary_type)) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_SUMMARY_RESPONSE', false);
  }
  if (payload.summary_results !== undefined) {
    if (!Array.isArray(payload.summary_results)
      || payload.summary_results.length > SUMMARY_TYPES.length
      || payload.summary_results.some(result => (
        !result
        || !SUMMARY_TYPES.includes(result.summary_type)
        || (result.summary !== null && typeof result.summary !== 'string')
        || (result.status !== undefined && !AUDIO_BATCH_SUMMARY_TERMINAL_STATUSES.has(result.status)
          && !['queued', 'processing', 'cancel_requested'].includes(result.status))
      ))
      || new Set(payload.summary_results.map(result => result.summary_type)).size !== payload.summary_results.length) {
      throw new AudioBatchApiError(200, 'INVALID_BATCH_SUMMARY_RESPONSE', false);
    }
  }
  if (payload.summaries !== undefined
    && (!payload.summaries || typeof payload.summaries !== 'object' || Array.isArray(payload.summaries))) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_SUMMARY_RESPONSE', false);
  }
  if (!Array.isArray(payload.source_manifest)
    || payload.source_manifest.length < 1
    || payload.source_manifest.length > AUDIO_BATCH_MAX_FILES
    || payload.source_manifest.some((source, index) => (
      source.position !== index
      || typeof source.task_id !== 'string'
      || source.task_id.length === 0
      || typeof source.filename !== 'string'
      || source.filename.length === 0
    ))
    || new Set(payload.source_manifest.map(source => source.task_id)).size !== payload.source_manifest.length
    || typeof payload.user_prompt_applied !== 'boolean'
    || (payload.error !== null && (
      typeof payload.error !== 'object'
      || !SAFE_ERROR_CODE_PATTERN.test(payload.error.code)
      || typeof payload.error.retryable !== 'boolean'
    ))) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_SUMMARY_RESPONSE', false);
  }
  return payload;
}

function requireAudioBatchAccepted(
  payload: AudioBatchAcceptedResponse,
  expectedBatchId: string,
): AudioBatchAcceptedResponse {
  if (!UUID_PATTERN.test(payload.batch_id)
    || payload.batch_id !== expectedBatchId
    || !AUDIO_BATCH_STATUSES.includes(payload.status)) {
    throw new AudioBatchApiError(200, 'INVALID_BATCH_RESPONSE', false);
  }
  return payload;
}

export function createAudioBatchIdempotencyKey(): string {
  const randomPart = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `web-${randomPart}`;
}

export async function createAudioBatch(input: CreateAudioBatchInput): Promise<AudioBatchResponse> {
  if (input.files.length === 0) {
    throw new AudioBatchApiError(0, 'BATCH_FILES_REQUIRED', false);
  }
  const formData = new FormData();
  input.files.forEach(file => formData.append('files[]', file, file.name));
  formData.append('case_id', input.caseId);
  formData.append('idempotency_key', input.idempotencyKey);
  const response = await apiFetch(`${API_BASE_URL}/api/v1/audio/v2/batches`, {
    method: 'POST',
    body: formData,
  });
  return requireAudioBatchResponse(await readBatchResponse<AudioBatchResponse>(response));
}

export async function getAudioBatch(batchId: string): Promise<AudioBatchResponse> {
  const response = await apiFetch(`${API_BASE_URL}/api/v1/audio/v2/batches/${encodeURIComponent(batchId)}`);
  return requireAudioBatchResponse(await readBatchResponse<AudioBatchResponse>(response), batchId);
}

export async function transcribeAudioBatch(
  batchId: string,
  options: BatchTranscriptionOptions,
): Promise<AudioBatchAcceptedResponse> {
  const taskIds = options.task_ids.map(taskId => taskId.trim()).filter(Boolean);
  if (taskIds.length === 0 || new Set(taskIds).size !== taskIds.length) {
    throw new AudioBatchApiError(0, 'BATCH_TRANSCRIBE_TASKS_INVALID', false);
  }
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/audio/v2/batches/${encodeURIComponent(batchId)}/transcribe`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...options, task_ids: taskIds }),
    },
  );
  return requireAudioBatchAccepted(
    await readBatchResponse<AudioBatchAcceptedResponse>(response),
    batchId,
  );
}

export async function submitAudioBatchSummary(
  batchId: string,
  input: AudioBatchSummaryRequest,
): Promise<AudioBatchSummaryJob> {
  const taskIds = input.task_ids.map(taskId => taskId.trim()).filter(Boolean);
  if (taskIds.length === 0 || new Set(taskIds).size !== taskIds.length) {
    throw new AudioBatchApiError(0, 'BATCH_SUMMARY_TASKS_INVALID', false);
  }
  const userPrompt = normalizeSummaryUserPrompt(input.user_prompt);
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/audio/v2/batches/${encodeURIComponent(batchId)}/summary`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...input,
        task_ids: taskIds,
        ...(userPrompt ? { user_prompt: userPrompt } : {}),
      }),
    },
  );
  return requireAudioBatchSummaryJob(
    await readBatchResponse<AudioBatchSummaryJob>(response),
    batchId,
  );
}

export async function getAudioBatchSummary(
  batchId: string,
  summaryJobId: string,
): Promise<AudioBatchSummaryJob> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/audio/v2/batches/${encodeURIComponent(batchId)}`
      + `/summary/${encodeURIComponent(summaryJobId)}`,
  );
  return requireAudioBatchSummaryJob(
    await readBatchResponse<AudioBatchSummaryJob>(response),
    batchId,
    summaryJobId,
  );
}

export async function cancelAudioBatch(batchId: string): Promise<AudioBatchAcceptedResponse> {
  const response = await apiFetch(
    `${API_BASE_URL}/api/v1/audio/v2/batches/${encodeURIComponent(batchId)}/cancel`,
    { method: 'POST' },
  );
  return requireAudioBatchAccepted(
    await readBatchResponse<AudioBatchAcceptedResponse>(response),
    batchId,
  );
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
