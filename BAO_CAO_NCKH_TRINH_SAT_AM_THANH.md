# Báo cáo đề tài sinh viên nghiên cứu khoa học

## Tên đề tài

**Nghiên cứu, thiết kế và nâng cấp hệ thống phân tích âm thanh có căn cứ chứng cứ phục vụ công tác trinh sát, điều tra**

## Tóm tắt

Đề tài đánh giá hiện trạng dự án SpeechToInformation theo hướng một hệ thống "audio intelligence" có khả năng chuyển âm thanh thành dữ liệu phân tích có nguồn gốc, bằng chứng và trạng thái kiểm duyệt. Hệ thống hiện có đã tích hợp nhiều kỹ thuật quan trọng: nhận dạng tiếng nói tự động (ASR) bằng Whisper/PhoWhisper, tách người nói bằng pyannote và fallback offline, tiền xử lý/VAD, tóm tắt bằng LLM, và lớp Analysis Intelligence V2 có evidence refs, schema version, review state, clip evidence và giao diện Analysis.

Kết quả review cho thấy kiến trúc V2 đi đúng hướng: không trình bày output AI như kết luận đã xác minh, mọi thực thể/fact/slot đều phải gắn với evidence span và trạng thái review. Tuy nhiên, chất lượng "phân tích sâu theo ngữ cảnh" mới ở mức nền móng. Deterministic extractor đã bắt được nhiều thông tin từ transcript khách sạn mẫu, nhưng chưa có true forced alignment, chưa có speech enhancement thật, chưa có LLM structured extraction có ràng buộc evidence, chưa có UI tạo/chọn domain template, chưa có benchmark nghiệp vụ tiếng Việt, và chưa có speaker identification/cross-case analytics.

Báo cáo đề xuất lộ trình nâng cấp gồm: chuẩn hóa quy trình chứng cứ số, thêm audio quality/enhancement pipeline, benchmark ASR/diarization/slot extraction, tích hợp WhisperX hoặc forced alignment tương đương, nâng diarization bằng pyannote Community-1/Sortformer, triển khai LLM structured extraction theo schema và source grounding, hoàn thiện domain template UI, và xây dựng bộ fixture tiếng Việt hand-labeled.

**Từ khóa:** trinh sát âm thanh, ASR, diarization, Whisper, PhoWhisper, pyannote, evidence-grounded extraction, GraphRAG, LangExtract, slot filling, forensic audio.

## 1. Lý do chọn đề tài

Âm thanh từ cuộc gọi, ghi âm, phỏng vấn, camera và thiết bị hiện trường thường chứa nhiều thông tin nghiệp vụ: danh tính, số điện thoại, email, CCCD/CMND, số tiền, thời gian, địa điểm, yêu cầu, cam kết, hành động tiếp theo và mối quan hệ giữa các bên. Xử lý thủ công tốn thời gian, dễ bỏ sót chi tiết, khó truy vết lại đoạn audio gốc và khó đồng bộ giữa transcript, tóm tắt và visualization.

Các hệ thống ASR/LLM hiện đại không được phép coi là bằng chứng tuyệt đối. Các nghiên cứu về audio pháp y chỉ ra ASR có thể hoạt động tốt với audio sạch, ít chồng lấn lời nói, ngôn ngữ quen thuộc; nhưng suy giảm mạnh trong audio mờ, nhiễu, người nói di chuyển, lời nói chồng lấn. Vì vậy, hướng tiếp cận phù hợp với môi trường thực thi pháp luật là "machine-suggested, not verified": máy gợi ý, cán bộ phân tích kiểm tra evidence và xác minh.

## 2. Mục tiêu nghiên cứu

1. Khảo sát toàn bộ kỹ thuật trinh sát âm thanh đang có trong dự án.
2. Đánh giá điểm mạnh, điểm yếu và khoảng trống chất lượng trên transcript tiếng Việt giàu thông tin.
3. Tổng hợp các công trình, repo và chuẩn thực hành uy tín có thể giúp nâng cấp hệ thống.
4. Đề xuất kiến trúc nâng cấp theo từng giai đoạn, phù hợp với nguyên tắc evidence-grounded và bảo vệ dữ liệu nhạy cảm.
5. Đề xuất bộ đánh giá khoa học cho ASR, diarization, trích xuất thông tin và giao diện review.

## 3. Phạm vi và phương pháp

