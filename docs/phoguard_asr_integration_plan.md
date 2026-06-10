# Kế hoạch tích hợp PhoGuard-ASR vào SpeechToInfomation

Ngày lập: 03/05/2026

Phạm vi: worktree `D:\Workspace\SpeechToInfomation-pr`, branch `feature/architecture-refactor-pr`

Tài liệu nguồn đã review:

- `D:\Workspace\SpeechToInfomation\docs\PHOGUARD_ASR_HANDOFF_AND_INTEGRATION_GUIDE_2026-05-03.md`
- `E:\research\Cherry2\cherry_core\docs\paper_pack\PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`
- `E:\research\Cherry2\cherry_core\output\phoguard_asr\paper_readiness_cuda_stronger_paper.json`
- `E:\research\Cherry2\cherry_core\research\phoguard_asr\decision_schema.py`
- `E:\research\Cherry2\cherry_core\research\phoguard_asr\gate.py`
- `E:\research\Cherry2\cherry_core\research\phoguard_asr\risk_features.py`
- `E:\research\Cherry2\cherry_core\research\phoguard_asr\text_metrics.py`

> Nguyên tắc sử dụng: PhoGuard-ASR chỉ là lớp đánh giá độ tin cậy transcript và giảm false-speech/hallucination-proxy. Kết quả không phải xác nhận nội dung audio là đúng tuyệt đối, không phải kết luận giám định, và không thay thế analyst review.

---

## 1. Verdict review nghiên cứu

### 1.1. Kết luận

Nghiên cứu PhoGuard-ASR đủ giá trị để tích hợp vào SpeechToInfomation, nhưng chỉ nên tích hợp phần runtime gate tối thiểu. Không bê benchmark harness, public dataset scripts, paper validators hoặc aggregate readiness scripts vào production app.

PhoGuard giải quyết đúng một lỗ hổng lớn của dự án hiện tại: pipeline sau ASR đang coi transcript là nguồn thật để summarize/visualize/analyze. Nếu ASR hallucinate trên đoạn không lời hoặc nhiễu, các lớp sau sẽ khuếch đại hallucination thành summary, graph hoặc fact. Vì vậy PhoGuard nên đứng ngay sau ASR và trước mọi bước summary/analysis.

### 1.2. Kết quả có thể dùng trong báo cáo

| Lane | Baseline | PhoGuard | Claim an toàn |
|---|---:|---:|---|
| Internal speech macro WER | 0.0689826609 | 0.0689826609 | no-regression trên internal synthetic Vietnamese long-form speech |
| Internal speech micro WER | 0.0692570073 | 0.0692570073 | no-regression trên internal synthetic Vietnamese long-form speech |
| Synthetic B20 false words/min | 157.2 | 0.0 | giảm false-speech proxy bằng abstention |
| Synthetic B20 output rate | 1.0 | 0.0 | giảm output trên non-speech synthetic |
| Public MUSAN false words/min | 105.375 | 8.7 | giảm false-speech proxy, chưa loại bỏ hoàn toàn |
| Public MUSAN output rate | 1.0 | 0.1125 | giảm output trên music/noise public |
| Public VIVOS macro WER | 0.1833718219 | 0.1787214941 | public reproducibility/no-regression, không claim WER improvement |
| Public VIVOS micro WER | 0.1428386428 | 0.1427091427 | public reproducibility/no-regression, không claim WER improvement |

Sampled audit có thể dùng nhưng phải ghi đúng giới hạn:

- 50 paired non-speech source units.
- 100 transcript units.
- Rule-assisted, single annotator.
- Baseline hallucination utterance rate: `1.0`.
- PhoGuard hallucination utterance rate: `0.1`.
- Paired wins: PhoGuard `45`, baseline `0`, ties `5`.
- Exact McNemar/sign-test p-value: `5.684e-14`.

### 1.3. Claim bị chặn

Không dùng các claim sau trong UI, báo cáo hoặc README:

- Không claim PhoGuard là ASR model mới.
- Không claim SOTA ASR tiếng Việt.
- Không claim WER improvement hoặc broad ASR accuracy improvement.
- Không claim loại bỏ hallucination, vì MUSAN vẫn còn residual false words/min.
- Không claim broad field-audio generalization.
- Không claim double-annotated human audit.
- Không claim confidence/risk score là xác suất hiệu chuẩn.
- Không claim denoising, correction, diarization, summary hoặc analysis được cải thiện định lượng nếu chưa có benchmark riêng.
- Không claim GPU nhanh hơn CPU nếu chưa có matched CPU run.

### 1.4. Điểm mạnh để đưa vào dự án

