# Adaptive Summary/Analysis Research Source Audit

**Ngày audit:** 2026-08-09
**Phạm vi:** thiết kế Summary/Analysis thích ứng, bảo toàn bằng chứng; không audit model ASR/diarization trong tài liệu này
**Tài liệu được audit:** `docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md` và `docs/plans/2026-08-09-adaptive-investigative-intelligence-plan.md`
**Trạng thái:** source audit cho T0; không phải benchmark chất lượng production

## 1. Kết luận audit

Thiết kế `extract -> verify -> synthesize` hiện tại có nền tảng đúng, nhưng cần bổ sung một lớp reasoning có contract rõ ràng để LLM không bị thu hẹp thành form filling và cũng không được biến suy đoán thành sự thật. Kiến trúc được source audit chấp nhận theo bốn tầng:

1. **Open-schema evidence discovery:** khám phá claim/entity/event/relation không bị khóa bởi form nghiệp vụ.
2. **Atomic verification:** tách claim nguyên tử, resolve span và kiểm tra value/polarity/owner trước khi release.
3. **Bounded intelligence reasoning:** chỉ suy luận trên verified ledger để tạo insight, hypothesis và verification action có premise/counterevidence rõ ràng.
4. **Grounded projections:** Summary và Analysis là hai projection của cùng ledger/reasoning run, không tự trích xuất độc lập.

Các nguồn 2024-2026 không chứng minh một model hay framework duy nhất giải quyết được toàn bộ bài toán. Kết luận có bằng chứng mạnh nhất là phải kết hợp nhiều cơ chế và benchmark trực tiếp trên corpus tiếng Việt của dự án.

## 2. RTK contract và phương pháp

### 2.1 Yêu cầu có thể bác bỏ

| ID | Yêu cầu audit | Điều kiện fail |
|---|---|---|
| A1 | Mỗi claim kiến trúc quan trọng có primary source hoặc local artifact trực tiếp. | Chỉ dựa vào blog, README không chính thức hoặc suy đoán. |
| A2 | Quan sát khoa học được tách khỏi đề xuất triển khai. | Paper result được trình bày như chất lượng đã đạt trong repo. |
| A3 | Source mới chỉ đi vào T0-T9 khi làm thay đổi gate, ablation hoặc implementation contract. | Thêm công nghệ chỉ vì mới/SOTA. |
| A4 | Giới hạn English-domain, Vietnamese transfer, license và offline runtime được ghi rõ. | Promote model/runtime từ paper/model card mà không benchmark cục bộ. |
| A5 | Insight, hypothesis và verification action có ranh giới release kiểm thử được. | Hypothesis có thể xuất hiện trong factual overview hoặc không có premise. |

### 2.2 Evidence protocol

- Ưu tiên paper/proceedings, specification, official repository và official model card.
- Metadata arXiv được đối chiếu qua arXiv API theo identifier; venue ACL dùng ACL Anthology khi có record rõ.
- Claim chi tiết chỉ dùng khi xuất hiện trong abstract/paper/repository chính thức; venue chưa có primary record rõ được ghi là arXiv thay vì suy đoán.
- Repository/runtime evidence chỉ chứng minh capability và license của software surface, không chứng minh chất lượng mô hình.
- Tất cả URL trong tài liệu này được truy cập ngày **2026-08-09**.

## 3. Ranh giới reasoning đã audit