Phạm vi review chính là worktree `D:\Workspace\SpeechToInfomation-pr`, branch `feature/architecture-refactor-pr`, vì đây là nơi có implementation Analysis V2 mới nhất. Worktree gốc `D:\Workspace\SpeechToInfomation` có thêm một số adapter/báo cáo cũ, nhưng không phải nguồn chính cho kết quả Analysis V2 hiện tại.

Phương pháp thực hiện:

- Đọc code theo luồng xử lý: upload/task -> transcribe -> diarization -> summary -> analysis_intelligence -> UI.
- Chạy trực tiếp deterministic extractor trên transcript khách sạn mẫu để đối chiếu kết quả thực tế.
- Research tài liệu chính thống: bài báo, repo/framework gốc, tài liệu NIST/SWGDE, ACL/Interspeech/arXiv, docs của pyannote, NVIDIA NeMo, OpenAI/Ollama structured outputs.
- Phân loại năng lực thành ba nhóm: đã implement, đã có nền móng, chưa implement.

## 4. Kiến trúc hiện tại của dự án

### 4.1 Luồng nghiệp vụ chính

1. Upload audio và tạo task/audio file.
2. Transcribe qua API v2, ưu tiên Cherry Core.
3. Nếu bật diarization, gán speaker label theo overlap giữa transcript segment và speaker segment.
4. Summarize khi người dùng yêu cầu, có Ollama/llama.cpp/Cherry summarizer.
5. Generate Analysis/Visualization V2 để tạo `Task.result.visualization_data`.
6. UI Analysis đọc `display_sections_vi`, facts/entities/risk flags/evidence refs và graph legacy projection.
7. Review endpoints cho confirm/reject/edit/merge/split đã có backend foundation.
8. Clip endpoint cắt đoạn audio evidence theo timestamp.

### 4.2 Các file then chốt đã review

| Nhóm | File | Vai trò |
|---|---|---|
| ASR manager | `src/services/transcription/models/whisper_manager.py` | faster-whisper, lazy loading, local cache, CUDA fallback |
| Transcribe V2 | `src/services/transcription/transcribe_service_v2.py` | orchestration, Cherry Core first, fallback faster-whisper |
| Cherry ASR | `src/cherry_core/adapters/asr/whisperv2_adapter.py` | Whisper large-v2 offline, anti-hallucination decode params |
| Vietnamese ASR | `src/cherry_core/adapters/asr/phowhisper_adapter.py` | PhoWhisper local, chunking 30s, timestamp ước lượng |
| Hallucination filter | `src/cherry_core/adapters/asr/hallucination_filter.py` | Bag-of-Hallucinations, repetition/delooping |
| Diarization | `src/services/transcription/models/pyannote_loader.py` | pyannote local-first, Community-1/3.1 fallback |
| Diarization adapter | `src/cherry_core/adapters/diarization/pyannote_adapter.py` | chuẩn hóa output thành speaker segments |
| Fallback diarization | `src/audio_processing/diarization/simple_vad.py` | MFCC/energy + clustering |
| Tiền xử lý | `src/audio_processing/vad/silero_adapter.py` | Silero VAD offline, conservative threshold |
| Audio processor | `src/audio_processing/processor.py` | load/normalize/trim/segment; enhancement placeholders |
| Analysis schema | `src/services/analysis_intelligence/schemas.py` | V2 graph, evidence refs, facts, risk flags, slots, display sections |
| Core extractor | `src/services/analysis_intelligence/extractor.py` | deterministic Vietnamese facts/entities |
| Segment builder | `src/services/analysis_intelligence/segment_builder.py` | segment priority và transcript fallback |
| Domain templates | `src/services/analysis_intelligence/domain_templates.py` | backend registry, schema validation, version immutable |
| API V2 | `src/api/endpoints/audio_v2.py` | generate analysis, review endpoints |
| Clip endpoint | `src/api/endpoints/audio.py` | ffmpeg argv list, stream WAV, no raw path |
| UI Analysis | `frontend/src/components/AnalysisPanel.tsx` | Overview/Graph/Evidence, display_sections_vi |

## 5. Các kỹ thuật đang sử dụng trong dự án

### 5.1 Tiền xử lý âm thanh và VAD

`AudioProcessor` load audio về mono 16 kHz, normalize, trim silence bằng librosa và chia segment 30 giây. Các hàm `enhance_speech_llase`, `enhance_speech_sepalm`, `enhance_speech_wavlm` hiện chỉ là placeholder, trả về audio gốc. Vì vậy không nên báo cáo rằng project đã có speech enhancement thực sự.

