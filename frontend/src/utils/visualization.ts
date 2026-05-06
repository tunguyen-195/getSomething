export type LegacyVisualizationData = {
  nodes?: Array<Record<string, any>>;
  edges?: Array<Record<string, any>>;
  timeline?: Array<Record<string, any>>;
  main_events?: string[];
  entity_types?: string[];
  extracted_entities?: Array<Record<string, any>>;
  [key: string]: any;
};

export type EvidenceRef = {
  source_kind?: string;
  text_span?: string;
  char_start?: number;
  char_end?: number;
  audio_id?: number | string | null;
  segment_id?: string | null;
  start_time?: number | null;
  end_time?: number | null;
  speaker_id?: string | null;
  source_text_sha256?: string;
};

export type EvidenceItem = {
  id: string;
  type: string;
  label: string;
  value?: string | null;
  confidence?: number;
  confidence_reason?: string;
  source_method?: string;
  review_status?: string;
  requires_review?: boolean;
  evidence_refs?: EvidenceRef[];
  [key: string]: any;
};

export type RelationItem = EvidenceItem & {
  source_entity_id?: string;
  target_entity_id?: string;
};

export type SegmentUnit = {
  id: string;
  text?: string;
  speaker_id?: string | null;
  start_time?: number | null;
  end_time?: number | null;
  [key: string]: any;
};

export type AnalysisGraphV2 = {
  schema_version: 'analysis_intelligence.v2';
  graph_revision?: number;
  task_id?: string | null;
  audio_id?: number | string | null;
  source_file?: string | null;
  segments?: SegmentUnit[];
  entities?: EvidenceItem[];
  relations?: RelationItem[];
  events?: EvidenceItem[];
  claims?: EvidenceItem[];
  facts?: EvidenceItem[];
  risk_flags?: EvidenceItem[];
  slots?: EvidenceItem[];
  insight_items?: EvidenceItem[];
  insights?: string[];
  key_items?: Array<Record<string, any>>;
  visibility?: {
    visible_item_ids?: string[];
    blocked_item_ids?: string[];
    blocked_reasons?: Record<string, string[]>;
  };
  display_sections_vi?: Array<{
    id: string;
    title_vi: string;
    kind: string;
    item_ids?: string[];
    items?: Array<Record<string, any>>;
  }>;
  legacy_view?: LegacyVisualizationData;
  [key: string]: any;
};

export type KeyEntity = {
  type: string;
  value: string;
  context?: string;
};

export const stringifyAnalysisValue = (value: any): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (typeof value === 'object') {
    if ('amount_vnd' in value && value.amount_vnd) {
      return `${Number(value.amount_vnd).toLocaleString('vi-VN')} VND`;
    }
    if ('quantity' in value && 'unit' in value) {
      return `${value.quantity} ${value.unit}`;
    }
    if ('day' in value && 'month' in value) {
      const year = value.year ? `/${value.year}` : '';
      return `${value.day}/${value.month}${year}`;
    }
    if ('start' in value && 'end' in value) {
      return `${stringifyAnalysisValue(value.start)} - ${stringifyAnalysisValue(value.end)}`;
    }
    return JSON.stringify(value);
  }
  return String(value);
};

export const isAnalysisGraphV2 = (data?: unknown): data is AnalysisGraphV2 => (
  Boolean(data)
  && typeof data === 'object'
  && (data as { schema_version?: string }).schema_version === 'analysis_intelligence.v2'
);

export const getCanonicalAnalysisGraph = (data?: unknown): AnalysisGraphV2 | null => (
  isAnalysisGraphV2(data) ? data : null
);

export const getLegacyVisualizationData = <T extends LegacyVisualizationData>(
  data?: (T & { legacy_view?: T }) | null,
): T => {
  if (!data) {
    return {} as T;
  }
  if (data.legacy_view && typeof data.legacy_view === 'object') {
    return data.legacy_view;
  }
  return data;
};

const KEY_ENTITY_TYPES = new Set([
  'phone',
  'email',
  'email_candidate',
  'id_number_candidate',
  'money',
  'money_range',
  'date',
  'date_range',
  'date_time',
  'time',
  'quantity',
  'payment_method',
  'purpose',
  'person',
  'person_name',
  'organization',
  'location',
  'address',
]);

export const getKeyEntities = (data?: AnalysisGraphV2 | LegacyVisualizationData | null): KeyEntity[] => {
  if (!data) {
    return [];
  }

  if (isAnalysisGraphV2(data)) {
    const blockedIds = new Set(data.visibility?.blocked_item_ids || []);
    const canonical = Array.isArray(data.key_items) && data.key_items.length > 0
      ? data.key_items
      : (Array.isArray(data.legacy_view?.extracted_entities) ? data.legacy_view.extracted_entities : []);
    if (canonical.length > 0) {
      return canonical
        .filter(item => item.review_status !== 'rejected')
        .filter(item => !blockedIds.has(String(item.id || '')))
        .filter(item => KEY_ENTITY_TYPES.has(String(item.type || '').toLowerCase()))
        .map(item => ({
          type: String(item.type || 'entity'),
          value: stringifyAnalysisValue(item.value || item.normalized_value || item.label_vi || item.label),
          context: item.context || item.source_item_type,
        }))
        .filter(item => item.value);
    }

    const canonicalItems = [
      ...(data.entities || []),
      ...(data.facts || []),
      ...(data.slots || []),
    ];
    return canonicalItems
      .filter(item => item.review_status !== 'rejected')
      .filter(item => !blockedIds.has(item.id))
      .filter(item => KEY_ENTITY_TYPES.has(String(item.type || '').toLowerCase()))
      .map(item => ({
        type: String(item.type || 'entity'),
        value: stringifyAnalysisValue(item.value || item.normalized_value || item.label_vi || item.label),
        context: item.source_method || item.confidence_reason,
      }))
      .filter(item => item.value);
  }

  const legacy = getLegacyVisualizationData(data);
  return (legacy.extracted_entities || [])
    .filter(item => KEY_ENTITY_TYPES.has(String(item.type || '').toLowerCase()))
    .map(item => ({
      type: String(item.type || 'entity'),
      value: String(item.value || item.label || ''),
      context: item.context,
    }))
    .filter(item => item.value);
};