| Output | Điều kiện tạo | Nội dung được phép | Release rule |
|---|---|---|---|
| `evidence_backed_insight` | Tất cả premise là released claim; phép biến đổi có type và kiểm tra được. | Tổng hợp thời gian, đồng tham chiếu, pattern lặp, quan hệ hoặc theme được entail bởi premise. | Có `premise_claim_ids`, `evidence_refs`, `derivation_type`, counterevidence và sentence mapping; được phép vào factual projection. |
| `hypothesis` | Có premise nhưng kết luận không được nguồn entail đầy đủ. | Khả năng giải thích, liên hệ tiềm tàng, bất thường hoặc câu hỏi điều tra. | Luôn gắn nhãn hypothesis, có alternative explanations và `human_verification_required=true`; cấm vào factual overview. |
| `verification_action` | Có information gap, contradiction hoặc hypothesis cần kiểm tra. | Câu hỏi/đối chiếu cụ thể, nguồn cần thu thập và tiêu chí promote/reject. | Không được biểu diễn như fact; phải tham chiếu gap/hypothesis và không được tự đổi trạng thái evidence. |

Không lưu hoặc hiển thị chain-of-thought tự do. Hệ thống chỉ lưu structured justification tối thiểu gồm premise, phép suy dẫn, counterevidence, uncertainty và hành động xác minh. Cách này khai thác reasoning của LLM nhưng giữ được auditability và giới hạn dữ liệu nhạy cảm.

## 4. Audit nguồn hiện có S1-S24

