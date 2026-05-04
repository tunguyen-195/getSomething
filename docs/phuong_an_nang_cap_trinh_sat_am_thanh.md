# Phương án nâng cấp dự án theo hướng trinh sát âm thanh có căn cứ chứng cứ

Ngày lập: 03/05/2026

Phạm vi: worktree `D:\Workspace\SpeechToInfomation-pr`, branch `feature/architecture-refactor-pr`

Mục tiêu: chuyển SpeechToInformation từ hệ thống "transcribe + summary + visualization" thành workspace phân tích âm thanh hợp pháp, có căn cứ chứng cứ, đo lường được, ưu tiên tiếng Việt và hỗ trợ analyst review.

> Nguyên tắc sử dụng: hệ thống chỉ hỗ trợ phân tích audio đã được thu thập, lưu trữ và truy cập hợp pháp theo case. Kết quả AI là gợi ý có evidence, không phải kết luận pháp lý hay kết quả giám định cuối cùng.

---

## 1. Review kết luận nghiên cứu hiện tại

### 1.1. Điểm đúng hướng

- Analysis V2 đã chọn đúng hướng: `schema_version`, `graph_revision`, `EvidenceRef`, `review_status`, `legacy_view` generated server-side.
- Deterministic extractor tiếng Việt đã cải thiện mạnh so với visualization rỗng: bắt được phone, email candidate, CCCD candidate, ngày, tiền, số lượng, payment, purpose, offer, policy.
- Domain Template Registry backend là nền móng đúng: scope `global|user|case`, draft/published/archived, immutable published version, schema hash, audit.
- Clip endpoint đã đúng hướng privacy: auth, path safety, duration cap, ffmpeg argv list, `Cache-Control: no-store`, filename generic.
- Research sources phù hợp: Whisper/faster-whisper/PhoWhisper cho ASR, Pyannote/Sortformer/Diart cho diarization, WhisperX/forced alignment cho timestamp, GraphRAG/LangExtract cho provenance, SWGDE/Frontiers cho giới hạn forensic ASR.

### 1.2. Điểm cần chỉnh trong báo cáo/nghiên cứu

1. `ORG_RE` vẫn lỗi thật: probe hiện tại vẫn extract `G.R.P.Marius Hotel Hà Nội Rất`. Đây là bug ưu tiên phase 0.
2. `WhisperXPipeline` trong code chưa phải WhisperX forced alignment; cần đổi tên hoặc implement thật, tránh overclaim.
3. Các hàm `enhance_speech_llase`, `enhance_speech_sepalm`, `enhance_speech_wavlm` vẫn là placeholder; không được coi là speech enhancement đã triển khai.
4. "Speaker identification/cross-case analytics" là năng lực nhạy cảm. Không bật mặc định. Chỉ đưa vào module tùy chọn khi có enrollment hợp pháp, threshold calibration, audit và human verification.
5. Domain Template Registry hiện mới là backend CRUD; chưa có UI builder, selector, runtime slot extraction.
6. LLM config đã có nhưng chưa có LLM gateway evidence-bound; chưa nên claim "structured extraction" đã chạy.
7. Summary/forensic prompt cũ có thể hữu ích để đọc hiểu, nhưng không được làm nguồn truth cho graph.

---

## 2. Kiến trúc mục tiêu

### 2.1. Luồng xử lý mục tiêu

1. **Ingest hợp pháp**
   - Upload audio vào case.
   - Validate bằng `ffprobe`.
   - Tạo hash file gốc.
   - Ghi artifact ledger.

2. **Audio QC**
   - Đo sample rate, channel, codec, duration.
   - Đo clipping, RMS, silence/speech ratio, SNR proxy, DC offset.
   - Sinh warning: audio quá nhiễu, quá im, clipping, không đủ speech.

