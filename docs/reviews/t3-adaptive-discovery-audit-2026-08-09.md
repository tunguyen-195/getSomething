# T3 Adaptive Discovery Audit - 2026-08-09

## Kết luận

T3 đạt điều kiện promote sang T4 ở phạm vi **candidate discovery**. T3 không có quyền xác minh, phát hành fact, gán risk hay tạo hypothesis. Chất lượng model thực tế chưa được tuyên bố vì chưa chạy controlled ablation trên corpus Tier-A có nhãn người.

## Objective và completion gates

| Gate | Kết quả | Bằng chứng |
|---|---|---|
| Open-schema discovery thay cho form cố định | PASS | `LLMAtomicCandidateDraft`, `LLMEntityMentionDraft`, six-arm ablation manifest |
| Model không sở hữu ID/provenance/risk/release | PASS | Strict raw schema, nested forbidden-key validation, canonical host ID tests |
| Quote phải resolve về source revision bất biến | PASS | T2 selector resolver + final batch replay |
| Overlap chỉ là context, không phải output scope | PASS | Primary-only materialization và cross-chunk rejection |
| Chunk coverage/budget/determinism | PASS | Full prompt estimate, focus reserve, contiguous overlap, cross-process hash test |
| Exact-value recall không tự suy diễn owner/relation | PASS | Cue-sensitive detectors; ambiguous mentions giữ candidate-only |
| Prompt injection và privacy boundary | PASS | Transcript/focus nằm trong user JSON; system prompt tách hash; không đưa case/file timestamps |
| Replay manifest đủ metadata cốt lõi | PASS | Model/runtime/tokenizer/template/quantization/chunk/detector/retry/Git/source hashes |
| Static + regression gates | PASS | 211 tests; Black/Flake8/MyPy/compileall PASS |
| Production quality claim | NOT CLAIMED | Chưa có locked human-labelled Vietnamese Tier-A corpus và model ablation |

## Findings đã sửa trong audit

1. **High - forged chunk qua `model_copy()`**: prompt/materialization từng chấp nhận segment khác nhưng giữ `chunk_id` cũ. Mọi public builder nay revalidate canonical chunk/plan và bind prompt với verified plan.
2. **High - prompt budget sai**: planner từng chỉ đếm transcript (`10` tokens) trong khi prompt truyền thực tế khoảng `845` tokens. Planner nay dùng chung canonical user-content builder, tính system + JSON + framing + focus reserve, và replay lại estimate.
3. **High - overlap sinh duplicate output**: LLM/entity output nay chỉ được phép tham chiếu primary segments; overlap chỉ cung cấp ngữ cảnh.
4. **High - `entity_mentions` bị bỏ mất**: entity mentions từ LLM nay được materialize thành evidence-bound candidate records, không bị parse rồi discard.
5. **High - nested authority smuggling**: attributes không còn được chứa ID, provenance, risk, verification, release hoặc entity-relation authority fields.
6. **High - forged IDs và cross-chunk selectors**: candidate/evidence IDs được recompute từ evidence-bound content; final replay kiểm tra selector thuộc primary scope của đúng chunk.
7. **High - public verification seal**: public seal helper đã bị loại khỏi API; chỉ successful replay tạo `VerifiedDiscoveryBatch`.
8. **Medium - detector số nhập nhằng**: regex không còn gộp hai số cạnh nhau; cue gần nhất quyết định phone/account/identity và giữ leading zero.
9. **Medium - provenance malleability**: candidate/entity record bắt buộc đúng một selector; extra unbound selector bị reject.
10. **Performance - selector setup lặp lại**: `EvidenceSelectorResolver` tái sử dụng normalization, segment index và occurrence cache cho cùng revision; final replay vẫn được giữ nguyên.

## Harness và kết quả

### Static gates

```powershell
.\venv\Scripts\python.exe -m black --check <9 scoped files>
.\venv\Scripts\python.exe -m flake8 --ignore=E501,E203,W503 <9 scoped files>
.\venv\Scripts\python.exe -m mypy <7 scoped source/test files>
.\venv\Scripts\python.exe -m compileall -q src\services\investigation tests\test_investigation_evidence_selectors.py tests\test_investigation_discovery.py
```

Kết quả: Black PASS (`9 files unchanged`), Flake8 PASS, MyPy PASS (`7 source files`), compileall PASS.