- Có decision schema nghiên cứu rõ: `selected_text`, `review_text`, `abstain_flag`, `selected_condition`, `reason_codes`, `risk_score`, `speech_ratio`, `branch_scores`. Khi đưa vào runtime app, text nhạy cảm phải nằm ở top-level transcript fields, không duplicate trong `phoguard`.
- Gate rule minh bạch, dễ test và không phụ thuộc LLM.
- Có policy tự nhận giới hạn: `risk_score_policy = rule_based_ranking_signal_not_calibration`, `hallucination_label_policy = proxy_metrics_only`.
- Dùng VAD-informed abstention cho case `speech_ratio < 0.05` nhưng ASR vẫn sinh nhiều từ.
- Có repetition và Bag-of-Hallucinations proxy phù hợp với các lỗi Whisper trên non-speech.

### 1.5. Rủi ro cần kiểm soát khi tích hợp

- VAD có thể lỗi hoặc không sẵn model. Nếu thiếu `speech_ratio`, không được abstain dựa trên VAD; chỉ tính text risk features.
- `risk_score` là tín hiệu xếp hạng rule-based, không phải xác suất hallucination.
- Abstain không phải lỗi hệ thống. UI phải hiển thị là "cần nghe lại/duyệt lại".
- Không được mất raw transcript. Analyst phải xem được cả transcript gốc và transcript được chọn.
- Không được log transcript, prompt, raw response hoặc dữ liệu PII.
- Không copy VIVOS/MUSAN/audio benchmark artifacts vào repo app.

### 1.6. Findings từ review trực tiếp `cherry_core`

- `cherry_core` hiện là worktree nghiên cứu đang bẩn; nhiều artifact PhoGuard quan trọng đang untracked. Trước khi tích hợp code vào app, cần chốt source bằng commit/tag hoặc export package có SHA.
- `research/phoguard_asr/*` dùng namespace nghiên cứu (`research.*`, `infrastructure.*`) và không phải production package của SpeechToInfomation. Không import trực tiếp từ đường dẫn `E:\research\Cherry2\cherry_core` trong runtime app.
- `risk_features.py` phụ thuộc `infrastructure.adapters.asr.hallucination_filter.HallucinationFilter`; khi port sang app phải dùng namespace `src.cherry_core...` hoặc copy allowlist BoH tối thiểu để giữ import-safe.
- `artifacts.py` có hàm thu thập environment import `torch`; không đưa module này vào runtime PhoGuard service vì mục tiêu import-safe của API startup.
- `gate.py` đang nhận `speech_ratio: float`, trong khi runtime app phải hỗ trợ `speech_ratio=None`. Khi port cần thêm nhánh missing-VAD rõ ràng.
- `SCHEMA_VERSION = "phoguard_asr.benchmark.v1"` trong `decision_schema.py` chỉ dùng cho benchmark. Runtime app phải dùng `phoguard_asr.runtime.v1`.
- `tests/test_phoguard_asr.py` có nhiều test hữu ích cho logic gate/readiness, nhưng cũng import benchmark scripts/plot/validators. Production app chỉ nên port subset test cho runtime gate, không kéo toàn bộ benchmark suite.

---

## 2. Vị trí tích hợp trong kiến trúc dự án

### 2.1. Luồng hiện tại cần chèn PhoGuard

Entry point code hiện tại:

- `src/services/transcription/transcribe_service_v2.py`
- `src/services/transcription/cherry_transcription_service.py`
- `src/cherry_core/adapters/asr/whisperv2_adapter.py`
- `src/cherry_core/adapters/vad/silero_adapter.py`
- `src/api/endpoints/audio_v2.py`
- `src/services/task_service.py`
- `frontend/src/App.tsx`
- `frontend/src/components/AnalysisPanel.tsx`

Luồng mục tiêu:

```text
AudioFile
  -> transcribe_audio_v2
  -> CherryTranscriberService / WhisperV2Adapter / PhoWhisperAdapter
  -> raw segments + raw transcript
  -> PhoGuardRuntimeService.analyze(...)
  -> Task.result:
       raw_transcription
       review_transcription
       transcription follows rollout mode:
         off|shadow|failed = raw_transcription
         enforce + accepted|needs_review = selected transcript
         enforce + abstained = empty string, raw_transcription preserved
       phoguard
       needs_review
       warnings
  -> shadow mode never blocks summary/analysis
  -> enforce mode can block summary/analysis until review or forced override
```

### 2.2. Module runtime đề xuất

Không đưa `research/phoguard_asr/*` nguyên xi vào production namespace. Tạo runtime service mỏng:

```text
src/cherry_core/services/phoguard_service.py
src/cherry_core/services/phoguard_schema.py
src/cherry_core/services/phoguard_features.py
```

Hoặc nếu muốn tách rõ domain:

```text
src/cherry_core/phoguard/
  __init__.py
  schema.py
  features.py
  gate.py
  runtime_service.py
```

Khuyến nghị phase đầu: dùng `src/cherry_core/services/phoguard_service.py` để giảm refactor.

### 2.3. Không tích hợp vào production

Không copy các phần này vào runtime app:

- `scripts/benchmark_phoguard_asr.py`
- `scripts/aggregate_phoguard_readiness.py`
- `scripts/prepare_phoguard_public_manifest.py`
- `scripts/validate_phoguard_artifacts.py`
- public VIVOS/MUSAN manifests/audio files
- paper validators, plot scripts, manual audit sheets
- benchmark profiles chỉ phục vụ bài báo

Các phần này chỉ được tham chiếu trong tài liệu nghiên cứu và phụ lục báo cáo.

---

## 3. Runtime data contract

### 3.1. Schema version riêng cho production

Benchmark schema hiện là:

```text
phoguard_asr.benchmark.v1
```

Production runtime phải dùng schema riêng:

```text
phoguard_asr.runtime.v1
```

Lý do: benchmark artifact có run/provenance fields phục vụ paper; runtime payload cần nhỏ, ổn định, không kéo dataset/paper concerns vào app.

### 3.2. PhoGuard payload trong `Task.result`

`phoguard` không lưu full transcript để giảm rủi ro leak qua log/debug/status payload. Text nhạy cảm chỉ nằm ở top-level `transcription`, `raw_transcription`, `review_transcription` và phải đi qua access control hiện có.

```json
{
  "schema_version": "phoguard_asr.runtime.v1",
  "status": "accepted|needs_review|abstained|failed|disabled",
  "abstain_flag": false,
  "selected_condition": "raw_current|filtered|abstain_needs_review",
  "reason_codes": ["raw_current_lowest_or_tie"],
  "risk_score": 0.0,
  "coverage": 1.0,
  "speech_ratio": 0.83,
  "selected_text_sha256": "hex-or-null",
  "review_text_sha256": "hex-or-null",
  "selected_text_length": 1200,
  "review_text_length": 1200,
  "selected_word_count": 220,
  "review_word_count": 220,
  "features": {
    "word_count": 120,
    "words_per_sec": 1.7,
    "repeated_3gram_ratio": 0.0,
    "repeated_8gram_hits": 0,
    "boh_hit_count": 0,
    "non_speech_mismatch": false
  },
  "policy": {
    "risk_score_policy": "rule_based_ranking_signal_not_calibration",
    "hallucination_label_policy": "proxy_metrics_only"
  },
  "warnings": []
}
```

### 3.2.1. Runtime schema validation

Implement bằng Pydantic, không dùng dict tự do.

Required constraints:

- `status`: `Literal["accepted", "needs_review", "abstained", "failed", "disabled"]`.
- `selected_condition`: `Literal["raw_current", "filtered", "abstain_needs_review", "disabled", "failed"]`.
- `reason_codes`: allowlist enum, ví dụ `raw_current_lowest_or_tie`, `low_speech_ratio_with_output`, `repetition_risk`, `boh_hit_filtered`, `missing_speech_ratio`, `phoguard_failed`; max 10 items.
- `risk_score`, `coverage`: clamp/enforce `[0, 1]`.
- `speech_ratio`: `float | None`, nếu có thì `[0, 1]`.
- `features`: allowlist keys only, không cho arbitrary reason text.
- `warnings`: enum/short code list, max 10 items.
- Không có field `selected_text`, `review_text`, `raw_text`, `segment_text` bên trong `phoguard`.

### 3.3. Task result fields

Thêm vào `Task.result`:

```json
{
  "transcription": "selected transcript dùng cho pipeline tiếp theo",
  "raw_transcription": "raw ASR transcript không chỉnh sửa",
  "review_transcription": "text analyst cần xem lại, thường là raw transcript",
  "phoguard": {},
  "needs_review": false,
  "asr_reliability": {
    "status": "accepted|needs_review|abstained|disabled|failed",
    "reason_codes": [],
    "risk_score": 0.0
  },
  "asr_review_status": "unreviewed|confirmed|rejected",
  "asr_reviewed_by": null,
  "asr_reviewed_at": null,
  "asr_review_note": null,
  "asr_review_revision": 0,
  "asr_override_status": "none|forced",
  "asr_forced_by": null,
  "asr_forced_at": null,
  "asr_forced_reason_code": null,
  "warnings": []
}
```