| ID | Primary source và URL | Claim được source hỗ trợ | Mức hỗ trợ | Giới hạn áp dụng |
|---|---|---|---|---|
| S1 | SummEval, TACL 2021, https://doi.org/10.1162/tacl_a_00373 | Human evaluation cần tách coherence, consistency, fluency và relevance; metric tự động không đại diện đầy đủ chất lượng. | Mạnh cho rubric | English/CNN-DM; không phải attribution hoặc investigative utility metric. |
| S2 | Maynez et al., ACL 2020, https://aclanthology.org/2020.acl-main.173/ | Abstractive summary có factual errors đáng kể; entailment-based signals liên quan faithfulness hơn overlap đơn thuần. | Mạnh | English summarization; không cung cấp production verifier hay provenance selector. |
| S3 | FactCC, EMNLP 2020, https://aclanthology.org/2020.emnlp-main.750/ | Factual consistency có thể kiểm tra ở claim level và kèm supporting/conflicting spans. | Mạnh cho span-assisted review | Dữ liệu perturbation tổng hợp và English news; không phải sole release gate. |
| S4 | QAFactEval, NAACL 2022, https://aclanthology.org/2022.naacl-main.187/ | QA-based factuality có thể cải thiện khi kết hợp các thành phần QA/entailment được chọn đúng. | Mạnh cho secondary metric | English; phụ thuộc question generation/answering và không bảo đảm attribution. |
| S5 | SummaC, TACL 2022, https://doi.org/10.1162/tacl_a_00453 | Aggregation NLI ở granularity phù hợp cải thiện inconsistency detection. | Mạnh cho secondary metric | Metric-level evidence; không tạo claim ledger hoặc exact span contract. |
| S6 | AlignScore, ACL 2023, https://aclanthology.org/2023.acl-long.634/ | Unified alignment model có thể chấm factual consistency trên nhiều task. | Mạnh cho candidate metric | Transfer sang tiếng Việt và noisy ASR chưa được chứng minh. |
| S7 | FActScore, EMNLP 2023, https://aclanthology.org/2023.emnlp-main.741/ | Long-form output nên được tách thành atomic facts rồi kiểm tra từng fact. | Mạnh cho atomic decomposition | Thiết kế gốc kiểm tra với knowledge source; không tự cung cấp transcript span attribution. |
| S8 | AIS, Computational Linguistics 2023, https://doi.org/10.1162/coli_a_00486 | Attribution phải được đánh giá đối với source được xác định rõ. | Mạnh cho human judgment | Không phải automated release checker; cần guideline tiếng Việt riêng. |
| S9 | ALCE, EMNLP 2023, https://aclanthology.org/2023.emnlp-main.398/ | Citation generation cần đo correctness và completeness/recall, không chỉ có marker citation. | Mạnh cho citation evaluation | RAG/QA setting; citation marker không tương đương immutable forensic provenance. |
| S10 | QMSum, NAACL 2021, https://aclanthology.org/2021.naacl-main.472/ | Query-based meeting summarization dùng locate-then-summarize và long multi-speaker context. | Mạnh cho coverage architecture | English meetings; không phải corpus điều tra hoặc claim verifier. |
| S11 | DYLE, ACL 2022, https://aclanthology.org/2022.acl-long.118/ | Long-input summarization có lợi từ extraction kết hợp generation. | Mạnh cho extract-before-generate | Latent extraction không bảo đảm support span hay factual release. |
| S12 | Lost in the Middle, TACL 2024, https://doi.org/10.1162/tacl_a_00638 | Context window danh nghĩa không bảo đảm dùng đều evidence, đặc biệt ở vị trí giữa. | Mạnh | Không đưa ra chunk strategy tối ưu cho tiếng Việt; cần benchmark project-specific. |
| S13 | UIE, ACL 2022, https://aclanthology.org/2022.acl-long.395/ | Schema-conditioned structure generation có thể thống nhất nhiều task information extraction. | Mạnh cho adaptive extraction | Vẫn cần schema prompt; không chứng minh open-ended investigative ontology hoặc span fidelity. |
| S14 | GoLLIE, ICLR 2024, https://arxiv.org/abs/2310.03668 | Guideline chi tiết cải thiện zero-shot IE trên schema chưa thấy. | Mạnh cho guideline-driven discovery | Kết quả không trực tiếp trên tiếng Việt/noisy transcript; model scale và license cần audit riêng. |
| S15 | GCD, EMNLP 2023, https://aclanthology.org/2023.emnlp-main.674/ | Input-dependent grammar có thể enforce structured output không cần finetune. | Mạnh cho structure | Chỉ bảo đảm output thuộc grammar; không bảo đảm claim đúng hoặc đủ. |
| S16 | Ollama Structured Outputs, https://docs.ollama.com/capabilities/structured-outputs | Runtime hỗ trợ JSON schema và khuyến nghị temperature thấp cho structured generation. | Mạnh cho capability | Official runtime documentation, không phải quality/factuality evidence. |
| S17 | JSON Schema required properties, https://json-schema.org/understanding-json-schema/reference/object#required | Optional property có thể bị omit nếu không nằm trong `required`. | Mạnh/chuẩn | Chỉ là structural semantics; sanitizer và business invariants vẫn cần riêng. |
| S18 | W3C Web Annotation Data Model, https://www.w3.org/TR/annotation-model/ | TextQuoteSelector dùng exact/prefix/suffix; TextPositionSelector dùng start/end. | Mạnh/chuẩn | Selector không tự chống source revision drift; immutable source hash vẫn bắt buộc. |
| S19 | ViT5, NAACL SRW 2022, https://aclanthology.org/2022.naacl-srw.18/ | Vietnamese text-to-text pretraining là generation/summarization baseline phù hợp. | Vừa | Không chứng minh long-dialogue, evidence-grounded hoặc investigative reasoning quality. |
| S20 | PhoBERT, Findings EMNLP 2020, https://aclanthology.org/2020.findings-emnlp.92/ | Vietnamese pretrained encoder là baseline tốt cho downstream language understanding. | Mạnh cho baseline | Encoder không thay thế generative cross-turn synthesis hoặc open relation discovery. |
| S21 | VnCoreNLP, NAACL Demo 2018, https://aclanthology.org/N18-5012/ | Cung cấp Vietnamese linguistic processing/NER baseline. | Mạnh cho baseline | Ontology và pipeline cổ điển; không giải quyết open claim/relation reasoning. |
| S22 | ERASER, ACL 2020, https://aclanthology.org/2020.acl-main.408/ | Rationale evaluation cần agreement, comprehensiveness và sufficiency. | Mạnh cho evidence metric design | Rationale quality không đồng nghĩa factual truth; benchmark chủ yếu English. |
| S23 | SAMSum, EMNLP-IJCNLP 2019, https://aclanthology.org/D19-5409/ | Human-annotated chat summarization là regression baseline hội thoại. | Mạnh cho baseline | English casual chat, ngắn và không có investigative provenance. |
| S24 | FRANK, NAACL 2021, https://aclanthology.org/2021.naacl-main.383/ | Error typology và human benchmark giúp phân tích factuality metric. | Mạnh cho error taxonomy | English news datasets; không tự đánh giá omission/salience tiếng Việt. |

