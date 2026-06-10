# PhoGuard-ASR Source Manifest

Ngày lập: 03/05/2026

Mục đích: ghi lại nguồn PhoGuard-ASR được phép dùng để port vào runtime `SpeechToInfomation`.

## Current Status

```yaml
implementation_blocked: true
reason: "Source repo E:\\research\\Cherry2\\cherry_core đang dirty và nhiều file PhoGuard còn untracked."
source_repo: "E:\\research\\Cherry2\\cherry_core"
source_commit: null
source_export_sha256: null
source_package_path: null
enforce_blocked: true
pilot_audio_count: 0
pilot_duration_hours: 0.0
pilot_reviewer: null
threshold_decision: null
threshold_decided_at: null
```

Không bắt đầu Phase P1 runtime port cho tới khi một trong hai điều kiện sau đúng:

- `source_commit` trỏ tới commit/tag đã chứa đầy đủ `research/phoguard_asr/*`, tests, handoff docs và paper source-of-truth.
- `source_package_path` trỏ tới export package đã freeze, có `source_export_sha256`.

Không bật `PHOGUARD_MODE=enforce` cho môi trường chính cho tới khi `enforce_blocked=false` và các trường pilot có giá trị đầy đủ:

- `pilot_audio_count >= 30` hoặc `pilot_duration_hours >= 2.0`.
- `pilot_reviewer` là người duyệt ngưỡng.
- `threshold_decision` ghi threshold được chọn và lý do ngắn gọn.
- `threshold_decided_at` là timestamp ISO-8601.

## Files Expected In Frozen Source

Runtime logic candidates:

- `research/phoguard_asr/decision_schema.py`
- `research/phoguard_asr/gate.py`
- `research/phoguard_asr/risk_features.py`
- `research/phoguard_asr/text_metrics.py`

Research/paper evidence only:

- `docs/paper_pack/PHOGUARD_ASR_HANDOFF_AND_INTEGRATION_GUIDE_2026-05-03.md`
- `docs/paper_pack/PHOGUARD_ASR_STRONGER_PAPER_RESULTS_2026-05-03.md`
- `docs/paper_pack/CLAIM_MATRIX.md`
- `docs/paper_pack/DATASET_PROVENANCE.md`
- `docs/paper_pack/EVIDENCE_REGISTRY.md`
- `output/phoguard_asr/paper_readiness_cuda_stronger_paper.json`

Do not port to runtime:

- benchmark scripts
- aggregate readiness scripts
- validators for paper artifacts
- dataset preparation scripts
- public dataset manifests/audio
- plotting code
- `research/phoguard_asr/artifacts.py` environment collector

## Runtime Port Rules

- Runtime schema must be `phoguard_asr.runtime.v1`, not benchmark schema.
- Do not import directly from `E:\research\Cherry2\cherry_core`.
- Do not import modules that load `torch`, `faster_whisper`, `pyannote.audio` at module import time.
- `phoguard` payload must not contain full transcript text.
- File list/status/task polling/dashboard must not return raw transcript text.
- Transcript detail must be served only by a dedicated authenticated endpoint with no-store/no-cache headers.
- Reason codes must be enum/allowlist values.
- Default rollout must be `PHOGUARD_MODE=shadow`.
