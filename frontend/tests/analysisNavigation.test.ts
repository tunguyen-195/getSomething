{
const assert = require('node:assert/strict');
const test = require('node:test');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

function source(path: string): string {
  return readFileSync(resolve(__dirname, '..', 'src', path), 'utf8');
}

test('overview exposes a per-file Analysis action wired to the Analysis tab', () => {
  const app = source('App.tsx');
  const fileTable = source('components/FileTable.tsx');
  const analysisPanel = source('components/AnalysisPanel.tsx');

  assert.match(fileTable, /onAnalyze: \(taskId: string\) => void/);
  assert.match(fileTable, /onAnalyze\(file\.task_id\)/);
  assert.match(fileTable, />\s*Analysis\s*<\/Button>/);
  assert.match(fileTable, /disabled=\{isProcessing \|\| !file\.transcript\}/);
  assert.match(app, /onAnalyze=\{\(taskId\) =>/);
  assert.match(app, /if \(!file\?\.transcript\)/);
  assert.match(app, /Cần transcript trước khi mở Analysis\./);
  assert.match(app, /setAnalysisTaskId\(taskId\)/);
  assert.match(app, /setTab\(4\)/);
  assert.match(app, /focusTaskId=\{analysisTaskId\}/);
  assert.match(analysisPanel, /row\.file\.task_id === focusTaskId/);
});

test('case navigation keeps the Analysis tab reachable on narrow screens', () => {
  const app = source('App.tsx');

  assert.match(app, /<Tab label="📊 Analysis" \/>/);
  assert.match(app, /variant="scrollable"/);
  assert.match(app, /scrollButtons="auto"/);
  assert.match(app, /allowScrollButtonsMobile/);
  assert.match(app, /useMediaQuery\('\(min-width:900px\)'\)/);
  assert.match(app, /variant=\{isDesktopViewport \? 'persistent' : 'temporary'\}/);
  assert.match(app, /onClose=\{\(\) => setSidebarOpen\(false\)\}/);
  assert.match(app, /ml: isDesktopViewport && sidebarOpen/);
  assert.match(app, /if \(!isDesktopViewport\) setSidebarOpen\(false\)/);
});
}
