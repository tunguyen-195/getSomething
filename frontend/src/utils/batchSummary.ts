import {
  SUMMARY_TYPES,
} from '../api/client';
import type {
  AudioBatchSummaryJob,
  AudioBatchSummaryResult,
  AudioBatchSummaryStatus,
  AudioBatchSummaryType,
  SafeApiErrorEnvelope,
} from '../api/client';
import { sanitizeSummaryDisplayText } from './summaryDisplay';

export const BATCH_SUMMARY_TYPE_LABELS: Record<AudioBatchSummaryType, string> = {
  brief: 'Tóm tắt ngắn',
  detailed: 'Tóm tắt chi tiết',
  investigation: 'Tóm tắt điều tra',
  forensic: 'Tóm tắt pháp chứng',
};

export const BATCH_SUMMARY_TYPE_DESCRIPTIONS: Record<AudioBatchSummaryType, string> = {
  brief: 'Các ý chính và kết luận ngắn gọn.',
  detailed: 'Diễn biến, thông tin và hành động đầy đủ hơn.',
  investigation: 'Người tham gia, sự kiện, thực thể và điểm cần xác minh.',
  forensic: 'Thông tin theo hướng chứng cứ, nguồn và điểm cần đối chiếu.',
};

export interface BatchSummaryDisplayResult {
  summary_type: AudioBatchSummaryType;
  summary: string;
  status: AudioBatchSummaryStatus | 'missing';
  error: SafeApiErrorEnvelope | null;
}

function isSummaryType(value: unknown): value is AudioBatchSummaryType {
  return typeof value === 'string'
    && (SUMMARY_TYPES as readonly string[]).includes(value);
}

function asSummaryResult(value: unknown, fallbackType?: AudioBatchSummaryType): BatchSummaryDisplayResult | null {
  if (typeof value === 'string') {
    if (!fallbackType) return null;
    const summary = sanitizeSummaryDisplayText(value);
    return {
      summary_type: fallbackType,
      summary,
      status: summary ? 'succeeded' : 'missing',
      error: null,
    };
  }
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  const typeValue = record.summary_type ?? record.type ?? fallbackType;
  if (!isSummaryType(typeValue)) return null;
  const rawSummary = record.summary ?? record.content ?? record.text;
  const summary = typeof rawSummary === 'string' ? sanitizeSummaryDisplayText(rawSummary) : '';
  const rawStatus = record.status;
  const rawState = typeof record.summary_state === 'string' ? record.summary_state : '';
  const rawError = record.error ?? record.summary_error;
  const hasError = Boolean(rawError && typeof rawError === 'object');
  const status = rawStatus === 'queued' || rawStatus === 'processing'
    || rawStatus === 'partially_succeeded' || rawStatus === 'succeeded' || rawStatus === 'failed'
    || rawStatus === 'cancel_requested' || rawStatus === 'cancelled'
    ? rawStatus
    : hasError || /fail|error|unavailable/i.test(rawState) ? 'failed'
    : summary ? 'succeeded' : 'missing';
  const error = rawError && typeof rawError === 'object'
    ? {
      code: typeof (rawError as Record<string, unknown>).code === 'string'
        ? (rawError as Record<string, unknown>).code as string : 'SUMMARY_RESULT_FAILED',
      message: typeof (rawError as Record<string, unknown>).message === 'string'
        ? (rawError as Record<string, unknown>).message as string : 'Summary processing failed.',
      retryable: typeof (rawError as Record<string, unknown>).retryable === 'boolean'
        ? (rawError as Record<string, unknown>).retryable as boolean : false,
    } as SafeApiErrorEnvelope
    : null;
  return { summary_type: typeValue, summary, status, error };
}

/**
 * Normalize both the new `summary_results` projection and rolling-upgrade
 * aliases into one deterministic list. The root `summary` is only used when
 * no typed result for that type was returned, so it can never overwrite a
 * separately persisted variant.
 */
export function normalizeBatchSummaryResults(
  job: Pick<AudioBatchSummaryJob, 'summary' | 'summary_type' | 'summary_results' | 'summaries' | 'summary_variants'>,
): BatchSummaryDisplayResult[] {
  const byType = new Map<AudioBatchSummaryType, BatchSummaryDisplayResult>();
  const add = (candidate: BatchSummaryDisplayResult | null) => {
    if (!candidate || byType.has(candidate.summary_type)) return;
    byType.set(candidate.summary_type, candidate);
  };

  if (Array.isArray(job.summary_results)) {
    job.summary_results.forEach(result => add(asSummaryResult(result)));
  }
  if (job.summaries && typeof job.summaries === 'object') {
    Object.entries(job.summaries).forEach(([type, value]) => {
      if (isSummaryType(type)) add(asSummaryResult(value, type));
    });
  }
  if (job.summary_variants && typeof job.summary_variants === 'object') {
    Object.entries(job.summary_variants).forEach(([type, value]) => {
      if (isSummaryType(type)) add(asSummaryResult(value, type));
    });
  }
  if (isSummaryType(job.summary_type)) {
    add(asSummaryResult(job.summary, job.summary_type));
  }
  // Old API responses had no type. Treat them as detailed for display only.
  if (byType.size === 0) add(asSummaryResult(job.summary, 'detailed'));

  return Array.from(byType.values()).sort(
    (left, right) => SUMMARY_TYPES.indexOf(left.summary_type) - SUMMARY_TYPES.indexOf(right.summary_type),
  );
}

export function batchSummaryTypeLabel(type: AudioBatchSummaryType): string {
  return BATCH_SUMMARY_TYPE_LABELS[type];
}

export function hasUsableBatchSummaryResult(result: BatchSummaryDisplayResult): boolean {
  return (result.status === 'succeeded' || result.status === 'partially_succeeded')
    && Boolean(result.summary.trim());
}

// Keep the imported result type visible to consumers that only import this helper.
export type { AudioBatchSummaryResult };
