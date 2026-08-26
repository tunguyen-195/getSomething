export type AnalysisPreviewState =
  | 'source_preview'
  | 'needs_review'
  | 'failed'
  | 'missing';

export interface AnalysisEvidence {
  evidence_id: string;
  quote: string;
  segment_index?: number;
  start_seconds?: number;
  end_seconds?: number;
  speaker_id?: string;
}

export interface AnalysisFact {
  id: string;
  category: string;
  statement: string;
  status: string;
  verification_status: string;
  evidence: AnalysisEvidence[];
}

export interface AnalysisParticipant {
  id: string;
  name: string;
  role?: string;
  description?: string;
  speaker_id?: string;
  evidence: AnalysisEvidence[];
}

export interface AnalysisEntity {
  id: string;
  type: string;
  value: string;
  role?: string;
  count?: number;
  verification_status: string;
  evidence: AnalysisEvidence[];
}

export interface AnalysisEvent {
  id: string;
  description: string;
  status: string;
  described_time?: string;
  actors: string[];
  location?: string;
  evidence: AnalysisEvidence[];
}

export interface AnalysisAction {
  id: string;
  description: string;
  kind: 'action' | 'decision' | 'commitment' | 'follow_up';
  actor?: string;
  target?: string;
  assignee?: string;
  deadline?: string;
  reason?: string;
  priority?: string;
  status: string;
  evidence: AnalysisEvidence[];
}

export interface AnalysisRelationship {
  id: string;
  source: string;
  target: string;
  label: string;
  status: string;
  evidence: AnalysisEvidence[];
}

export interface AnalysisConcern {
  id: string;
  statement: string;
  kind: 'contradiction' | 'uncertainty' | 'open_question';
  details: string[];
  evidence: AnalysisEvidence[];
}

export interface AnalysisInsight {
  id: string;
  kind: 'explicit_role' | 'explicit_relationship' | 'repeated_mention';
  statement: string;
  premise_ids: string[];
  evidence: AnalysisEvidence[];
}

export interface SpeakerContribution {
  speaker: string;
  word_count: number;
  segment_count: number;
  percentage: number;
}

export interface InvestigationAnalysisPreview {
  state: AnalysisPreviewState;
  state_label: string;
  analysis_text?: string;
  overview?: string;
  model_id?: string;
  error_code?: string;
  error_message?: string;
  key_points: string[];
  facts: AnalysisFact[];
  participants: AnalysisParticipant[];
  entities: AnalysisEntity[];
  exact_values: AnalysisEntity[];
  events: AnalysisEvent[];
  actions: AnalysisAction[];
  decisions: AnalysisAction[];
  commitments: AnalysisAction[];
  relationships: AnalysisRelationship[];
  contradictions: AnalysisConcern[];
  uncertainties: AnalysisConcern[];
  follow_ups: AnalysisAction[];
  insights: AnalysisInsight[];
  evidence_spans: AnalysisEvidence[];
  covered_segment_count: number;
  total_segment_count: number;
  gaps: string[];
}

export interface InvestigationVisualizationPreview {
  nodes: Array<{ id: string; label: string; type: string }>;
  edges: Array<{ id: string; source: string; target: string; label: string }>;
  timeline: Array<{ id: string; event: string; time?: string }>;
  speaker_contributions: SpeakerContribution[];
  entity_frequencies: Array<{ label: string; type: string; count: number }>;
  action_statuses: Array<{ status: string; count: number }>;
}

type UnknownRecord = Record<string, unknown>;

const EXACT_VALUE_MARKERS = [
  'account', 'address', 'amount', 'coordinate', 'currency', 'date', 'device',
  'document', 'email', 'identity', 'money', 'phone', 'plate', 'quantity',
  'time', 'url', 'vehicle',
];

function asRecord(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function normalizedText(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized || null;
}

function firstText(record: UnknownRecord, names: string[]): string | null {
  for (const name of names) {
    const value = normalizedText(record[name]);
    if (value) return value;
  }
  return null;
}

function safeNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

function records(value: unknown): UnknownRecord[] {
  return Array.isArray(value)
    ? value.flatMap(item => {
      const record = asRecord(item);
      return record ? [record] : [];
    })
    : [];
}

function textItems(value: unknown, names: string[] = []): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => {
    const direct = normalizedText(item);
    if (direct) return [direct];
    const record = asRecord(item);
    const nested = record ? firstText(record, names) : null;
    return nested ? [nested] : [];
  });
}