Silero VAD adapter được cấu hình theo hướng conservative: threshold thấp, min speech ngắn, có padding trước/sau speech. Mục tiêu đúng là không cắt mất lời nói, chấp nhận giữ thêm silence. Tuy nhiên CherryTranscriberService hiện khởi tạo WhisperV2Adapter với `use_vad=False` để tránh cắt mất phần đầu audio; vì vậy Silero VAD không phải lúc nào cũng nằm trên path mặc định.

### 5.2 Nhận dạng tiếng nói tự động

Hệ thống có hai hướng ASR:

- `WhisperManager`: dùng faster-whisper/CTranslate2, lazy-load, local cache, compute type theo config. Fallback path có `word_timestamps=True`, `condition_on_previous_text=False`, VAD filter của faster-whisper và các threshold chống hallucination.
- Cherry Core `WhisperV2Adapter`: dùng openai-whisper large-v2 offline, temperature 0, beam/best_of, `condition_on_previous_text=False`, `compression_ratio_threshold`, `logprob_threshold`, `no_speech_threshold`, và filter lặp từ.
- `PhoWhisperAdapter`: dùng PhoWhisper của VinAI cho tiếng Việt, ưu tiên local safetensors. Chia audio dài thành chunk 30s với overlap 5s. Tuy nhiên word timestamps trong adapter là ước lượng theo phân bố đều trên segment, chưa phải forced alignment thật.

Đánh giá: nền tảng ASR khá tốt, nhưng `transcribe_service_v2.py` đang force `model_type_sel = "whisper"`, nên PhoWhisper chưa được chọn mặc định dù đã có adapter. Cần thêm model selection/evaluation để dùng PhoWhisper khi transcript tiếng Việt cần chính xác.

### 5.3 Chống hallucination ASR

Project có các cơ chế: decoding thresholds của Whisper, `condition_on_previous_text=False`, delooping lặp từ/cụm từ, Bag-of-Hallucinations với các cụm như "thanks for watching", "đăng ký kênh", "[âm nhạc]", "[im lặng]".

Đánh giá: đây là hướng đúng, phù hợp với nghiên cứu về Whisper hallucination do non-speech audio. Tuy nhiên BoH hiện còn thủ công, chưa có metric theo fixture, chưa có per-segment confidence và chưa kết hợp audio QC để đánh dấu đoạn có nguy cơ hallucination.

### 5.4 Diarization và gán người nói

Hệ thống có:

- `pyannote_loader.py`: local-first, pyannote Community-1 là primary, 3.1 là fallback, auto-download mặc định tắt.
- `PyannoteAdapter`: run pipeline và chuẩn hóa output thành `SpeakerSegment`.
- Gán speaker cho transcript segment bằng tỉ lệ overlap > 0.3.
- `WhisperXPipeline` trong code thực chất là wrapper pyannote + assign overlap; chưa phải WhisperX forced alignment.
- `SimpleVADDiarizer`: fallback offline bằng MFCC/energy + Spectral/KMeans, đã ghi rõ độ chính xác thấp hơn SOTA và không xử lý overlap speech.
- `NeMoPipeline`: có subprocess placeholder, chưa tích hợp sâu.

Đánh giá: diarization hiện đạt mức "speaker label aid", chưa phải speaker identification. Chưa có enrollment/voiceprint, chưa có speaker verification score, chưa có DER/JER benchmark nội bộ, chưa xử lý tốt overlap speech và speaker change trong ASR segment dài.

### 5.5 Hiệu chỉnh transcript

`TranscriptCorrector` có các bước: normalize ký tự lặp, fuzzy hotel vocabulary, optional Ollama correction với similarity > 0.95, consistency capitalization/phone format. Hướng này tốt cho domain khách sạn, nhưng không tổng quát. Đây chỉ nên xem là domain overlay tùy biến, không nên hardcode thành engine chính.

### 5.6 Tóm tắt và LLM phân tích

`summary_service_v2.py` hỗ trợ forensic/investigation summary bằng Cherry/Ollama/llama.cpp. Các prompt cũ rất mạnh về "phân tích điều tra", yêu cầu trích xuất entities/events/relationships/key_info, nhưng không ràng buộc source span, không bắt buộc validate evidence và có nguy cơ hallucinated relation. V2 mới đi đúng hướng khi legacy summary/report path được mark review-required và không tạo trusted relation.

