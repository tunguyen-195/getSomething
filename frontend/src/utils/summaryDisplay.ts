const LEGACY_PREVIEW_HEADERS = new Set([
  'bản xem trước evidence transcript - chưa phải tóm tắt điều tra đã phát hành.',
  'bản xem trước evidence transcript - chưa phải tóm tắt điều tra đã phát hành',
  'transcript evidence preview - not a released investigation summary.',
  'transcript evidence preview - not a released investigation summary',
  'transcript evidence preview - not a released investigation narrative.',
  'transcript evidence preview - not a released investigation narrative',
]);

const LEGACY_LINE_PREFIX = /^(?:#{1,6}\s+)?(?:(?:[-*•]|\d+[.)])\s+)?(?:\*\*)?\s*/;

const LEGACY_ATTRIBUTION_MARKER = new RegExp(
  '\\[\\s*(?:audio[\\s_-]*offset|offset[\\s_-]+(?:âm|am)[\\s_-]+thanh)'
    + '\\s*:[^\\]]*\\](?:\\*\\*)?\\s*',
  'ig',
);

const LEGACY_SOURCE_PREFIX = /^(?:nguồn ghi nhận|source(?: record| quote)?)\s*:\s*/i;

function unwrapLegacyQuote(value: string): string {
  const trimmed = value.trim();
  const pairs: Array<[string, string]> = [
    ['"', '"'],
    ['“', '”'],
    ["'", "'"],
  ];
  for (const [left, right] of pairs) {
    if (trimmed.startsWith(left) && trimmed.endsWith(right) && trimmed.length >= 2) {
      return trimmed.slice(left.length, -right.length).trim();
    }
  }
  return trimmed;
}

export function sanitizeSummaryDisplayText(value: unknown): string {
  if (typeof value !== 'string') return '';

  const cleanedLines: string[] = [];
  for (const line of value.split(/\r?\n/)) {
    const cleaned = line.trim();
    if (!cleaned) {
      cleanedLines.push('');
      continue;
    }
    if (LEGACY_PREVIEW_HEADERS.has(cleaned.toLocaleLowerCase('vi-VN'))) continue;

    // Preview v1 could persist multiple attributed excerpts on the same line.
    const prefix = cleaned.match(LEGACY_LINE_PREFIX)?.[0] ?? '';
    const content = cleaned.slice(prefix.length);
    const markers = [...content.matchAll(LEGACY_ATTRIBUTION_MARKER)];
    if (markers.length > 0 && markers[0].index === 0) {
      for (let index = 0; index < markers.length; index += 1) {
        const marker = markers[index];
        const start = (marker.index ?? 0) + marker[0].length;
        const end = index + 1 < markers.length
          ? (markers[index + 1].index ?? content.length)
          : content.length;
        let chunk = content.slice(start, end).trim();
        chunk = chunk.replace(LEGACY_SOURCE_PREFIX, '').replace(/[;|]\s*$/, '');
        chunk = unwrapLegacyQuote(chunk);
        if (chunk) cleanedLines.push(chunk);
      }
      continue;
    }
    if (cleaned) cleanedLines.push(cleaned);
  }

  return cleanedLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

export function summaryDisplayText(file: any): string {
  if (file?.summary_state === 'grounded_transcript_only') return '';
  return sanitizeSummaryDisplayText(file?.summary);
}