3. **Optional enhancement**
   - Chỉ chạy khi user bật hoặc rule QC đề xuất.
   - Không overwrite audio gốc.
   - Lưu artifact enhanced + hash + tool version + config.
   - ASR có thể chạy trên enhanced audio, nhưng evidence luôn truy về audio gốc và transcript span.

4. **ASR engine registry**
   - Engine: faster-whisper, Cherry Whisper V2, PhoWhisper, optional NeMo.
   - Benchmark theo fixture tiếng Việt.
   - Lưu `asr_engine`, `model_id`, `model_version`, `decode_params`, `runtime`.
   - Nếu nhiều engine mâu thuẫn ở PII/số tiền/ngày, tạo risk flag.

5. **Alignment + diarization**
   - Forced alignment thật để có word-level timestamps.
   - Pyannote Community-1 baseline.
   - Optional Sortformer/NeMo provider.
   - Gán speaker theo word/segment confidence, đánh dấu overlap/uncertain.

6. **Analysis Intelligence V2**
   - Deterministic core luôn chạy.
   - Domain overlay chạy khi chọn template.
   - LLM second pass chỉ khi bật và phải structured/evidence-bound.
   - Mọi fact/slot/relation/event/claim có evidence refs, confidence, reason, source method, review status.

7. **Analyst workspace**
   - Overview tiếng Việt.
   - Evidence inspector có transcript span, timestamp, speaker, play clip.
   - Review actions: confirm/reject/edit/merge/split.
   - Domain template UI.
   - Export báo cáo có hash, model version, review status.

### 2.2. Data model đề xuất

Giữ backward compatibility với `Task.result.visualization_data`, nhưng thêm dữ liệu vận hành rõ hơn.

**Option A: phase đầu lưu trong JSON**

Thêm vào `Task.result`:

```json
{
  "audio_artifacts": [],
  "audio_quality": {},
  "asr_runs": [],
  "alignment_runs": [],
  "analysis_runs": []
}
```

Ưu điểm: ít migration, nhanh. Nhược điểm: khó query/audit/export ở quy mô lớn.

**Option B: DB chuẩn hơn**

Thêm bảng:

- `audio_artifacts`
- `audio_quality_reports`
- `analysis_runs`

Khuyến nghị: Phase 1 dùng JSON để giảm rủi ro PR; sau pilot chuyển sang DB nếu dữ liệu lớn hoặc cần audit truy vấn.

### 2.3. Artifact schema tối thiểu

```json
{
  "id": "art_original_<hash>",
  "audio_id": 303,
  "task_id": "uuid",
  "kind": "original|normalized|enhanced|asr_input|clip",
  "parent_artifact_id": null,
  "relative_path": "cases/549/xxx.wav",
  "sha256": "hex",
  "size_bytes": 123456,
  "codec": "pcm_s16le",
  "sample_rate": 16000,
  "channels": 1,
  "duration_seconds": 92.4,
  "tool": "ffmpeg|deepfilternet|rnnoise|upload",
  "tool_version": "string",
  "config": {},
  "created_at": "iso8601"
}
```

### 2.4. LLM provider credential policy

Vì user cần thêm API key dịch vụ online khi cần, chia làm 2 mức:

**MVP an toàn**

- Chỉ dùng env:
  - `ANALYSIS_LLM_PROVIDER`
  - `ANALYSIS_LLM_BASE_URL`
  - `ANALYSIS_LLM_MODEL`
  - `ANALYSIS_LLM_API_KEY`
  - `ANALYSIS_LLM_TIMEOUT_SECONDS`
  - `ANALYSIS_LLM_MAX_INPUT_CHARS`
- Không log prompt/transcript/raw response/API key.
- UI chỉ hiển thị provider/model/status, không hiển thị key.

**Nâng cấp sau**

- Bảng encrypted credentials theo `user|case|global`.
- Key mã hóa bằng app secret/KMS.
- RBAC: chỉ owner/admin/case manager được tạo/sửa.
- Audit chỉ ghi provider, scope, action, không ghi key.

---

## 3. Lộ trình triển khai theo phase

