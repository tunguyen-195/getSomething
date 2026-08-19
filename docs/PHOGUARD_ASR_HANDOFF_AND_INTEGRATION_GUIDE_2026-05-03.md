# PhoGuard-ASR Handoff And Integration Guide

Ngày lập: 2026-05-03

Tài liệu này dùng để bàn giao phần nghiên cứu PhoGuard-ASR từ repo `E:/research/Cherry2/cherry_core` cho đội phát triển hệ thống `D:/Workspace/SpeechToInfomation`. Mục tiêu là giúp hai bên thống nhất:

- PhoGuard-ASR đã làm được gì.
- Kết quả nào được phép đưa vào báo cáo.
- Phần nào thuộc trách nhiệm của repo nghiên cứu và phần nào thuộc trách nhiệm của repo ứng dụng.
- Nên tích hợp PhoGuard-ASR vào `SpeechToInfomation` như thế nào.
- Phần nào không nên tích hợp hoặc không nên claim trong giai đoạn hiện tại.

## 1. Tóm tắt điều hành

`cherry_core` hiện là base nghiên cứu cho giảm ảo giác/proxy hallucination và bảo toàn độ chính xác ASR. Thành phần chính là `PhoGuard-ASR`, một lớp reliability gate cho ASR tiếng Việt, dùng conservative decoding, VAD-informed abstention, repetition/BoH proxy và rule-based routing để quyết định giữ transcript hoặc abstain/needs-review.

`SpeechToInfomation` hiện là base ứng dụng và base trinh sát âm thanh. Repo này có UI, API, workflow upload/transcribe/summarize/visualize, database, case management, auth/security, diagrams và các test hệ thống. Vì vậy `SpeechToInfomation` nên nhận PhoGuard-ASR như một module nghiên cứu đã được benchmark, rồi tích hợp vào luồng transcribe và UI review.

Thông điệp chính cho báo cáo:

> PhoGuard-ASR cung cấp bằng chứng khoa học về giảm false-speech/hallucination-proxy và bảo toàn WER/CER; SpeechToInfomation cung cấp nền tảng ứng dụng để biến bằng chứng đó thành hệ thống trinh sát âm thanh offline có giao diện, cơ sở dữ liệu, workflow và kiểm thử.

## 2. Trạng thái hiện tại của PhoGuard-ASR

### 2.1 Thành phần đã có trong `cherry_core`

Các file/module chính:

- `research/phoguard_asr/decision_schema.py`: schema quyết định của PhoGuard.
- `research/phoguard_asr/gate.py`: rule-based reliability gate.
- `research/phoguard_asr/risk_features.py`: risk features, repeated n-gram, BoH hits, false words/min.
- `research/phoguard_asr/text_metrics.py`: WER/CER/word distance utilities.
- `scripts/benchmark_phoguard_asr.py`: harness benchmark, không phải runtime production.
- `scripts/validate_phoguard_artifacts.py`: validator run artifacts.
- `scripts/validate_phoguard_research_artifacts.py`: validator manifest/audit/research artifacts.
- `scripts/aggregate_phoguard_readiness.py`: aggregate readiness theo target claim.
- `scripts/prepare_phoguard_public_manifest.py`: chuẩn bị manifest VIVOS/MUSAN.
- `configs/phoguard_asr/*.json`: profiles benchmark.
- `docs/paper_pack/PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`: source-of-truth kết quả mạnh nhất.
- `output/phoguard_asr/paper_readiness_cuda_stronger_paper.json`: aggregate readiness mới nhất.

### 2.2 Kết quả thực nghiệm đã đạt

Source-of-truth:

- `docs/paper_pack/PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`
- `output/phoguard_asr/paper_readiness_cuda_stronger_paper.json`

Kết quả chính:

| Lane | Baseline | PhoGuard | Kết luận an toàn |
| --- | ---: | ---: | --- |
| Internal speech macro WER | 0.0689826609 | 0.0689826609 | no-regression |
| Internal speech micro WER | 0.0692570073 | 0.0692570073 | no-regression |
| Synthetic B20 false words/min | 157.2 | 0.0 | giảm bằng abstention |
| Synthetic B20 output rate | 1.0 | 0.0 | giảm bằng abstention |
| Public MUSAN false words/min | 105.375 | 8.7 | giảm, chưa loại bỏ hoàn toàn |
| Public MUSAN output rate | 1.0 | 0.1125 | giảm, còn residual output |
| Public VIVOS macro WER | 0.1833718219 | 0.1787214941 | no-regression/public reproducibility |
| Public VIVOS micro WER | 0.1428386428 | 0.1427091427 | no-regression/public reproducibility |

Sampled audit:

- 50 paired non-speech source units.
- 100 transcript units.
- Rule-assisted single annotator.
- Baseline hallucination utterance rate: `1.0`.
- PhoGuard hallucination utterance rate: `0.1`.
- PhoGuard paired wins: `45`.
- Baseline paired wins: `0`.
- Ties: `5`.
- Exact McNemar/sign-test p-value: `5.684e-14`.

### 2.3 Claim được phép dùng

Được claim:

- PhoGuard-ASR bảo toàn WER/CER trên internal synthetic Vietnamese long-form speech.
- PhoGuard-ASR bảo toàn WER/CER trên public VIVOS Vietnamese read-speech test split.
- PhoGuard-ASR giảm false-speech/hallucination-proxy trên synthetic non-speech B20.
- PhoGuard-ASR giảm false-speech/hallucination-proxy trên public MUSAN music/noise non-speech.
- Sampled rule-assisted single-annotator audit cho thấy giảm labeled non-speech hallucination trong sample được audit.
- Kết quả hiện tại là CUDA-scoped, có model provenance/model SHA.

Không được claim:

- Không claim SOTA ASR tiếng Việt.
- Không claim WER improvement hoặc broad ASR accuracy improvement.
- Không claim "loại bỏ ảo giác" vì MUSAN vẫn còn `8.7` false words/min.
- Không claim broad human-labeled hallucination reduction.
- Không claim double-annotated audit.
- Không claim natural field-audio generalization.
- Không claim denoising/correction/diarization/summary cải thiện định lượng nếu chưa có benchmark riêng.
- Không claim PhoWhisper.cpp hoặc quantization giảm ảo giác.
- Không claim GPU nhanh hơn CPU nếu chưa có matched CPU run.

## 3. Trách nhiệm của từng repo

### 3.1 `cherry_core` phụ trách

Repo nghiên cứu phụ trách:

- PhoGuard-ASR core logic.
- Benchmark protocol.
- Dataset manifest/provenance.
- Public VIVOS/MUSAN lanes.
- Synthetic non-speech dataset/generator.
- Manual/sampled audit schema và summarizer.
- Validator và aggregate readiness.
- Paper pack, claim matrix, evidence registry.
- Các bảng/hình/kết quả khoa học cho Chương 1 và Chương 2 của báo cáo.

Đội `cherry_core` chịu trách nhiệm giữ claim đúng scope:

- WER/CER no-regression, không nói WER improvement.
- Hallucination-proxy reduction, không nói broad hallucination elimination.
- Public reproducibility, không nói SOTA/public benchmark leadership.

### 3.2 `SpeechToInfomation` phụ trách

Repo ứng dụng phụ trách:

- Web UI/UX cho quy trình trinh sát âm thanh.
- Case management, audio management, task management.
- API upload/transcribe/summarize/visualize.
- Celery/Redis worker workflow.
- PostgreSQL schema, migrations, storage policy.
- Auth, CSRF, RBAC/resource-level access, security audit log.
- Frontend panels: file list, transcript, summary, visualization, speaker/diarization.
- System tests, API tests, security tests, E2E tests.
- ZAP/pentest report nếu đưa vào Chương 4.
- Diagrams hệ thống: use case, activity, sequence, ERD, component, deployment, class, trust boundary.

Đội `SpeechToInfomation` không nên tự claim giảm ảo giác nếu chưa dùng PhoGuard-ASR hoặc chưa tạo artifact tương đương.

### 3.3 Phân chia phần trong báo cáo 4 chương

