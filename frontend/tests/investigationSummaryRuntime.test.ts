{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

function source(path: string): string {
  return readFileSync(resolve(__dirname, '..', 'src', path), 'utf8');
}

test('polling presents a completed LLM summary directly', () => {
  const app = source('App.tsx');

  assert.match(app, /summary_state: f\.summary_state/);
  assert.match(app, /summary_notice: f\.summary_notice/);
  assert.match(app, /summary_preview: f\.summary_preview/);
  assert.match(app, /status\?include_result=false/);
  assert.doesNotMatch(app, /statusData\.summary_state === 'source_grounded_narrative'/);
  assert.match(app, /Summarization completed!/);
  assert.match(app, /currentStatus === 'failed'/);
});

test('reader-facing summary displays plain LLM text without requiring JSON', () => {
  const app = source('App.tsx');
  const analysis = source('components/AnalysisPanel.tsx');
  const card = source('components/InvestigationSummaryCard.tsx');
  const fileCard = source('components/FileCard.tsx');
  const taskItem = source('components/TaskListItem.tsx');

  assert.match(app, /summaryDisplayText/);
  assert.match(card, /summaryState === 'source_grounded_narrative'/);
  assert.doesNotMatch(card, /Evidence:/);
  assert.match(card, /sanitizeSummaryDisplayText/);
  assert.match(card, /const plainSummaryText = typeof summary === 'string'/);
  assert.match(card, /if \(plainSummaryText && !parsedAnalysis\)/);
  assert.match(card, /whiteSpace: 'pre-wrap'/);
  assert.match(card, /Không có nội dung tóm tắt/);
  assert.doesNotMatch(card, /dữ liệu trả về không hợp lệ từ backend/);
  assert.match(analysis, /summary: sanitizeSummaryDisplayText\(file\.summary \|\| ''\)/);
  assert.match(fileCard, /const displaySummary = sanitizeSummaryDisplayText\(file\.summary\)/);
  assert.match(taskItem, /summary_state === 'grounded_transcript_only'/);
  assert.match(taskItem, /sanitizeSummaryDisplayText\(summary\)/);
  assert.doesNotMatch(taskItem, /summaryPreview\?\.text/);
  assert.match(taskItem, /summaryState=\{task\.result\?\.summary_state\}/);
});
}