## Phase 0: Sửa sai số hiện tại và khóa overclaim

Mục tiêu: làm sạch các lỗi chất lượng rõ ràng trước khi mở rộng.

### Việc cần làm

1. Fix `ORG_RE` không ăn quá tên khách sạn.
   - File: `src/services/analysis_intelligence/extractor.py`
   - Ví dụ phải pass: `G.R.P.Marius Hotel Hà Nội`, không lấy `Rất`.
   - Thêm stop words sau org: `rất`, `vâng`, `cảm`, `xin`, `chúc`, `hân`, `phục`, `chị`, `anh`, `em`.

2. Đổi tên `WhisperXPipeline` nếu chưa implement forced alignment.
   - File: `src/audio_processing/diarization/whisperx.py`
   - Đề xuất tên: `PyannoteOverlapDiarizationPipeline`.
   - Giữ alias deprecated nếu sợ vỡ import.

3. Đánh dấu enhancement placeholder rõ trong UI/report/log.
   - File: `src/audio_processing/processor.py`
   - Không gọi `enhance_speech_llase()` như thể đang enhance thật trong path production nếu chưa có provider.

4. Cập nhật báo cáo NCKH:
   - "speaker identification" -> "speaker verification/enrollment tùy chọn, bị khóa bởi policy".
   - "WhisperXPipeline" -> "pyannote overlap wrapper hiện tại".

### Acceptance gates

- `python -m pytest tests/test_analysis_intelligence.py -q`
- Test extractor không còn org `... Rất`.
- `rg "enhance_speech_llase" src` không còn path production im lặng gọi placeholder như tính năng thật.

---

## Phase 1: Evidence ledger và Audio Quality Report

Mục tiêu: mọi xử lý audio có nguồn gốc, hash, tool version, config.

### Backend tasks

1. Tạo module `src/services/audio_quality.py`.
   - Input: audio path.
   - Output: sample rate, channel, duration, codec, clipping ratio, RMS, silence ratio, speech ratio nếu VAD có, SNR proxy.

2. Tạo module `src/services/audio_artifacts.py`.
   - `create_original_artifact(audio_file)`
   - `create_derived_artifact(parent, path, kind, tool, config)`
   - `sha256_file(path)`

3. Lưu vào `Task.result.audio_artifacts` và `Task.result.audio_quality`.

4. Bổ sung audit:
   - upload artifact hash.
   - generate clip artifact nếu clip được lưu/export.

### UI tasks

- Analysis/File detail hiển thị "Chất lượng audio":
  - duration, sample rate, channel
  - warnings: clipping/noise/low speech ratio
  - "Audio gốc được giữ nguyên"

### Acceptance gates

- Upload audio tạo original artifact có SHA-256.
- `resolve_audio_path()` vẫn là đường duy nhất đọc file.
- Không lưu absolute path vào response API.
- Tests cho invalid audio, clipping warning, artifact hash stable.

---

## Phase 2: Benchmark ASR tiếng Việt và engine selector

Mục tiêu: chọn ASR bằng dữ liệu đo được, không chọn theo cảm tính.

### Backend tasks

1. Thêm `src/services/transcription/asr_registry.py`.
   - Engine interface:
     - `transcribe(audio_path, language, options) -> TranscriptResult`
   - Providers:
     - `faster_whisper`
     - `cherry_whisper_v2`
     - `phowhisper`
     - optional `nemo`

2. Thêm config:
   - `ASR_ENGINE=auto|faster_whisper|cherry_whisper_v2|phowhisper`
   - `ASR_BENCHMARK_ENABLED=false`

3. Tạo benchmark script:
   - `scripts/benchmark_asr.py`
   - Input fixture JSON + audio.
   - Metrics: WER, CER, keyword recall, hallucination rate, latency, memory.

4. Fact-level ASR disagreement risk.
   - Nếu phone/date/money khác nhau giữa 2 engine, tạo `RiskFlag` loại `asr_disagreement`.

