export type VisualizationEpistemicType = 'source_attributed' | 'fact';

export type InvestigationVerificationStatus =
  | 'unverified'
  | 'human_verified'
  | 'rejected';

export interface InvestigationKeyPoint {
  statement: string;
  evidence_ids: string[];
  verification_status: InvestigationVerificationStatus;
  model_generated: boolean;
}

export interface InvestigationSummaryContextProjection {
  investigation_knowledge: {
    facts: Array<InvestigationKeyPoint & { category: 'key_point' }>;
  };
}

export interface ReleasedVisualizationEvidence {
  evidence_id: string;
  segment_id: string;
  quote_exact: string;
  quote_sha256: string;
  source_sha256: string;
  source_revision_id: string;
  start_seconds?: number;
  end_seconds?: number;
  speaker_id?: string;
}

export interface ReleasedVisualizationNode {
  id: string;
  kind: 'claim' | 'concept';
  label: string;
  type: string;
  epistemic_type: VisualizationEpistemicType;
  source_revision_id: string;
  claim_refs: string[];
  evidence: ReleasedVisualizationEvidence[];
  role?: string;
}

export interface ReleasedVisualizationEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  type: string;
  epistemic_type: VisualizationEpistemicType;
  source_revision_id: string;
  claim_refs: string[];
  evidence: ReleasedVisualizationEvidence[];
}

export interface ReleasedVisualizationTimelineItem {
  id: string;
  time: string;
  event: string;
  claim_ref: string;
  epistemic_type: VisualizationEpistemicType;
  source_revision_id: string;
  start_seconds: number;
  end_seconds: number;
  evidence: [ReleasedVisualizationEvidence];
}

export interface ReleasedVisualizationEvent {
  id: string;
  event: string;
  type: string;
  claim_ref: string;
  epistemic_type: VisualizationEpistemicType;
  source_revision_id: string;
  evidence: ReleasedVisualizationEvidence[];
}

export interface ReleasedVisualizationEntity {
  id: string;
  type: string;
  value: string;
  source_revision_id: string;
  claim_refs: string[];
  evidence: ReleasedVisualizationEvidence[];
  context?: string;
}

export interface ReleasedVisualizationArtifact {
  schema_version: 'investigation-visualization-v1';
  authority: 'released_investigation_run';
  run_id: string;
  source_revision_id: string;
  release_subject_sha256: string;
  content_hash: string;
  nodes: ReleasedVisualizationNode[];
  edges: ReleasedVisualizationEdge[];
  timeline: ReleasedVisualizationTimelineItem[];
  main_events: ReleasedVisualizationEvent[];
  extracted_entities: ReleasedVisualizationEntity[];
}

export type ValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

type UnknownRecord = Record<string, unknown>;

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

function asRecord(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function hasExactKeys(
  value: UnknownRecord,
  required: string[],
  optional: string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => Object.prototype.hasOwnProperty.call(value, key))
    && Object.keys(value).every((key) => allowed.has(key));
}

function nonBlankString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text ? text : null;
}

function sha256(value: unknown): string | null {
  const text = nonBlankString(value);
  return text && SHA256_PATTERN.test(text) ? text : null;
}

function nonNegativeNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

function stringArray(value: unknown, minimum = 0): string[] | null {
  if (!Array.isArray(value) || value.length < minimum) return null;
  const result: string[] = [];
  for (const item of value) {
    const text = nonBlankString(item);
    if (!text) return null;
    result.push(text);
  }
  return result;
}

function epistemicType(value: unknown): VisualizationEpistemicType | null {
  return value === 'source_attributed' || value === 'fact' ? value : null;
}

function investigationKnowledge(value: unknown): UnknownRecord | null {
  const root = asRecord(value);
  if (!root) return null;
  return asRecord(root.investigation_knowledge) ?? root;
}

export function selectKeyPointStatements(value: unknown): string[] {
  return selectKeyPoints(value).map((item) => item.statement);
}

