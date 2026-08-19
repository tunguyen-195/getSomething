{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const {
  selectKeyPointStatements,
  selectKeyPoints,
  selectReleasedInsightStatements,
  selectReleasedVisualizationArtifactFromTask,
  projectInvestigationSummaryContext,
  validateReleasedVisualizationArtifact,
} = require('../src/utils/investigationProjection.ts');

function releasedVisualization() {
  return JSON.parse(readFileSync(
    resolve(__dirname, 'fixtures', 'investigationVisualization.json'),
    'utf8',
  ));
}

test('key-point projection selects only category=key_point and emits statement text once', () => {
  const payload = {
    schema_version: 'investigation-run-v1.0',
    run_status: 'success',
    gate_failures: null,
    investigation_knowledge: {
      facts: [
        {
          fact_id: 'fact-1',
          category: 'key_point',
          statement: 'Lan hen gap luc 09:00.',
          evidence_ids: ['ev-1'],
          model_generated: true,
          verification_status: 'human_verified',
        },
        {
          fact_id: 'fact-2',
          category: 'financial',
          statement: 'So tien la 5 trieu dong.',
          evidence_ids: ['ev-2'],
        },
        {
          fact_id: 'fact-3',
          category: 'key_point',
          statement: 'Lan hen gap luc 09:00.',
          evidence_ids: ['ev-3'],
          verification_status: 'human_verified',
        },
        {
          fact_id: 'fact-rejected',
          category: 'key_point',
          statement: 'Noi dung da bi bac bo.',
          evidence_ids: ['ev-rejected'],
          verification_status: 'rejected',
        },
      ],
    },
  };

  assert.deepEqual(selectKeyPointStatements(payload), ['Lan hen gap luc 09:00.']);
  assert.deepEqual(selectKeyPoints(payload), [{
    statement: 'Lan hen gap luc 09:00.',
    evidence_ids: ['ev-1', 'ev-3'],
    verification_status: 'human_verified',
    model_generated: true,
  }]);
  assert.equal(JSON.stringify(selectKeyPointStatements(payload)).includes('fact_id'), false);
  assert.equal(JSON.stringify(selectKeyPointStatements(payload)).includes('verification_status'), false);
});

test('reasoning insights remain hidden until production exposes release authority', () => {
  const payload = {
    schema_version: 'investigation-run-v1.0',
    run_status: 'success',
    gate_failures: null,
    investigation_knowledge: {
      facts: [
        { category: 'key_point', statement: 'Lan hen gap luc 09:00.' },
      ],
    },
    ledger: {
      insights: [
        { insight_id: 'ins-1', statement: 'Lan hen gap luc 09:00.' },
        { insight_id: 'ins-2', statement: 'Hai chi tiet co chung mot moc thoi gian.' },
        {
          insight_id: 'ins-withheld',
          statement: 'Khong duoc release.',
          projection_eligibility: 'withheld',
        },
      ],
    },
    projections: {
      analysis: { insight_refs: ['ins-1', 'ins-2'] },
    },
  };

  assert.deepEqual(selectReleasedInsightStatements(payload), []);
  assert.deepEqual(selectReleasedInsightStatements({
    ...payload,
    projections: { analysis: { insight_refs: ['ins-withheld'] } },
  }), []);
  assert.deepEqual(
    selectReleasedInsightStatements({ investigation_knowledge: payload.investigation_knowledge }),
    [],
  );
  assert.deepEqual(
    selectReleasedInsightStatements({ ...payload, run_status: 'needs_review' }),
    [],
  );
});

test('key-point projection rejects rejected facts and sanitizes legacy context', () => {
  const rawContext = {
    investigation_knowledge: {
      facts: [
        {
          category: 'key_point',
          statement: 'Du kien hop luc.',
          evidence_ids: ['ev-safe'],
          verification_status: 'unverified',
        },
        {
          category: 'key_point',
          statement: 'Du kien da bi bac bo.',
          evidence_ids: ['ev-rejected'],
          verification_status: 'rejected',
        },
      ],
    },
    ledger: { insights: [{ insight_id: 'spoof', statement: 'Spoofed insight' }] },
    projections: { analysis: { insight_refs: ['spoof'] } },
    sensitive_info: [{ value: 'must not cross the legacy boundary' }],
  };

  assert.deepEqual(projectInvestigationSummaryContext(rawContext), {
    investigation_knowledge: {
      facts: [{
        category: 'key_point',
        statement: 'Du kien hop luc.',
        evidence_ids: ['ev-safe'],
        verification_status: 'unverified',
        model_generated: false,
      }],
    },
  });
  assert.equal(
    JSON.stringify(projectInvestigationSummaryContext(rawContext)).includes('Spoofed insight'),
    false,
  );
});

test('released visualization validator accepts only the authority envelope', () => {
  const fixture = releasedVisualization();
  const accepted = validateReleasedVisualizationArtifact(fixture);
  assert.equal(accepted.ok, true);
  if (accepted.ok) {
    assert.equal(accepted.value.nodes[0].label, 'Lan hen gap luc 09:00.');
    assert.equal(
      accepted.value.release_subject_sha256,
      'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
    );
    assert.equal(
      Object.prototype.hasOwnProperty.call(accepted.value, 'unsafe_metadata'),
      false,
    );
  }

  const legacy: any = releasedVisualization();
  delete legacy.schema_version;
  delete legacy.authority;
  assert.equal(validateReleasedVisualizationArtifact(legacy).ok, false);
});

test('released visualization validator rejects invalid hashes and dangling graph edges', () => {
  const invalidHash = releasedVisualization();
  invalidHash.content_hash = 'not-a-sha256';
  assert.equal(validateReleasedVisualizationArtifact(invalidHash).ok, false);

  const missingSubjectHash = releasedVisualization();
  delete missingSubjectHash.release_subject_sha256;
  assert.equal(validateReleasedVisualizationArtifact(missingSubjectHash).ok, false);

  const invalidSubjectHash = releasedVisualization();
  invalidSubjectHash.release_subject_sha256 = 'not-a-sha256';
  assert.equal(validateReleasedVisualizationArtifact(invalidSubjectHash).ok, false);

  const dangling = releasedVisualization();
  dangling.edges[0].target = 'missing-node';
  assert.equal(validateReleasedVisualizationArtifact(dangling).ok, false);
});

test('released visualization validator rejects reversed evidence and timeline bounds', () => {
  const oneSidedEvidence = releasedVisualization();
  delete oneSidedEvidence.nodes[0].evidence[0].end_seconds;
  assert.equal(validateReleasedVisualizationArtifact(oneSidedEvidence).ok, false);

  const reversedEvidence = releasedVisualization();
  reversedEvidence.nodes[0].evidence[0].start_seconds = 3;
  reversedEvidence.nodes[0].evidence[0].end_seconds = 2;
  assert.equal(validateReleasedVisualizationArtifact(reversedEvidence).ok, false);

  const reversedTimeline = releasedVisualization();
  reversedTimeline.timeline[0].start_seconds = 3;
  reversedTimeline.timeline[0].end_seconds = 2;
  assert.equal(validateReleasedVisualizationArtifact(reversedTimeline).ok, false);
});

test('released visualization validator rejects legacy nested shapes and extra metadata', () => {
  const legacy = releasedVisualization();
  legacy.edges[0] = { from: 'claim-1', to: 'concept-1', label: 'mentions' };
  assert.equal(validateReleasedVisualizationArtifact(legacy).ok, false);

  const extra = releasedVisualization();
  extra.nodes[0].unsafe_metadata = { model_generated: true };
  assert.equal(validateReleasedVisualizationArtifact(extra).ok, false);
});

test('task selector reads visualization_data without falling back to summary or context', () => {
  assert.equal(
    selectReleasedVisualizationArtifactFromTask({
      result: { visualization_data: releasedVisualization() },
    }).ok,
    true,
  );
  assert.equal(
    selectReleasedVisualizationArtifactFromTask({
      result: { summary: 'unsafe prose', context_analysis: { nodes: [] } },
    }).ok,
    false,
  );
});

test('component wiring remains read-only and uses the semantic validators', () => {
  const component = (name: string) => readFileSync(
    resolve(__dirname, '..', 'src', 'components', name),
    'utf8',
  );
  const card = component('InvestigationSummaryCard.tsx');
  const dialog = component('VisualizationDialog.tsx');
  const fileCard = component('FileCard.tsx');
  const taskList = component('TaskList.tsx');
  const taskListItem = component('TaskListItem.tsx');

  assert.doesNotMatch(card, /summaries\/analyze|method:\s*['"]POST|Phan tich lai bang AI/i);
  assert.match(card, /selectKeyPoints/);
  assert.match(card, /insight\.length > 0 && <Tab/);
  assert.match(card, /human_verified/);
  assert.match(card, /Đã bác bỏ/);
  assert.doesNotMatch(card, /verification_status === ['"]verified['"]/);
  assert.doesNotMatch(
    card,
    /react-flow-renderer|ReactFlow|<Timeline|Sơ đồ quan hệ|Timeline sự kiện/,
  );
  assert.match(dialog, /buildInvestigationVisualization/);
  assert.doesNotMatch(dialog, /selectReleasedVisualizationArtifactFromTask/);
  assert.match(dialog, /react-flow-renderer|ReactFlow/);
  assert.doesNotMatch(dialog, /result\?\.summary|InvestigationSummaryCard/);
  assert.doesNotMatch(
    dialog,
    /start_seconds|end_seconds|\.quote|evidence_id|run_id|source_revision_id|content_hash/,
  );
  assert.match(fileCard, /validateReleasedVisualizationArtifact/);
  assert.doesNotMatch(fileCard, />\s*(?:Re-)?Generate\s*</i);
  assert.match(taskList, /projectInvestigationSummaryContext/);
  assert.match(taskListItem, /contextAnalysis=\{safeContextAnalysis\}/);
  assert.doesNotMatch(taskListItem, /Data Visualization/);
  assert.match(taskListItem, /Thông tin trích xuất/);
  assert.doesNotMatch(
    taskListItem,
    /contextAnalysis=\{task\.result\?\.context_analysis\}/,
  );
});
}