**Verdict S1-S24:** không phát hiện citation sai nghiêm trọng. Cần giữ cách diễn đạt giới hạn: các nguồn này hỗ trợ từng cơ chế/rubric, không chứng minh pipeline đề xuất đã tốt hơn baseline trong repo.

## 5. Nguồn 2024-2026 và quyết định áp dụng

| ID | Primary/official source | Observation đã xác minh | Áp dụng đề xuất | Giới hạn và quyết định |
|---|---|---|---|---|
| S25 | UniversalNER, arXiv:2308.03279, https://arxiv.org/abs/2308.03279 | Targeted distillation cho open NER; paper đánh giá 43 datasets, 9 domains và nhiều entity types. | Baseline cho open entity discovery và unseen-type recall. | Không có bằng chứng tiếng Việt điều tra; **benchmark only**, không promote mặc định. |
| S26 | GLiNER, NAACL 2024, https://aclanthology.org/2024.naacl-long.300/ ; code https://github.com/urchade/GLiNER | Compact bidirectional encoder trích entity type tùy ý theo natural-language label, song song thay vì autoregressive. | Candidate deterministic/neural entity channel cạnh LLM discovery; multilingual checkpoint là challenger. | NER-only, không thay claim/event/relation reasoner; phải pin model revision/license và benchmark Vietnamese ASR. |
| S27 | MiniCheck, EMNLP 2024, https://aclanthology.org/2024.emnlp-main.499/ ; code https://github.com/Liyan06/MiniCheck | Compact fact-checker; paper báo MiniCheck-FT5 770M đạt mức GPT-4 trên LLM-AggreFact với chi phí thấp hơn nhiều. | Local secondary verifier/ablation ở T4. | Official HF checkpoint khai `language=en`; synthetic GPT-4 training; không được override missing span hoặc làm sole Vietnamese gate. |
| S28 | SAFE, “Long-form factuality in large language models,” arXiv:2403.18802, https://arxiv.org/abs/2403.18802 | Tách long-form response thành individual facts rồi dùng multi-step search-based verification. | Hỗ trợ atomic decomposition và per-fact audit protocol. | Dùng Google Search/LLM agent và open-domain truth; không offline, không transcript-grounded. **Không tích hợp runtime SAFE**. |
| S29 | RefChecker, arXiv:2405.14486, https://arxiv.org/abs/2405.14486 ; code https://github.com/amazon-science/RefChecker | Claim-triplet granularity và checker theo zero/noisy/accurate context; benchmark 11k triplets từ 2.1k responses. | Baseline representation/checker cho relation claim và noisy-ASR evaluation. | Official repo đang archived tại ngày audit; không khóa production dependency vào repo này. |
| S30 | VERISCORE, Findings of EMNLP 2024, https://aclanthology.org/2024.findings-emnlp.552/ | Phân biệt verifiable và unverifiable claims; kết quả factuality thay đổi theo task/fact density. | Củng cố ranh giới claim/insight/hypothesis và yêu cầu benchmark theo task. | Không phải source-span verifier cho tiếng Việt; reference retrieval dùng web service, nên chỉ dùng concept/eval baseline. |
| S31 | LongCite, arXiv:2409.02897, https://arxiv.org/abs/2409.02897 ; code https://github.com/THUDM/LongCite | Fine-grained sentence-level citation cho long-context QA; cung cấp LongBench-Cite và models/dataset. | Tham khảo sentence-to-claim mapping, citation completeness/correctness và long-context citation regression. | QA setting; released evaluation dùng GPT-4o judge ở một phần; model/dataset không phải Vietnamese investigative solution. |
| S32 | RULER, arXiv:2404.06654, https://arxiv.org/abs/2404.06654 ; code https://github.com/NVIDIA/RULER | NIAH không đủ; multi-needle, multi-hop và aggregation cho thấy effective context thấp hơn advertised context ở nhiều model. | Thêm effective-context/position/multi-hop harness trước khi tăng one-shot context. | Synthetic benchmark; cần chuyển task sang turn/claim/value tiếng Việt của dự án. |
| S33 | GraphRAG, arXiv:2404.16130, https://arxiv.org/abs/2404.16130 ; code https://github.com/microsoft/graphrag | Entity graph + community summaries cải thiện global sensemaking/query-focused summarization trên corpora lớn trong paper. | Tham khảo graph community/theme planning và global overview trên verified ledger. | Graph và community summary do LLM tạo có thể sai; không dùng raw GraphRAG index làm evidence authority. |
| S34 | XGrammar technical report, arXiv:2411.15100, https://arxiv.org/abs/2411.15100 ; code https://github.com/mlc-ai/xgrammar | Efficient grammar-constrained decoding; official repo hỗ trợ JSON/CFG và nhiều runtime/platform. | Candidate structured-decoding backend; benchmark schema validity/latency với llama-server path. | Chỉ bảo đảm cấu trúc; pin release/build và kiểm tra compatibility. Không thay verifier. |
| S35 | SGLang, arXiv:2312.07104, https://arxiv.org/abs/2312.07104 ; code https://github.com/sgl-project/sglang | Runtime cho multi-call structured programs, KV-cache reuse và compressed-FSM structured decoding; paper báo throughput gains trên workload được thử. | Candidate batch/high-concurrency sidecar khi workload/hardware biện minh. | Không phải lựa chọn mặc định cho Windows single-GPU hiện tại; cần benchmark cùng request mix, model, context và quantization. |
| S36 | Qwen3 Technical Report, arXiv:2505.09388, https://arxiv.org/abs/2505.09388 ; model card https://huggingface.co/Qwen/Qwen3-8B | Dense/MoE family, thinking/non-thinking mode, 119 languages/dialects; model card Qwen3-8B dùng Apache-2.0. | Balanced local LLM candidate cho discovery/synthesis; non-thinking deterministic profile trước, thinking chỉ ở bounded reasoner ablation. | Multilingual aggregate không chứng minh Vietnamese investigative quality; thinking có thể tăng latency/verbosity và vẫn cần strict release gate. |
| S37 | Sailor2, arXiv:2502.12982, https://arxiv.org/abs/2502.12982 ; model card https://huggingface.co/sail/Sailor2-8B | Qwen2.5-based SEA model family 1B/8B/20B, có Vietnamese; paper/model card công bố Apache-2.0. | Vietnamese/SEA challenger đối chứng Qwen3 ở T8. | Chưa có evidence cho claim extraction/factuality/noisy ASR của dự án; official GGUF/runtime bundle cần audit trước air-gap use. |
| S38 | llama.cpp official repository, https://github.com/ggml-org/llama.cpp | Local C/C++ inference, GGUF quantization, CUDA và CPU/GPU hybrid, server API và grammar support trên Windows. | Runtime mặc định hợp lý để benchmark Qwen3/Sailor2 trên host 12 GB, với binary/model manifest pin tuyệt đối. | Runtime capability không chứng minh quality; quantization level phải có ablation và release binary phải được checksum/license bundle. |