| Phần báo cáo | Chủ trì | Input chính |
| --- | --- | --- |
| Mở đầu | Cả hai | framing chung: nghiên cứu + ứng dụng |
| Chương 1 - cơ sở lý thuyết/phương pháp/benchmark | `cherry_core` | paper pack, research basis, protocol |
| Chương 2 - thực nghiệm/kết quả PhoGuard-ASR | `cherry_core` | stronger paper artifacts |
| Chương 3 - phân tích thiết kế hệ thống | `SpeechToInfomation` | UI/API/DB/diagrams/workflows |
| Chương 4 - kiểm thử hệ thống/đánh giá/kết luận | `SpeechToInfomation` chủ trì, `cherry_core` cung cấp benchmark khoa học | pytest, frontend build, ZAP, benchmark summary |
| Phụ lục benchmark/provenance | `cherry_core` | manifests, run IDs, validators |
| Phụ lục hệ thống/diagrams/API | `SpeechToInfomation` | PlantUML, OpenAPI, DB schema |

## 4. Tích hợp PhoGuard-ASR vào `SpeechToInfomation`

### 4.1 Nguyên tắc tích hợp

Không bê nguyên `scripts/benchmark_phoguard_asr.py` vào production. Benchmark harness dùng để tạo evidence, không phải runtime service.

Nên tích hợp phần runtime tối thiểu:

- text metrics;
- risk features;
- decision schema;
- gate decision;
- artifact writer nhẹ cho task result;
- optional audit/export JSON.

Không nên tích hợp ở giai đoạn đầu:

- public dataset download/prep scripts;
- aggregate readiness scripts;
- validator paper artifacts;
- plotting code;
- benchmark profiles;
- manual audit generator;
- PhoWhisper.cpp runtime lane;
- denoising/correction candidate lanes chưa có claim chính.

### 4.2 Integration target trong `SpeechToInfomation`

Các entry point hiện có:

- `src/services/transcription/transcribe_service_v2.py`
- `src/services/transcription/cherry_transcription_service.py`
- `src/cherry_core/adapters/asr/whisperv2_adapter.py`
- `src/cherry_core/adapters/vad/silero_adapter.py`
- `src/api/endpoints/audio_v2.py`
- `src/services/task_service.py`
- `frontend/src/components/FileCard.tsx`
- `frontend/src/components/TranscriptPanel.tsx`
- `frontend/src/components/DiarizationPanel.tsx`
- `frontend/src/components/InvestigationSummaryCard.tsx`

Recommended placement:

```text
src/cherry_core/phoguard/
  __init__.py
  decision_schema.py
  text_metrics.py
  risk_features.py
  gate.py
  runtime_service.py
```

Hoặc nếu muốn theo ports/adapters:

```text
src/cherry_core/ports/phoguard_port.py
src/cherry_core/services/phoguard_service.py
src/cherry_core/adapters/asr/phoguard_adapter.py
```

Khuyến nghị thực tế: bắt đầu với `src/cherry_core/services/phoguard_service.py` để giảm thay đổi kiến trúc.

### 4.3 Runtime API đề xuất

Service runtime nên có interface:

```python
class PhoGuardRuntimeService:
    def analyze(
        self,
        *,
        task_id: str,
        audio_path: str,
        duration_sec: float,
        transcript_text: str,
        segments: list[dict],
        speech_ratio: float | None = None,
        baseline_condition: str = "whisper_v2_current",
    ) -> dict:
        ...
```

Output tối thiểu:

```json
{
  "schema_version": "phoguard_asr.runtime.v1",
  "selected_text": "...",
  "review_text": "...",
  "abstain_flag": false,
  "selected_condition": "whisper_v2_current|abstain_needs_review",
  "reason_codes": ["raw_current_lowest_or_tie"],
  "risk_score": 0.0,
  "coverage": 1.0,
  "speech_ratio": 0.83,
  "features": {
    "word_count": 120,
    "repeated_8gram_hits": 0,
    "boh_hit_count": 0,
    "false_words_per_min": null,
    "non_speech_output": null
  },
  "policy": {
    "risk_score_policy": "rule_based_ranking_signal_not_calibration",
    "hallucination_label_policy": "proxy_metrics_only"
  }
}
```

