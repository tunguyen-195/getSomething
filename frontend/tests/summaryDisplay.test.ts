{
const assert = require('node:assert/strict');
const test = require('node:test');
const ts = require('typescript');
const vm = require('node:vm');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

function loadSummaryDisplay() {
  const filename = resolve(__dirname, '..', 'src', 'utils', 'summaryDisplay.ts');
  const source = readFileSync(filename, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const loadedModule: { exports: any } = { exports: {} };
  vm.runInNewContext(
    compiled,
    { module: loadedModule, exports: loadedModule.exports },
    { filename },
  );
  return loadedModule.exports;
}

const { sanitizeSummaryDisplayText, summaryDisplayText } = loadSummaryDisplay();

test('sanitizes persisted preview v1 metadata without losing content', () => {
  const legacy = [
    'Bản xem trước evidence transcript - chưa phải tóm tắt điều tra đã phát hành.',
    '[offset âm thanh: 00:00-00:16; người nói: SPEAKER_00; đoạn: 0] Nguồn ghi nhận: "Minh nói sẽ chuyển 15 triệu đồng cho Lan."',
    '[offset âm thanh: 00:16-00:30; người nói: SPEAKER_01; đoạn: 1] Nguồn ghi nhận: “Lan yêu cầu gửi vào tài khoản 0123456789.”',
  ].join('\n');

  const clean = sanitizeSummaryDisplayText(legacy);
  assert.equal(
    clean,
    'Minh nói sẽ chuyển 15 triệu đồng cho Lan.\nLan yêu cầu gửi vào tài khoản 0123456789.',
  );
  assert.doesNotMatch(clean, /offset âm thanh|người nói|SPEAKER_|Nguồn ghi nhận|evidence/i);
});

test('uses only persisted summary and never promotes preview text', () => {
  assert.equal(
    summaryDisplayText({
      summary: '- **[offset âm thanh: 00:00-00:16; người nói: A; đoạn: 0]** Nội dung chính',
      summary_preview: { text: 'Không được chọn' },
    }),
    'Nội dung chính',
  );
  assert.equal(
    summaryDisplayText({
      summary: '',
      summary_preview: {
        text: '[offset âm thanh: 00:00-00:16; người nói: A; đoạn: 0] Nguồn ghi nhận: "Nội dung dự phòng"',
      },
    }),
    '',
  );
  assert.equal(
    summaryDisplayText({
      summary_state: 'grounded_transcript_only',
      summary: 'Nội dung quote preview cũ.',
    }),
    '',
  );
});

test('sanitizes English and mixed legacy metadata variants', () => {
  const clean = sanitizeSummaryDisplayText([
    'Transcript evidence preview - not a released investigation summary.',
    '[audio_offset: 00:00-00:16; speaker: SPEAKER_00; segment: 0] Source: "First statement"',
    '[offset am thanh: 00:16-00:30; speaker: SPEAKER_01; đoạn: 1] Source quote: “Second statement”',
  ].join('\n'));

  assert.equal(clean, 'First statement\nSecond statement');
  assert.doesNotMatch(clean, /audio[_ -]*offset|offset am thanh|speaker|segment|source/i);
});

test('sanitizes headings and multiple persisted excerpts on one line', () => {
  const clean = sanitizeSummaryDisplayText(
    '### **[offset-am-thanh: 00:00-00:16; người nói: A]** Nguồn ghi nhận: "Đoạn một" '
      + '[audio offset: 00:16-00:30; speaker: B] Source record: “Đoạn hai”',
  );

  assert.equal(clean, 'Đoạn một\nĐoạn hai');
  assert.doesNotMatch(clean, /offset|speaker|người nói|source|nguồn ghi nhận/i);
});

test('preserves ordinary quotes and legitimate source-label prose', () => {
  assert.equal(sanitizeSummaryDisplayText('"Trích dẫn hợp lệ"'), '"Trích dẫn hợp lệ"');
  assert.equal(
    sanitizeSummaryDisplayText('Nguồn ghi nhận: đây là tên một mục nghiệp vụ.'),
    'Nguồn ghi nhận: đây là tên một mục nghiệp vụ.',
  );
});
}