Kết luận: summary nên là sản phẩm đọc hiểu, không nên là nguồn truth cho graph. Phân tích có giá trị chứng cứ phải đi qua Analysis Intelligence V2.

### 5.7 Analysis Intelligence V2

V2 schema đã có các trường quan trọng: `schema_version`, `graph_revision`, `task_id`, `audio_id`, `source_file`, `analysis_mode`, `extractor_versions`, `segments`, `entities`, `relations`, `events`, `claims`, `facts`, `risk_flags`, `slots`, `domain_frames`, `display_sections_vi`, review fields và legacy aliases.

Validation đã có các rule quan trọng:

- Evidence refs bắt buộc không rỗng.
- Segment evidence phải có audio_id, segment_id, start/end.
- Text-only evidence tự động requires_review.
- Quan hệ high-risk/time-grounded phải có timestamp và speaker grounding.
- Rejected items không xuất hiện trong legacy aliases.

### 5.8 Deterministic Vietnamese extractor

Core extractor hiện bắt: phone có khoảng trắng/dấu chấm/dấu gạch; email hợp lệ và email candidate bị ASR làm mất `@`; CCCD/CMND candidate gần keyword căn cước/CMND; date/date_range tiếng Việt; time words như sáng/chiều/tối/đêm; money dạng "3 triệu 500 nghìn", "4.500.000", range; quantity với phòng/người/nam/nữ/đêm; person name theo mẫu tự giới thiệu; organization sau keyword khách sạn/công ty/bệnh viện/trường; payment method, purpose, request/action/policy/offer.

Chạy trên transcript "A - First Case" cho kết quả:

| Nhóm | Kết quả bắt được |
|---|---|
| Liên hệ | `0978 711 253`, email candidate `quyên24a.gmail.com`, `quên 24a.gmail.com` |
| Định danh | CCCD candidate `0912 1212 09012`, có risk do độ dài bất thường |
| Thời gian | date_range `15/2 - 16/2`, thêm date đơn lẻ `15/2`, các từ `đêm`, `tối`, `sáng` |
| Tiền | `3 triệu`, `3 triệu 500 nghìn`, `4.500.000`, `5 triệu`, `6 triệu`, hai price range |
| Số lượng | `2 phòng`, `4 người`, `2 nam`, `2 nữ`, `1 đêm` |
| Người | `Quyên`, `Nguyễn Thị Quyên` |
| Tổ chức | `G.R.P.Marius Hotel Hà Nội Rất` |
| Hành động | chuyển khoản, gửi STK qua email, điều khoản đặt phòng/hoàn hủy, ưu đãi fitness center |

Kết luận: chất lượng đã tốt hơn "visualization rỗng", nhưng vẫn còn lỗi:

- Organization bị ăn thêm từ `Rất` sau tên khách sạn.
- Chưa derive claim `2 phòng * 3 triệu = 6 triệu`.
- Chưa tạo hotel_booking domain frame/slots.
- Chưa phân biệt room price, total amount, price range, promotion thành slot nghiệp vụ.
- Chưa có speaker role: khách hàng/nhân viên.
- Nếu source là whole transcript fallback, tất cả item thành `needs_review` vì không có timestamp/speaker.

### 5.9 Review workflow, clip evidence và domain templates

Backend đã có review endpoints: review item, update entity, merge, split. Có optimistic revision và audit log không ghi PII/evidence text. Clip endpoint dùng `assert_audio_access`, duration cap, rate limit, `resolve_audio_path`, ffmpeg argv list, stderr DEVNULL, stream WAV, `Cache-Control: no-store`.

Domain Template Registry đã có backend foundation: scope global/user/case, status draft/published/archived, version immutable khi đã publish, schema hash, examples, auth/audit. Validate/test endpoint hiện mới chạy deterministic core preview, chưa có LLM slot extraction thật.

UI hiện mới view-only evidence, chưa có confirm/reject/edit/merge/split UI, chưa có play-clip action gắn evidence refs, chưa có tab "Mẫu phân tích" và domain selector khi Generate Analysis.

## 6. Đối chiếu với công trình và công nghệ uy tín

### 6.1 ASR: Whisper, faster-whisper, PhoWhisper, NeMo

Whisper của OpenAI được công bố trong bài "Robust Speech Recognition via Large-Scale Weak Supervision", huấn luyện trên 680.000 giờ dữ liệu đa ngôn ngữ/đa nhiệm vụ, là nền tảng tốt cho ASR tổng quát. faster-whisper/SYSTRAN đưa Whisper sang CTranslate2 để tăng tốc và giảm bộ nhớ. PhoWhisper của VinAI fine-tune Whisper cho tiếng Việt, phù hợp để benchmark với dữ liệu nội bộ.