## 6. Observation và proposal

| Observation có nguồn | Proposal trong dự án | Trạng thái |
|---|---|---|
| Open-schema/open-type extraction khả thi với UIE, GoLLIE, UniversalNER và GLiNER. | Kết hợp LLM claim discovery với compact open-type entity channel; không dùng fixed business enum. | Cần benchmark tiếng Việt; T3 ablation. |
| Atomic decomposition cải thiện granularity kiểm tra trong FActScore, SAFE, RefChecker và VERISCORE. | Split mọi candidate thành atomic claim trước verification; relation dùng premise IDs/triplet có evidence. | Contract/gate T4. |
| MiniCheck cho thấy compact local checker có thể cạnh tranh trên benchmark grounding English. | Thử MiniCheck như secondary signal, sau deterministic span/value checks. | Không promote trước Vietnamese calibration. |
| LongCite/AIS/ALCE nhấn mạnh fine-grained attribution và citation quality. | Mỗi factual sentence map về released claim IDs và resolvable source spans. | Hard gate T5. |
| Lost in the Middle và RULER cho thấy advertised context không phải effective context. | Turn-aware chunking, position-balanced recall và multi-hop/aggregation stress tests. | T3/T8 gate. |
| GraphRAG cho thấy graph community có ích cho global themes. | Theme/community reasoning chỉ chạy trên verified claim graph; raw transcript không phải graph fact authority. | T5 ablation. |
| XGrammar/SGLang/llama.cpp hỗ trợ structured decoding ở các runtime khác nhau. | Benchmark structure validity + latency trên runtime phù hợp hardware; không gắn factuality claim vào grammar. | T0/T8 runtime decision. |
| Qwen3 và Sailor2 có multilingual/Vietnamese coverage và permissive model licenses. | So sánh task-specific trên cùng ledger prompts/corpus/quantization; không xếp hạng từ benchmark tổng hợp. | T8 model selection. |