### Regression

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\test_adaptive_summary_contracts.py tests\test_investigation_evidence_selectors.py tests\test_adaptive_eval_harness.py tests\test_investigation_discovery.py
```

Kết quả: `211 passed, 13 warnings in 83.44s`. Warnings là deprecation hiện hữu ngoài phạm vi T3.

### Standalone performance

Corpus dài: 1.200 segments, 2.400 mentions, 55 chunks; toàn bộ source revision + planning + detector hoàn thành `0.825096s`. Chunk lớn nhất `3322/3328` input tokens theo estimator đã pin.

Candidate materialization, median 5 lần chạy:

| Candidates | Median | Max |
|---:|---:|---:|
| 40 | 0.023231s | 0.023838s |
| 80 | 0.044769s | 0.047340s |
| 160 | 0.089491s | 0.095118s |

Trước resolver cache, 160 candidates mất khoảng `4.11s`; sau sửa còn khoảng `0.089s` trên cùng kiểu corpus/config.

## Artifact hashes

```text
5b651183a8a9ba67dca3822336d043cfaad521bc65edad55445e0b35a577b85e  src/services/investigation/__init__.py
d0dc5b717dbdfefa0d129b141a5bc0296cf417ccb8b05653f07ef9479ed2bc69  src/services/investigation/evidence_selector.py
79cd79a0d465be0f92cb8112d5e698519e564c52faf9240bfb5a24edc3dd78e8  src/services/investigation/discovery_common.py
c1380efb1657ea1f6dc502963fe32f16c67b13eb003479795ed21e4018662745  src/services/investigation/chunk_planner.py
71d86eb3dd951083815b58a66fbd1b7ea8e0815339d364873f97a328a9adb9b8  src/services/investigation/exact_detectors.py
7bacf0adc05089a93802fcf9317a350e5df0536ffb75636790477935ade9f75f  src/services/investigation/discovery_contracts.py
b22849ee2ef501f1a2164efe9933713d7599918c8439a274bb5be1c483ae14e1  src/services/investigation/discovery.py
e3678fb02b83b951041655092c800aba2773c8aadf2f5c10866a874556689208  tests/test_investigation_evidence_selectors.py
44098fe8238558eab69396829cd25e60be7f342abddfea8136bfa622f0501e31  tests/test_investigation_discovery.py
```

Các hash trên là snapshot ngay trước khi tạo audit document; source HEAD nền là `11a268ab6b26a08d7a853c334af9c51edc405798`.

## Security, privacy và epistemic boundary

- Transcript và focus là untrusted user data; không được ghép vào system instruction.
- Ordinary logs không chứa transcript/model output theo manifest retry policy.
- T3 chỉ tạo candidate; `verification_decisions=None`, `canonical_claims=None`, `release_authority=False` là invariant.
- Detector/LLM không được gán owner, intent, criminality, risk hoặc human-review policy.
- Case creation time và file upload time không nằm trong model payload; các timestamp UI/DB chỉ phục vụ người dùng.

## Residual risks và rollback triggers

- Chưa chạy model local thật, entity challenger thật hoặc six-arm ablation; không suy diễn chất lượng production từ unit tests.
- Token estimate vẫn là conservative UTF-8 estimator, chưa phải tokenizer thật. Runtime phải pin tokenizer/template và reject khi measured prompt vượt context.
- Regex detectors vẫn là high-recall candidates và có thể false positive; T4 phải verify/dedupe/merge uncertainty.
- Chưa có locked Vietnamese investigative corpus có nhãn người, inter-annotator agreement và baseline fixed-form.
- Independent auditor tìm được nhiều blocker quan trọng, nhưng final re-audit bị gián đoạn bởi tool safety false-positive; root đã rerun toàn bộ adversarial/static/regression gates trên snapshot cuối.
- Rollback T3 nếu: selector replay mismatch, prompt vượt context, candidate lọt khỏi primary chunk, factual/release authority xuất hiện trong T3, hoặc p95 materialization tăng trên 2 giây/160 candidates trong môi trường mục tiêu.

## Next gate

T4 phải xác minh evidence, canonicalize/dedupe claim, giữ contradiction/uncertainty, và tách fact khỏi hypothesis trước khi T5 reasoning hoặc UI Summary/Analysis được phép hiển thị nội dung như tri thức điều tra.