function stringArray(value: unknown): string[] {
  return textItems(value);
}

function evidenceMap(value: unknown): Map<string, AnalysisEvidence> {
  const result = new Map<string, AnalysisEvidence>();
  records(value).forEach((item, index) => {
    const evidenceId = firstText(item, ['evidence_id', 'id']) || `evidence-${index}`;
    const quote = firstText(item, ['quote', 'evidence_quote', 'text']);
    if (!quote || result.has(evidenceId)) return;
    const evidence: AnalysisEvidence = { evidence_id: evidenceId, quote };
    const segmentIndex = safeNumber(item.segment_index);
    const startSeconds = safeNumber(item.start_seconds ?? item.start);
    const endSeconds = safeNumber(item.end_seconds ?? item.end);
    const speakerId = firstText(item, ['speaker_id', 'speaker']);
    if (segmentIndex !== undefined) evidence.segment_index = segmentIndex;
    if (startSeconds !== undefined) evidence.start_seconds = startSeconds;
    if (endSeconds !== undefined) evidence.end_seconds = endSeconds;
    if (speakerId) evidence.speaker_id = speakerId;
    result.set(evidenceId, evidence);
  });
  return result;
}

function inlineEvidence(record: UnknownRecord, id: string): AnalysisEvidence[] {
  const quote = firstText(record, ['evidence_quote', 'quote']);
  if (!quote) return [];
  return [{ evidence_id: `inline:${id}`, quote }];
}

function resolveEvidence(
  record: UnknownRecord,
  evidenceById: Map<string, AnalysisEvidence>,
  id: string,
): AnalysisEvidence[] {
  const ids = stringArray(record.evidence_ids);
  const resolved = ids.flatMap(evidenceId => {
    const evidence = evidenceById.get(evidenceId);
    return evidence ? [evidence] : [];
  });
  return resolved.length > 0 ? resolved : inlineEvidence(record, id);
}

function hasDanglingEvidence(
  record: UnknownRecord,
  evidenceById: Map<string, AnalysisEvidence>,
): boolean {
  const ids = stringArray(record.evidence_ids);
  return ids.length > 0 && ids.some(id => !evidenceById.has(id));
}

function exactValue(entity: AnalysisEntity): boolean {
  const type = entity.type.toLocaleLowerCase('en');
  return EXACT_VALUE_MARKERS.some(marker => type.includes(marker));
}

function isRejected(record: UnknownRecord): boolean {
  return record.verification_status === 'rejected';
}

function uniqueBy<T>(items: T[], key: (item: T) => string): T[] {
  return [...new Map(items.map(item => [key(item), item])).values()];
}

function listFromAliases(root: UnknownRecord, aliases: string[]): unknown[] {
  return aliases.flatMap(alias => Array.isArray(root[alias]) ? root[alias] as unknown[] : []);
}

function normalizeParticipants(root: UnknownRecord, evidence: Map<string, AnalysisEvidence>): AnalysisParticipant[] {
  return listFromAliases(root, ['participants', 'speakers']).flatMap((item, index) => {
    const record = asRecord(item);
    if (!record) return [];
    const name = firstText(record, ['name', 'label', 'participant', 'speaker']);
    if (!name) return [];
    const id = firstText(record, ['id', 'participant_id']) || `participant-${index}`;
    const role = firstText(record, ['role']);
    const description = firstText(record, ['description']);
    const speakerId = firstText(record, ['speaker_id']);
    return [{
      id,
      name,
      ...(role ? { role } : {}),
      ...(description ? { description } : {}),
      ...(speakerId ? { speaker_id: speakerId } : {}),
      evidence: resolveEvidence(record, evidence, id),
    }];
  });
}

function normalizeFacts(root: UnknownRecord, evidence: Map<string, AnalysisEvidence>): AnalysisFact[] {
  return records(root.facts).flatMap((record, index) => {
    if (isRejected(record) || hasDanglingEvidence(record, evidence)) return [];
    const statement = firstText(record, ['statement', 'text', 'description']);
    if (!statement) return [];
    const id = firstText(record, ['id', 'fact_id']) || `fact-${index}`;
    return [{
      id,
      category: firstText(record, ['category', 'type']) || 'fact',
      statement,
      status: firstText(record, ['status']) || 'reported',
      verification_status: firstText(record, ['verification_status']) || 'unverified',
      evidence: resolveEvidence(record, evidence, id),
    }];
  });
}