Backward compatibility:

- `transcription` vẫn tồn tại để summary/analysis cũ không vỡ.
- `raw_transcription` không bao giờ bị xóa khi PhoGuard chọn text rỗng.
- `formatted_transcript` giữ theo raw segments, nhưng UI phải biết text chính có thể là selected transcript.

### 3.4. Segment-level extension

Phase đầu có thể file-level gate. Sau đó mở rộng segment-level:

```json
{
  "segments": [
    {
      "segment_id": "seg_001",
      "start": 0.0,
      "end": 8.2,
      "speaker": "SPEAKER_00",
      "phoguard": {
        "status": "accepted|needs_review|abstained",
        "reason_codes": [],
        "risk_score": 0.0
      }
    }
  ]
}
```

Segment-level rất hữu ích cho long audio, nhưng không bắt buộc cho MVP.

Nếu segment `text` đang tồn tại vì compatibility trong `segments`, không trả segment text ở file list/status/task polling/dashboard và không log. Nested `segment.phoguard` không bao giờ chứa transcript text hoặc raw text.

---

## 4. Runtime behavior

### 4.1. Decision policy

```text
if PHOGUARD_MODE=off:
    status = disabled
    transcription = raw_transcription

if PHOGUARD_MODE=shadow:
    calculate phoguard/asr_reliability only
    transcription = raw_transcription
    do not block summary/analysis
    do not mark existing workflow failed

if PHOGUARD_MODE=enforce and PhoGuard lỗi runtime:
    status = failed
    transcription = raw_transcription
    warnings += ["phoguard_failed"]
    không fail toàn bộ transcribe

if PHOGUARD_MODE=enforce and abstain_flag=true:
    status = abstained
    transcription = ""
    raw_transcription = raw ASR output
    review_transcription = raw ASR output
    needs_review = true

if PHOGUARD_MODE=enforce and high risk but not abstained:
    status = needs_review
    transcription = selected_text
    needs_review = true

if PHOGUARD_MODE=enforce and accepted:
    status = accepted
    transcription = selected_text
    needs_review = false
```

### 4.2. VAD policy

`src/cherry_core/adapters/vad/silero_adapter.py` đã có `get_speech_ratio(audio_path)`.

Policy:

- Nếu Silero load thành công: dùng `speech_ratio`.
- Nếu Silero thiếu model/lỗi import/lỗi runtime: ghi warning, set `speech_ratio=null`.
- Nếu `speech_ratio=null`: tắt VAD-informed abstention, vẫn tính repetition/BoH/text features.
- Không để VAD failure làm fail transcribe.

### 4.3. Summary/analysis gating

`/api/v1/audio/v2/summarize/{task_id}` và `/api/v1/audio/v2/visualize/{task_id}` cần behavior:

- Shadow mode không block và không overwrite transcript. Enforcement chỉ áp dụng khi `PHOGUARD_MODE=enforce`.
- Nếu `phoguard.status=abstained` và config block tương ứng bật, trả `409 Conflict`.
- Nếu `Task.result.needs_review=true` và config block needs-review tương ứng bật, trả `409 Conflict`.
- Error body luôn có `task_id`, `phoguard.status`, `needs_review`, `reason_codes`:
  - "Transcript cần duyệt lại trước khi tóm tắt/phân tích."
- Không dùng `400` cho trạng thái này vì đây là conflict workflow, không phải malformed request.
- Cho phép override có chủ đích sau khi có review workflow:
  - transcript đã `asr_review_status=confirmed`; hoặc
  - `POST /api/v1/audio/v2/transcriptions/{task_id}/override` với quyền `write`, `expected_revision`, reason code allowlist, audit riêng.
- Nếu vẫn chạy analysis trên transcript needs-review, mọi fact/slot/relation/event/claim phải `requires_review=true`.
- Nếu `abstained`, không emit critical relation/fact tự động.

### 4.3.1. Transcript review endpoint

Không dùng `force_after_review=true` như bypass đơn lẻ nếu chưa có trạng thái review bền vững. Thêm endpoint:

```text
PATCH /api/v1/audio/v2/transcriptions/{task_id}/review
```

Request:

```json
{
  "review_status": "confirmed|rejected",
  "review_note": "ghi chú nội bộ tùy chọn",
  "expected_revision": 0
}
```

Rules:

- Yêu cầu `assert_task_access(..., "write")`.
- Case archived thì không cho sửa.
- Dùng `asr_review_revision` để tránh lost update; mismatch trả `409` kèm current revision.
- Audit chỉ ghi `task_id`, `audio_id`, `review_status`, `revision`, `user_id`; không ghi transcript/review note vào audit log.
- `review_note` được lưu trong case-authorized `Task.result`, nhưng không log.