### Fixture tối thiểu

- Hotel booking transcript mẫu.
- Hội thoại có số điện thoại đọc ngắt quãng.
- Hội thoại có email bị đọc "gmail chấm com".
- Đoạn im lặng/noise dễ hallucinate.

### Acceptance gates

- Không đổi engine mặc định nếu chưa có benchmark.
- Có bảng kết quả ASR trên fixture.
- Phone/date/money recall không giảm so với baseline hiện tại.

---

## Phase 2A: PhoGuard-ASR runtime reliability gate

Mục tiêu: giảm nguy cơ ASR hallucination/false-speech bị khuếch đại thành summary, graph hoặc fact nghiệp vụ.

Tài liệu chi tiết: `docs/phoguard_asr_integration_plan.md`.

### Review kết quả nghiên cứu PhoGuard

- PhoGuard-ASR không phải ASR model mới; đây là reliability gate sau ASR.
- Kết quả được phép claim: no-regression WER/CER trên internal speech và public VIVOS, giảm false-speech/hallucination-proxy trên synthetic B20 và public MUSAN.
- Không được claim: SOTA, WER improvement, loại bỏ hallucination, broad field-audio generalization, calibrated confidence.
- `risk_score` là rule-based ranking signal, không phải xác suất.

### Backend tasks

1. Chốt source manifest trước khi code:
   - `docs/phoguard_asr_source_manifest.md` phải có `implementation_blocked=false`.
   - Bắt buộc có `source_commit` hoặc `source_export_sha256`.
   - Không port từ worktree `cherry_core` đang dirty/untracked.

2. Tạo runtime service import-safe:
   - `src/cherry_core/services/phoguard_service.py`
   - `src/cherry_core/services/phoguard_schema.py`
   - `src/cherry_core/services/phoguard_features.py`

3. Gắn vào `transcribe_audio_v2()` sau khi có transcript/segments và trước khi lưu `Task.result`.

4. Lưu trong `Task.result`:
   - `raw_transcription`
   - `review_transcription`
   - `transcription` theo mode: shadow/off/failed dùng raw transcript; enforce accepted/needs-review mới dùng selected transcript; enforce abstained dùng empty string.
   - `phoguard` metadata không chứa full transcript text
   - `needs_review`
   - `asr_reliability`
   - `asr_review_status`, `asr_reviewed_by`, `asr_reviewed_at`, `asr_review_note`, `asr_review_revision`
   - `asr_override_status`, `asr_forced_by`, `asr_forced_at`, `asr_forced_reason_code`

5. Dùng `SileroVADAdapter.get_speech_ratio()` nếu khả dụng.
   - Nếu VAD lỗi hoặc thiếu model, không fail transcribe.
   - Khi thiếu `speech_ratio`, không abstain dựa trên VAD.

6. Rollout bằng mode:
   - `PHOGUARD_MODE=shadow` là default: chỉ tính reliability, không overwrite transcript, không block.
   - `PHOGUARD_MODE=enforce` mới được abstain/block.

7. Thêm transcript review endpoint:
   - `PATCH /api/v1/audio/v2/transcriptions/{task_id}/review`
   - `POST /api/v1/audio/v2/transcriptions/{task_id}/override`
   - Dùng revision để tránh lost update.
   - Forced override dùng reason code allowlist, không phải free-text.
   - Audit không log transcript/review note/free text.

8. Gate summary/analysis trong enforce mode:
   - Block `abstained` theo config riêng.
   - Block `needs_review` theo config riêng.
   - Trả `409 Conflict` kèm `phoguard.status`.
   - Nếu forced override, Analysis V2 mark mọi extracted item `requires_review=true`; critical facts/relations không được auto-confirm.

