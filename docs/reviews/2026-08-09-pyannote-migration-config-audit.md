# Pyannote Migration and Runtime Configuration Audit

**Ngày audit:** 2026-08-09

**Workspace canonical:** `E:\research\STT`

**Harness:** `scripts/capture_diarization_primary_sources.py` và `scripts/audit_pyannote_migration_config.py`

**Machine evidence:** `docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json`

**Phạm vi an toàn:** chỉ đọc workspace và migration evidence trên ổ E; không đọc, sửa, đồng bộ hoặc xóa repo D; không tải hay kích hoạt model gated.

## Verdict

| Câu hỏi | Verdict | Kết luận |
|---|---|---|
| Migration có làm mất model Pyannote không? | **PASS - không có mất thêm dữ liệu** | Inventory nguồn và đích được lưu trên E đều có đúng 9 file/25,179 byte, mọi material hash đều match. |
| Local model hiện tại có phải snapshot chạy được không? | **FAIL** | `models/pyannote` có 0 file; `models/pyannote_cache` chỉ có refs, README và LICENSE của pipeline cũ. |
| Cấu hình runtime hiện tại có tìm đúng payload đang có không? | **FAIL** | Manager và Cherry adapter tìm `models/pyannote`; cache metadata nằm ở `models/pyannote_cache`. Dù đổi path, cache này vẫn thiếu toàn bộ weight/config cần thiết. |
| Stack hiện tại có tương thích Community-1 không? | **FAIL/UNPROVEN** | Runtime là `pyannote.audio 3.1.1`, Torch/Torchaudio `2.1.1+cu121`, không có TorchCodec; Community-1 đi cùng API và dependency line 4.x. |
| Có thể coi kết quả một speaker hiện tại là diarization thành công không? | **NO** | Runtime log xác nhận pipeline không load; contract hiện gộp failure và verified one-speaker qua điều kiện `num_speakers > 1`. |

Product diarization vẫn **BLOCKED**. Đây không phải lỗi copy workspace; source payload trước migration đã không phải model hoàn chỉnh.

## 1. Migration Evidence

Harness đọc ba artifact migration đã nằm trên E:

- `E:\research\_STT_migration_evidence\2026-08-09-d-to-e/source-inventory.csv`
- `E:\research\_STT_migration_evidence\2026-08-09-d-to-e/destination-inventory.csv`
- `E:\research\_STT_migration_evidence\2026-08-09-d-to-e/material-hashes.csv`