function normalizeEntities(root: UnknownRecord, evidence: Map<string, AnalysisEvidence>): AnalysisEntity[] {
  return records(root.entities).flatMap((record, index) => {
    if (isRejected(record) || hasDanglingEvidence(record, evidence)) return [];
    const value = firstText(record, ['value', 'name', 'label']);
    if (!value) return [];
    const id = firstText(record, ['id', 'entity_id']) || `entity-${index}`;
    const role = firstText(record, ['role', 'description']);
    return [{
      id,
      type: firstText(record, ['type', 'entity_type', 'category']) || 'entity',
      value,
      ...(role ? { role } : {}),
      ...(safeNumber(record.count) !== undefined ? { count: safeNumber(record.count) } : {}),
      verification_status: firstText(record, ['verification_status']) || 'unverified',
      evidence: resolveEvidence(record, evidence, id),
    }];
  });
}

function normalizeEvents(root: UnknownRecord, evidence: Map<string, AnalysisEvidence>): AnalysisEvent[] {
  return listFromAliases(root, ['events', 'timeline']).flatMap((item, index) => {
    const record = asRecord(item);
    if (!record || isRejected(record) || hasDanglingEvidence(record, evidence)) return [];
    const description = firstText(record, ['description', 'event', 'statement', 'text']);
    if (!description) return [];
    const id = firstText(record, ['id', 'event_id']) || `event-${index}`;
    const describedTime = firstText(record, ['time', 'time_text', 'described_time', 'date']);
    const location = firstText(record, ['location', 'place']);
    return [{
      id,
      description,
      status: firstText(record, ['status']) || 'reported',
      actors: stringArray(record.actors ?? record.participants),
      ...(describedTime ? { described_time: describedTime } : {}),
      ...(location ? { location } : {}),
      evidence: resolveEvidence(record, evidence, id),
    }];
  });
}

function normalizeActions(
  root: UnknownRecord,
  aliases: string[],
  kind: AnalysisAction['kind'],
  evidence: Map<string, AnalysisEvidence>,
): AnalysisAction[] {
  return listFromAliases(root, aliases).flatMap((item, index) => {
    const direct = normalizedText(item);
    const record = asRecord(item);
    const description = direct || (record && firstText(record, [
      'description', 'action', 'decision', 'commitment', 'task', 'statement', 'text', 'question',
    ]));
    if (!description) return [];
    const id = (record && firstText(record, ['id', `${kind}_id`])) || `${kind}-${index}`;
    return [{
      id,
      description,
      kind,
      ...(record && firstText(record, ['actor', 'owner']) ? { actor: firstText(record, ['actor', 'owner']) as string } : {}),
      ...(record && firstText(record, ['target']) ? { target: firstText(record, ['target']) as string } : {}),
      ...(record && firstText(record, ['assignee', 'responsible']) ? { assignee: firstText(record, ['assignee', 'responsible']) as string } : {}),
      ...(record && firstText(record, ['deadline', 'due_date', 'time']) ? { deadline: firstText(record, ['deadline', 'due_date', 'time']) as string } : {}),
      ...(record && firstText(record, ['reason']) ? { reason: firstText(record, ['reason']) as string } : {}),
      ...(record && firstText(record, ['priority']) ? { priority: firstText(record, ['priority']) as string } : {}),
      status: (record && firstText(record, ['status'])) || (kind === 'follow_up' ? 'open' : 'reported'),
      evidence: record ? resolveEvidence(record, evidence, id) : [],
    }];
  });
}

function normalizeRelationships(root: UnknownRecord, evidence: Map<string, AnalysisEvidence>): AnalysisRelationship[] {
  return records(root.relationships).flatMap((record, index) => {
    if (isRejected(record) || hasDanglingEvidence(record, evidence)) return [];
    const source = firstText(record, ['source', 'from']);
    const target = firstText(record, ['target', 'to']);
    const label = firstText(record, ['label', 'relationship', 'type', 'description']);
    if (!source || !target || !label) return [];
    const id = firstText(record, ['id', 'relationship_id']) || `relationship-${index}`;
    return [{
      id,
      source,
      target,
      label,
      status: firstText(record, ['status']) || 'reported',
      evidence: resolveEvidence(record, evidence, id),
    }];
  });
}