### 4.3.2. Forced override endpoint

Forced override không phải review xác nhận nội dung đúng. Nó chỉ là quyết định vận hành cho phép workflow chạy tiếp trong trạng thái có rủi ro.

```text
POST /api/v1/audio/v2/transcriptions/{task_id}/override
```

Request:

```json
{
  "forced_reason_code": "urgent_case|supervisor_approved|manual_audio_reviewed|other_policy_approved",
  "expected_revision": 0
}
```

Rules:

- Yêu cầu `assert_task_access(..., "write")`.
- Case archived thì không cho sửa.
- `expected_revision` bắt buộc; mismatch trả `409` kèm current revision.
- `forced_reason_code` là enum allowlist, không phải free-text.
- Lưu `asr_override_status=forced`, `asr_forced_by`, `asr_forced_at`, `asr_forced_reason_code`.
- Audit không ghi transcript, review note, prompt hoặc free-text.
- Forced không mở khóa critical facts/relations như accepted. Nếu workflow chạy tiếp từ forced state, mọi extracted item phải `requires_review=true`, critical relation/fact không được auto-confirm.

### 4.3.3. Transcript detail endpoint

Transcript text chỉ được trả qua endpoint detail chuyên dụng:

```text
GET /api/v1/audio/v2/transcriptions/{task_id}
```

Rules:

- Yêu cầu `assert_task_access(..., "read")`.
- Response chỉ gồm transcript fields cần thiết: `transcription`, `raw_transcription`, `review_transcription`, hashes/length/count và ASR reliability metadata.
- Không kèm full `Task.result`, `visualization_data`, summary, analysis graph hoặc unrelated case data.
- Headers bắt buộc: `Cache-Control: no-store`, `Pragma: no-cache`.
- Không ghi transcript text vào audit, access log, app log hoặc error detail.

### 4.4. Interaction với Analysis Intelligence V2

Analysis V2 phải đọc metadata PhoGuard:

- `model_info.asr_reliability_status`
- `model_info.phoguard_schema_version`
- `warnings[]`

Rules:

- Nếu `phoguard.status=abstained`, deterministic extraction chỉ chạy khi analyst đã confirm transcript hoặc override.
- Nếu `phoguard.status=needs_review`, facts/slots lấy từ transcript phải `requires_review=true`.
- Critical relation/event không emit nếu ASR reliability chưa accepted.
- Evidence refs vẫn trỏ về segments, nhưng UI hiển thị warning "Transcript cần kiểm chứng".

---

## 5. Config và môi trường

Thêm vào `src/core/config.py` và `.env.example`:

```env
PHOGUARD_MODE=shadow
PHOGUARD_BLOCK_SUMMARY_ON_ABSTAIN=true
PHOGUARD_BLOCK_SUMMARY_ON_NEEDS_REVIEW=false
PHOGUARD_BLOCK_ANALYSIS_ON_ABSTAIN=true
PHOGUARD_BLOCK_ANALYSIS_ON_NEEDS_REVIEW=false
PHOGUARD_LOW_SPEECH_RATIO_THRESHOLD=0.05
PHOGUARD_HIGH_RISK_THRESHOLD=0.65
PHOGUARD_GATE_VARIANT=phoguard_text_gate
PHOGUARD_USE_SILERO_SPEECH_RATIO=true
```

`PHOGUARD_MODE`:

- `off`: không chạy PhoGuard.
- `shadow`: default an toàn; tính `phoguard/asr_reliability`, không overwrite `transcription`, không block summary/analysis.
- `enforce`: cho phép selected transcript, abstain, needs-review, block summary/analysis theo config.

`PHOGUARD_HIGH_RISK_THRESHOLD=0.65` chỉ là default pilot. Không bật `PHOGUARD_MODE=enforce` cho môi trường chính cho tới khi shadow pilot hoàn tất:

- Ít nhất `>=30` audio files hoặc `>=2` giờ audio, chọn mức lớn hơn nếu có thể.
- Bộ pilot phải có speech sạch, noisy speech, silence/non-speech, music/noise và audio thực tế đã được phép dùng.
- Ghi distribution của `risk_score`, `speech_ratio`, `reason_codes`.
- Review mẫu false abstain và false accept.
- Threshold/sign-off được ghi vào manifest với ngày, reviewer, sample size, false abstain rate, false accept sample notes và threshold đã chọn.

Không thêm API key cho PhoGuard vì đây là rule-based runtime. API key online vẫn thuộc nhóm `ANALYSIS_LLM_*`:

```env
ANALYSIS_LLM_PROVIDER=ollama
ANALYSIS_LLM_BASE_URL=http://localhost:11434
ANALYSIS_LLM_MODEL=gpt-oss
ANALYSIS_LLM_API_KEY=
ANALYSIS_LLM_TIMEOUT_SECONDS=60
ANALYSIS_LLM_MAX_INPUT_CHARS=24000
```

---

## 6. UI/UX cần bổ sung

### 6.1. Transcript panel

Hiển thị:

- Badge: `Đã chấp nhận`, `Cần duyệt lại`, `Đã abstain`, `PhoGuard lỗi`, `PhoGuard tắt`.
- Reason codes tiếng Việt.
- Risk score với wording: "Điểm rủi ro rule-based, không phải xác suất."
- Toggle raw/selected:
  - "Transcript dùng cho phân tích"
  - "Transcript gốc từ ASR"
- Nếu abstained: empty selected transcript không phải lỗi UI; hiện message cần nghe lại.

### 6.2. File table/card

Thêm cột/badge:

- `ASR: OK`
- `ASR: Cần duyệt`
- `ASR: Không đủ tin cậy`

Nút Summary/Analysis:

- Trong `shadow` mode: không disable, chỉ hiển thị cảnh báo ASR reliability.
- Trong `enforce` mode: disable hoặc show confirm dialog khi `needs_review=true` theo config.
- Không tự POST summary/visualize khi task đang `abstained` trong `enforce` mode.
- Nếu cần chạy tiếp, user phải confirm transcript qua review endpoint hoặc dùng forced action có audit.
- Forced action là override vận hành riêng, không làm transcript trở thành accepted.

### 6.3. Analysis workspace

Trong `AnalysisPanel`:

- Overview hiện banner nếu source transcript needs-review.
- Evidence/facts hiển thị `source_method` kèm reliability status.
- Fact từ transcript needs-review mặc định có review status `needs_review`.

---

## 7. Security, privacy và audit

### 7.1. Logging

Được log:

- `task_id`
- `audio_id`
- `phoguard.status`
- `reason_codes` từ allowlist enum, không phải free-text
- `risk_score`
- `speech_ratio`
- counts/latency

Không được log:

- raw transcript
- selected transcript
- segment text
- phone/email/ID/money extracted
- API key
- local absolute path

### 7.2. Audit

Audit các action:

- `phoguard_decision_created`
- `asr_transcript_reviewed`
- `phoguard_review_overridden`
- `summary_blocked_by_phoguard`
- `analysis_blocked_by_phoguard`
- `summary_forced_override`
- `analysis_forced_override`

Audit payload chỉ ghi IDs/status/reason count/revision, không ghi transcript text hoặc review note.

### 7.3. Dataset và artifact boundary

- Không đưa VIVOS/MUSAN/public audio vào app repo.
- Không đưa output benchmark lớn vào production image.
- Báo cáo khoa học được trích dẫn từ `cherry_core` artifact.
- SpeechToInfomation chỉ lưu system integration test artifacts của chính app.

---

## 8. Lộ trình tích hợp

### Phase P0: Source lock và claim cleanup

Mục tiêu: chốt đúng phạm vi khoa học trước khi code.

Tasks:

1. Chốt source PhoGuard từ `cherry_core`:
   - commit/tag sạch hoặc export zip/package;
   - ghi `source_repo`, `source_commit`, `source_files`, `source_sha256` vào tài liệu tích hợp;
   - không port từ worktree nghiên cứu chưa được freeze.
2. Tạo/cập nhật source manifest trong repo app, ví dụ `docs/phoguard_asr_source_manifest.md`.
3. Copy hoặc link handoff doc vào `SpeechToInfomation-pr/docs/`.
4. Thêm claim matrix ngắn vào báo cáo NCKH:
   - allowed claims
   - blocked claims
   - dataset provenance
5. Cập nhật `docs/phuong_an_nang_cap_trinh_sat_am_thanh.md` để PhoGuard là Phase 2A trong ASR reliability.

Acceptance:

- Không có câu "loại bỏ ảo giác" hoặc "tăng WER" trong báo cáo/UI.
- Tài liệu phân biệt rõ benchmark schema và runtime schema.
- `P1` bị block cho tới khi source manifest có `source_commit` hoặc `source_sha256` đầy đủ.
- Nếu source chưa freeze, tài liệu phải ghi rõ `implementation_blocked=true`.

### Phase P1: PhoGuard runtime service

Mục tiêu: tạo service rule-based, import-safe, không kéo benchmark code.

