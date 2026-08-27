{
const summaryAssert = require('node:assert/strict');
const summaryTest = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const {
  DEFAULT_MULTI_SUMMARY_MAX_LENGTH,
  DEFAULT_MULTI_SUMMARY_MIN_LENGTH,
  DEFAULT_INTERACTIVE_SUMMARY_TYPE,
  DEFAULT_INVESTIGATION_SUMMARY_MAX_LENGTH,
  DEFAULT_INVESTIGATION_SUMMARY_MIN_LENGTH,
  DEFAULT_SUMMARY_MAX_LENGTH,
  DEFAULT_SUMMARY_MIN_LENGTH,
  DEFAULT_SUMMARY_TYPE,
  normalizeSummaryUserPrompt,
  SUMMARY_TYPES,
  SUMMARY_USER_PROMPT_MAX_LENGTH,
} = require('../src/api/client.ts');
const { countTranscriptWords } = require('../src/utils/transcriptText.ts');

function source(path: string): string {
  return readFileSync(resolve(__dirname, '..', 'src', path), 'utf8');
}

summaryTest('frontend summary defaults match the shared S3 contract', () => {
  summaryAssert.deepEqual(SUMMARY_TYPES, [
    'brief',
    'detailed',
    'investigation',
    'forensic',
  ]);
  summaryAssert.equal(DEFAULT_SUMMARY_TYPE, 'detailed');
  summaryAssert.equal(DEFAULT_INTERACTIVE_SUMMARY_TYPE, 'investigation');
  summaryAssert.equal(DEFAULT_INVESTIGATION_SUMMARY_MIN_LENGTH, 120);
  summaryAssert.equal(DEFAULT_INVESTIGATION_SUMMARY_MAX_LENGTH, 400);
  summaryAssert.equal(DEFAULT_SUMMARY_MIN_LENGTH, 50);
  summaryAssert.equal(DEFAULT_SUMMARY_MAX_LENGTH, 200);
  summaryAssert.equal(DEFAULT_MULTI_SUMMARY_MIN_LENGTH, 100);
  summaryAssert.equal(DEFAULT_MULTI_SUMMARY_MAX_LENGTH, 400);
});

summaryTest('single-summary request remains typed and propagates both bounds', () => {
  const app = source('App.tsx');
  const dialog = source('components/SummarizeDialog.tsx');

  summaryAssert.match(app, /options: SummaryDialogOptions/);
  summaryAssert.doesNotMatch(app, /handleSummarize = async \(options: any\)/);
  summaryAssert.match(app, /summary_type: options\.summary_type/);
  summaryAssert.match(app, /normalizeSummaryUserPrompt\(options\.user_prompt\)/);
  summaryAssert.match(app, /\.\.\.\(userPrompt \? \{ user_prompt: userPrompt \} : \{\}\)/);
  summaryAssert.match(app, /min_length: options\.min_length/);
  summaryAssert.match(app, /max_length: options\.max_length/);
  summaryAssert.match(app, /length_mode: options\.length_mode/);
  summaryAssert.match(app, /transcriptLength=\{selectedSummaryTranscriptLength\}/);
  summaryAssert.match(dialog, /useState<SummaryType>\(DEFAULT_INTERACTIVE_SUMMARY_TYPE\)/);
  summaryAssert.match(dialog, /length_mode: 'auto'/);
  summaryAssert.match(dialog, /include_context_analysis: false/);
  summaryAssert.doesNotMatch(dialog, /Maximum words \(enforced\)/);
  summaryAssert.doesNotMatch(dialog, /Include context analysis/);
  summaryAssert.match(dialog, /investigation_scenario: 'auto'/);
  summaryAssert.match(dialog, /user_prompt: normalizeSummaryUserPrompt\(userPrompt\)/);
  summaryAssert.match(dialog, /disabled=\{userPromptTooLong\}/);
  summaryAssert.match(dialog, /multiline/);
  summaryAssert.match(dialog, /SUMMARY_USER_PROMPT_MAX_LENGTH/);
  summaryAssert.doesNotMatch(dialog, /KỊCH BẢN NGHIỆP VỤ/);
});

summaryTest('optional summary prompt is trimmed, omitted when blank, and Unicode bounded', () => {
  summaryAssert.equal(SUMMARY_USER_PROMPT_MAX_LENGTH, 2000);
  summaryAssert.equal(normalizeSummaryUserPrompt(undefined), undefined);
  summaryAssert.equal(normalizeSummaryUserPrompt('  \n\t  '), undefined);
  summaryAssert.equal(
    normalizeSummaryUserPrompt('  Tập trung vào mốc thời gian.  '),
    'Tập trung vào mốc thời gian.',
  );
  summaryAssert.equal(normalizeSummaryUserPrompt('😀'.repeat(2000)), '😀'.repeat(2000));
  const blankRequest = JSON.stringify({
    summary_type: 'investigation',
    user_prompt: normalizeSummaryUserPrompt('   '),
  });
  summaryAssert.doesNotMatch(blankRequest, /user_prompt/);
  summaryAssert.throws(
    () => normalizeSummaryUserPrompt('😀'.repeat(2001)),
    /must not exceed 2000 characters/,
  );
});

summaryTest('summary dialog word count uses the selected transcript text', () => {
  summaryAssert.equal(countTranscriptWords('  mot\n hai\tba  '), 3);
  summaryAssert.equal(countTranscriptWords(''), 0);
  summaryAssert.equal(countTranscriptWords(undefined), 0);
});

summaryTest('multi and case summaries use adaptive length without hardcoded word caps', () => {
  const taskList = source('components/TaskList.tsx');

  summaryAssert.equal(
    (taskList.match(/summary_type: DEFAULT_SUMMARY_TYPE/g) || []).length,
    2,
  );
  summaryAssert.ok((taskList.match(/length_mode: 'auto'/g) || []).length >= 2);
  summaryAssert.doesNotMatch(taskList, /min_length:/);
  summaryAssert.doesNotMatch(taskList, /max_length:/);
  summaryAssert.doesNotMatch(taskList, /model_name: 'gemma2:9b'/);
});

summaryTest('resummarize uses canonical investigation auto mode and checks HTTP failure', () => {
  const taskList = source('components/TaskList.tsx');

  summaryAssert.match(taskList, /summary_type: 'investigation'/);
  summaryAssert.match(taskList, /length_mode: 'auto'/);
  summaryAssert.match(taskList, /if \(!response\.ok/);
  summaryAssert.match(taskList, /typeof summary !== 'string'/);
  summaryAssert.equal((taskList.match(/readSummaryResponse\(res\)/g) || []).length, 3);
});
}