export function selectKeyPoints(value: unknown): InvestigationKeyPoint[] {
  const knowledge = investigationKnowledge(value);
  const facts = Array.isArray(knowledge?.facts) ? knowledge.facts : [];
  const selected = new Map<string, InvestigationKeyPoint>();
  for (const fact of facts) {
    const record = asRecord(fact);
    if (record?.category !== 'key_point') continue;
    const statement = nonBlankString(record.statement);
    if (!statement) continue;
    const identity = statement.replace(/\s+/g, ' ').toLocaleLowerCase('vi');
    const evidenceIds = stringArray(record.evidence_ids) ?? [];
    const status: InvestigationVerificationStatus =
      record.verification_status === 'human_verified'
      || record.verification_status === 'rejected'
      || record.verification_status === 'unverified'
        ? record.verification_status
        : 'unverified';
    if (status === 'rejected') continue;
    const existing = selected.get(identity);
    if (existing) {
      existing.evidence_ids = [...new Set([...existing.evidence_ids, ...evidenceIds])];
      existing.verification_status =
        existing.verification_status === 'human_verified'
        && status === 'human_verified'
          ? 'human_verified'
          : 'unverified';
      existing.model_generated = existing.model_generated || record.model_generated === true;
      continue;
    }
    selected.set(identity, {
      statement,
      evidence_ids: evidenceIds,
      verification_status: status,
      model_generated: record.model_generated === true,
    });
  }
  return [...selected.values()];
}

export function projectInvestigationSummaryContext(
  value: unknown,
): InvestigationSummaryContextProjection | null {
  const keyPoints = selectKeyPoints(value);
  if (keyPoints.length === 0) return null;
  return {
    investigation_knowledge: {
      facts: keyPoints.map((item) => ({ ...item, category: 'key_point' as const })),
    },
  };
}

export function selectReleasedInsightStatements(_value: unknown): string[] {
  // Production does not expose a reconstructible reasoning-release authority yet.
  return [];
}

function validateEvidence(
  value: unknown,
  sourceRevisionId: string,
): ReleasedVisualizationEvidence | null {
  const row = asRecord(value);
  const required = [
    'evidence_id',
    'segment_id',
    'quote_exact',
    'quote_sha256',
    'source_sha256',
    'source_revision_id',
  ];
  if (!row || !hasExactKeys(row, required, ['start_seconds', 'end_seconds', 'speaker_id'])) {
    return null;
  }
  const evidenceId = nonBlankString(row.evidence_id);
  const segmentId = nonBlankString(row.segment_id);
  const quoteExact = nonBlankString(row.quote_exact);
  const quoteSha256 = sha256(row.quote_sha256);
  const sourceSha256 = sha256(row.source_sha256);
  const revision = nonBlankString(row.source_revision_id);
  if (!evidenceId || !segmentId || !quoteExact || !quoteSha256 || !sourceSha256 || revision !== sourceRevisionId) {
    return null;
  }

  const result: ReleasedVisualizationEvidence = {
    evidence_id: evidenceId,
    segment_id: segmentId,
    quote_exact: quoteExact,
    quote_sha256: quoteSha256,
    source_sha256: sourceSha256,
    source_revision_id: revision,
  };
  const hasStart = Object.prototype.hasOwnProperty.call(row, 'start_seconds');
  const hasEnd = Object.prototype.hasOwnProperty.call(row, 'end_seconds');
  if (hasStart !== hasEnd) return null;
  if (hasStart) {
    const start = nonNegativeNumber(row.start_seconds);
    if (start === null) return null;
    result.start_seconds = start;
  }
  if (hasEnd) {
    const end = nonNegativeNumber(row.end_seconds);
    if (end === null) return null;
    result.end_seconds = end;
  }
  if (
    result.start_seconds !== undefined
    && result.end_seconds !== undefined
    && result.end_seconds < result.start_seconds
  ) {
    return null;
  }
  if (Object.prototype.hasOwnProperty.call(row, 'speaker_id')) {
    const speaker = nonBlankString(row.speaker_id);
    if (!speaker) return null;
    result.speaker_id = speaker;
  }
  return result;
}