function normalizeConcerns(
  root: UnknownRecord,
  aliases: string[],
  kind: AnalysisConcern['kind'],
  evidence: Map<string, AnalysisEvidence>,
): AnalysisConcern[] {
  return listFromAliases(root, aliases).flatMap((item, index) => {
    const direct = normalizedText(item);
    const record = asRecord(item);
    const statement = direct || (record && firstText(record, ['statement', 'description', 'question', 'text']));
    if (!statement) return [];
    const id = (record && firstText(record, ['id', `${kind}_id`])) || `${kind}-${index}`;
    return [{
      id,
      statement,
      kind,
      details: record ? stringArray(record.items) : [],
      evidence: record ? resolveEvidence(record, evidence, id) : [],
    }];
  });
}

function buildInsights(
  entities: AnalysisEntity[],
  relationships: AnalysisRelationship[],
): AnalysisInsight[] {
  const insights: AnalysisInsight[] = [];
  entities.forEach(entity => {
    if (entity.role) {
      insights.push({
        id: `role:${entity.id}`,
        kind: 'explicit_role',
        statement: `${entity.value} được nhắc với vai trò: ${entity.role}.`,
        premise_ids: [entity.id],
        evidence: entity.evidence,
      });
    }
    if (entity.evidence.length > 1) {
      insights.push({
        id: `repeat:${entity.id}`,
        kind: 'repeated_mention',
        statement: `${entity.value} xuất hiện trong ${entity.evidence.length} phần nội dung khác nhau.`,
        premise_ids: [entity.id],
        evidence: entity.evidence,
      });
    }
  });
  relationships.forEach(relationship => insights.push({
    id: `relationship:${relationship.id}`,
    kind: 'explicit_relationship',
    statement: `${relationship.source} - ${relationship.label} -> ${relationship.target}.`,
    premise_ids: [relationship.id],
    evidence: relationship.evidence,
  }));
  return insights;
}

function emptyPreview(): InvestigationAnalysisPreview {
  return {
    state: 'missing',
    state_label: 'Chưa chạy',
    key_points: [], facts: [], participants: [], entities: [], exact_values: [], events: [],
    actions: [], decisions: [], commitments: [], relationships: [], contradictions: [],
    uncertainties: [], follow_ups: [], insights: [], evidence_spans: [],
    covered_segment_count: 0, total_segment_count: 0, gaps: [],
  };
}

export function analysisContextFromTask(value: unknown): unknown {
  const task = asRecord(value);
  const result = asRecord(task?.result);
  return task?.context_analysis
    ?? task?.analysis
    ?? result?.context_analysis
    ?? result?.analysis
    ?? result?.context
    ?? null;
}

