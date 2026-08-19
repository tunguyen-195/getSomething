{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

function source(path: string): string {
  return readFileSync(resolve(__dirname, '..', 'src', path), 'utf8');
}

test('visualization projects Analysis content without technical source trails', () => {
  const dialog = source('components/VisualizationDialog.tsx');
  const app = source('App.tsx');

  assert.match(dialog, /buildInvestigationVisualization/);
  assert.match(dialog, /Sơ đồ đối tượng và quan hệ/);
  assert.match(dialog, /Timeline sự kiện/);
  assert.match(dialog, /Mức độ tham gia của người nói/);
  assert.match(dialog, /Thực thể được nhắc tới/);
  assert.match(dialog, /Tổng quan hành động và trạng thái/);
  assert.match(dialog, /không gọi LLM thêm khi đổi cách xem/);
  assert.doesNotMatch(dialog, /selectReleasedVisualizationArtifactFromTask|ReleasedVisualizationArtifact/);
  assert.doesNotMatch(dialog, /api\/v1\/summaries\/visualize|method:\s*['"]POST['"]/);
  assert.doesNotMatch(dialog, /transcriptEvidenceVisualization|buildTranscriptEvidenceVisualization/);
  assert.doesNotMatch(dialog, /Evidence graph|Validated authority|run_id|source_revision_id|content_hash/);
  assert.doesNotMatch(dialog, /start_seconds|end_seconds|\.quote|audio offset|offset âm thanh/i);
  assert.match(app, /<VisualizationDialog/);
  assert.match(app, /onVisualize=/);
});

test('text-only Analysis shows an explicit no-structured-data state before charts', () => {
  const dialog = source('components/VisualizationDialog.tsx');
  const textOnlyBranch = dialog.indexOf(') : isTextOnlyAnalysis ? (');
  const emptyBranch = dialog.indexOf(') : !hasVisualization ? (');
  const chartBranch = dialog.indexOf(') : preview ? (');

  assert.match(dialog, /analysisContextFromTask/);
  assert.match(dialog, /projectInvestigationAnalysis/);
  assert.match(
    dialog,
    /isTextOnlyAnalysis = Boolean\(analysis\?\.analysis_text && !hasStructuredVisualizationData\)/,
  );
  assert.match(
    dialog,
    /Analysis dạng văn bản đã có, nhưng chưa có dữ liệu cấu trúc để dựng timeline hoặc sơ đồ quan hệ\./,
  );
  assert.match(dialog, /Vui lòng xem nội dung đầy đủ tại tab Analysis\./);
  assert.ok(textOnlyBranch >= 0, 'text-only state must be rendered');
  assert.ok(emptyBranch > textOnlyBranch, 'text-only state must precede the generic empty state');
  assert.ok(chartBranch > textOnlyBranch, 'text-only state must prevent chart rendering');
});
}