function validateEvidenceArray(
  value: unknown,
  sourceRevisionId: string,
  exactLength?: number,
): ReleasedVisualizationEvidence[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  if (exactLength !== undefined && value.length !== exactLength) return null;
  const result = value.map((item) => validateEvidence(item, sourceRevisionId));
  return result.every((item): item is ReleasedVisualizationEvidence => item !== null)
    ? result
    : null;
}

function validateNodes(
  value: unknown,
  sourceRevisionId: string,
): ValidationResult<ReleasedVisualizationNode[]> {
  if (!Array.isArray(value)) return { ok: false, error: 'nodes must be an array' };
  const nodes: ReleasedVisualizationNode[] = [];
  const ids = new Set<string>();
  const required = [
    'id', 'kind', 'label', 'type', 'epistemic_type', 'source_revision_id',
    'claim_refs', 'evidence',
  ];
  for (const item of value) {
    const row = asRecord(item);
    if (!row || !hasExactKeys(row, required, ['role'])) {
      return { ok: false, error: 'nodes contain an invalid released node' };
    }
    const id = nonBlankString(row.id);
    const kind = row.kind === 'claim' || row.kind === 'concept' ? row.kind : null;
    const label = nonBlankString(row.label);
    const type = nonBlankString(row.type);
    const epistemic = epistemicType(row.epistemic_type);
    const revision = nonBlankString(row.source_revision_id);
    const claimRefs = stringArray(row.claim_refs, 1);
    const evidence = validateEvidenceArray(row.evidence, sourceRevisionId);
    if (!id || !kind || !label || !type || !epistemic || revision !== sourceRevisionId || !claimRefs || !evidence || ids.has(id)) {
      return { ok: false, error: 'nodes contain an invalid released node' };
    }
    ids.add(id);
    const node: ReleasedVisualizationNode = {
      id,
      kind,
      label,
      type,
      epistemic_type: epistemic,
      source_revision_id: revision,
      claim_refs: claimRefs,
      evidence,
    };
    if (Object.prototype.hasOwnProperty.call(row, 'role')) {
      const role = nonBlankString(row.role);
      if (!role) return { ok: false, error: 'nodes contain an invalid role' };
      node.role = role;
    }
    nodes.push(node);
  }
  return { ok: true, value: nodes };
}

function validateEdges(
  value: unknown,
  sourceRevisionId: string,
  nodeIds: Set<string>,
): ValidationResult<ReleasedVisualizationEdge[]> {
  if (!Array.isArray(value)) return { ok: false, error: 'edges must be an array' };
  const edges: ReleasedVisualizationEdge[] = [];
  const required = [
    'id', 'source', 'target', 'label', 'type', 'epistemic_type',
    'source_revision_id', 'claim_refs', 'evidence',
  ];
  for (const item of value) {
    const row = asRecord(item);
    if (!row || !hasExactKeys(row, required)) {
      return { ok: false, error: 'edges contain an invalid released edge' };
    }
    const id = nonBlankString(row.id);
    const source = nonBlankString(row.source);
    const target = nonBlankString(row.target);
    const label = nonBlankString(row.label);
    const type = nonBlankString(row.type);
    const epistemic = epistemicType(row.epistemic_type);
    const revision = nonBlankString(row.source_revision_id);
    const claimRefs = stringArray(row.claim_refs, 1);
    const evidence = validateEvidenceArray(row.evidence, sourceRevisionId);
    if (!id || !source || !target || !label || !type || !epistemic || revision !== sourceRevisionId || !claimRefs || !evidence) {
      return { ok: false, error: 'edges contain an invalid released edge' };
    }
    if (!nodeIds.has(source) || !nodeIds.has(target)) {
      return { ok: false, error: 'edge endpoints must reference released nodes' };
    }
    edges.push({
      id,
      source,
      target,
      label,
      type,
      epistemic_type: epistemic,
      source_revision_id: revision,
      claim_refs: claimRefs,
      evidence,
    });
  }
  return { ok: true, value: edges };
}