9. API boundary:
   - File list/status/task polling/dashboard không trả `raw_transcription` hoặc segment transcript text.
   - `GET /api/v1/audio/v2/transcriptions/{task_id}` mới trả transcript detail only, có `Cache-Control: no-store` và `Pragma: no-cache`.
   - Detail endpoint không kèm full `Task.result`, `visualization_data`, summary hoặc analysis graph.

### UI tasks

- Transcript panel hiển thị badge `Đã chấp nhận | Cần duyệt lại | Đã abstain | PhoGuard lỗi | PhoGuard tắt`.
- Cho xem raw transcript và selected transcript.
- File table/card hiển thị ASR reliability badge.
- Summary/Analysis button cảnh báo hoặc disable khi transcript cần review.
- Analysis Overview hiện banner "Transcript cần duyệt lại" nếu nguồn chưa accepted.
- Transcript review controls: confirm/reject, có revision và audit.
- Forced override là action riêng, có reason code allowlist và không biến transcript thành accepted.

### Acceptance gates

- Fresh import PhoGuard service không load `torch`, `faster_whisper`, `pyannote.audio`.
- Source manifest chưa freeze thì không bắt đầu runtime port.
- Shadow mode không đổi transcript và không block summary/analysis.
- File list/status/task polling/dashboard không leak raw transcript.
- Low speech ratio + ASR output nhiều từ -> `abstained`.
- Missing speech ratio -> no VAD-informed abstain.
- Raw transcript không mất khi selected transcript rỗng.
- Summary/visualize bị block trên abstained task theo config trong enforce mode.
- Needs-review block tách riêng với abstained block.
- Forced override vẫn giữ downstream items `requires_review=true`.
- Enforce chỉ bật sau shadow pilot >=30 audio files hoặc >=2 giờ audio, có reviewer sign-off trong manifest.
- Không log transcript/PII/reason text dài.

---

## Phase 3: Forced alignment và diarization nâng cao

Mục tiêu: evidence clip chính xác hơn, speaker attribution đáng tin hơn.

### Backend tasks

1. Implement alignment provider thật.
   - Ưu tiên WhisperX hoặc forced alignment tương đương.
   - Output `words[]`: word, start, end, confidence, source.
   - Lưu vào `SegmentUnit.words`.

2. Tách diarization provider registry.
   - `pyannote_community_1`
   - optional `sortformer`
   - fallback `simple_vad`

3. Speaker attribution confidence.
   - `speaker_confidence`
   - `overlap_detected`
   - `requires_review=true` nếu overlap/uncertain.

4. Không làm speaker identification mặc định.
   - Module speaker verification/enrollment tách riêng, feature-gated.
   - Không cross-case matching nếu chưa có legal policy.

### Acceptance gates

- Timestamp median error <= 2s trên fixture có word alignment.
- Speaker attribution accuracy đo được.
- Evidence clip start/end lấy từ word span nếu có, fallback segment nếu không.
- Nếu overlap speech, UI/graph phải cảnh báo.

---

## Phase 4: General/domain analysis engine và LLM structured extraction

Mục tiêu: phân tích sâu nhiều ngữ cảnh, nhưng vẫn có evidence.

### Core extraction

Giữ deterministic core luôn chạy trước:

- contact/identity: phone, email, email candidate, ID candidate
- time/money/quantity
- person/org/location
- action/request/offer/decision/obligation/policy
- risk flags: noisy email, ID length, ASR disagreement, missing timestamp

### Domain overlay

Domain template tạo `slots` và `domain_frames`.

Ví dụ `hotel_booking`:

- `customer_name`
- `hotel_name`
- `room_count`
- `guest_count`
- `guest_composition`
- `check_in_date`
- `check_out_date`
- `stay_nights`
- `purpose`
- `room_price`
- `total_amount`
- `payment_method`
- `promotion`
- `post_call_action`
- `policy_terms`

### LLM gateway

Tạo:

- `src/services/analysis_intelligence/llm_gateway.py`
- `src/services/analysis_intelligence/evidence_locator.py`
- `src/services/analysis_intelligence/domain_extractor.py`