### 4.4 Cách gắn vào `transcribe_service_v2.py`

Vị trí tích hợp: sau khi có `segments`, `full_transcript`, `duration`, trước khi `result_dict` được ghi vào `Task.result`.

Luồng đề xuất:

```text
AudioFile
  -> transcribe_audio_v2
  -> CherryTranscriberService / WhisperV2Adapter
  -> segments + transcript
  -> PhoGuardRuntimeService.analyze(...)
  -> update Task.result:
       transcription = phoguard.selected_text
       review_transcription = phoguard.review_text
       phoguard = full phoguard payload
       needs_review = phoguard.abstain_flag or high risk
```

Không nên xóa transcript raw. Phải lưu cả hai:

- `raw_transcription` hoặc `review_transcription`: transcript gốc để chuyên viên đối chiếu.
- `transcription`: transcript được chọn để hệ thống dùng tiếp.
- `phoguard`: payload risk/decision.

### 4.5 Cách gắn vào `CherryTranscriberService`

`CherryTranscriberService` hiện trả:

```python
{
    "transcript": transcript_entity.text,
    "segments": result_segments,
    "num_speakers": num_speakers,
    "language": language,
    "duration": ...,
    "processing_time": ...,
    "diarization_time": ...,
    "model_used": model_type
}
```

Nên thêm optional PhoGuard sau ASR:

```python
if enable_phoguard:
    phoguard_result = PhoGuardRuntimeService().analyze(...)
    final_text = phoguard_result["selected_text"]
else:
    phoguard_result = None
    final_text = transcript_entity.text
```

Return thêm:

```python
{
    "transcript": final_text,
    "raw_transcript": transcript_entity.text,
    "phoguard": phoguard_result,
    "needs_review": phoguard_result["abstain_flag"] if phoguard_result else False,
    ...
}
```

### 4.6 Cách tính `speech_ratio`

`SpeechToInfomation` đã có:

- `src/cherry_core/adapters/vad/silero_adapter.py`
- method `get_speech_ratio(audio_path)`

Nên dùng method này nếu model Silero có sẵn. Nếu VAD lỗi:

- không fail toàn bộ transcribe;
- ghi warning;
- set `speech_ratio=None`;
- PhoGuard runtime không được abstain dựa trên VAD khi thiếu speech_ratio.

Policy:

```text
if speech_ratio is None:
    disable VAD-informed abstention for this task
    still compute text risk features
```

### 4.7 UI/UX cần thêm

Tối thiểu:

- Hiển thị badge: `PhoGuard: accepted`, `PhoGuard: abstained`, `PhoGuard: needs review`.
- Hiển thị `risk_score` nhưng ghi rõ: rule-based risk, không phải calibrated confidence.
- Hiển thị `reason_codes`.
- Cho phép mở raw/review transcript.
- Nếu `abstain_flag=true`, không coi là lỗi hệ thống; hiển thị "Không xuất transcript tự động do rủi ro false-speech, cần nghe lại".
- Trong summary/visualization, nếu task abstained thì yêu cầu user xác nhận hoặc nghe lại trước khi chạy LLM summary.

Frontend files likely touched:

- `frontend/src/components/FileCard.tsx`
- `frontend/src/components/TranscriptPanel.tsx`
- `frontend/src/components/StatusBadge.tsx`
- `frontend/src/components/InvestigationSummaryCard.tsx`
- `frontend/src/api/client.ts`

### 4.8 Database/API storage

Không cần tạo bảng mới ở phase 1. Có thể lưu trong `Task.result` JSON:

```json
{
  "transcription": "selected text",
  "raw_transcription": "raw ASR text",
  "review_transcription": "raw ASR text",
  "phoguard": {
    "schema_version": "phoguard_asr.runtime.v1",
    "abstain_flag": false,
    "risk_score": 0.123,
    "reason_codes": [],
    "features": {}
  },
  "needs_review": false
}
```

Nếu sau này cần query thống kê nhiều, mới thêm bảng:

```text
phoguard_decisions
  id
  task_id
  audio_file_id
  risk_score
  abstain_flag
  selected_condition
  reason_codes JSONB
  features JSONB
  created_at
```