Kết quả đối chiếu riêng prefix `models\pyannote_cache\`:

- Source: 9 file, 25,179 byte.
- Destination: 9 file, 25,179 byte.
- Material hash rows: 9/9 match.
- File thực tế trên E: 9 file, cùng path/size/SHA-256.
- `models/pyannote`: 153 directory cache-layout nhưng 0 file.

Chín file chỉ gồm ba `refs/main`, ba `LICENSE` và ba `README.md`. Không có `config.yaml`, `pytorch_model.bin`, PLDA NPZ hay segmentation weight.

Cache speaker-diarization hiện có revision `0949b739131820b428f82569d616ba84a1903c11`; README tự mô tả pipeline 2.1/pyannote.audio 2.1.1. Nó không phải `speaker-diarization-3.1`, càng không phải Community-1 revision `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`.

## 2. Resolver and Configuration Findings

### Model root không thống nhất

- `PyannoteManager` dùng relative `Path("models/pyannote")`, phụ thuộc current working directory.
- `PyannoteAdapter` dùng absolute project-aware `MODELS_DIR / "pyannote"`.
- Không path production nào tìm `models/pyannote_cache`.
- Token path cũng khác: manager lấy `settings.HF_TOKEN`, adapter ưu tiên `os.getenv("HF_TOKEN")`; `.env` có thể được settings nạp nhưng chưa chắc có trong process environment.

Việc đổi resolver sang cache cũ không phải fix hợp lệ vì cache thiếu payload. D1 phải chọn một canonical absolute model root và chỉ chấp nhận snapshot có full tree + manifest hash.

### Resolver có thể pass quá sớm

`resolve_huggingface_snapshot` mặc định chỉ yêu cầu `config.yaml`. Hai caller hiện không truyền full Community-1 required tree. Một snapshot chỉ có config có thể được resolver chọn rồi fail muộn khi model bắt đầu load nested embedding/PLDA/segmentation asset.

Required tree tối thiểu đã khóa:

- `config.yaml`
- `embedding/pytorch_model.bin`
- `plda/plda.npz`
- `plda/xvec_transform.npz`
- `segmentation/pytorch_model.bin`

## 3. Runtime Evidence

Celery log trên E ghi ba lần cùng lỗi trong ngày audit:

- `celery.runtime.e.log:23`
- `celery.runtime.e.log:60`
- `celery.runtime.e.log:96`

Thông báo là `No complete local snapshot; offline strict mode refuses provider fallback`. Đây là fail-closed hợp lệ ở loader boundary, nhưng caller phía trên vẫn có thể tiếp tục transcription và persist trạng thái một-speaker mơ hồ.

Effective configuration:

- `OFFLINE_STRICT=true` từ default config.
- `TRANSCRIPTION_ENGINE=legacy` từ `.env`.
- HF token được cấu hình nhưng giá trị không được ghi vào artifact; offline strict chặn provider fallback.
- `HF_HUB_OFFLINE` và `TRANSFORMERS_OFFLINE` chưa được đặt.

`PyannoteManager.is_available()` hiện kích hoạt lazy model load. Một health/readiness probe do đó có thể gây load GPU hoặc network attempt khi offline strict bị tắt; D1 cần tách artifact availability, load readiness và live loaded state.

## 4. Community-1 Compatibility

Một canonical primary-source capture tải đúng 7 official metadata responses, lưu raw content dạng Base64, rồi tự kiểm lại URL, HTTP status, byte count, SHA-256 và parsed semantics. Migration audit không fetch hoặc tự khai báo lại provenance; nó cross-bind chính xác capture path, artifact SHA-256, capture ID, timestamp và ba source bindings cần cho Pyannote.

Official source capture trả HTTP 200 và được hash trong machine artifact:

- Hugging Face metadata xác nhận model ID, gated access, CC-BY-4.0, revision `3533c8cf...` và full required tree.
- PyPI `pyannote.audio==4.0.0` yêu cầu Python >=3.10, Torch >=2.8.0, Torchaudio >=2.8.0 và TorchCodec >=0.6.0.
- Official 4.0.0 release ghi breaking changes: `use_auth_token` đổi thành `token`, audio I/O chuyển sang TorchCodec, local air-gapped pipeline được hỗ trợ, và Community-1 trả object có `speaker_diarization` cùng `exclusive_speaker_diarization`.

Local stack:

| Thành phần | Local | Community-1/4.0 contract | Trạng thái |
|---|---:|---:|---|
| Python | 3.11.9 | >=3.10 | Compatible |
| pyannote.audio | 3.1.1 | 4.x API target | Incompatible/unproven |
| torch | 2.1.1+cu121 | >=2.8.0 | Incompatible |
| torchaudio | 2.1.1+cu121 | >=2.8.0 | Incompatible |
| torchcodec | missing | >=0.6.0 | Missing |
| FFmpeg | 7.1.1 | required by TorchCodec | Present |

`requirements.txt` không pin `pyannote.audio` hoặc `torchcodec`; Pyannote 3.1.1 hiện được kéo gián tiếp qua `diart>=0.9.2`. Vì vậy clean install không khóa được cùng runtime đã audit.

Code cũng chưa tương thích 4.x:

- Cả manager và adapter dùng keyword `use_auth_token` đã bị đổi.
- Adapter gọi `diarization.itertracks(...)` trực tiếp, chưa unwrap Community-1 output object.
- Adapter docstring nói Community-1/4.0 nhưng error guidance lại trỏ license 3.1.
- Manager fallback online lại request 3.1, còn adapter request Community-1.

Chỉ chép weight Community-1 vào `models/pyannote` sẽ không đủ và có khả năng fail ngay khi load hoặc khi đọc output.

## 5. Impact on User-visible Diarization

Current persistence dùng `has_diarization = enable_diarization and num_speakers > 1`. Hệ quả:

1. Pipeline không load và fallback một speaker bị biểu diễn giống verified one-speaker audio.
2. `diarization_method=pyannote` có thể được persist dù method thực tế không chạy.
3. Cherry path nuốt diarization exception rồi tiếp tục, không persist degraded reason.
4. Legacy alignment gán toàn ASR segment cho speaker có overlap lớn nhất; overlap, tie và uncertainty bị mất.
5. Community-1 exclusive diarization chưa được dùng để cải thiện ASR alignment.

Do đó dữ liệu speaker hiện tại không đủ tin cậy để gán đối tượng, số tiền, tài khoản, lời hứa, hành động hay vai trò nhạy cảm trong bulletin điều tra.

## 6. Locked Remediation for D1/D2

### D1 - Artifact and runtime profile

1. Không promote cache 2.1 cũ và không đổi path để giả lập thành công.
2. Sau khi user/organization hoàn tất gated acceptance, acquisition harness tải đúng Community-1 revision `3533c8cf...` vào một canonical absolute repo-local root.
3. Manifest ghi mọi file/path/size/SHA-256, model revision, metadata response hash, license/attribution và authorization event.
4. Trước khi thay shared venv, chạy compatibility preflight cho hai phương án: isolated diarization runtime và coordinated shared-stack upgrade. Chọn theo correctness, GPU handoff, startup latency, VRAM và regression ASR; không chọn chỉ vì cài đặt dễ hơn.
5. Pin Pyannote/Torch/Torchaudio/TorchCodec/FFmpeg-compatible runtime. Clean install phải tái tạo đúng version set.
6. Manager và adapter dùng cùng canonical path, full-tree resolver và cùng token/config authority.
7. Network-denied loader phải chứng minh không tạo cache ngoài release root, tampered/missing nested asset fail trước audio, và output API được unwrap đúng.

### D2 - Contract and alignment

1. Persist riêng `requested_method`, `method_used`, model/revision/hash và `diarization_status`.
2. Phân biệt `verified_one_speaker`, `multi_speaker`, `unavailable`, `degraded` và `failed`.
3. Giữ regular/exclusive turns, overlap, ambiguity, confidence provenance và file identity.
4. Chỉ dùng word-aware alignment khi timestamp provenance đạt gate; không dùng winner-take-all toàn segment làm ground truth.
5. Speaker-dependent claim phải bị withhold/qualify khi diarization chưa verified.

## 7. Acceptance Gates

Diarization chỉ được gọi là hoạt động khi tất cả điều kiện sau PASS:

- Full snapshot + manifest + acquisition/license evidence replay được.
- Clean, network-denied loader PASS và external cache inventory không đổi.
- Runtime dependency/API compatibility PASS.
- Missing/tampered asset fail trước audio processing.
- Live one-speaker fixture được ghi là verified, khác failure fallback.
- Multi-speaker/overlap/tie/zero-duration fixtures PASS.
- DER/JER, speaker-count, overlap recall, cpWER/tcpWER và latency/VRAM được đo trên corpus khóa ở E1A/E1.
- Summary release không gán sensitive value cho speaker khi assignment unresolved.

## 8. Rerun

```powershell
Set-Location E:\research\STT

.\venv\Scripts\python.exe -B scripts\capture_diarization_primary_sources.py `
  --output docs\reviews\artifacts\2026-08-09-diarization-primary-source-verification.json

.\venv\Scripts\python.exe -B scripts\audit_pyannote_migration_config.py `
  --no-network `
  --output docs\reviews\artifacts\2026-08-09-pyannote-migration-config-audit.json
```

Không hardcode raw digest của Hugging Face API làm hằng số vĩnh viễn vì response có metadata động. Mỗi lần freeze phải dùng đúng một sealed capture; digest từ lần capture khác phải bị reject.

Exit `2` là expected khi product blockers còn tồn tại; artifact vẫn phải parse được và `migration_verdict` phải là `PASS_NO_ADDITIONAL_LOSS`.

**Boundary:** audit này chứng minh nguyên nhân cấu hình/artifact hiện tại và khóa remediation gate. Nó chưa cài model và chưa chứng minh chất lượng diarization tiếng Việt.
