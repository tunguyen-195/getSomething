# Investigative Summary Product Technology Scout

**Ngày xác minh:** 2026-08-11
**Workspace:** `E:\research\STT`
**Mục đích:** chọn kỹ thuật, model và runtime có thể áp dụng trực tiếp để hoàn thiện sản phẩm hỗ trợ điều tra, trinh sát; không dùng kết quả này như một nghiên cứu học thuật hoặc tuyên bố benchmark.

## Yêu cầu sản phẩm có thể kiểm chứng

1. Summary là bản tin tiếng Việt liền mạch, không phải transcript rút gọn hoặc danh sách field.
2. Nội dung bao phủ câu chuyện, đối tượng, vai trò, sự kiện, quan hệ, giá trị chính xác, kế hoạch/kết quả và mâu thuẫn quan trọng của toàn file.
3. Writer được phép diễn đạt lại nhưng không được đổi actor/action/object/recipient, số liệu, phủ định, attribution hoặc planned/completed state.
4. Evidence ID, speaker ID, offset âm thanh, hash, model/prompt metadata và thông báo hệ thống không xuất hiện trong thân bản tin.
5. Writer/model không sẵn sàng hoặc critic không đạt thì task fail closed; preview/transcript excerpt không được persist hoặc hiển thị như Summary.
6. Audio dài phải giữ full-source coverage bằng map/merge/coverage có source-unit refs; không giải quyết chỉ bằng cách tăng context window.

## Quyết định áp dụng ngay

- Giữ `Qwen3-8B Q4_K_M` chạy qua repository-local `llama-server` làm baseline cần kích hoạt lại và kiểm chứng end-to-end. Không dùng Ollama `llama3.2:3b` đang chạy live làm chuẩn chất lượng sản phẩm.
- Ưu tiên `Gemma 4 E4B-it Q4_0` rồi `Gemma 4 12B-it Q4_0` làm challenger trên RTX 4070 SUPER 12 GB. Chỉ promote sau Vietnamese product evaluation và VRAM/latency smoke thực tế.
- `Qwen3.5-9B` chỉ vào vòng thử nghiệm sau khi có self-conversion, manifest/hash và reproducible offline load; không promote từ community GGUF chưa được dự án kiểm soát.
- Dùng native JSON schema/grammar của runtime để khóa writer output. Provider adapter phải normalize hai dạng `response_format` của llama.cpp và OpenAI-compatible runtimes.
- Reranker như `gte-multilingual-reranker-base` chỉ chọn evidence candidate. Verdict factual cuối vẫn do exact-value, semantic-role, negation, modality, attribution và contradiction critics của host quyết định.

## Kiến trúc sản phẩm mục tiêu

```text
Transcript + speaker turns
        -> immutable source units
        -> chunk-level typed extraction
        -> canonical claim ledger + contradictions
        -> scenario-specific coverage obligations
        -> hierarchical ref-preserving rollup
        -> officer-style narrative writer JSON
        -> deterministic claim/length/public-body critics
        -> reader-facing report body
```

Mỗi obligation đại diện cho một claim nghiệp vụ canonical và có thể có nhiều projection alias từ fact/entity/event/relationship. Writer phải bao phủ obligation đúng một lần, thay vì lặp lại cùng một nghĩa vì claim xuất hiện ở nhiều bảng dữ liệu.

## Candidate matrix

| Ứng viên | Điểm phù hợp sản phẩm | Ràng buộc triển khai | Quyết định |
|---|---|---|---|
| Qwen3-8B official GGUF | Apache-2.0, official Q4_K_M khoảng 5 GB, đã có bundle/hash trong repo | Cần kích hoạt `llama-server` canonical và chạy corpus Việt | Baseline |
| Gemma 4 E4B-it Q4_0 official GGUF | Apache-2.0, 128K, official quant khoảng 5.15 GB | Kiểm tra chất lượng tiếng Việt và instruction fidelity | Challenger 1 |
| Gemma 4 12B-it Q4_0 official GGUF | Apache-2.0, 256K, official quant khoảng 6.98 GB | Context 8-16K, concurrency 1 trên 12 GB | Quality challenger |
| Qwen3.5-9B | Apache-2.0, long context, multilingual | Chưa có project-controlled official GGUF; local smoke từng chết runner | Sau self-conversion |
| Ministral 3 8B official GGUF | Apache-2.0, official Q4_K_M khoảng 5.2 GB | Model card không nêu tiếng Việt rõ | Challenger phụ |
| Sailor2 3B/8B/14B | Chuyên Đông Nam Á, có tiếng Việt | Quant/runtime artifact chưa được pin | Vietnamese control |

## Product promotion gate

Harness phải ghi model ID, revision/hash, quantization, runtime build, context, decoding params, hardware, input corpus revision, latency, RAM/VRAM và raw result JSONL. Một candidate chỉ PASS khi:

- JSON/schema valid 100%;
- required canonical obligations exact-once 100%;
- exact values và actor/action/object/recipient không sai;
- phủ định, attribution, planned/completed và contradiction được giữ nguyên;
- unsupported high-risk claim, legal overclaim, prompt-injection execution và public-body metadata leakage đều bằng 0;
- không OOM, không silent fallback, chạy offline từ canonical release root;
- chất lượng bản tin tiếng Việt được cán bộ đọc và đánh giá tốt hơn baseline trên cùng frozen product cases.

Các product case bắt buộc gồm: một/hai/nhiều speaker, overlap, tiền/tài khoản/số điện thoại/biển số, cáo buộc-kế hoạch-phủ nhận, mâu thuẫn, alias, nội dung quan trọng ở giữa/cuối audio, audio dài và writer/model unavailable.

## Nguồn chính thức đã kiểm tra

- Qwen3-8B GGUF: https://huggingface.co/Qwen/Qwen3-8B-GGUF
- Qwen3.5-9B: https://huggingface.co/Qwen/Qwen3.5-9B
- Qwen3 Embedding/Reranker: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B và https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- Gemma 4 E4B/12B official GGUF: https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf và https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf
- Ministral 3 8B official GGUF: https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF
- Sailor2: https://huggingface.co/sail/Sailor2-8B-Chat
- llama.cpp: https://github.com/ggml-org/llama.cpp
- vLLM structured output và Windows support: https://docs.vllm.ai/
- SGLang structured outputs: https://docs.sglang.ai/advanced_features/structured_outputs.html
- GTE multilingual reranker: https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base
- GraphRAG local/global pattern: https://microsoft.github.io/graphrag/query/overview/

## Giới hạn còn lại

Đây là technology selection cho sản phẩm, chưa phải bằng chứng candidate nào tốt hơn baseline trên audio tiếng Việt của dự án. Promotion chỉ được quyết định sau khi runtime canonical, frozen product corpus và evaluation harness chạy thực tế.