## 7. Thay đổi bắt buộc đối với plan

1. **T1:** contract phải có ba object tách biệt `EvidenceBackedInsight`, `Hypothesis`, `VerificationAction`; mọi reference phải resolve, và factual projection chỉ nhận claim/insight released.
2. **T3:** thêm GLiNER/UniversalNER-style open entity challenger; đo unseen-type recall và không coi entity detector là relation/claim reasoner.
3. **T4:** thêm atomicity test, claim-triplet/owner-unit binding, verifiable-vs-unverifiable disposition và MiniCheck/RefChecker-style secondary ablation.
4. **T5:** thêm bounded reasoner trên verified graph; hypothesis leakage count phải bằng 0; verification action phải có target/source/promotion criterion.
5. **T8:** thêm effective-context stress set theo RULER, citation regression theo LongCite và model/runtime matrix Qwen3/Sailor2 x quantization x llama.cpp; SGLang chỉ vào matrix nếu Linux sidecar/concurrency thực sự cần.
6. **T9:** human review UI và audit log phải giữ nguyên hypothesis/action history; acceptance của hypothesis tạo một human assertion mới, không sửa model output cũ.

## 8. Claim-to-evidence map cho quyết định mới

| Claim thiết kế | Evidence chính | Support strength | Không được suy rộng thành |
|---|---|---|---|
| Open schema tốt hơn fixed form cho discovery chưa biết trước. | S13, S14, S25, S26 | Vừa-mạnh | Chất lượng tiếng Việt đã tốt hoặc mọi ontology đều nên bỏ. |
| Atomic claim/triplet là granularity phù hợp để verify. | S7, S28, S29, S30 | Mạnh | Automated checker luôn đúng hoặc span evidence không cần thiết. |
| Compact local verifier đáng thử. | S27 | Vừa-mạnh | MiniCheck English là production gate cho tiếng Việt. |
| Citation phải fine-grained và đo correctness/completeness. | S8, S9, S31 | Mạnh | Citation marker tự chứng minh truth. |
| Long context phải đo effective coverage/multi-hop. | S12, S32 | Mạnh | Chỉ tăng `num_ctx` sẽ giải quyết omission. |
| Graph/community planning có thể hỗ trợ themes toàn cục. | S33 | Vừa | GraphRAG output là verified evidence. |
| Structured decoding cải thiện structural validity/efficiency. | S15, S16, S34, S35, S38 | Mạnh cho structure | Grammar làm claim factual hoặc complete. |
| Qwen3/Sailor2 là local Vietnamese candidates hợp lệ để benchmark. | S36, S37, S38 | Vừa | Model card/aggregate benchmark đủ để promote. |

