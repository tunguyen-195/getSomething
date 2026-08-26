{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { projectInvestigationAnalysis } = require('../src/utils/investigationAnalysis.ts');

function contextFixture() {
  return {
    analysis_status: 'success',
    compatibility: {
      release_authority: 'withheld_pending_claim_attestation',
    },
    investigation_knowledge: {
      evidence_spans: [
        {
          evidence_id: 'ev-1',
          quote: 'Anh Nam chuyển 20 triệu đồng cho tài khoản 123456789.',
          segment_index: 0,
          start_seconds: 3,
          end_seconds: 9,
          speaker_id: 'SPEAKER_00',
        },
        {
          evidence_id: 'ev-2',
          quote: 'Gặp chị Lan tại bến xe lúc 20 giờ ngày 12/08/2026.',
          segment_index: 2,
          start_seconds: 18,
          end_seconds: 25,
        },
      ],
      facts: [
        {
          fact_id: 'fact-1',
          category: 'key_point',
          statement: 'Nguồn nói về việc chuyển 20 triệu đồng.',
          status: 'reported',
          verification_status: 'unverified',
          evidence_ids: ['ev-1'],
        },
        {
          fact_id: 'fact-dangling',
          category: 'key_point',
          statement: 'Không được hiển thị.',
          evidence_ids: ['missing'],
        },
      ],
      entities: [
        {
          entity_id: 'entity-nam',
          entity_type: 'person',
          value: 'Anh Nam',
          role: 'người chuyển',
          verification_status: 'unverified',
          evidence_ids: ['ev-1'],
        },
        {
          entity_id: 'entity-account',
          entity_type: 'exact_value.account',
          value: '123456789',
          role: 'tài khoản nhận được nhắc tới',
          verification_status: 'unverified',
          evidence_ids: ['ev-1'],
        },
      ],
      events: [
        {
          event_id: 'event-1',
          description: 'Nguồn nói Anh Nam chuyển tiền.',
          time_text: '12/08/2026 20:00',
          actors: ['Anh Nam'],
          location: 'bến xe',
          status: 'reported',
          verification_status: 'unverified',
          evidence_ids: ['ev-1', 'ev-2'],
        },
      ],
      relationships: [
        {
          relationship_id: 'rel-1',
          source: 'Anh Nam',
          target: '123456789',
          label: 'được nguồn nói là chuyển tiền tới',
          status: 'reported',
          verification_status: 'unverified',
          evidence_ids: ['ev-1'],
        },
      ],
      provenance: {
        model_id: 'deterministic-transcript-fallback-v1',
        transcript_segment_count: 4,
      },
    },
  };
}

test('projects a source preview without calling it grounded or released', () => {
  const view = projectInvestigationAnalysis(contextFixture());

  assert.equal(view.state, 'source_preview');
  assert.equal(view.state_label, 'Phân tích sơ bộ - chưa xác nhận');
  assert.equal(view.model_id, 'deterministic-transcript-fallback-v1');
  assert.equal(view.facts.length, 0);
  assert.equal(view.entities.length, 1);
  assert.equal(view.exact_values.length, 1);
  assert.equal(view.events.length, 1);
  assert.equal(view.relationships.length, 1);
  assert.equal(view.covered_segment_count, 2);
  assert.equal(view.total_segment_count, 4);
  assert.ok(view.gaps.some((item: string) => item.includes('2/4 phần hội thoại')));
});

test('keeps described event time separate from audio offsets', () => {
  const view = projectInvestigationAnalysis(contextFixture());
  const event = view.events[0];

  assert.equal(event.described_time, '12/08/2026 20:00');
  assert.equal(event.evidence[0].start_seconds, 3);
  assert.equal(event.evidence[1].start_seconds, 18);
});

test('does not promote an audio offset to described event time', () => {
  const fixture = contextFixture();
  delete (fixture.investigation_knowledge.events[0] as { time_text?: string }).time_text;

  const view = projectInvestigationAnalysis(fixture);
  assert.equal(view.events[0].described_time, undefined);
});

test('derives only bounded insights with explicit premise and evidence paths', () => {
  const view = projectInvestigationAnalysis(contextFixture());

  assert.ok(view.insights.some((item: any) => (
    item.kind === 'explicit_role'
    && item.premise_ids.includes('entity-nam')
    && item.evidence[0].evidence_id === 'ev-1'
  )));
  assert.ok(view.insights.some((item: any) => (
    item.kind === 'explicit_relationship'
    && item.premise_ids.includes('rel-1')
  )));
  assert.ok(view.insights.every((item: any) => item.evidence.length > 0));
});

test('drops items with dangling evidence instead of rendering unsupported claims', () => {
  const fixture = contextFixture();
  fixture.investigation_knowledge.entities.push({
    entity_id: 'entity-unsafe',
    entity_type: 'person',
    value: 'Không có bằng chứng',
    role: 'unknown',
    verification_status: 'unverified',
    evidence_ids: ['missing'],
  });

  const view = projectInvestigationAnalysis(fixture);
  assert.equal(view.entities.some((item: any) => item.id === 'entity-unsafe'), false);
  assert.equal(view.facts.some((item: any) => item.id === 'fact-dangling'), false);
});

test('does not duplicate key points or exact values across Analysis sections', () => {
  const fixture = contextFixture();
  fixture.investigation_knowledge.facts.push({
    fact_id: 'fact-money',
    category: 'exact_value.money',
    statement: '20 triệu đồng',
    status: 'reported',
    verification_status: 'unverified',
    evidence_ids: ['ev-1'],
  });

  const view = projectInvestigationAnalysis(fixture);

  assert.equal(view.facts.length, 0);
  assert.deepEqual(view.entities.map((item: any) => item.value), ['Anh Nam']);
  assert.deepEqual(view.exact_values.map((item: any) => item.value), ['123456789']);
});

test('projects reader-safe analysis without requiring technical evidence fields', () => {
  const view = projectInvestigationAnalysis({
    schema_version: 'public-investigation-analysis-v1',
    analysis_status: 'success',
    facts: [{
      category: 'financial.plan',
      statement: 'Lan dự kiến chuyển 15 triệu đồng cho Minh.',
      status: 'planned',
      verification_status: 'unverified',
    }],
    entities: [
      {
        entity_type: 'person',
        value: 'Lan',
        role: 'người chuyển tiền dự kiến',
        verification_status: 'unverified',
      },
      {
        entity_type: 'exact_value.money',
        value: '15 triệu đồng',
        verification_status: 'unverified',
      },
    ],
    events: [{
      description: 'Lan dự kiến chuyển tiền cho Minh.',
      status: 'planned',
      time_text: 'ngày mai',
      actors: ['Lan', 'Minh'],
      verification_status: 'unverified',
    }],
    relationships: [{
      source: 'Lan',
      target: 'Minh',
      label: 'dự kiến chuyển tiền cho',
      status: 'planned',
      verification_status: 'unverified',
    }],
    metrics: {
      covered_segment_count: 2,
      total_segment_count: 3,
    },
  });

  assert.equal(view.state, 'source_preview');
  assert.equal(view.facts[0].statement, 'Lan dự kiến chuyển 15 triệu đồng cho Minh.');
  assert.equal(view.entities[0].value, 'Lan');
  assert.equal(view.exact_values[0].value, '15 triệu đồng');
  assert.equal(view.events[0].described_time, 'ngày mai');
  assert.equal(view.relationships[0].source, 'Lan');
  assert.equal(view.evidence_spans.length, 0);
  assert.equal(view.covered_segment_count, 2);
  assert.equal(view.total_segment_count, 3);
});

test('projects the compact tolerant v2 payload and keeps every business section optional', () => {
  const view = projectInvestigationAnalysis({
    schema_version: 'investigation-analysis-simple-v2',
    analysis_status: 'partial',
    analysis_generation: 'single_prompt_llm',
    overview: 'Cuộc trao đổi tập trung vào việc giao tài liệu và xác nhận thời gian gặp.',
    key_points: [{ text: 'Lan giao hồ sơ cho Minh.' }, 'Cuộc hẹn diễn ra vào sáng mai.'],
    participants: [{ name: 'Lan', role: 'người giao hồ sơ', description: 'Được nêu rõ trong hội thoại.' }],
    events: [{ description: 'Lan giao hồ sơ cho Minh.', time: 'sáng mai', participants: ['Lan', 'Minh'] }],
    actions: [{ description: 'Minh xác nhận đã nhận hồ sơ.', actor: 'Minh', status: 'completed' }],
    decisions: [{ description: 'Hai bên thống nhất gặp tại bến xe.', status: 'planned' }],
    commitments: [{ description: 'Lan sẽ gọi lại.', actor: 'Lan', deadline: 'trước 09:00' }],
    entities: [{ type: 'document', value: 'hồ sơ A', count: 3 }],
    relationships: [{ source: 'Lan', target: 'Minh', label: 'giao hồ sơ cho' }],
    contradictions: [{ description: 'Hai mốc giờ khác nhau được nêu.', items: ['08:00', '09:00'] }],
    uncertainties: ['Chưa rõ ai chuẩn bị phương tiện.'],
    follow_ups: [{ question: 'Ai chuẩn bị phương tiện?', reason: 'Chưa được nêu', priority: 'high' }],
  });

  assert.equal(view.state, 'source_preview');
  assert.equal(view.overview, 'Cuộc trao đổi tập trung vào việc giao tài liệu và xác nhận thời gian gặp.');
  assert.deepEqual(view.key_points, ['Lan giao hồ sơ cho Minh.', 'Cuộc hẹn diễn ra vào sáng mai.']);
  assert.equal(view.participants[0].description, 'Được nêu rõ trong hội thoại.');
  assert.equal(view.events[0].actors[1], 'Minh');
  assert.equal(view.actions[0].status, 'completed');
  assert.equal(view.decisions.length, 1);
  assert.equal(view.commitments[0].deadline, 'trước 09:00');
  assert.equal(view.exact_values[0].count, 3);
  assert.deepEqual(view.contradictions[0].details, ['08:00', '09:00']);
  assert.equal(view.uncertainties[0].statement, 'Chưa rõ ai chuẩn bị phương tiện.');
  assert.equal(view.follow_ups[0].priority, 'high');
});

test('plain analysis_text remains visible when structured JSON sections are absent', () => {
  const view = projectInvestigationAnalysis({
    schema_version: 'investigation-analysis-simple-v2',
    analysis_status: 'partial',
    analysis_text: 'LLM đã phân tích được nội dung nhưng không trả đủ cấu trúc.',
  });

  assert.equal(view.state, 'source_preview');
  assert.equal(view.analysis_text, 'LLM đã phân tích được nội dung nhưng không trả đủ cấu trúc.');
  assert.equal(view.events.length, 0);
  assert.equal(view.relationships.length, 0);
});

test('derives visualization metrics from persisted Analysis and diarized segments', () => {
  const { buildInvestigationVisualization } = require('../src/utils/investigationAnalysis.ts');
  const view = buildInvestigationVisualization({
    context_analysis: {
      schema_version: 'investigation-analysis-simple-v2',
      analysis_status: 'success',
      participants: [{ name: 'Lan' }, { name: 'Minh' }],
      entities: [{ type: 'organization', value: 'Công ty A', count: 4 }],
      events: [{ description: 'Hai bên gặp nhau.', time: '09:00' }],
      actions: [{ description: 'Gọi xác nhận', status: 'completed' }],
      relationships: [{ source: 'Lan', target: 'Minh', label: 'liên hệ' }],
    },
    segments: [
      { speaker: 'SPEAKER_00', text: 'một hai ba bốn' },
      { speaker: 'SPEAKER_01', text: 'năm sáu' },
    ],
  });

  assert.equal(view.timeline[0].time, '09:00');
  assert.equal(view.edges.length, 1);
  assert.equal(view.speaker_contributions[0].speaker, 'SPEAKER_00');
  assert.equal(view.speaker_contributions[0].percentage, 67);
  assert.equal(view.entity_frequencies[0].count, 4);
  assert.deepEqual(view.action_statuses, [{ status: 'completed', count: 1 }]);
});

test('uses persisted top-level speaker contributions before deriving them from segments', () => {
  const { buildInvestigationVisualization } = require('../src/utils/investigationAnalysis.ts');
  const view = buildInvestigationVisualization({
    context_analysis: {
      schema_version: 'investigation-analysis-simple-v2',
      analysis_status: 'success',
      speaker_contributions: [
        { speaker: 'SPEAKER_01', word_count: 9, segment_count: 3 },
        { speaker: 'SPEAKER_00', word_count: 3, segment_count: 1 },
      ],
      metrics: {
        speaker_contributions: [
          { speaker: 'STALE_METRIC_SHAPE', word_count: 100, segment_count: 1 },
        ],
      },
    },
    segments: [{ speaker: 'DERIVED_SEGMENT', text: 'không được ưu tiên' }],
  });

  assert.deepEqual(view.speaker_contributions, [
    { speaker: 'SPEAKER_01', word_count: 9, segment_count: 3, percentage: 75 },
    { speaker: 'SPEAKER_00', word_count: 3, segment_count: 1, percentage: 25 },
  ]);
});

test('converts persisted fractional word_share to display percentages', () => {
  const { buildInvestigationVisualization } = require('../src/utils/investigationAnalysis.ts');
  const view = buildInvestigationVisualization({
    context_analysis: {
      schema_version: 'investigation-analysis-simple-v2',
      analysis_status: 'success',
      speaker_contributions: [
        { speaker: 'SPEAKER_00', word_count: 181, segment_count: 25, word_share: 0.5355 },
        { speaker: 'SPEAKER_01', word_count: 157, segment_count: 26, word_share: 0.4645 },
      ],
    },
  });

  assert.deepEqual(
    view.speaker_contributions.map((item: { percentage: number }) => item.percentage),
    [54, 46],
  );
});

test('Analysis UI exposes investigative content without technical evidence trails', () => {
  const panel = readFileSync(
    resolve(__dirname, '..', 'src', 'components', 'AnalysisPanel.tsx'),
    'utf8',
  );
  const projection = readFileSync(
    resolve(__dirname, '..', 'src', 'utils', 'investigationAnalysis.ts'),
    'utf8',
  );

  assert.doesNotMatch(panel, /label=\{row\.status === 'success' \? 'Grounded'/);
  assert.doesNotMatch(panel, /label: 'Đã phân tích'/);
  assert.match(panel, /preview\.state_label/);
  assert.match(projection, /Phân tích sơ bộ - chưa xác nhận/);
  assert.match(panel, /Người tham gia và vai trò/);
  assert.match(panel, /Thực thể và giá trị chính xác/);
  assert.match(panel, /Timeline sự kiện/);
  assert.match(panel, /Mối quan hệ được nêu/);
  assert.match(panel, /Mâu thuẫn cần đối chiếu/);
  assert.match(panel, /Câu hỏi và việc cần làm tiếp/);
  assert.match(panel, /Nội dung phân tích/);
  assert.doesNotMatch(panel, /EvidenceTrail/);
  assert.doesNotMatch(panel, /start_seconds|end_seconds|evidence_id|\.quote/);
  assert.doesNotMatch(panel, /evidence preview|Bằng chứng mô hình hóa|bản đồ evidence/);
  assert.doesNotMatch(panel, /premise_ids|premise:|verification_status/);
  assert.doesNotMatch(panel, /Ngữ nghĩa\/owner explicit|actors:/);
});
}