LLM contract:

```json
{
  "domain_frames": [
    {
      "domain_template_key": "hotel_booking",
      "confidence": 0.91,
      "slots": [
        {
          "name": "room_count",
          "value": "2 phòng",
          "normalized_value": {"quantity": 2, "unit": "phòng"},
          "evidence_text": "đặt 2 phòng",
          "confidence": 0.92,
          "confidence_reason": "nêu trực tiếp"
        }
      ]
    }
  ]
}
```

Rules:

- Prompt được backend build từ schema đã validate.
- Template không được lưu system prompt tự do.
- Mọi slot/fact/event/claim từ LLM phải có `evidence_text`.
- Backend locate lại `evidence_text` trong segment bằng normalized whitespace/case/accent tolerant matching.
- Không locate được: drop hoặc `needs_review`, tùy loại.
- Critical relation không emit nếu thiếu timestamp/speaker grounding.
- Không log transcript/prompt/raw response/API key.

### Acceptance gates

- CI dùng mocked LLM, không phụ thuộc provider thật.
- Fixture hotel đạt slot F1 >= 0.85 với mocked LLM.
- Evidence coverage = 100%.
- Critical false positives = 0.
- Provider lỗi -> graph vẫn có deterministic results, `llm_status=failed|partial`.

---

## Phase 5: UI Analyst Workspace và Domain Template UI

Mục tiêu: analyst có thể dùng kết quả, kiểm tra evidence, review và xuất báo cáo.

### UI tasks

1. Analysis Overview
   - Ưu tiên `display_sections_vi`.
   - Domain cards tiếng Việt.
   - Warning rõ: "Kết quả do máy gợi ý, chưa xác minh".

2. Evidence Inspector
   - Transcript span.
   - Speaker/time range.
   - Confidence reason/source method.
   - Play clip.
   - Review buttons: confirm/reject/edit.

3. Graph
   - Graph chỉ là view phụ.
   - Không hiển thị rejected items.
   - Click node/edge mở evidence inspector.

4. Domain Template UI
   - List/detail.
   - JSON editor có validation.
   - Test transcript.
   - Publish/archive.
   - Import/export.
   - Domain selector ở Generate Analysis.

5. Export report
   - Audio artifact hashes.
   - ASR model/version.
   - Facts/slots/evidence refs.
   - Review statuses.
   - Warnings/limitations.

### Acceptance gates

- Hard refresh vẫn mở được Analysis của file đã visualized.
- Open Analysis không POST regenerate.
- Generate/Regenerate có domain selector.
- Review action update graph và legacy aliases.
- Export không chứa raw filesystem path hoặc API key.

---

## Phase 6: Speaker verification/enrollment tùy chọn

Mục tiêu: chỉ triển khai khi có cơ sở pháp lý và dữ liệu enrollment hợp lệ.

### Không làm mặc định

Không tự động cross-case speaker identification. Không gọi speaker label là danh tính người thật nếu chỉ có diarization.

### Nếu triển khai

- Enrollment voice samples có consent/authority metadata.
- Extract embedding bằng SpeechBrain ECAPA-TDNN hoặc provider tương đương.
- Lưu embedding encrypted hoặc trong vector store có access control.
- Threshold calibration: ROC, EER, FAR/FRR.
- Output chỉ là `candidate_match`, luôn `requires_review=true`.
- Audit mọi search/match.

### Acceptance gates

- Legal/policy checklist pass.
- False accept budget được định nghĩa.
- Human verification workflow bắt buộc.
- Không bật trong CI/default production.

---

## Phase 7: Benchmark, báo cáo khoa học và pilot

### Bộ dữ liệu

Tạo `tests/fixtures/investigation_transcripts/`:

- `hotel_booking_a_first_case.json`
- `transaction_transfer.json`
- `appointment_schedule.json`
- `complaint_customer_service.json`
- `unknown_domain_general.json`
- `no_entity_false_positive_trap.json`
- `noisy_asr_transcript.json`
- `overlap_speakers.json`
- `prompt_injection_transcript.json`

