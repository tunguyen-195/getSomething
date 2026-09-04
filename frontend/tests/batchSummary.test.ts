{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');

function loadTypeScriptModule(filename: string, cache = new Map<string, { exports: any }>()) {
  const existing = cache.get(filename);
  if (existing) return existing.exports;
  const loaded = { exports: {} };
  cache.set(filename, loaded);
  const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const localRequire = (request: string) => {
    if (!request.startsWith('.')) return require(request);
    const dependency = resolve(filename, '..', `${request}.ts`);
    return loadTypeScriptModule(dependency, cache);
  };
  vm.runInNewContext(compiled, {
    module: loaded,
    exports: loaded.exports,
    require: localRequire,
  }, { filename });
  return loaded.exports;
}

const {
  normalizeBatchSummaryResults,
  hasUsableBatchSummaryResult,
} = loadTypeScriptModule(resolve(__dirname, '..', 'src', 'utils', 'batchSummary.ts'));
const native = (value: unknown) => JSON.parse(JSON.stringify(value));

test('normalizes every independently persisted summary type without overwriting content', () => {
  const results = normalizeBatchSummaryResults({
    summary: 'legacy detailed text must not replace the typed result',
    summary_type: 'detailed',
    summary_results: [
      { summary_type: 'brief', summary: 'Brief output', status: 'succeeded' },
      { summary_type: 'detailed', summary: 'Detailed output', status: 'succeeded' },
      { summary_type: 'investigation', summary: 'Investigation output', status: 'succeeded' },
      { summary_type: 'forensic', summary: 'Forensic output', status: 'succeeded' },
    ],
  });

  assert.deepEqual(native(results.map((item: any) => item.summary_type)), ['brief', 'detailed', 'investigation', 'forensic']);
  assert.deepEqual(native(results.map((item: any) => item.summary)), [
    'Brief output',
    'Detailed output',
    'Investigation output',
    'Forensic output',
  ]);
  assert.equal(results.filter((item: any) => item.summary === 'legacy detailed text must not replace the typed result').length, 0);
  assert.equal(results.every(hasUsableBatchSummaryResult), true);
});

test('supports rolling-upgrade summaries alias and legacy single result', () => {
  const aliased = normalizeBatchSummaryResults({
    summary: null,
    summary_results: undefined,
    summaries: {
      investigation: { content: 'Investigation alias', status: 'succeeded' },
      forensic: 'Forensic alias',
    },
  });
  assert.deepEqual(native(aliased.map((item: any) => [item.summary_type, item.summary])), [
    ['investigation', 'Investigation alias'],
    ['forensic', 'Forensic alias'],
  ]);

  const legacy = normalizeBatchSummaryResults({ summary: 'Old API output' });
  assert.deepEqual(native(legacy), [{
    summary_type: 'detailed',
    summary: 'Old API output',
    status: 'succeeded',
    error: null,
  }]);

  const failedVariant = normalizeBatchSummaryResults({
    summary: null,
    summary_variants: {
      forensic: { summary_type: 'forensic', summary_state: 'llm_unavailable', summary_error: { code: 'LLM_UNAVAILABLE' } },
    },
  });
  assert.equal(failedVariant[0].status, 'failed');
  assert.ok(failedVariant[0].error);
  assert.equal(failedVariant[0].error.code, 'LLM_UNAVAILABLE');
});

test('frontend contract exposes all summary modes and file-scoped diarization', () => {
  const client = readFileSync(resolve(__dirname, '..', 'src', 'api', 'client.ts'), 'utf8');
  const dialog = readFileSync(resolve(__dirname, '..', 'src', 'components', 'BatchSummaryDialog.tsx'), 'utf8');
  const results = readFileSync(resolve(__dirname, '..', 'src', 'components', 'BatchSummaryResults.tsx'), 'utf8');
  const variants = readFileSync(resolve(__dirname, '..', 'src', 'components', 'SummaryVariants.tsx'), 'utf8');
  const diarization = readFileSync(resolve(__dirname, '..', 'src', 'components', 'DiarizationPanel.tsx'), 'utf8');
  assert.match(client, /export type AudioBatchSummaryType = SummaryType/);
  assert.match(client, /summary_results\?: AudioBatchSummaryResult\[\]/);
  assert.match(dialog, /summary_types: summaryTypes/);
  assert.match(dialog, /SUMMARY_TYPES\.map/);
  assert.match(results, /normalizeBatchSummaryResults/);
  assert.match(results, /data-testid={`batch-summary-result-\$\{result\.summary_type\}`}/);
  assert.match(variants, /file-summary-variants/);
  assert.match(diarization, /fileGroups\?: DiarizationFileGroup\[\]/);
  assert.match(diarization, /Diarization theo từng file/);
  assert.match(diarization, /group\.segments/);
  const app = readFileSync(resolve(__dirname, '..', 'src', 'App.tsx'), 'utf8');
  assert.match(app, /file\.segments\?\.length \? file\.segments : file\.diarization\?\.segments/);
});

}