Phase 1 khuyến nghị không thêm bảng để giảm migration risk.

## 5. Các phần không nên tích hợp ngay

Không tích hợp ngay:

- `scripts/benchmark_phoguard_asr.py`: chỉ dùng để benchmark/paper.
- `scripts/aggregate_phoguard_readiness.py`: chỉ dùng cho paper readiness.
- `scripts/prepare_phoguard_public_manifest.py`: chỉ dùng lab/dataset.
- `scripts/summarize_manual_audit.py`: chỉ dùng audit/research.
- `configs/phoguard_asr/public_vivos_test.json`, `musan_non_speech_80.json`: không dùng runtime production.
- Public datasets VIVOS/MUSAN vào app production.
- Manual audit sheets vào app.
- Denoising/correction candidate as default, vì chưa có benchmark chính.
- PhoWhisper.cpp/quantization vào hallucination path.

Có thể giữ làm phụ lục nghiên cứu:

- benchmark configs;
- validators;
- evidence registry;
- claim matrix;
- paper pack docs.

## 6. Kế hoạch tích hợp theo phase

### Phase 0 - Handoff và lock evidence

Owner: `cherry_core`

Deliverables:

- Tài liệu này.
- `PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`.
- `paper_readiness_cuda_stronger_paper.json`.
- Claim matrix/evidence registry.

Acceptance:

- Đội `SpeechToInfomation` hiểu scope: runtime integration khác benchmark harness.
- Không copy dataset/output lớn vào app repo.

### Phase 1 - Runtime PhoGuard tối thiểu

Owner: `SpeechToInfomation`, support bởi `cherry_core`

Tasks:

1. Tạo `src/cherry_core/services/phoguard_service.py`.
2. Copy/adapt logic từ:
   - `research/phoguard_asr/decision_schema.py`
   - `research/phoguard_asr/text_metrics.py`
   - `research/phoguard_asr/risk_features.py`
   - `research/phoguard_asr/gate.py`
3. Sửa imports để dùng namespace `src.cherry_core`.
4. Dùng `SileroVADAdapter.get_speech_ratio()` nếu khả dụng.
5. Gắn PhoGuard vào `transcribe_service_v2.py`.
6. Lưu `raw_transcription`, `transcription`, `phoguard`, `needs_review` vào `Task.result`.

Acceptance:

- Unit tests pass.
- Transcribe vẫn hoạt động khi PhoGuard lỗi hoặc VAD thiếu.
- Raw transcript không bị mất.
- Non-speech short test không tạo summary tự động nếu abstained.

### Phase 2 - UI/UX review panel

Owner: `SpeechToInfomation`

Tasks:

1. Thêm PhoGuard status badge.
2. Thêm risk/reason panel.
3. Thêm raw vs selected transcript view.
4. Chặn hoặc cảnh báo summary/visualization khi task `needs_review=true`.
5. Thêm export JSON artifact.

Acceptance:

- User nhìn được vì sao hệ thống abstain.
- Không có wording "confidence calibrated".
- UI không giấu raw transcript.

### Phase 3 - System testing

Owner: `SpeechToInfomation`

Tasks:

1. Unit test PhoGuard runtime.
2. API test transcribe response có `phoguard`.
3. Security regression tests vẫn pass.
4. E2E upload -> transcribe -> view PhoGuard -> summary.
5. Test fake audio/non-speech short clip.
6. Frontend build.

Acceptance:

- `python -m pytest tests -q` hoặc subset documented pass.
- `npm run build` pass.
- Không regression auth/access control.

### Phase 4 - ZAP/security report

Owner: `SpeechToInfomation`

Tasks:

1. Start app test environment.
2. Run ZAP baseline unauthenticated.
3. Nếu có auth flow, thêm authenticated scan/context.
4. Lưu report HTML/JSON.
5. Ghi High/Medium/Low/Info findings.
6. Fix hoặc accepted-risk từng finding.

Acceptance:

- Có artifact ZAP report.
- Không ghi "pentest pass" nếu chỉ scan baseline.

### Phase 5 - Optional deeper integration

Chỉ làm sau khi phase 1-4 ổn:

