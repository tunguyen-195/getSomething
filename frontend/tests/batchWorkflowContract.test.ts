{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const {
  AUDIO_BATCH_ITEM_STATUSES,
  AUDIO_BATCH_MAX_FILES,
  AUDIO_BATCH_MAX_FILE_BYTES,
  AUDIO_BATCH_MAX_TOTAL_BYTES,
  AUDIO_BATCH_STATUSES,
  audioBatchResumeStorageKey,
  isAudioBatchProcessing,
  isAudioBatchTerminal,
  orderTaskIdsByBatch,
  parseAudioBatchResumeRecord,
} = require('../src/api/client.ts');

function source(path: string): string {
  return readFileSync(resolve(__dirname, '..', 'src', path), 'utf8');
}

test('frontend batch constants and states match the canonical backend contract', () => {
  assert.equal(AUDIO_BATCH_MAX_FILES, 20);
  assert.equal(AUDIO_BATCH_MAX_FILE_BYTES, 100_000_000);
  assert.equal(AUDIO_BATCH_MAX_TOTAL_BYTES, 1_000_000_000);
  assert.deepEqual(AUDIO_BATCH_STATUSES, [
    'created',
    'queued',
    'processing',
    'partially_succeeded',
    'succeeded',
    'failed',
    'cancel_requested',
    'cancelled',
  ]);
  assert.deepEqual(AUDIO_BATCH_ITEM_STATUSES, [
    'uploaded',
    'queued',
    'transcribing',
    'transcribed',
    'failed',
    'cancel_requested',
    'cancelled',
  ]);
});

test('typed client uses the canonical V2 endpoints and omits a blank merged-summary prompt', () => {
  const client = source('api/client.ts');
  assert.match(client, /formData\.append\('files\[\]', file, file\.name\)/);
  assert.match(client, /formData\.append\('case_id', input\.caseId\)/);
  assert.match(client, /formData\.append\('idempotency_key', input\.idempotencyKey\)/);
  assert.match(client, /\/api\/v1\/audio\/v2\/batches`/);
  assert.match(client, /\/batches\/\$\{encodeURIComponent\(batchId\)\}\/transcribe/);
  assert.match(client, /body: JSON\.stringify\(\{ \.\.\.options, task_ids: taskIds \}\)/);
  assert.match(client, /\/batches\/\$\{encodeURIComponent\(batchId\)\}\/summary/);
  assert.match(client, /summary\/\$\{encodeURIComponent\(summaryJobId\)\}/);
  assert.match(client, /\/batches\/\$\{encodeURIComponent\(batchId\)\}\/cancel/);
  assert.match(client, /normalizeSummaryUserPrompt\(input\.user_prompt\)/);
  assert.match(client, /\.\.\.\(userPrompt \? \{ user_prompt: userPrompt \} : \{\}\)/);
  assert.doesNotMatch(client, /user_prompt: undefined/);
  assert.doesNotMatch(client, /detail\.message/);
});

test('refresh record is scoped, strict, and rejects malformed persisted state', () => {
  assert.equal(audioBatchResumeStorageKey('user/name', 7), 'stt:audio-batch:v1:user%2Fname:7');
  const valid = JSON.stringify({
    batch_id: '5a27d1e8-6c9c-4b93-85a1-f068744796cc',
    summary_job_id: '2f92b7ec-53a3-4637-b66c-ac14f69fb876',
    selected_task_ids: ['task-b', 'task-a'],
  });
  assert.deepEqual(parseAudioBatchResumeRecord(valid), JSON.parse(valid));
  assert.equal(parseAudioBatchResumeRecord('{broken'), null);
  assert.equal(parseAudioBatchResumeRecord(JSON.stringify({
    batch_id: 'not-a-uuid',
    selected_task_ids: ['task-a'],
  })), null);
  assert.equal(parseAudioBatchResumeRecord(JSON.stringify({
    batch_id: '5a27d1e8-6c9c-4b93-85a1-f068744796cc',
    selected_task_ids: ['task-a', 'task-a'],
  })), null);
});

test('selected task IDs are projected in immutable parent position order', () => {
  const batch = {
    items: [
      { position: 0, task_id: 'task-a' },
      { position: 1, task_id: 'task-b' },
      { position: 2, task_id: 'task-c' },
    ],
  };
  assert.deepEqual(orderTaskIdsByBatch(batch, ['task-c', 'unknown', 'task-a']), ['task-a', 'task-c']);
  assert.equal(isAudioBatchTerminal('processing'), false);
  assert.equal(isAudioBatchTerminal('cancel_requested'), false);
  assert.equal(isAudioBatchTerminal('partially_succeeded'), true);
  assert.equal(isAudioBatchProcessing('created'), false);
  assert.equal(isAudioBatchProcessing('queued'), true);
  assert.equal(isAudioBatchProcessing('cancel_requested'), true);
});

test('compact uploader sends one ordered multipart request and retains item outcomes', () => {
  const uploader = source('components/CompactUploader.tsx');
  assert.equal((uploader.match(/createAudioBatch\(/g) || []).length, 1);
  assert.doesNotMatch(uploader, /for \(let i = 0; i < files\.length/);
  assert.match(uploader, /files: items\.map\(item => item\.file\)/);
  assert.match(uploader, /idempotencyKey: idempotencyKeyRef\.current/);
  assert.match(uploader, /response\.items\.find\(item => item\.position === index\)/);
  assert.match(uploader, /status: accepted \? 'accepted' : 'rejected'/);
  assert.match(uploader, /batch\.id/);
  assert.match(uploader, /duplicateNameCount/);
  assert.match(uploader, /AUDIO_BATCH_MAX_TOTAL_BYTES/);
  assert.match(
    uploader,
    /if \(requestSequenceRef\.current !== requestSequence\) return;\s+onUploadComplete\?\.\(response\)/,
  );
});

test('file table bulk summary fails closed until every selected transcript is ready', () => {
  const table = source('components/FileTable.tsx');
  assert.match(table, /onBulkTranscribe\?: \(taskIds: string\[\]\)/);
  assert.match(table, /onBulkSummarize\?: \(taskIds: string\[\]\)/);
  assert.match(table, /orderedSelectedFiles\.filter\(file => !file\.transcript\)\.length/);
  assert.match(table, /incompleteSummaryCount > 0/);
  assert.match(table, /Tất cả file đã chọn phải có transcript/);
  assert.match(table, /onBulkSummarize, orderedSelectedTaskIds/);
  assert.match(table, /aria-label': 'Chọn tất cả file khả dụng'/);
});

test('merged summary dialog preserves source order and reuses optional prompt bounds', () => {
  const dialog = source('components/BatchSummaryDialog.tsx');
  assert.match(dialog, /task_ids: sources\.map\(source => source\.task_id\)/);
  assert.match(dialog, /incompleteCount === 0/);
  assert.match(dialog, /SUMMARY_USER_PROMPT_MAX_LENGTH/);
  assert.match(dialog, /normalizeSummaryUserPrompt\(userPrompt\)/);
  assert.match(dialog, /user_prompt: normalizeSummaryUserPrompt\(userPrompt\)/);
  assert.doesNotMatch(dialog, /error\.message|response\.detail|provider/i);
});

test('active App persists and restores parent and summary progress per user and case', () => {
  const app = source('App.tsx');
  assert.match(app, /audioBatchResumeStorageKey\(currentUser\.id \?\? currentUser\.username, selectedCase\.id\)/);
  assert.match(app, /parseAudioBatchResumeRecord\(rawRecord\)/);
  assert.match(app, /getAudioBatch\(resumeRecord\.batch_id\)/);
  assert.match(app, /getAudioBatchSummary\(restoredBatch\.id, resumeRecord\.summary_job_id\)/);
  assert.match(app, /String\(restoredBatch\.case_id\) !== String\(selectedCase\.id\)/);
  assert.match(app, /isAudioBatchTerminal\(nextBatch\.status\)/);
  assert.match(app, /Math\.min\(15000, 2000 \* \(2 \*\* Math\.min\(failureCount, 3\)\)\)/);
});

test('active App wires ordered bulk actions, cancellation, progress, and provenance rendering', () => {
  const app = source('App.tsx');
  assert.match(app, /selectableTaskIds=\{activeBatch\?\.items\.map\(item => item\.task_id\)\}/);
  assert.match(app, /onBulkTranscribe=\{activeBatch \? handleBulkTranscribe : undefined\}/);
  assert.match(app, /onBulkSummarize=\{activeBatch \? handleBulkSummarize : undefined\}/);
  assert.match(app, /task_ids: orderedTaskIds/);
  assert.match(app, /cancelAudioBatch\(activeBatch\.id\)/);
  assert.match(app, /source_manifest/);
  assert.match(app, /user_prompt_applied/);
  assert.match(app, /BatchProgressRegion/);
});
}