Mỗi fixture gồm:

```json
{
  "transcript": "...",
  "segments": [],
  "ground_truth": {
    "facts": [],
    "slots": [],
    "entities": [],
    "risk_flags": []
  }
}
```

### Metrics

| Lớp | Metrics |
|---|---|
| ASR | WER, CER, keyword recall, hallucination rate, latency |
| Diarization | DER, JER, speaker attribution accuracy, cpWER |
| Alignment | median/p95 timestamp error |
| Extraction | precision, recall, F1, normalized value accuracy |
| Evidence | evidence coverage, unlocated evidence rate |
| Safety | critical false positives, PII log leaks, unauthorized access tests |
| UI | generate -> open -> review -> export success |

### Gates bật mặc định

- Deterministic core: tests/build/security pass, no critical false positives.
- LLM selected template: slot F1 >= 0.85, evidence coverage = 100%, critical false positives = 0.
- Forced alignment: timestamp median error <= 2s trên fixture.
- Speaker verification: chỉ bật khi có policy + threshold calibration + human review.

---

## 4. Backlog ưu tiên gần nhất

### Sprint 1: Chất lượng extractor và evidence UI

1. Fix `ORG_RE`.
2. Derived claim validator cho `room_count * room_price = total_amount`.
3. Deterministic `hotel_booking` domain frame từ facts hiện có.
4. UI Evidence: play clip + confirm/reject.
5. Fixture A - First Case vào CI.

### Sprint 2: Audio QC và artifact ledger

1. `audio_quality.py`.
2. `audio_artifacts.py`.
3. UI audio quality warnings.
4. Export report có hashes.

### Sprint 3: Domain template runtime

1. Domain selector trong Generate Analysis.
2. Domain frame/slot generation deterministic cho hotel template.
3. Minimal template UI JSON editor/test/publish.
4. Mocked LLM slot extraction tests.

### Sprint 4: LLM provider gateway

1. Env-based provider configs.
2. OpenAI-compatible/Ollama structured output adapters.
3. Evidence locator.
4. Chunking/merge stable IDs.
5. Prompt injection and log redaction tests.

---

## 5. Nguồn nghiên cứu đã đối chiếu

- Whisper: https://arxiv.org/abs/2212.04356
- faster-whisper/CTranslate2: https://github.com/SYSTRAN/faster-whisper, https://github.com/OpenNMT/CTranslate2
- PhoWhisper: https://github.com/VinAIResearch/PhoWhisper
- WhisperX: https://arxiv.org/abs/2303.00747
- Pyannote Community-1: https://huggingface.co/pyannote/speaker-diarization-community-1
- NVIDIA NeMo diarization/Sortformer: https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/intro.html
- Silero VAD: https://github.com/snakers4/silero-vad
- DeepFilterNet: https://github.com/Rikorose/DeepFilterNet
- RNNoise: https://github.com/xiph/rnnoise
- GraphRAG dataflow/outputs: https://microsoft.github.io/graphrag/index/default_dataflow/, https://microsoft.github.io/graphrag/index/outputs/
- LangExtract: https://github.com/google/langextract
- Speech-based Slot Filling using LLMs, Findings ACL 2024: https://aclanthology.org/2024.findings-acl.379/
- SWGDE Forensic Audio: https://www.swgde.org/documents/published-complete-listing/08-a-001-swgde-best-practices-for-forensic-audio/
- SWGDE Digital Audio Enhancement: https://www.swgde.org/documents/published-complete-listing/20-a-001-swgde-best-practices-for-the-enhancement-of-digital-audio/
- Frontiers 2024 forensic ASR warning: https://www.frontiersin.org/journals/communication/articles/10.3389/fcomm.2024.1281407/full
- OpenAI structured outputs: https://platform.openai.com/docs/guides/structured-outputs
- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
