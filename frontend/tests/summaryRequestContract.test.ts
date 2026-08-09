const summaryAssert = require('node:assert/strict');
const summaryTest = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const {
  DEFAULT_MULTI_SUMMARY_MAX_LENGTH,
  DEFAULT_MULTI_SUMMARY_MIN_LENGTH,
  DEFAULT_SUMMARY_MAX_LENGTH,
  DEFAULT_SUMMARY_MIN_LENGTH,
  DEFAULT_SUMMARY_TYPE,
  SUMMARY_TYPES,
} = require('../src/api/client.ts');

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
  summaryAssert.match(app, /min_length: options\.min_length/);
  summaryAssert.match(app, /max_length: options\.max_length/);
  summaryAssert.match(dialog, /useState<SummaryType>\(DEFAULT_SUMMARY_TYPE\)/);
  summaryAssert.match(dialog, /min_length: minLength/);
  summaryAssert.match(dialog, /max_length: maxLength/);
});

summaryTest('multi and case summaries send explicit shared type and length defaults', () => {
  const taskList = source('components/TaskList.tsx');

  summaryAssert.equal(
    (taskList.match(/summary_type: DEFAULT_SUMMARY_TYPE/g) || []).length,
    2,
  );
  summaryAssert.equal(
    (taskList.match(/min_length: DEFAULT_MULTI_SUMMARY_MIN_LENGTH/g) || []).length,
    2,
  );
  summaryAssert.equal(
    (taskList.match(/max_length: DEFAULT_MULTI_SUMMARY_MAX_LENGTH/g) || []).length,
    2,
  );
});

summaryTest('needs-review summary state is terminal and visible to the user', () => {
  const app = source('App.tsx');
  const fileCard = source('components/FileCard.tsx');

  summaryAssert.match(app, /currentStatus === 'needs_review'/);
  summaryAssert.match(app, /Summary withheld for human review/);
  summaryAssert.match(app, /severity: 'warning'/);
  summaryAssert.match(fileCard, /\| 'needs_review'/);
  summaryAssert.match(fileCard, /Needs human review/);
  summaryAssert.match(fileCard, /evidence or release verification did not pass/);
});