function validateTimeline(
  value: unknown,
  sourceRevisionId: string,
): ValidationResult<ReleasedVisualizationTimelineItem[]> {
  if (!Array.isArray(value)) return { ok: false, error: 'timeline must be an array' };
  const timeline: ReleasedVisualizationTimelineItem[] = [];
  const required = [
    'id', 'time', 'event', 'claim_ref', 'epistemic_type', 'source_revision_id',
    'start_seconds', 'end_seconds', 'evidence',
  ];
  for (const item of value) {
    const row = asRecord(item);
    if (!row || !hasExactKeys(row, required)) {
      return { ok: false, error: 'timeline contains an invalid released event' };
    }
    const id = nonBlankString(row.id);
    const time = nonBlankString(row.time);
    const event = nonBlankString(row.event);
    const claimRef = nonBlankString(row.claim_ref);
    const epistemic = epistemicType(row.epistemic_type);
    const revision = nonBlankString(row.source_revision_id);
    const start = nonNegativeNumber(row.start_seconds);
    const end = nonNegativeNumber(row.end_seconds);
    const evidence = validateEvidenceArray(row.evidence, sourceRevisionId, 1);
    if (!id || !time || !event || !claimRef || !epistemic || revision !== sourceRevisionId || start === null || end === null || end < start || !evidence) {
      return { ok: false, error: 'timeline contains an invalid released event' };
    }
    timeline.push({
      id,
      time,
      event,
      claim_ref: claimRef,
      epistemic_type: epistemic,
      source_revision_id: revision,
      start_seconds: start,
      end_seconds: end,
      evidence: [evidence[0]],
    });
  }
  return { ok: true, value: timeline };
}

function validateMainEvents(
  value: unknown,
  sourceRevisionId: string,
): ValidationResult<ReleasedVisualizationEvent[]> {
  if (!Array.isArray(value)) return { ok: false, error: 'main_events must be an array' };
  const events: ReleasedVisualizationEvent[] = [];
  const required = [
    'id', 'event', 'type', 'claim_ref', 'epistemic_type', 'source_revision_id',
    'evidence',
  ];
  for (const item of value) {
    const row = asRecord(item);
    if (!row || !hasExactKeys(row, required)) {
      return { ok: false, error: 'main_events contain an invalid released event' };
    }
    const id = nonBlankString(row.id);
    const event = nonBlankString(row.event);
    const type = nonBlankString(row.type);
    const claimRef = nonBlankString(row.claim_ref);
    const epistemic = epistemicType(row.epistemic_type);
    const revision = nonBlankString(row.source_revision_id);
    const evidence = validateEvidenceArray(row.evidence, sourceRevisionId);
    if (!id || !event || !type || !claimRef || !epistemic || revision !== sourceRevisionId || !evidence) {
      return { ok: false, error: 'main_events contain an invalid released event' };
    }
    events.push({
      id,
      event,
      type,
      claim_ref: claimRef,
      epistemic_type: epistemic,
      source_revision_id: revision,
      evidence,
    });
  }
  return { ok: true, value: events };
}

