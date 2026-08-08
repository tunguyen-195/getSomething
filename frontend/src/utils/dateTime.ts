export const DISPLAY_TIME_ZONE = (
  Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Ho_Chi_Minh'
);

const API_NAIVE_DATE_TIME = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;
const API_DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const HAS_TIME_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;

const displayFormatter = new Intl.DateTimeFormat('vi-VN', {
  timeZone: DISPLAY_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

export interface FormattedDateTime {
  display: string;
  iso: string;
  epochMs: number;
}

const normalizeApiTimestamp = (value: string): string => {
  if (HAS_TIME_ZONE.test(value)) {
    return value;
  }

  // Legacy database fields are local wall-clock values without an offset.
  if (API_NAIVE_DATE_TIME.test(value)) {
    return value.replace(' ', 'T');
  }

  if (API_DATE_ONLY.test(value)) {
    return `${value}T00:00:00`;
  }

  return value;
};

export const formatApiDateTime = (value?: string | null): FormattedDateTime | null => {
  const source = value?.trim();
  if (!source) {
    return null;
  }

  const date = new Date(normalizeApiTimestamp(source));
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  const parts = Object.fromEntries(
    displayFormatter
      .formatToParts(date)
      .filter(part => part.type !== 'literal')
      .map(part => [part.type, part.value]),
  );

  return {
    display: `${parts.day}/${parts.month}/${parts.year}, ${parts.hour}:${parts.minute}`,
    iso: date.toISOString(),
    epochMs: date.getTime(),
  };
};

export const apiDateTimeToEpoch = (value?: string | null): number => (
  formatApiDateTime(value)?.epochMs ?? 0
);