export function projectInvestigationAnalysis(value: unknown): InvestigationAnalysisPreview {
  const root = asRecord(value);
  if (!root) return emptyPreview();

  const nestedKnowledge = asRecord(root.investigation_knowledge);
  const content = nestedKnowledge || asRecord(root.analysis) || root;
  const evidenceById = evidenceMap(content.evidence_spans ?? root.evidence_spans);
  const facts = normalizeFacts(content, evidenceById);
  const participants = normalizeParticipants(content, evidenceById);
  const allEntities = normalizeEntities(content, evidenceById);
  const exactValues = allEntities.filter(exactValue);
  const entities = allEntities.filter(entity => !exactValue(entity));
  const events = normalizeEvents(content, evidenceById);
  const actions = normalizeActions(content, ['actions'], 'action', evidenceById);
  const decisions = normalizeActions(content, ['decisions'], 'decision', evidenceById);
  const commitments = normalizeActions(content, ['commitments'], 'commitment', evidenceById);
  const followUps = normalizeActions(content, ['follow_ups', 'followups', 'next_steps'], 'follow_up', evidenceById);
  const relationships = normalizeRelationships(content, evidenceById);
  const contradictions = normalizeConcerns(content, ['contradictions'], 'contradiction', evidenceById);
  const uncertainties = normalizeConcerns(content, ['uncertainties', 'open_questions'], 'uncertainty', evidenceById);
  const metrics = asRecord(root.metrics) || asRecord(content.metrics);
  const provenance = asRecord(content.provenance);
  const modelId = firstText(provenance || {}, ['model_id']);
  const totalSegmentCount = safeNumber(metrics?.total_segment_count ?? provenance?.transcript_segment_count) ?? 0;
  const evidenceSpans = uniqueBy([
    ...evidenceById.values(),
    ...facts.flatMap(item => item.evidence),
    ...allEntities.flatMap(item => item.evidence),
    ...events.flatMap(item => item.evidence),
    ...actions.flatMap(item => item.evidence),
    ...decisions.flatMap(item => item.evidence),
    ...commitments.flatMap(item => item.evidence),
    ...relationships.flatMap(item => item.evidence),
  ], item => item.evidence_id);
  const coveredFromEvidence = new Set(evidenceSpans.flatMap(item => (
    item.segment_index === undefined ? [] : [item.segment_index]
  ))).size;
  const coveredSegmentCount = safeNumber(metrics?.covered_segment_count) ?? coveredFromEvidence;
  const analysisText = firstText(root, ['analysis_text', 'raw_analysis_text', 'text'])
    || firstText(content, ['analysis_text', 'raw_analysis_text']);
  const overview = firstText(content, ['overview', 'summary']) || firstText(root, ['overview']);
  const keyPoints = uniqueBy([
    ...textItems(content.key_points, ['statement', 'text', 'description']),
    ...facts.filter(item => item.category === 'key_point').map(item => item.statement),
  ], item => item.toLocaleLowerCase('vi-VN'));
  const status = normalizedText(root.analysis_status ?? content.analysis_status);
  const hasContent = Boolean(
    analysisText || overview || keyPoints.length || facts.length || participants.length || allEntities.length
    || events.length || actions.length || decisions.length || commitments.length || relationships.length
    || contradictions.length || uncertainties.length || followUps.length,
  );
  const state: AnalysisPreviewState = status === 'failed' && !hasContent
    ? 'failed'
    : hasContent
      ? 'source_preview'
      : 'missing';
  const error = asRecord(root.error);
  const gaps = textItems(content.gaps ?? root.gaps, ['statement', 'description', 'text']);
  if (totalSegmentCount > coveredSegmentCount && coveredSegmentCount > 0) {
    gaps.push(`${totalSegmentCount - coveredSegmentCount}/${totalSegmentCount} phần hội thoại chưa được mô hình hóa.`);
  }

  return {
    state,
    state_label: state === 'source_preview'
        ? 'Phân tích sơ bộ - chưa xác nhận'
      : state === 'failed'
        ? 'Không thể hoàn tất phân tích'
        : 'Chưa chạy',
    ...(analysisText ? { analysis_text: analysisText } : {}),
    ...(overview ? { overview } : {}),
    ...(modelId ? { model_id: modelId } : {}),
    ...(firstText(error || {}, ['code']) ? { error_code: firstText(error || {}, ['code']) as string } : {}),
    ...(firstText(error || {}, ['message']) ? { error_message: firstText(error || {}, ['message']) as string } : {}),
    key_points: keyPoints,
    facts: facts.filter(item => item.category !== 'key_point' && !item.category.startsWith('exact_value.')),
    participants,
    entities,
    exact_values: exactValues,
    events,
    actions,
    decisions,
    commitments,
    relationships,
    contradictions,
    uncertainties,
    follow_ups: followUps,
    insights: buildInsights(entities, relationships),
    evidence_spans: evidenceSpans,
    covered_segment_count: coveredSegmentCount,
    total_segment_count: totalSegmentCount,
    gaps: uniqueBy(gaps, item => item.toLocaleLowerCase('vi-VN')),
  };
}

function segmentWords(value: unknown): number {
  const content = normalizedText(value);
  return content ? content.split(/\s+/u).length : 0;
}

export function deriveSpeakerContributions(segments: unknown): SpeakerContribution[] {
  const counts = new Map<string, { word_count: number; segment_count: number }>();
  records(segments).forEach(record => {
    const words = segmentWords(record.text ?? record.transcript);
    if (!words) return;
    const speaker = firstText(record, ['speaker', 'speaker_id']) || 'Chưa xác định';
    const current = counts.get(speaker) || { word_count: 0, segment_count: 0 };
    current.word_count += words;
    current.segment_count += 1;
    counts.set(speaker, current);
  });
  const total = [...counts.values()].reduce((sum, item) => sum + item.word_count, 0);
  return [...counts.entries()]
    .map(([speaker, item]) => ({
      speaker,
      ...item,
      percentage: total > 0 ? Math.round((item.word_count / total) * 100) : 0,
    }))
    .sort((left, right) => right.word_count - left.word_count);
}