function validateEntities(
  value: unknown,
  sourceRevisionId: string,
): ValidationResult<ReleasedVisualizationEntity[]> {
  if (!Array.isArray(value)) {
    return { ok: false, error: 'extracted_entities must be an array' };
  }
  const entities: ReleasedVisualizationEntity[] = [];
  const required = [
    'id', 'type', 'value', 'source_revision_id', 'claim_refs', 'evidence',
  ];
  for (const item of value) {
    const row = asRecord(item);
    if (!row || !hasExactKeys(row, required, ['context'])) {
      return { ok: false, error: 'extracted_entities contain an invalid entity' };
    }
    const id = nonBlankString(row.id);
    const type = nonBlankString(row.type);
    const entityValue = nonBlankString(row.value);
    const revision = nonBlankString(row.source_revision_id);
    const claimRefs = stringArray(row.claim_refs, 1);
    const evidence = validateEvidenceArray(row.evidence, sourceRevisionId);
    if (!id || !type || !entityValue || revision !== sourceRevisionId || !claimRefs || !evidence) {
      return { ok: false, error: 'extracted_entities contain an invalid entity' };
    }
    const entity: ReleasedVisualizationEntity = {
      id,
      type,
      value: entityValue,
      source_revision_id: revision,
      claim_refs: claimRefs,
      evidence,
    };
    if (Object.prototype.hasOwnProperty.call(row, 'context')) {
      const context = nonBlankString(row.context);
      if (!context) return { ok: false, error: 'extracted_entities contain invalid context' };
      entity.context = context;
    }
    entities.push(entity);
  }
  return { ok: true, value: entities };
}

export function validateReleasedVisualizationArtifact(
  value: unknown,
): ValidationResult<ReleasedVisualizationArtifact> {
  const root = asRecord(value);
  const required = [
    'schema_version', 'authority', 'run_id', 'source_revision_id',
    'release_subject_sha256', 'content_hash',
    'nodes', 'edges', 'timeline', 'main_events', 'extracted_entities',
  ];
  if (!root || !hasExactKeys(root, required)) {
    return { ok: false, error: 'visualization artifact has an invalid envelope' };
  }
  if (root.schema_version !== 'investigation-visualization-v1') {
    return { ok: false, error: 'unsupported visualization schema_version' };
  }
  if (root.authority !== 'released_investigation_run') {
    return { ok: false, error: 'visualization artifact is not release-authorized' };
  }

  const runId = nonBlankString(root.run_id);
  const sourceRevisionId = nonBlankString(root.source_revision_id);
  const releaseSubjectSha256 = sha256(root.release_subject_sha256);
  const contentHash = sha256(root.content_hash);
  if (!runId || !sourceRevisionId || !releaseSubjectSha256 || !contentHash) {
    return { ok: false, error: 'visualization release identity is invalid' };
  }

  const nodes = validateNodes(root.nodes, sourceRevisionId);
  if (!nodes.ok) return nodes;
  const edges = validateEdges(
    root.edges,
    sourceRevisionId,
    new Set(nodes.value.map((node) => node.id)),
  );
  if (!edges.ok) return edges;
  const timeline = validateTimeline(root.timeline, sourceRevisionId);
  if (!timeline.ok) return timeline;
  const mainEvents = validateMainEvents(root.main_events, sourceRevisionId);
  if (!mainEvents.ok) return mainEvents;
  const entities = validateEntities(root.extracted_entities, sourceRevisionId);
  if (!entities.ok) return entities;

  return {
    ok: true,
    value: {
      schema_version: 'investigation-visualization-v1',
      authority: 'released_investigation_run',
      run_id: runId,
      source_revision_id: sourceRevisionId,
      release_subject_sha256: releaseSubjectSha256,
      content_hash: contentHash,
      nodes: nodes.value,
      edges: edges.value,
      timeline: timeline.value,
      main_events: mainEvents.value,
      extracted_entities: entities.value,
    },
  };
}

export function selectReleasedVisualizationArtifactFromTask(
  taskPayload: unknown,
): ValidationResult<ReleasedVisualizationArtifact> {
  const task = asRecord(taskPayload);
  const result = asRecord(task?.result);
  const candidate = task?.visualization_data ?? result?.visualization_data;
  return validateReleasedVisualizationArtifact(candidate);
}