Blocker: không bắt đầu P1 nếu `docs/phoguard_asr_source_manifest.md` chưa có source commit/SHA hoặc exported package SHA.

Tasks:

1. Tạo `phoguard_service.py`, `phoguard_schema.py`, `phoguard_features.py`.
2. Port/adapt:
   - word count/text metrics
   - repeated n-gram features
   - BoH hit count
   - non-speech mismatch
   - gate decision
3. Dùng `schema_version = "phoguard_asr.runtime.v1"`.
4. Implement Pydantic schema với enum/allowlist/size limit.
5. Không import ASR model nặng ở module import time.
6. Không port `artifacts.py`, benchmark scripts, validators, plot code hoặc dataset preparation code vào runtime.

Acceptance:

- Fresh import `src.cherry_core.services.phoguard_service` không load `torch`, `faster_whisper`, `pyannote.audio`.
- Unit test low speech + output -> `abstained`.
- Unit test missing speech_ratio -> no VAD-informed abstain.
- Unit test repetition/BoH reason codes.

### Phase P2: Transcribe pipeline integration

Mục tiêu: PhoGuard quyết định transcript nào đi tiếp.

Tasks:

1. Gắn vào `transcribe_audio_v2()` sau khi có `full_transcript`, `segments`, `duration`.
2. Optional: gắn trong `CherryTranscriberService` nếu muốn return raw/final/phoguard cùng lúc.
3. Tính `speech_ratio` bằng Silero nếu `PHOGUARD_USE_SILERO_SPEECH_RATIO=true`.
4. Lưu `raw_transcription`, `review_transcription`, `transcription`, `phoguard`, `needs_review`, `asr_review_*`.
5. API status/list/polling/dashboard chỉ trả `phoguard`, `needs_review`, hash/length/count và reliability metadata; transcript text bị loại khỏi các response này.
6. Thêm detail endpoint `GET /api/v1/audio/v2/transcriptions/{task_id}` cho raw/selected/review transcript only.
7. Default rollout là `PHOGUARD_MODE=shadow`, không overwrite `transcription`.

Acceptance:

- Raw transcript không mất khi selected transcript rỗng.
- PhoGuard lỗi không làm transcribe fail.
- Existing frontend vẫn đọc được `transcription`.
- Shadow mode không đổi output hiện tại.
- Status/list không leak raw transcript.
- Không log transcript trong path lỗi.

### Phase P3: Transcript review endpoint

Mục tiêu: có trạng thái review bền vững trước khi enforcement.

Tasks:

1. Thêm `PATCH /api/v1/audio/v2/transcriptions/{task_id}/review`.
2. Lưu `asr_review_status`, `asr_reviewed_by`, `asr_reviewed_at`, `asr_review_note`, `asr_review_revision`.
3. Thêm `POST /api/v1/audio/v2/transcriptions/{task_id}/override`.
4. Lưu `asr_override_status`, `asr_forced_by`, `asr_forced_at`, `asr_forced_reason_code`.
5. Concurrency bằng `expected_revision`; mismatch trả `409`.
6. Audit action không PII.

Acceptance:

- Confirm/reject review persist qua hard refresh.
- Forced override persist riêng, không đổi `asr_review_status` thành confirmed.
- Archived case không cho sửa.
- Audit không ghi transcript hoặc review note.

### Phase P4: Gate summary và analysis

Mục tiêu: chặn amplification của hallucinated transcript khi bật enforcement.

Tasks:

1. Sửa `/summarize/{task_id}`:
   - block `abstained` theo `PHOGUARD_BLOCK_SUMMARY_ON_ABSTAIN`.
   - block `needs_review` theo `PHOGUARD_BLOCK_SUMMARY_ON_NEEDS_REVIEW`.
   - trả `409 Conflict` với error message tiếng Việt.
2. Sửa `/visualize/{task_id}`:
   - block `abstained` theo `PHOGUARD_BLOCK_ANALYSIS_ON_ABSTAIN`.
   - block `needs_review` theo `PHOGUARD_BLOCK_ANALYSIS_ON_NEEDS_REVIEW`.
   - nếu override, Analysis V2 mark all extracted items `requires_review=true`.
3. Thêm audit action không PII.

Acceptance:

- Abstained task không tự summary/analysis.
- Needs-review policy tách khỏi abstained policy.
- Override chỉ sau review confirmed hoặc forced action có audit.
- Forced override giữ mọi downstream item `requires_review=true`.
- Critical relations không emit từ transcript chưa accepted.

### Phase P5: UI review controls tối thiểu

Mục tiêu: analyst hiểu được vì sao hệ thống không tin transcript.

Tasks:

1. Transcript panel: badge, reason codes, raw/selected toggle.
2. File table/card: ASR reliability badge.
3. Transcript review controls: confirm/reject with note, plus separate forced override action with allowlisted reason.
4. Summary/Analysis buttons: disabled/warning khi needs-review trong enforce mode.
5. Analysis Overview: banner "Transcript cần duyệt lại".

Acceptance:

- Không dùng wording "xác suất hallucination".
- User thấy raw transcript khi selected rỗng.
- Hard refresh vẫn giữ trạng thái PhoGuard.
- Review status/revision hiển thị đúng sau reload.
- Forced override status hiển thị riêng với review status.

### Phase P6: Tests và fixtures

Mục tiêu: CI bắt regression.

Tests bắt buộc:

- `test_phoguard_features.py`
  - repeated n-gram ratio
  - BoH hit count
  - non-speech mismatch
- `test_phoguard_runtime.py`
  - accepted transcript
  - abstain low speech + output
  - missing speech_ratio
  - runtime failure fallback
  - schema rejects free-text reason code
  - shadow mode does not overwrite transcript
- `test_transcribe_phoguard_integration.py`
  - stores raw/selected/phoguard
  - no raw transcript loss
  - status/list omit raw transcript
  - detail endpoint returns transcript only with `Cache-Control: no-store` and `Pragma: no-cache`
- `test_summary_analysis_phoguard_gate.py`
  - summary blocked on abstain
  - summary not blocked in shadow mode
  - needs-review block controlled by separate config
  - visualize blocked on abstain
  - override audit path
- `test_asr_review_endpoint.py`
  - review persist
  - forced override persists separately from review status
  - revision mismatch returns 409
  - archived case blocked
- Docs/contract checks:
  - high-level flow block must not contain a generic `transcription = selected_text` line.
  - review status contract must keep forced override separate from review confirmation.
  - transcribe integration contract must keep transcript text out of list/status/polling/dashboard responses.
- Frontend build:
  - `cmd /c "cd frontend && npm run build"`

Fixtures:

- short synthetic non-speech placeholder
- repeated hallucination text
- normal Vietnamese speech transcript
- hotel booking sample from current project

### Phase P7: Báo cáo và pilot

Mục tiêu: đưa vào báo cáo sinh viên NCKH và pilot app.

Tasks:

1. Chương 1/2 lấy benchmark từ `cherry_core`.
2. Chương 3 mô tả tích hợp runtime trong `SpeechToInfomation`.
3. Chương 4 chỉ claim system integration:
   - UI hiển thị trạng thái PhoGuard
   - summary/analysis bị chặn khi abstain
   - tests pass
   - no PII logs
4. Pilot với audio thực tế đã được phép dùng, ghi rõ giới hạn.

Acceptance:

- Báo cáo phân biệt "proxy hallucination reduction" và "actual forensic truth".
- Không có public dataset artifact trong app repo.

---

## 9. Bổ sung vào roadmap trinh sát âm thanh

PhoGuard nên được chèn vào roadmap hiện tại như Phase 2A:

```text
Phase 1: Evidence ledger và Audio Quality Report
Phase 2: Benchmark ASR tiếng Việt và engine selector
Phase 2A: PhoGuard-ASR runtime reliability gate
Phase 3: Forced alignment và diarization nâng cao
Phase 4: General/domain analysis engine và LLM structured extraction
Phase 5: UI Analyst Workspace và Domain Template UI
```

Tác động đến các phase:

- Phase 1 cần lưu audio quality/speech ratio để PhoGuard dùng.
- Phase 2 benchmark chọn ASR engine; PhoGuard không thay ASR engine.
- Phase 3 alignment giúp PhoGuard/Analysis chạy segment-level tốt hơn.
- Phase 4 LLM chỉ chạy trên transcript accepted hoặc transcript đã được analyst override.
- Phase 5 UI phải coi ASR reliability là phần đầu tiên của evidence chain.

---

## 10. Nguồn đối chiếu ngoài repo

- VIVOS Vietnamese Speech Corpus, license CC BY-NC-SA 4.0: https://zenodo.org/records/7068130
- MUSAN corpus cho music/speech/noise và VAD/music-speech discrimination: https://arxiv.org/abs/1510.08484
- WhisperX word-level timestamps bằng VAD + forced alignment: https://arxiv.org/abs/2303.00747
- Whisper non-speech hallucination và Bag of Hallucinations: https://arxiv.org/abs/2501.11378
- OpenAI Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
- Ollama Structured Outputs: https://docs.ollama.com/capabilities/structured-outputs
- LangExtract source-grounded extraction: https://github.com/google/langextract