- Database table riêng `phoguard_decisions`.
- Dashboard thống kê risk theo case.
- Manual audit workflow trong UI.
- Mechanism ablation as lab mode.
- Correction/denoising benchmark lanes.

## 7. Test plan tối thiểu cho integration

### Unit tests

- `risk_features` tính repeated_8gram_hits đúng.
- `false_words_per_minute` đúng với duration.
- `select_phoguard_text` abstain khi speech_ratio thấp và raw_words > 3.
- Không abstain khi speech_ratio missing.
- `risk_score` không được gọi là probability.

### API tests

- `/api/v1/audio/v2/transcribe/{task_id}` trả `phoguard` trong result.
- Task result có cả `raw_transcription` và `transcription`.
- `needs_review=true` khi PhoGuard abstain.
- Summary endpoint cảnh báo hoặc block khi `needs_review=true` nếu policy bật.

### Security regression

- Auth-required route inventory vẫn pass.
- CSRF vẫn bắt buộc khi auth enabled.
- Cross-case task access vẫn bị 403.
- Upload traversal filename vẫn bị 400.
- Fake audio content vẫn bị 400.

### E2E/manual tests

- Speech audio bình thường: transcript hiển thị, PhoGuard accepted.
- Silence/noise audio: PhoGuard abstain hoặc needs-review.
- UI hiển thị raw transcript/reason_codes.
- Export result chứa phoguard payload.

## 8. Báo cáo: cách hai bên ghi phần của mình

### `cherry_core` cung cấp cho Chương 1-2

Cung cấp:

- Problem framing.
- Related work/research basis.
- PhoGuard-ASR method.
- Dataset/protocol.
- Tables and results.
- Claim matrix.
- Limitations.

Không cần cung cấp:

- UI diagrams chi tiết.
- Database thiết kế chi tiết.
- ZAP report của app.

### `SpeechToInfomation` cung cấp cho Chương 3-4

Cung cấp:

- Requirements.
- Use case diagram.
- Activity/state/sequence diagrams.
- Component/deployment diagrams.
- ERD/database schema.
- UI/UX screenshots/wireframes.
- API docs.
- Test results.
- Security/ZAP results.

Không nên tự viết:

- Claim khoa học giam hallucination nếu không trích đúng PhoGuard artifacts.
- WER/CER benchmark nếu không chạy đúng protocol.

## 9. Checklist trước khi tích hợp

Trước khi code:

- Đọc `PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`.
- Đọc `CLAIM_MATRIX.md`.
- Chốt output schema runtime.
- Chốt UI policy cho `needs_review`.
- Không copy output/audio/model lớn.

Trước khi merge:

- Unit/API/security tests pass.
- Frontend build pass.
- Không làm mất raw transcript.
- Không gọi risk_score là calibrated confidence.
- Không tự động summary khi PhoGuard abstain nếu policy chưa cho phép.
- Có migration hoặc không cần migration được ghi rõ.

Trước khi viết báo cáo:

- Chỉ đưa số liệu đã có artifact.
- Chương 2 dùng source-of-truth của `cherry_core`.
- Chương 3 dùng source/design của `SpeechToInfomation`.
- Chương 4 chỉ đưa test/ZAP thật đã chạy.

## 10. Liên hệ artifact

Các file nên trích dẫn trong báo cáo:

- `E:/research/Cherry2/cherry_core/docs/paper_pack/PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`
- `E:/research/Cherry2/cherry_core/output/phoguard_asr/paper_readiness_cuda_stronger_paper.json`
- `E:/research/Cherry2/cherry_core/docs/paper_pack/CLAIM_MATRIX.md`
- `E:/research/Cherry2/cherry_core/docs/paper_pack/EVIDENCE_REGISTRY.md`
- `D:/Workspace/SpeechToInfomation/BAO_CAO_PHAN_TICH_THIET_KE_HE_THONG_SPEECHTOINFORMATION.md`
- `D:/Workspace/SpeechToInfomation/docs/diagrams/`
- `D:/Workspace/SpeechToInfomation/tests/test_security.py`
- `D:/Workspace/SpeechToInfomation/tests/test_system.py`

