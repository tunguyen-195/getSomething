const assert = require('node:assert/strict');
const test = require('node:test');
const { formatAnalysisValue, formatSlangDetected } = require('../src/utils/analysisRender.ts');

test('formatAnalysisValue preserves scalar, array, and object semantics as text', () => {
  assert.equal(formatAnalysisValue('plain text'), 'plain text');
  assert.equal(formatAnalysisValue(null), '');
  assert.equal(formatAnalysisValue(['alpha', 2, null]), 'alpha, 2');
  assert.equal(
    formatAnalysisValue({ status: 'pending', count: 2 }),
    'status: pending; count: 2',
  );
});

test('formatSlangDetected hides negative detections and preserves detected terms', () => {
  assert.equal(formatSlangDetected({ has_slang: false, terms: [] }), '');
  assert.equal(
    formatSlangDetected({ has_slang: true, terms: ['deal', { value: 'hàng' }] }),
    'deal, value: hàng',
  );
  assert.equal(formatSlangDetected('mật ngữ'), 'mật ngữ');
  assert.equal(formatSlangDetected(null), '');
});
