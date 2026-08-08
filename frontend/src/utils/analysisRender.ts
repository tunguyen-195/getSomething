function formatValue(value: unknown, seen: Set<object>): string {
  if (value == null) return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(item => formatValue(item, seen)).filter(Boolean).join(', ');
  }
  if (typeof value !== 'object') return String(value);
  if (seen.has(value)) return '[circular]';

  seen.add(value);
  const text = Object.entries(value)
    .map(([key, item]) => {
      const itemText = formatValue(item, seen);
      return itemText ? `${key}: ${itemText}` : '';
    })
    .filter(Boolean)
    .join('; ');
  seen.delete(value);
  return text;
}

export function formatAnalysisValue(value: unknown): string {
  return formatValue(value, new Set<object>());
}

export function formatSlangDetected(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return formatAnalysisValue(value);
  }

  const slang = value as { has_slang?: unknown; terms?: unknown };
  const terms = formatAnalysisValue(slang.terms);
  if (terms) return terms;
  if (slang.has_slang === false) return '';
  if (slang.has_slang === true) return 'Có phát hiện tiếng lóng/mật ngữ';
  return formatAnalysisValue(value);
}