export function buildInvestigationVisualization(value: unknown): InvestigationVisualizationPreview {
  const task = asRecord(value);
  const result = asRecord(task?.result);
  const analysis = projectInvestigationAnalysis(analysisContextFromTask(value) ?? value);
  const nodes: InvestigationVisualizationPreview['nodes'] = [];
  const nodeByLabel = new Map<string, string>();

  const addNode = (id: string, label: string, type: string): string => {
    const normalized = label.toLocaleLowerCase('vi-VN');
    const existing = nodeByLabel.get(normalized);
    if (existing) return existing;
    let safeId = id;
    while (nodes.some(node => node.id === safeId)) safeId = `${safeId}-1`;
    nodeByLabel.set(normalized, safeId);
    nodes.push({ id: safeId, label, type });
    return safeId;
  };

  analysis.participants.forEach(item => addNode(item.id, item.name, 'participant'));
  [...analysis.entities, ...analysis.exact_values].forEach(item => addNode(item.id, item.value, item.type));
  const edges = analysis.relationships.map(item => ({
    id: item.id,
    source: addNode(`source-${item.id}`, item.source, 'entity'),
    target: addNode(`target-${item.id}`, item.target, 'entity'),
    label: item.label,
  }));
  const frequencies = new Map<string, { label: string; type: string; count: number }>();
  [...analysis.entities, ...analysis.exact_values].forEach(item => {
    const key = `${item.type}\u0000${item.value.toLocaleLowerCase('vi-VN')}`;
    const current = frequencies.get(key) || { label: item.value, type: item.type, count: 0 };
    current.count += item.count ?? Math.max(1, item.evidence.length);
    frequencies.set(key, current);
  });
  const statuses = new Map<string, number>();
  [...analysis.actions, ...analysis.decisions, ...analysis.commitments, ...analysis.follow_ups].forEach(item => {
    statuses.set(item.status, (statuses.get(item.status) || 0) + 1);
  });

  const contextRoot = asRecord(analysisContextFromTask(value));
  const metrics = asRecord(contextRoot?.metrics);
  // Direct-text analysis stores this projection at the top level; older
  // payloads put it below metrics. Accept both shapes so visualization is
  // compatible with persisted tasks from either release.
  const suppliedSpeakerContributions = records(
    contextRoot?.speaker_contributions ?? metrics?.speaker_contributions,
  ).flatMap(record => {
    const speaker = firstText(record, ['speaker', 'speaker_id']);
    const wordCount = safeNumber(record.word_count);
    const segmentCount = safeNumber(record.segment_count);
    const explicitPercentage = safeNumber(record.percentage);
    const wordShare = safeNumber(record.word_share);
    const percentage = explicitPercentage
      ?? (wordShare !== undefined
        ? (wordShare <= 1 ? Math.round(wordShare * 100) : Math.round(wordShare))
        : undefined);
    if (!speaker || wordCount === undefined || segmentCount === undefined) return [];
    return [{
      speaker,
      word_count: wordCount,
      segment_count: segmentCount,
      percentage: percentage ?? 0,
    }];
  });
  if (suppliedSpeakerContributions.length > 0) {
    const totalWords = suppliedSpeakerContributions.reduce(
      (total, item) => total + item.word_count,
      0,
    );
    suppliedSpeakerContributions.forEach(item => {
      if (item.percentage === 0 && totalWords > 0) {
        item.percentage = Math.round((item.word_count / totalWords) * 100);
      }
    });
  }

  return {
    nodes,
    edges,
    timeline: analysis.events.map(item => ({
      id: item.id,
      event: item.description,
      ...(item.described_time ? { time: item.described_time } : {}),
    })),
    speaker_contributions: suppliedSpeakerContributions.length > 0
      ? suppliedSpeakerContributions
      : deriveSpeakerContributions(task?.segments ?? result?.segments ?? []),
    entity_frequencies: [...frequencies.values()].sort((left, right) => right.count - left.count),
    action_statuses: [...statuses.entries()]
      .map(([status, count]) => ({ status, count }))
      .sort((left, right) => right.count - left.count),
  };
}