## 9. Residual uncertainty

1. Phần lớn factuality/attribution benchmark vẫn là English; chưa có calibration tiếng Việt noisy-ASR và hội thoại vùng miền.
2. Open NER không đồng nghĩa open claim/event/relation extraction; GLiNER/UniversalNER chỉ là một kênh candidate.
3. Confidence từ LLM không được coi là xác suất đã hiệu chỉnh; cần human-labelled calibration hoặc chỉ dùng ordinal review priority.
4. Graph clustering/theme quality và investigative usefulness cần blind human review, không có metric tự động đủ mạnh.
5. Qwen3 và Sailor2 chưa được so sánh trên cùng prompt/schema/quantization/hardware của repo.
6. MiniCheck official checkpoint khai English; Vietnamese transfer và ASR robustness chưa biết.
7. XGrammar/SGLang/llama.cpp thay đổi nhanh; production phải pin source/release/binary hash thay vì dựa vào trạng thái `main` tại ngày audit.
8. Model license, code license và license của dataset/derived GGUF là ba bề mặt khác nhau, phải được manifest độc lập.

## 10. Validation đã chạy

| Check | Kết quả 2026-08-09 | Verdict |
|---|---|---|
| Citation ID consistency | Used và defined đều đúng tập S1-S38; `Compare-Object` rỗng. | PASS |
| External URL request check | 60 URL duy nhất: 55 trả HTTP 200; bốn DOI MIT Press và W3C spec trả HTTP 403 sau khi resolve đúng final URL do bot policy. Không có 404/5xx/timeout. | PASS_WITH_ACCESS_NOTE |
| Scope check | Chỉ ba file research/plan/source-audit trong phạm vi audit; cả ba vẫn untracked, không stage/commit/push. | PASS |
| Runtime/code tests | Không chạy vì lượt này chỉ thay tài liệu và không sửa production code. | NOT_APPLICABLE |

## 11. Rerunnable audit commands

```powershell
# Citation ID consistency in the research document.
$p = 'docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md'
$text = Get-Content -Raw $p
$used = [regex]::Matches($text, '\[S(\d+)\]') |
  ForEach-Object { [int]$_.Groups[1].Value } | Sort-Object -Unique
$defined = [regex]::Matches($text, '^\- \*\*\[S(\d+)\]\*\*', 'Multiline') |
  ForEach-Object { [int]$_.Groups[1].Value } | Sort-Object -Unique
Compare-Object $used $defined

# URL extraction; request checks must record redirects/status separately.
$files = @(
  'docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md',
  'docs/reviews/adaptive-summary-research-source-audit-2026-08-09.md'
)
$urls = foreach ($file in $files) {
  [regex]::Matches((Get-Content -Raw $file), 'https?://[^\s)>;]+') |
    ForEach-Object { $_.Value.TrimEnd('.', ',') }
}
$urls | Sort-Object -Unique

# Diff scope: this audit is allowed to touch only these three files.
git status --short -- `
  docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md `
  docs/plans/2026-08-09-adaptive-investigative-intelligence-plan.md `
  docs/reviews/adaptive-summary-research-source-audit-2026-08-09.md
```

**Audit boundary:** source review xác nhận thiết kế và các candidate cần benchmark. Nó không chứng minh model hiện tại đạt chất lượng, không thay legal/privacy review và không cho phép phát hành hypothesis như fact.