Đề xuất: benchmark song song faster-whisper large-v3-turbo, PhoWhisper large, và NeMo Canary/Parakeet trên fixture tiếng Việt nội bộ. Chọn theo WER/CER, keyword recall, phone/money/date preservation, latency và GPU memory.

### 6.2 Alignment: WhisperX và forced alignment

WhisperX kết hợp VAD, batched inference và forced phoneme alignment để có word-level timestamp chính xác hơn Whisper. Project hiện chưa có WhisperX thật: PhoWhisper word timestamps đang ước lượng đều theo thời lượng chunk; `WhisperXPipeline` chỉ là pyannote diarization wrapper.

Đề xuất: tích hợp forced alignment thật, lưu word-level timestamps và confidence vào `SegmentUnit.words`, sau đó evidence inspector phát đúng clip theo span.

### 6.3 Diarization: pyannote Community-1, NeMo/Sortformer, SpeechBrain

pyannote Community-1/pyannote.audio 4.0 là hướng open-source mạnh, cải thiện speaker confusion so với 3.1. NVIDIA Sortformer và Streaming Sortformer là hướng mới cho diarization end-to-end/streaming. SpeechBrain cung cấp toolkit cho speaker recognition/verification với ECAPA-TDNN, ResNet, x-vector, PLDA.

Đề xuất: giữ pyannote Community-1 làm baseline, thêm Sortformer/NeMo như provider tùy chọn, thêm SpeechBrain ECAPA-TDNN cho speaker verification/enrollment nếu có cơ sở pháp lý và mẫu giọng hợp lệ.

### 6.4 Speech enhancement

SWGDE khuyến cáo audio enhancement phải lặp lại được, ghi rõ tool/version/setting, so sánh trước/sau, tránh over-processing và giữ intermediate uncompressed. DeepFilterNet là speech enhancement real-time/full-band; RNNoise là hybrid DSP/deep learning real-time denoise; Demucs/source separation có thể hữu ích khi cần tách nguồn trong môi trường có nhạc/nhiễu nền, nhưng phải đánh giá kỹ vì có thể tạo artefact.

Đề xuất: thêm audio quality report trước ASR: sample rate, channel, clipping, speech ratio, SNR proxy, noise profile, reverb proxy. Nếu enhancement được bật, lưu cả file gốc, file đã xử lý, hash, config và score trước/sau.

### 6.5 Evidence-grounded extraction

GraphRAG dataflow dùng text units/source references cho entity/relationship/claim, phù hợp với V2 provenance pattern. LangExtract của Google nhấn mạnh source-grounded extraction: mỗi extraction map về vị trí trong source text và có visualization để review. MultiWOZ 2.2 và các nghiên cứu dialogue state/slot filling cho thấy domain slots là pattern tốt cho hội thoại nghiệp vụ. Bài "Speech-based Slot Filling using Large Language Models" tại ACL 2024 nghiên cứu slot filling trên ASR noisy, phù hợp với hướng domain templates + LLM second pass.

Đề xuất: core deterministic extraction luôn chạy trước; LLM chỉ là second pass có JSON schema, evidence_text và backend locate lại source span. Output không locate được thì drop hoặc `needs_review`.

### 6.6 Structured outputs và LLM safety

Ollama và OpenAI đều hỗ trợ structured outputs theo JSON Schema/Pydantic. Tuy nhiên structured outputs chỉ đảm bảo đúng schema, không đảm bảo giá trị đúng sự thật. Vì vậy cần validation: evidence span, hash, confidence calibration, prompt injection filtering, không log prompt/transcript/raw response/API key.

### 6.7 Chuẩn pháp y và đánh giá

SWGDE Forensic Audio yêu cầu examiner được đào tạo, ghi chú đầy đủ, bảo quản evidence và không vượt quá năng lực chuyên môn. Frontiers 2024 cảnh báo ASR trên forensic-like indistinct audio còn rất hạn chế. NIST SRE hữu ích nếu sau này làm speaker verification. NIST SP 800-86, RFC 3227 và ISO/IEC 27037 cung cấp nguyên tắc thu thập, bảo quản và kiểm tra tính toàn vẹn của evidence số.

## 7. Khoảng trống kỹ thuật hiện tại

1. Chưa có audio evidence ledger đầy đủ: file gốc, file converted, file enhanced, clip evidence chưa có hash chain/export report.
2. Speech enhancement đang là placeholder.
3. PhoWhisper adapter có nhưng chưa được chọn mặc định; word timestamps chỉ ước lượng.
4. `WhisperXPipeline` đặt tên gây hiểu nhầm vì chưa forced-align.
5. Diarization chưa có benchmark DER/JER/cpWER trên audio tiếng Việt nội bộ.
6. Chưa có speaker identification/voiceprint, chỉ có anonymous speaker labels.
7. Old LLM summary/context prompts vẫn có nguy cơ hallucination nếu dùng làm truth.
8. Domain templates backend đã có, nhưng chưa có UI builder/selector và chưa tạo slots/domain_frames runtime.
9. LLM structured extraction chưa implement, config env mới là nền móng.
10. UI Evidence chưa có review controls, clip playback, conflict handling đầy đủ.
11. Chưa có bộ fixture hand-labeled đủ để đo slot F1, relation F1, critical false positives, timestamp error, speaker attribution.
12. Organization regex còn false positive `G.R.P.Marius Hotel Hà Nội Rất`.

## 8. Đề xuất kiến trúc nâng cấp

### 8.1 Evidence and chain-of-custody core

- Tạo `audio_artifacts` logical model trong JSON hoặc DB: original, normalized, enhanced, asr_input, clip.
- Mỗi artifact có SHA-256, duration, sample rate, channel, codec, tool version, config, parent artifact id.
- Export báo cáo evidence: task id, audio id, hashes, model versions, timestamps, reviewer actions.
- Không overwrite audio gốc; không dùng enhanced audio làm evidence duy nhất.

### 8.2 Audio quality and enhancement

- Thêm audio QC deterministic trước ASR: clipping ratio, RMS, silence/speech ratio, SNR proxy, DC offset, duration, channel.
- Tích hợp DeepFilterNet/RNNoise như optional denoise provider; ghi rõ config.
- Nếu có nhiều nguồn/nhạc nền, thử nghiệm source separation bằng Demucs hoặc speech separation model nhưng luôn AB test với audio gốc.
- UI hiển thị "audio quality warnings" và "enhanced audio used/not used".

### 8.3 ASR ensemble and Vietnamese benchmark

- Thêm engine selector: `whisper_large_v3_turbo`, `phowhisper_large`, `nemo_canary/parakeet` nếu môi trường cho phép.
- Chạy fixture benchmark: WER/CER, keyword recall cho phone/email/money/date/name, hallucination rate trong silence, latency.
- Dùng consensus/ensemble ở mức fact: nếu ASR A/B khác nhau ở phone/CCCD/email thì tạo risk flag.
- Thêm contextual biasing/dictionary theo case/domain nhưng phải review-required.

### 8.4 True alignment and diarization

- Tích hợp WhisperX hoặc forced alignment tương đương cho word timestamps.
- Đổi tên `WhisperXPipeline` nếu chưa align để tránh hiểu nhầm.
- Dùng pyannote Community-1 baseline, thêm Sortformer/NeMo provider cho streaming/real-time.
- Lưu overlapped speech segments; nếu evidence nằm trong overlap thì requires_review.
- Nếu cần speaker identity, thêm enrollment với SpeechBrain ECAPA-TDNN, threshold calibration, ROC/EER, và quy trình phê duyệt pháp lý.

### 8.5 General/domain analysis engine

- Core extraction tiếp tục deterministic và tổng quát.
- Domain template UI: tạo domain, slot, label tiếng Việt, synonyms, examples, negative examples, test transcript, publish version.
- Runtime modes: general, selected, auto.
- LLM structured extraction:
  - prompt từ schema đã validate, không cho template lưu system prompt tự do;
  - response JSON schema;
  - evidence_text bắt buộc locate lại vào segment;
  - normalize phone/money/date bằng deterministic normalizer;
  - long transcript chunking + merge stable IDs;
  - không log transcript/prompt/raw response/API key.
- Domain frame/slots cho transcript khách sạn mẫu nên có: customer_name, hotel_name, room_count, guest_count, guest_composition, check_in/out, stay_nights, purpose, room_price, total_amount, payment_method, post_call_action, policy_terms, promotion.

### 8.6 UI analyst workspace

- Analysis Overview ưu tiên `display_sections_vi`.
- Evidence Inspector: source span, speaker, timestamp, confidence reason, source method, review status, play clip.
- Review UI: confirm/reject/edit/merge/split với expected_revision.
- Domain selector ở Generate Analysis.
- Export report: transcript + facts + evidence refs + review status + artifact hashes.

## 9. Thiết kế thực nghiệm đánh giá

### 9.1 Bộ dữ liệu nội bộ

Cần xây `tests/fixtures/investigation_transcripts/*.json` và audio tương ứng nếu có. Tối thiểu gồm: khách sạn/đặt phòng; giao dịch/chuyển khoản; khiếu nại/dịch vụ; hẹn gặp/lịch trình; hội thoại không domain rõ; audio sạch/noisy/overlap; không có entity; false-positive traps.

### 9.2 Metrics

| Lớp | Metric |
|---|---|
| ASR | WER, CER, keyword recall, hallucination rate, latency |
| Diarization | DER, JER, speaker attribution accuracy, cpWER |
| Alignment | median/p95 timestamp error |
| Extraction | entity/fact/slot precision/recall/F1, normalized value accuracy |
| Safety | evidence coverage 100%, critical false positives = 0, PII logs = 0 |
| UI | generate -> open analysis -> verify evidence -> export |

### 9.3 Gates để bật mặc định

- Core deterministic có thể ship khi schema/privacy/UI build/tests pass.
- LLM/domain slot extraction chỉ bật mặc định khi slot F1 >= 0.85, normalized value accuracy >= 0.85, evidence coverage = 100%, critical false positives = 0.
- Speaker ID chỉ bật khi có enrollment policy, threshold calibration và human verification workflow.

## 10. Lộ trình thực hiện đề tài

### Giai đoạn 1: Ổn định V2 và UI evidence

- Fix org trimming cho hotel name.
- Thêm derived claim validator `2 phòng x 3 triệu = 6 triệu` nếu có evidence đầy đủ.
- Tạo hotel_booking deterministic domain frame từ facts hiện có.
- Hoàn thiện Evidence Inspector và clip playback.
- Thêm fixture A - First Case vào CI.

### Giai đoạn 2: Audio quality, ASR benchmark, forced alignment

- Audio QC report.
- Tích hợp DeepFilterNet/RNNoise optional.
- Benchmark Whisper/faster-whisper/PhoWhisper/NeMo trên fixture.
- Tích hợp true WhisperX/forced alignment; bỏ timestamp ước lượng khi có alignment.

### Giai đoạn 3: Domain templates runtime và LLM structured extraction

- UI Mẫu phân tích: list/detail/editor/test/publish/import/export.
- Runtime selected/general/auto.
- LLM gateway có structured outputs và evidence locate.
- Tests prompt injection/log redaction/unlocatable evidence.

### Giai đoạn 4: Diarization nâng cao và speaker intelligence

- Thêm Sortformer/NeMo provider.
- Benchmark DER/JER/cpWER.
- Thêm speaker verification optional bằng SpeechBrain ECAPA-TDNN nếu có cơ sở pháp lý.
- Thêm overlap detection và risk flag khi attribution không chắc.

### Giai đoạn 5: Báo cáo khoa học và pilot

- Hoàn thiện bộ fixture tiếng Việt.
- So sánh before/after trên các metric.
- Viết báo cáo kết quả thực nghiệm, phân tích sai số, giới hạn và khuyến nghị triển khai.

## 11. Giá trị ứng dụng trong lực lượng Công an nhân dân

- Rút ngắn thời gian nghe và ghi chép audio.
- Tăng khả năng phát hiện thông tin nhạy cảm/có giá trị nghiệp vụ.
- Giữ được provenance: mỗi thông tin có transcript span và clip audio để kiểm tra.
- Giảm rủi ro AI hallucination bằng review state và evidence validation.
- Hỗ trợ chuẩn hóa quy trình báo cáo, audit, và bàn giao kết quả phân tích.

Lưu ý: hệ thống chỉ nên dùng như công cụ hỗ trợ phân tích. Kết quả máy gợi ý không thay thế giám định viên, điều tra viên, quy trình thu thập chứng cứ hợp pháp, hay kết luận pháp lý.

## 12. Kết luận

Dự án đã có nền tảng tốt cho một hệ thống trinh sát âm thanh hiện đại: ASR offline/local, diarization, VAD, analysis V2 có evidence, review state và UI Analysis. Điểm đột phá gần nhất là chuyển từ graph suy đoán sang fact/evidence-grounded analysis. Tuy nhiên, để đạt chất lượng nghiên cứu khoa học và ứng dụng nghiệp vụ, cần tiếp tục nâng cấp theo hướng đo lường được: audio QC/enhancement, true alignment, benchmark tiếng Việt, domain templates runtime, structured LLM extraction có source grounding, và quy trình chain-of-custody.

Nếu triển khai đúng lộ trình, đề tài có thể đóng góp một mô hình hệ thống "audio-to-evidence intelligence" phù hợp với môi trường tiếng Việt, không phụ thuộc hoàn toàn vào public ASR dataset và không biến AI thành nguồn kết luận không kiểm chứng.

## Tài liệu tham khảo

1. Radford et al. "Robust Speech Recognition via Large-Scale Weak Supervision." arXiv 2212.04356. https://arxiv.org/abs/2212.04356
2. OpenAI. "Introducing Whisper." https://openai.com/research/whisper/
3. SYSTRAN. faster-whisper. https://github.com/SYSTRAN/faster-whisper
4. OpenNMT. CTranslate2. https://github.com/OpenNMT/CTranslate2
5. VinAI Research. PhoWhisper. https://github.com/VinAIResearch/PhoWhisper
6. Bain et al. "WhisperX: Time-Accurate Speech Transcription of Long-Form Audio." arXiv 2303.00747. https://arxiv.org/abs/2303.00747
7. pyannoteAI. "Community-1: Unleashing open-source diarization." https://www.pyannote.ai/blog/community-1
8. pyannote Community-1 model card. https://huggingface.co/pyannote/speaker-diarization-community-1
9. NVIDIA NeMo speaker diarization documentation. https://docs.nvidia.com/nemo-framework/user-guide/24.07/nemotoolkit/asr/speaker_diarization/intro.html
10. NVIDIA Streaming Sortformer model card. https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2
11. SpeechBrain. https://github.com/speechbrain/speechbrain
12. Desplanques et al. "ECAPA-TDNN." arXiv 2005.07143. https://arxiv.org/abs/2005.07143
13. Silero VAD. https://github.com/snakers4/silero-vad
14. DeepFilterNet. https://github.com/Rikorose/DeepFilterNet
15. Xiph RNNoise. https://github.com/xiph/rnnoise
16. Microsoft GraphRAG dataflow. https://microsoft.github.io/graphrag/index/default_dataflow/
17. Microsoft GraphRAG outputs. https://microsoft.github.io/graphrag/index/outputs/
18. Google LangExtract. https://github.com/google/langextract
19. Google Research. MultiWOZ 2.2. https://research.google/pubs/multiwoz-22-a-dialogue-dataset-with-additional-annotation-corrections-and-state-tracking-baselines/
20. Sun et al. "Speech-based Slot Filling using Large Language Models." Findings ACL 2024. https://aclanthology.org/2024.findings-acl.379/
21. Ollama structured outputs. https://docs.ollama.com/capabilities/structured-outputs
22. OpenAI structured outputs. https://platform.openai.com/docs/guides/structured-outputs
23. SWGDE. Best Practices for Forensic Audio. https://www.swgde.org/documents/published-complete-listing/08-a-001-swgde-best-practices-for-forensic-audio/
24. SWGDE. Best Practices for the Enhancement of Digital Audio. https://www.swgde.org/documents/published-complete-listing/20-a-001-swgde-best-practices-for-the-enhancement-of-digital-audio/
25. Loakes. "Automatic speech recognition and the transcription of indistinct forensic audio." Frontiers in Communication, 2024. https://www.frontiersin.org/journals/communication/articles/10.3389/fcomm.2024.1281407/full
26. NIST. Speaker and Language Recognition / SRE. https://www.nist.gov/programs-projects/speaker-and-language-recognition
27. NIST SP 800-86. https://csrc.nist.gov/pubs/sp/800/86/final
28. RFC 3227. https://datatracker.ietf.org/doc/html/rfc3227
29. ISO/IEC 27037:2012. https://www.iso.org/standard/44381.html
30. Mozilla Common Voice. https://www.mozillafoundation.org/en/common-voice
31. FLEURS benchmark. https://arxiv.org/abs/2205.12446
32. VoxConverse. https://github.com/joonson/voxconverse
33. AMI Meeting Corpus. https://www.idiap.ch/webarchives/sites/www.amiproject.org/ami-scientific-portal/meeting-corpus/
