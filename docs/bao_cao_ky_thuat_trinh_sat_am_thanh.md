<style>
@page {
  size: A4;
  margin: 2cm 2cm 2cm 3cm;
}
body {
  font-family: "Times New Roman", Times, serif;
  font-size: 13pt;
  line-height: 1.5;
  text-align: justify;
}
p {
  margin: 0 0 6pt 0;
  text-indent: 1.27cm;
}
h1, h2, h3, h4, h5, h6 {
  font-family: "Times New Roman", Times, serif;
  font-weight: 700;
  line-height: 1.3;
  margin: 12pt 0 6pt 0;
  text-indent: 0;
  text-align: left;
}
h1 {
  font-size: 16pt;
  text-align: center;
  text-transform: uppercase;
}
h2 {
  font-size: 14pt;
}
h3 {
  font-size: 13pt;
}
blockquote, blockquote p, li, li p, table, table p, th, td, pre, code {
  text-indent: 0;
}
ul, ol {
  margin-top: 0;
  margin-bottom: 6pt;
}
li {
  margin-bottom: 3pt;
  text-align: justify;
}
table {
  border-collapse: collapse;
  width: 100%;
  table-layout: fixed;
  margin: 12px 0;
  font-size: 0.95em;
}
th, td {
  border: 1px solid #6b7280;
  padding: 8px 10px;
  vertical-align: top;
  overflow-wrap: anywhere;
  word-break: break-word;
}
th {
  background: #eef2f7;
  font-weight: 700;
  text-align: left;
}
</style>

# BÁO CÁO NGHIÊN CỨU KHOA HỌC SINH VIÊN

## Đề tài

**Nghiên cứu các kỹ thuật trích xuất, định danh và trực quan hóa thông tin hỗ trợ trinh sát từ nguồn âm thanh số trong hệ thống SpeechToInformation**

> Tài liệu này được trình bày theo phong cách báo cáo đề tài nghiên cứu khoa học sinh viên. Nội dung kỹ thuật được giới hạn trong phạm vi xử lý, phân tích và khai thác audio đã được thu thập hợp pháp, có phân quyền theo vụ việc/case, phục vụ xác minh và điều tra; không hướng dẫn thu thập trái phép hay giám sát ngoài thẩm quyền.

Ngày cập nhật: 03/05/2026

Nguồn rà soát chính: mã nguồn dự án SpeechToInformation trên branch `feature/architecture-refactor-pr`

---

## Mục lục

1. Mở đầu
2. Tổng quan tình hình nghiên cứu và cơ sở khoa học
3. Khảo sát kiến trúc dự án SpeechToInformation
4. Các kỹ thuật xử lý và trinh sát âm thanh đang sử dụng
5. Đánh giá chất lượng, an toàn và giới hạn hiện tại
6. Đề xuất hoàn thiện
7. Kết luận
8. Tài liệu tham khảo
9. Phụ lục mã nguồn đối chiếu

---

## Danh mục từ viết tắt

<table border="1" cellspacing="0" cellpadding="0" style="border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; font-size: 0.95em;">
<thead>
<tr>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Viết tắt</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Ý nghĩa</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">ASR</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Automatic Speech Recognition - nhận dạng tiếng nói tự động</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">VAD</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Voice Activity Detection - phát hiện đoạn có tiếng nói</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">DER</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Diarization Error Rate - tỷ lệ lỗi phân tách người nói</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">WER/CER</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Word/Character Error Rate - tỷ lệ lỗi từ/ký tự trong nhận dạng tiếng nói</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">LLM</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Large Language Model - mô hình ngôn ngữ lớn</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">V2 graph</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Schema phân tích <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">analysis_intelligence.v2</code> trong dự án</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Evidence ref</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Tham chiếu bằng chứng gồm span transcript, hash, thời gian, speaker, segment</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Domain template</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Mẫu phân tích theo lĩnh vực nghiệp vụ do người dùng định nghĩa</td>
</tr>
</tbody>
</table>

---

# 1. Mở đầu

## 1.1. Tính cấp thiết của đề tài

Âm thanh số trong điện thoại, ghi âm hội thoại, ghi âm họp, dữ liệu từ thiết bị nghiệp vụ hoặc nguồn hợp pháp khác có thể chứa nhiều thông tin quan trọng: nhân thân, số điện thoại, thời gian, địa điểm, giao dịch tài chính, cam kết, yêu cầu, dấu hiệu bất thường và quan hệ giữa các bên liên quan. Tuy nhiên, việc nghe thủ công tốn thời gian, khó tổng hợp khi có nhiều file, và dễ bỏ sót chi tiết nhỏ nhưng có giá trị xác minh.

Dự án SpeechToInformation xây dựng pipeline hỗ trợ chuyển đổi audio thành transcript, phân tách người nói, tóm tắt, trích xuất thông tin có evidence, hiển thị trong giao diện Analysis/Visualization và lưu kết quả theo vụ việc. Trong bối cảnh đào tạo và nghiên cứu khoa học sinh viên CAND, đề tài này có ý nghĩa như một mô hình ứng dụng AI hỗ trợ cán bộ phân tích audio, đồng thời đặt ra yêu cầu nghiêm ngặt về quyền truy cập, bảo mật, log tối thiểu, bằng chứng có nguồn gốc và cảnh báo "máy gợi ý, chưa xác minh".

## 1.2. Mục tiêu nghiên cứu

1. Hệ thống hóa các kỹ thuật âm thanh và AI đang được sử dụng trong dự án.
2. Làm rõ luồng xử lý từ upload audio đến transcript, diarization, evidence graph, fact extraction và UI Analysis.
3. Đánh giá mức độ phù hợp với bài toán hỗ trợ trinh sát/điều tra từ nguồn âm thanh hợp pháp.
4. Chỉ ra hạn chế, rủi ro và hướng hoàn thiện để đáp ứng tính chất nghiệp vụ, khoa học và an toàn.

## 1.3. Đối tượng và phạm vi nghiên cứu

**Đối tượng nghiên cứu** là codebase SpeechToInformation trên branch `feature/architecture-refactor-pr`, đặc biệt các module:

- Xử lý upload và lưu trữ audio.
- ASR tiếng Việt bằng Whisper, faster-whisper, PhoWhisper.
- Phân tách người nói bằng Pyannote, Diart và fallback VAD/clustering.
- Phân tích nội dung bằng deterministic extractor, LLM summarization, schema V2 có evidence.
- Trực quan hóa và giao diện Analysis.
- Cơ chế bảo mật, phân quyền, audit, rate limit.

**Phạm vi không bao gồm**: hướng dẫn nghe lén, thu thập audio trái phép, nhận dạng danh tính sinh trắc học người nói theo cross-case, hoặc đưa ra kết luận pháp lý từ output tự động.

## 1.4. Phương pháp nghiên cứu

- Rà soát mã nguồn theo module và luồng nghiệp vụ.
- Đối chiếu với tài liệu kỹ thuật công khai: Whisper, faster-whisper/CTranslate2, PhoWhisper, Pyannote, WhisperX, Vosk, Silero VAD, Diart, GraphRAG.
- Đối chiếu với khuyến nghị forensic audio công khai: SWGDE và nghiên cứu về hạn chế ASR với audio chất lượng kém.
- Phân tích theo tiêu chí: độ chính xác, khả năng giải thích bằng evidence, bảo mật, khả năng vận hành offline, khả năng mở rộng nghiệp vụ.

---

# 2. Tổng quan tình hình nghiên cứu và cơ sở khoa học

## 2.1. Nghiên cứu khoa học sinh viên trong CAND

Các nguồn công khai từ Học viện Cảnh sát nhân dân và Học viện An ninh nhân dân cho thấy nghiên cứu khoa học sinh viên là hoạt động được tổ chức thường xuyên, gắn với mục tiêu nâng cao tư duy khoa học, năng lực thực tiễn và chuyển đổi số trong lực lượng CAND. Báo cáo này vì vậy được trình bày theo cấu trúc gần với một đề tài sinh viên: mở đầu, cơ sở khoa học, khảo sát thực trạng, nội dung kỹ thuật, đánh giá, kiến nghị và phụ lục.

## 2.2. Nhận dạng tiếng nói tự động

Whisper được đề xuất trong bài báo "Robust Speech Recognition via Large-Scale Weak Supervision" với huấn luyện đa ngôn ngữ trên kho dữ liệu lớn, tạo nền tảng ASR có tính tổng quát cao. Dự án sử dụng cả `openai-whisper` và `faster-whisper`. `faster-whisper` là bản triển khai Whisper trên CTranslate2, hướng tới suy diễn nhanh hơn, tiết kiệm bộ nhớ và hỗ trợ lượng hóa int8.

Với tiếng Việt, dự án có adapter PhoWhisper. PhoWhisper được VinAI công bố như bộ mô hình ASR tiếng Việt tinh chỉnh từ Whisper trên dữ liệu đa giọng vùng miền, có kết quả benchmark tốt trên VIVOS/CMV-Vi/VLSP. Trong code hiện tại, PhoWhisper được thiết kế chạy offline từ thư mục local model và ưu tiên safetensors để giảm rủi ro từ file `pytorch_model.bin`.

## 2.3. Tách người nói và căn chỉnh thời gian

Speaker diarization trả lời câu hỏi "ai nói lúc nào". Dự án sử dụng Pyannote Community-1/3.1 qua local snapshot. Model card Pyannote Community-1 cho biết pipeline nhận mono 16 kHz, có cải tiến speaker assignment/counting, hỗ trợ offline và có `exclusive_speaker_diarization` giúp reconcile timestamp transcript với speaker. Dự án cũng có các thành phần Diart, WhisperX/NeMo placeholder và fallback simple VAD diarizer.

WhisperX là hướng tham khảo quan trọng vì kết hợp VAD, batched inference và forced alignment để có timestamp mức từ. Trong dự án, word timestamps được lưu khi có, nếu không sẽ fallback về timestamp segment.

## 2.4. Evidence-grounded extraction

GraphRAG của Microsoft dùng TextUnit làm đơn vị nguồn, trích entity/relationship/claim và lưu source references để truy vết về văn bản gốc. Dự án áp dụng tinh thần này vào audio: `SegmentUnit` từ transcript/audio segment, `EvidenceRef` gắn segment, hash nội dung, span, timestamp và speaker, sau đó tạo `entities`, `facts`, `risk_flags`, `slots`, `domain_frames`.

Đây là điểm quan trọng: hệ thống không nên chỉ "vẽ graph đẹp" từ summary, mà phải trích xuất thông tin có bằng chứng, có confidence, có reason và có trạng thái review.

## 2.5. Giới hạn forensic audio

Nghiên cứu Frontiers in Communication 2024 về ASR với forensic-like audio cho thấy, với audio chất lượng kém, Whisper tốt nhất trong các hệ thống được so sánh nhưng vẫn chỉ đúng khoảng 50% vật liệu nói. Tài liệu SWGDE về forensic audio nhấn mạnh tiếp nhận, tài liệu hóa, xử lý, validation và bảo quản bằng chứng. Vì vậy, output trong dự án phải được xem là "machine-suggested, not verified", cần cán bộ/analyst xác minh trước khi sử dụng nghiệp vụ.

---

# 3. Khảo sát kiến trúc dự án SpeechToInformation

## 3.1. Kiến trúc tổng thể

<table border="1" cellspacing="0" cellpadding="0" style="border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; font-size: 0.95em;">
<thead>
<tr>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Lớp</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Thành phần</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Vai trò</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Frontend</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">React, Vite, MUI</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Upload, quản lý case/file, hiển thị Transcript, Summary, Analysis, Evidence</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">API</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">FastAPI routers <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">audio.py</code>, <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">audio_v2.py</code>, <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">analysis_templates.py</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Endpoint upload, transcribe, summarize, visualize, review, clip, template</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Database</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">SQLAlchemy, Alembic, PostgreSQL JSON/JSONB</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Lưu User, Case, AudioFile, Task, ActivityLog, AnalysisDomainTemplate</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Queue</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Celery, Redis</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Xử lý transcript/summarize bất đồng bộ</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Audio/AI</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Whisper, faster-whisper, PhoWhisper, Pyannote, Silero, LLM/Ollama</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Chuyển audio thành thông tin có cấu trúc</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Storage</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">storage/audio</code>, path safety</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Lưu file theo case, không expose raw filesystem path</td>
</tr>
</tbody>
</table>

## 3.2. Luồng nghiệp vụ chính

1. Người dùng upload audio vào case.
2. Backend sanitize filename, validate extension, kiểm tra nội dung audio bằng `ffprobe`.
3. File được stage trong temp, sau đó move vào `storage/audio/cases/{case_id}/{uuid}.{ext}`.
4. Tạo `AudioFile` và `Task`.
5. Transcribe: Cherry Core được ưu tiên, fallback sang faster-whisper nếu Cherry Core lỗi.
6. Diarization: Pyannote nếu có local model/token, fallback/no diarization nếu không khả dụng.
7. Lưu `transcription`, `segments`, `formatted_transcript`, `duration`, `num_speakers` trong `Task.result`.
8. Generate Analysis/Visualization tạo `analysis_intelligence.v2`.
9. Frontend Analysis tab đọc `visualization_data`, hiển thị Overview, Graph, Evidence.
10. Analyst có thể review/confirm/reject/update/merge/split item qua endpoint V2.

## 3.3. Mô hình dữ liệu chính

- `User`, `UserRole`: tài khoản, role, `permissions`.
- `Case`, `CaseParticipant`, `ParticipantRole`: vụ việc và phân quyền theo case.
- `AudioFile`: file audio, đường dẫn relative, status, case, uploader.
- `Task`: đơn vị xử lý, lưu `result` JSON.
- `ActivityLog`, `SecurityAuditLog`: audit hành động và sự kiện bảo mật.
- `AnalysisDomainTemplate`: registry mẫu phân tích nghiệp vụ có immutable versioning.

Dự án đã loại bỏ các bảng transcription/analysis cũ, lưu kết quả phân tích trong `Task.result` để giảm phân mảnh schema, đồng thời thêm schema V2 để tránh JSON vô định.

---

# 4. Các kỹ thuật xử lý và trinh sát âm thanh đang sử dụng

## 4.1. Tiếp nhận, kiểm định và lưu trữ audio

Module `src/services/audio_storage.py` thực hiện:

- Giải mã filename và chặn path traversal: filename không được chứa `/`, `\`, NULL byte, `..`.
- Allowlist extension: `wav`, `mp3`, `m4a`, `ogg`.
- Giới hạn upload theo `MAX_UPLOAD_SIZE`.
- Ghi upload thành chunk 1 MB vào temp.
- Kiểm tra nội dung bằng `ffprobe` để xác nhận có audio stream.
- Lưu file bằng UUID trong thư mục case, chỉ lưu relative path.
- `resolve_audio_path()` đảm bảo mọi path nằm dưới `AUDIO_STORAGE_ROOT`.

Giá trị nghiệp vụ: tăng tính toàn vẹn chuỗi xử lý, tránh nhầm file, giảm nguy cơ đọc file ngoài workspace và chuẩn hóa nơi lưu bằng chứng audio.

## 4.2. Chuẩn hóa và tiền xử lý tín hiệu

Module `src/audio_processing/processor.py` dùng:

- `librosa.load(..., sr=16000, mono=True)` để đưa audio về mono 16 kHz.
- `soundfile` để ghi WAV/array.
- `pydub.AudioSegment` để convert format.
- `librosa.util.normalize` để normalize biên độ.
- `librosa.effects.trim` để cắt im lặng theo ngưỡng dB.
- Chia segment theo độ dài cố định.

Ngoài ra, các hàm `enhance_speech_llase`, `enhance_speech_sepalm`, `enhance_speech_wavlm`, `augment_specaugment` hiện mới là placeholder. Không nên coi đây là kỹ thuật đã hoạt động trong sản phẩm.

## 4.3. Voice Activity Detection

Dự án có hai adapter Silero VAD:

- `src/audio_processing/vad/silero_adapter.py`
- `src/cherry_core/adapters/vad/silero_adapter.py`

Thông số được chọn theo triết lý bảo toàn thông tin:

- threshold 0.3: nhạy hơn, giảm nguy cơ bỏ sót tiếng nói.
- min speech 100 ms: bắt utterance ngắn.
- min silence 300 ms: tránh cắt quá mạnh.
- speech padding 200 ms: đệm trước/sau đoạn speech.

VAD được dùng để lấy timestamp có tiếng nói, cắt im lặng trước ASR trong một số flow và giảm hallucination trong silence. Cần lưu ý VAD có thể làm mất lời nói đầu/cuối nếu tuning quá gắt. Cherry Transcription Service hiện khởi tạo `WhisperV2Adapter(use_vad=False)` để bảo toàn đoạn đầu audio, cho thấy dự án đang ưu tiên không bỏ sót thông tin hơn tối ưu tốc độ.

## 4.4. ASR bằng Whisper/faster-whisper

### 4.4.1. WhisperManager

`src/services/transcription/models/whisper_manager.py` sử dụng singleton lazy loading:

- Chỉ load model khi gọi `model`.
- Đọc cấu hình `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`.
- Nếu cấu hình CUDA nhưng GPU không khả dụng, fallback CPU + int8.
- Dùng `models/whisper` làm cache root theo manifest artifact.
- Verify artifact trước rồi gọi `faster_whisper.WhisperModel(<verified local snapshot path>, ...)`.

Giá trị kỹ thuật: giảm thời gian startup API, tránh load nhiều model lớn trong một process, hỗ trợ cache local và vận hành offline/bán offline.

### 4.4.2. Transcribe fallback parameters

Trong `transcribe_service_v2.py`, fallback faster-whisper dùng:

- language `vi`
- beam size 1 trong fallback nhanh
- temperature 0.0
- `compression_ratio_threshold=2.4`
- `log_prob_threshold=-1.0`
- `no_speech_threshold=0.5`
- prompt ban đầu "Tiếng Việt"
- `vad_filter=True`
- `word_timestamps=True`
- `condition_on_previous_text=False`

`condition_on_previous_text=False` và temperature 0.0 giúp giảm lỗi lan truyền/hallucination. Các pattern như "subscribe", "đăng ký kênh", "thanks for watching" được lọc ra nếu xuất hiện như đoạn ngắn nghi ngờ.

## 4.5. ASR bằng Cherry Core Whisper V2

`src/services/transcription/cherry_transcription_service.py` ưu tiên Cherry Core. Trong flow hiện tại `USE_CHERRY_CORE = True`, `model_type_sel = "whisper"`.

`src/cherry_core/adapters/asr/whisperv2_adapter.py`:

- Dùng `openai-whisper` offline từ file `large-v2.pt`.
- Tự chọn device CUDA/CPU.
- Có cơ chế VAD preprocessing tùy chọn.
- Decoding với beam_size 5, best_of 5, temperature 0.0.
- `condition_on_previous_text=False`, `compression_ratio_threshold=2.0`, `logprob_threshold=-1.0`, `no_speech_threshold=0.5`.
- Hậu xử lý repetition loop bằng regex.

Đây là lớp ASR local-first phù hợp khi cần vận hành không phụ thuộc API ngoài.

## 4.6. ASR tiếng Việt bằng PhoWhisper

`src/cherry_core/adapters/asr/phowhisper_adapter.py`:

- Tìm local model trong `models/phowhisper-safe`, `models/phowhisper`, `models/phowhisper-full`.
- Ưu tiên safetensors để tránh rủi ro từ pytorch binary.
- Dùng `WhisperProcessor` và `WhisperForConditionalGeneration`.
- Resample về 16 kHz, mono.
- Chunk audio dài thành đoạn 30 giây, step 25 giây, overlap 5 giây.
- Tạo word timestamps ước lượng dựa trên độ dài segment.

Giá trị: PhoWhisper có lợi thế với tiếng Việt, nhưng trong flow hiện tại Transcribe V2 đang force `model_type_sel = "whisper"`. PhoWhisper là năng lực đã có trong code, chưa phải mặc định runtime.

## 4.7. Lọc hallucination ASR

`src/cherry_core/adapters/asr/hallucination_filter.py` xây dựng "Bag of Hallucinations" và filter:

- Cụm tiếng Anh thường gặp: "thanks for watching", "please subscribe", ...
- Cụm tiếng Việt quan sát: "cảm ơn đã xem", "đăng ký kênh", "hẹn gặp lại", ...
- Deloop word/phrase repeated.
- Kiểm tra segment quá ngắn hoặc toàn ký tự vô nghĩa.

Báo cáo cần ghi rõ: file này có comment dựa trên nghiên cứu 2025 về Whisper hallucination, nhưng việc áp dụng vào pipeline cần được kiểm thử trên bộ dữ liệu đánh giá của đề tài, vì bộ hallucination theo danh sách có thể vô tình xóa lời nói thật nếu ngữ cảnh trùng khớp.

## 4.8. Speaker diarization bằng Pyannote

`src/services/transcription/models/pyannote_loader.py` là điểm thiết kế tốt:

- Import-safe: không import `pyannote.audio`, `torch`, `huggingface_hub` ở top-level.
- Model mặc định: `pyannote/speaker-diarization-community-1`.
- Fallback: `pyannote/speaker-diarization-3.1`.
- Cache dir: `models/pyannote`.
- Local path: model id thay `/` bằng `--`.
- Runtime auto-download mặc định tắt (`PYANNOTE_AUTO_DOWNLOAD=false`).
- Chỉ download khi có `HF_TOKEN` và cấu hình bật auto download.
- Ưu tiên `exclusive_speaker_diarization`, sau đó `speaker_diarization`.
- Normalize label về `SPEAKER_00`, `SPEAKER_01`, ...

`pyannote_manager.py`:

- Lazy load pipeline.
- Convert `.m4a`, `.mp3`, `.ogg` sang WAV nếu Pyannote/soundfile không đọc được.
- Cleanup WAV tạm.
- Nếu Pyannote unavailable thì tiếp tục không diarization.

Giá trị nghiệp vụ: speaker diarization giúp gắn câu nói với người nói, tạo timeline và bằng chứng theo speaker. Hạn chế: speaker label là label kỹ thuật trong file, không phải danh tính người thật.

## 4.9. Diarization bằng Diart, WhisperX, NeMo và fallback VAD

Codebase có các module:

- `src/audio_processing/diarization_diart.py`
- `src/audio_processing/diarization/manager.py`
- `src/audio_processing/diarization/whisperx.py`
- `src/audio_processing/diarization/nemo.py`
- `src/audio_processing/diarization/simple_vad.py`

`manager.py` hiện map `whisperx`, `nemo`, `none`. `simple_vad.py` cài đặt fallback offline:

1. Load audio bằng librosa.
2. Trích feature RMS, ZCR, spectral centroid, MFCC.
3. Cluster bằng SpectralClustering hoặc KMeans.
4. Gắn speaker label vào transcript segments.

Đây là fallback có ích khi không có Pyannote/token, nhưng độ chính xác thấp hơn diarization SOTA, khó xử lý overlapping speech và giọng nói gần nhau.

## 4.10. Merge ASR segment với diarization

Trong `CherryTranscriberService._merge_speakers()` và fallback transcribe:

- Với mỗi transcript segment, tính overlap với diarization segment.
- Chọn speaker có overlap lớn nhất.
- Gắn speaker nếu overlap ratio > 0.3.

Đây là heuristic đơn giản, dễ hiểu và nhanh. Hạn chế là với segment dài hoặc nhiều người nói trong một segment, speaker có thể bị gắn sai. Hướng nâng cấp là cần timestamp mức từ hoặc forced alignment kiểu WhisperX.

## 4.11. Evidence-grounded Analysis V2

`src/services/analysis_intelligence/schemas.py` định nghĩa schema `analysis_intelligence.v2`.

### 4.11.1. Đơn vị nguồn

`SegmentUnit` gồm:

- `id`
- `source_kind`: audio/transcript segment, whole transcript, summary, report
- `text`
- `source_text_sha256`
- `audio_id`
- `start_time`, `end_time`
- `speaker_id`
- `words`

`segment_builder.py` tạo segments từ `Task.result.segments`; nếu không có segment thì fallback về `transcript_text`.

### 4.11.2. EvidenceRef

`EvidenceRef` gồm:

- `source_kind`
- `source_text_sha256`
- `text_span`
- `char_start`, `char_end`
- `audio_id`
- `segment_id`
- `start_time`, `end_time`
- `speaker_id`

Validator bắt buộc audio/time/segment cho `audio_segment` và `transcript_segment`. Với `transcript_text`, `summary_text`, `report_text`, time/speaker có thể null và item sẽ `requires_review=true`.

### 4.11.3. Item phân tích

Schema có các lớp:

- `EntityItem`: thực thể như phone, email, person, organization.
- `RelationItem`: quan hệ như `called`, `owns_phone`, `transferred_money`, ...
- `EventItem`, `ClaimItem`.
- `FactItem`: thông tin nghiệp vụ có value/normalized value.
- `RiskFlag`: có severity, category, `reason_vi`.
- `SlotItem`: slot theo domain template.
- `DomainFrame`: khung domain như "đặt phòng khách sạn".
- `DisplaySection`: section tiếng Việt server-derived.

Review status gồm `machine_suggested`, `needs_review`, `confirmed`, `rejected`.

### 4.11.4. Graph-level validation

`AnalysisGraphV2` validate:

- Schema version phải đúng.
- Relation phải tham chiếu entity tồn tại.
- Slot phải tham chiếu fact tồn tại.
- Domain frame phải tham chiếu slot/fact tồn tại.
- Evidence ref nếu có segment_id thì segment phải tồn tại.
- Legacy aliases `nodes`, `edges`, `timeline`, `main_events`, `entity_types` được regen server-side từ `to_legacy_view()`.
- Item rejected không được hiện trong legacy aliases.

Đây là cơ chế quan trọng để tránh LLM hoặc legacy code đẩy dữ liệu hình ảnh/graph không khớp với dữ liệu gốc.

## 4.12. Deterministic Vietnamese core extractor

`src/services/analysis_intelligence/extractor.py` là lớp trích xuất deterministic hiện đang thực sự chạy trong V2. Version: `deterministic_vi_core.2026-05-03`.

<table border="1" cellspacing="0" cellpadding="0" style="border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; font-size: 0.95em;">
<thead>
<tr>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Nhóm</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Kỹ thuật</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Ví dụ</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Phone</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex chấp nhận khoảng trắng, dấu chấm, dấu gạch</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">0978 711 253</code> -&gt; <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">0978711253</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Email</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex email chuẩn</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">a@b.com</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Email candidate</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex cho ASR mất <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">@</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">quyên24a.gmail.com</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">ID candidate</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex gần từ khóa CCCD/CMND/căn cước</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">cần review</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Date/date range</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex tiếng Việt</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">ngày 15 tháng 2 đến ngày 16 tháng 2</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Time</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex giờ, sáng/chiều/tối/đêm</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">10:30</code>, <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">buổi tối</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Money</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex số tiền</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">3 triệu 500 nghìn</code>, <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">4.500.000</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Quantity</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Regex số lượng + đơn vị</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">2 phòng</code>, <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">4 người</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Person</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Mẫu tự giới thiệu</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">Chị là Nguyễn Thị Quyên</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Organization</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Từ khóa khách sạn/công ty/... + tên riêng</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">khách sạn G.R.P.Marius Hotel Hà Nội</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Payment</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Từ khóa</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">chuyển khoản</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Purpose</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Từ khóa mục đích</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">công tác</code></td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Action/offer/policy</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Pattern nghiệp vụ</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">gửi số tài khoản, điều khoản, fitness free</td>
</tr>
</tbody>
</table>

Extractor đã được sửa để:

- Không nhận nhầm số điện thoại thành CCCD khi giữa keyword CCCD và number có "số điện thoại/email".
- Không match organization giả như "khách sạn mình ý".
- Dedupe fact theo `(type, normalized_value)` và append evidence.
- Không emit relation nguy cơ cao bằng deterministic mặc định.

Giá trị: với hội thoại đặt phòng khách sạn, extractor đã bắt được nhiều thông tin hơn bản đầu: phone, email candidate, CCCD candidate, ngày, tiền, số phòng/người, payment, purpose, offer, policy. Hạn chế: chưa có semantic relation/event/slot extraction sâu, nên hiểu nghiệp vụ vẫn còn giới hạn.

## 4.13. Domain Template Registry

`src/services/analysis_intelligence/domain_templates.py`, `src/api/endpoints/analysis_templates.py` và migration `f7a0b1c2d3e4_add_analysis_domain_templates.py` thêm registry mẫu phân tích.

Thiết kế:

- Scope phase đầu: `global`, `user`, `case`.
- Status: `draft`, `published`, `archived`.
- Published version là immutable; edit bản published tạo draft version mới.
- Field chính: `template_key`, `version`, `schema_hash`, `parent_template_id`, `schema_json`, `examples_json`, `published_at`, `archived_at`.
- Slot schema bắt buộc `name`, `label_vi`, `type`, `required`, `synonyms`, `description`.
- Type allowlist: text, person, organization, location, phone, email, id_number, date_time, money, quantity, enum, boolean.
- Giới hạn size: slots, examples, synonyms, hints, transcript test length.
- Global template cần permission `analysis_template:manage_global`.
- CRUD có audit log không ghi `schema_json`/`examples_json` chi tiết.

Trạng thái thực tế: backend registry đã có; UI "Mẫu phân tích" và extraction slots theo selected template/LLM chưa hoàn thiện. Khi `analysis_mode=selected` nhưng LLM tắt, graph chỉ ghi template refs và warning.

## 4.14. LLM summarization và forensic report

Dự án có hai hướng LLM:

1. `src/services/summarization/models/llm_manager.py`: Ollama local qua `/api/generate`.
2. `src/cherry_core/services/analysis_service.py`: LlamaCppAdapter + prompt Jinja2.

Summary V2:

- Hỗ trợ summary brief/detailed/investigation/forensic.
- Nếu `summary_type=forensic` có thể dùng Cherry Core.
- Nếu model `vistral`/`qwen3` có thể dùng llama.cpp.
- Fallback Ollama qua LLMManager.

Quan trọng: V2 evidence graph không tin trực tiếp vào summary/report LLM. Nếu summary/report được derive thành graph, source_method là `legacy_summary_derived` hoặc `cherry_report_derived`, items phải `requires_review=true`, không được tạo relation tin cậy.

LLM config đã có:

- `ANALYSIS_INTELLIGENCE_LLM_ENABLED`
- `ANALYSIS_LLM_PROVIDER`
- `ANALYSIS_LLM_BASE_URL`
- `ANALYSIS_LLM_MODEL`
- `ANALYSIS_LLM_API_KEY`
- `ANALYSIS_LLM_TIMEOUT_SECONDS`
- `ANALYSIS_LLM_MAX_INPUT_CHARS`

Trạng thái thực tế: đây mới là cấu hình và nền tảng; LLM gateway evidence-bound cho V2 slots/facts chưa được implement đầy đủ. Để sử dụng API key dịch vụ online bên ngoài an toàn, cần hoàn thiện provider gateway với structured outputs, chunking, evidence locating và validation.

## 4.15. Visualization và Analysis UI

Frontend hiện có:

- `AnalysisPanel.tsx`: sub-tabs `Tổng quan`, `Graph`, `Evidence`.
- `VisualizationPanel.tsx`: đọc legacy view từ V2 hoặc legacy payload.
- `frontend/src/utils/visualization.ts`: helper nhận diện V2, lấy legacy view, key entities.
- `FileTable.tsx` và `App.tsx`: Generate/Open Analysis flow.

Analysis Overview hiển thị:

- Số người, địa điểm, sự kiện, timeline.
- `display_sections_vi`: "Thông tin liên hệ và định danh", "Thông tin nghiệp vụ chính", "Yêu cầu, cam kết và hành động", "Điểm cần kiểm tra".
- Key entities phone/email/money/date.

Evidence tab hiển thị:

- Thông tin trích xuất, slots, risk flags, entities, relations, events, claims.
- Confidence, review status, source method, evidence count.
- Evidence refs: speaker, time range, source_kind, text span.

Graph tab hiện chỉ là view phụ/legacy compatibility, chưa phải evidence dashboard đầy đủ.

## 4.16. Evidence clip API

Endpoint `GET /api/v1/audio/{audio_id}/clip?start=...&end=...`:

- Kiểm tra `end > start`.
- Giới hạn duration theo `ANALYSIS_CLIP_MAX_DURATION_SECONDS`.
- `assert_audio_access(..., "read")`.
- `resolve_audio_path()` để tránh path traversal.
- Gọi ffmpeg bằng arg list, không shell string.
- Output WAV 16 kHz mono qua `pipe:1`.
- `stderr=subprocess.DEVNULL` để tránh deadlock pipe stderr.
- Cleanup process khi kết thúc/lỗi.
- Header privacy: `Cache-Control: no-store`, filename generic `audio-clip.wav`.

Giá trị: UI/evidence có thể nghe đoạn liên quan mà không expose raw filesystem path. Trạng thái UI clip playback chưa hoàn thiện trong phase hiện tại.

## 4.17. Bảo mật, phân quyền và audit

`src/core/auth.py` cung cấp:

- JWT/cookie session khi `AUTH_ENABLED=true`.
- CSRF cho method không an toàn.
- Rate limit qua Redis.
- `assert_case_access`, `assert_audio_access`, `assert_task_access`.
- Archived case read-only.
- UserRole permissions, trong đó global template dùng `analysis_template:manage_global`.

Audio endpoint:

- Upload/process cần case access và rate limit.
- Download/clip cần audio read access.
- Public static audio bị vô hiệu hóa, `/public/{filename}` trả 410.

Audit:

- Upload/delete/review graph/template CRUD có `log_activity`.
- Security audit log hash attempted identifier.
- Log nhạy cảm đã được redaction ở một số path, tránh log full transcript/context_analysis khi parse lỗi.

---

# 5. Đánh giá chất lượng, an toàn và giới hạn hiện tại

## 5.1. Điểm mạnh

1. **Local-first/offline-friendly**: Whisper, PhoWhisper, Pyannote local snapshots, Silero local JIT, Ollama/llama.cpp.
2. **Import-safe cho visualization/Pyannote loader**: tránh load torch/faster-whisper/librosa khi chỉ import visualization service.
3. **Evidence-grounded schema**: mọi item quan trọng có evidence refs, confidence, reason, review status.
4. **Backward compatibility**: V2 graph vẫn sinh `legacy_view`, `nodes`, `edges`, `timeline`.
5. **Vietnamese-first display**: `display_sections_vi`, label_vi, UI section tiếng Việt.
6. **Path safety và privacy**: audio path nằm dưới root, clip no-store, filename generic, không expose raw path.
7. **Review workflow backend**: confirm/reject/update/merge/split có revision guard và audit.
8. **Domain template registry**: đã có nền tảng versioning, scope, auth, audit.

## 5.2. Hạn chế kỹ thuật

1. **LLM V2 evidence-bound chưa hoàn thiện**: mới có config, chưa có provider gateway/chunking/structured schema validation cho slots.
2. **Selected domain chưa extract slots thật sự**: template refs được ghi, nhưng `slots`/`domain_frames` chưa được tạo từ LLM/domain schema.
3. **UI Domain Builder chưa có**: backend có CRUD, frontend chưa có tab "Mẫu phân tích" hoàn chỉnh.
4. **Relation/event extraction còn trống**: deterministic extractor chủ yếu emit entities/facts/risk_flags, tránh false positive nhưng làm graph quan hệ ít nội dung.
5. **Speaker attribution phụ thuộc ASR segment**: overlap heuristic > 0.3 có thể sai với segment dài hoặc overlap speech.
6. **Audio enhancement placeholder**: LLaSE/SepALM/WavLM/SpecAugment chưa là tính năng thực.
7. **Chưa có benchmark đủ lớn**: mới có fixture/test transcript mẫu; cần bộ dữ liệu đã gán nhãn cho nhiều domain.
8. **ASR forensic limitation**: với audio kém chất lượng, output không đủ tin cậy để tự động kết luận.

## 5.3. Rủi ro nghiệp vụ và biện pháp giảm thiểu

<table border="1" cellspacing="0" cellpadding="0" style="border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; font-size: 0.95em;">
<thead>
<tr>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Rủi ro</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Tác động</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Biện pháp hiện có</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Kiến nghị</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">ASR nghe sai số/tên/ngày</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Sai thông tin nhân thân/tài chính</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">confidence, evidence refs, review_status</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Bắt buộc review với PII/critical facts</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Diarization gán sai speaker</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Sai chủ thể phát ngôn</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">speaker_id chỉ là label kỹ thuật</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Hiển thị &quot;người nói dự kiến&quot;, không gán danh tính</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">LLM hallucination</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Tạo fact/quan hệ không có trong audio</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">V2 chưa tin LLM, legacy derived requires_review</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Structured output + evidence locating + fail closed</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Log lộ PII</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Lộ phone/email/transcript</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Đã redaction một số path</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Audit log định kỳ, grep secret/PII trong logs</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Truy cập trái phép audio</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Lộ file/chứng cứ</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">case access, audio access, path safety</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Bật AUTH_ENABLED trong production, CSRF, cookie secure</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Mẫu phân tích bị prompt injection</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Sai extraction</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Template chỉ lưu schema/hints/examples</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Validate schema, không dùng prompt tự do làm system prompt</td>
</tr>
</tbody>
</table>

## 5.4. Tiêu chí đánh giá đề xuất

### 5.4.1. ASR

- WER/CER trên tập audio tiếng Việt đã gán nhãn.
- Tỷ lệ bỏ sót số điện thoại/số tiền/ngày tháng.
- Tỷ lệ hallucination trên đoạn im lặng/noise.
- Tốc độ xử lý: real-time factor.

### 5.4.2. Diarization

- DER.
- Speaker attribution accuracy trên segment.
- Timestamp median/p95 error.
- Khả năng xử lý overlap speech.

### 5.4.3. Extraction/Analysis

- Fact precision/recall/F1.
- Slot F1 với domain template.
- Evidence coverage = 100% cho item hiển thị.
- Critical false positive = 0.
- Tỷ lệ item `needs_review` hợp lý với source_kind text-only/ASR noisy.

### 5.4.4. Bảo mật/vận hành

- Không có raw transcript/PII trong log.
- Không có token/model/audio artifact trong git diff.
- Endpoint unsafe có auth + CSRF khi `AUTH_ENABLED=true`.
- Clip endpoint không cache, không filename PII, cleanup subprocess.

---

# 6. Đề xuất hoàn thiện

## 6.1. Hoàn thiện LLM extraction evidence-bound

Xây dựng `analysis_intelligence/llm_gateway.py`:

- Provider: Ollama, OpenAI-compatible, custom HTTP.
- Config riêng `ANALYSIS_LLM_*`.
- JSON schema/Pydantic cho output.
- Chunk transcript theo segment, không truncate mất evidence.
- LLM trả `evidence_text`, backend locate lại trong transcript.
- Không locate được thì drop hoặc `needs_review`.
- Deterministic normalize phone/money/date giữ quyền ưu tiên.
- `model_info.llm_status`: disabled, failed, succeeded, partial.

## 6.2. Kết nối Domain Template vào runtime

Thêm selected mode thực sự:

- UI chọn template khi Generate Analysis.
- Backend resolve published template refs.
- LLM/deterministic overlay sinh `slots` và `domain_frames`.
- Preserve review metadata theo stable IDs.
- Template examples chỉ dùng làm extraction hints, không làm system prompt tự do.

## 6.3. Xây dựng UI "Mẫu phân tích"

Phase tối thiểu:

- List/detail templates.
- JSON schema editor có validation.
- Test transcript.
- Publish/archive.
- Import/export JSON.
- Form builder kéo thả có thể để sau.

## 6.4. Nâng cấp Analysis/Evidence UI

- Hiện warning rõ: "Kết quả do máy gợi ý, chưa được xác minh".
- Hiện reviewer, reviewed_at, review_note.
- Nút confirm/reject/edit trong Evidence tab.
- Play clip theo evidence ref.
- Conflict reload khi revision mismatch.
- Filter theo type, confidence, review_status, speaker, time.

## 6.5. Bộ benchmark nghiệp vụ

Tạo `tests/fixtures/investigation_transcripts/`:

- Hotel booking.
- Giao dịch/chuyển khoản.
- Hẹn gặp/lịch trình.
- Khiếu nại/dịch vụ.
- Cuộc gọi nhiều speaker.
- Audio/noisy transcript có ASR error.
- Unknown-domain để đảm bảo general analysis không rỗng.
- Prompt-injection fixture.

Mỗi fixture cần có transcript, segments, speaker, ground truth facts/slots/evidence spans.

## 6.6. Chuẩn hóa ngôn ngữ nghiệp vụ

Trong UI/report, nên tránh khẳng định vượt quá evidence:

- "Người nói dự kiến" thay cho "đối tượng" nếu chưa định danh.
- "Thông tin cần xác minh" thay cho "kết luận".
- "Rủi ro/điểm cần kiểm tra" thay cho "dấu hiệu tội phạm" nếu chỉ có gợi ý máy.
- "Đề xuất xác minh theo quy trình hợp pháp" thay cho "đối tượng giám sát" trong output mặc định.

## 6.7. Tăng cường forensic chain-of-custody

Thêm:

- Hash file audio gốc SHA-256.
- Metadata import: filename gốc, kích thước, mime, duration, uploader, time.
- Audit mở/nghe/download clip.
- Bản ghi model/extractor version cho mỗi lần transcribe/analyze.
- Re-analysis record: ai chạy, lúc nào, với template/model nào.

---

# 7. Kết luận

Dự án SpeechToInformation đã hình thành một pipeline tương đối đầy đủ cho bài toán hỗ trợ phân tích âm thanh hợp pháp: tiếp nhận file an toàn, ASR tiếng Việt/local-first, diarization bằng Pyannote, chuẩn hóa segment, evidence-grounded V2 graph, deterministic Vietnamese extractor, UI Analysis và review backend. Hướng thiết kế mới là đúng: không còn coi visualization là graph sinh từ summary, mà chuyển sang lớp phân tích có nguồn gốc bằng chứng.

Tuy nhiên, nếu đặt mục tiêu "trinh sát âm thanh" theo nghĩa nghiệp vụ sâu, hệ thống chưa nên được xem là hoàn thiện. Các thành phần LLM evidence-bound, selected domain slot extraction, UI domain builder, play clip trong evidence, bộ benchmark và chain-of-custody cần tiếp tục hoàn thiện. Quan điểm sử dụng đúng đắn là: hệ thống là công cụ hỗ trợ sàng lọc và gợi ý thông tin, không thay thế nghe kiểm tra, giám định âm thanh, đánh giá nghiệp vụ và quy trình pháp lý của cán bộ có thẩm quyền.

Kiến nghị tiếp tục phát triển theo ba trục:

1. **Độ tin cậy khoa học**: benchmark ASR/diarization/extraction với ground truth của bộ đánh giá.
2. **Truy vết bằng chứng**: mọi item hiển thị phải về được audio/text span, model version và review status.
3. **An toàn nghiệp vụ**: auth/audit/log redaction, manual review bắt buộc với PII và critical relation.

---

# 8. Tài liệu tham khảo

1. Học viện Cảnh sát nhân dân, "Đẩy mạnh công tác nghiên cứu khoa học sinh viên năm học 2025 - 2026", https://hvcsnd.edu.vn/day-manh-cong-tac-nghien-cuu-khoa-hoc-sinh-vien-nam-hoc-2025-2026-13374
2. Học viện An ninh nhân dân, "Tọa đàm khoa học Kinh nghiệm trong tổ chức hoạt động nghiên cứu khoa học của sinh viên", https://hvannd.edu.vn/bv/ct/17207/toa-dam-khoa-hoc-kinh-nghiem-trong-to-chuc-hoat-dong-nghien-cuu-khoa-hoc-cua-sinh-vien
3. Radford et al., "Robust Speech Recognition via Large-Scale Weak Supervision", arXiv:2212.04356, https://arxiv.org/abs/2212.04356
4. SYSTRAN, "faster-whisper: Faster Whisper transcription with CTranslate2", https://github.com/SYSTRAN/faster-whisper
5. OpenNMT, "CTranslate2", https://github.com/OpenNMT/CTranslate2
6. VinAIResearch, "PhoWhisper: Automatic Speech Recognition for Vietnamese", https://github.com/VinAIResearch/PhoWhisper
7. Pyannote, "speaker-diarization-community-1", https://huggingface.co/pyannote/speaker-diarization-community-1
8. Hugging Face, "Download files from the Hub", https://huggingface.co/docs/huggingface_hub/en/guides/download
9. Bain et al., "WhisperX: Time-Accurate Speech Transcription of Long-Form Audio", arXiv:2303.00747, https://arxiv.org/abs/2303.00747
10. Alpha Cephei, "Vosk Offline Speech Recognition", https://alphacephei.com/en
11. Silero Team, "silero-vad", https://github.com/snakers4/silero-vad
12. Diart, "A Python Library for Real-Time Speaker Diarization", JOSS, https://joss.theoj.org/papers/10.21105/joss.05266
13. Microsoft GraphRAG, "Dataflow", https://microsoft.github.io/graphrag/index/default_dataflow/
14. Microsoft GraphRAG, "Outputs", https://microsoft.github.io/graphrag/index/outputs/
15. SWGDE, "Best Practices for Forensic Audio", https://www.swgde.org/documents/published-complete-listing/08-a-001-swgde-best-practices-for-forensic-audio/
16. Loakes, "Automatic speech recognition and the transcription of indistinct forensic audio", Frontiers in Communication, 2024, https://www.frontiersin.org/articles/10.3389/fcomm.2024.1281407/full
17. Ollama, "Structured Outputs", https://docs.ollama.com/capabilities/structured-outputs
18. OpenAI, "Structured Outputs", https://platform.openai.com/docs/guides/structured-outputs
19. MultiWOZ 2.2, "A Dialogue Dataset with Additional Annotation Corrections and State Tracking Baselines", https://arxiv.org/abs/2007.12720

---

# 9. Phụ lục mã nguồn đối chiếu

## 9.1. Audio storage và access

- `src/services/audio_storage.py`
- `src/api/endpoints/audio.py`
- `src/core/auth.py`
- `src/database/models/models.py`

## 9.2. ASR và transcription

- `src/services/transcription/transcribe_service_v2.py`
- `src/services/transcription/cherry_transcription_service.py`
- `src/services/transcription/models/whisper_manager.py`
- `src/cherry_core/adapters/asr/whisperv2_adapter.py`
- `src/cherry_core/adapters/asr/phowhisper_adapter.py`
- `src/cherry_core/adapters/asr/hallucination_filter.py`

## 9.3. VAD và diarization

- `src/audio_processing/processor.py`
- `src/audio_processing/vad/silero_adapter.py`
- `src/cherry_core/adapters/vad/silero_adapter.py`
- `src/services/transcription/models/pyannote_loader.py`
- `src/services/transcription/models/pyannote_manager.py`
- `src/cherry_core/adapters/diarization/pyannote_adapter.py`
- `src/audio_processing/diarization/simple_vad.py`
- `src/audio_processing/diarization/manager.py`

## 9.4. Analysis intelligence V2

- `src/services/analysis_intelligence/schemas.py`
- `src/services/analysis_intelligence/segment_builder.py`
- `src/services/analysis_intelligence/extractor.py`
- `src/services/analysis_intelligence/service.py`
- `src/services/analysis_intelligence/storage.py`
- `src/services/analysis_intelligence/domain_templates.py`
- `src/api/endpoints/analysis_templates.py`
- `src/api/endpoints/audio_v2.py`

## 9.5. Summarization và LLM

- `src/services/summarization/summary_service_v2.py`
- `src/services/summarization/models/llm_manager.py`
- `src/services/cherry_summarizer.py`
- `src/cherry_core/services/analysis_service.py`
- `src/cherry_core/prompts/templates/forensic_report.j2`
- `src/cherry_core/prompts/scenarios/general_intelligence.yaml`

## 9.6. Frontend Analysis/Visualization

- `frontend/src/App.tsx`
- `frontend/src/components/AnalysisPanel.tsx`
- `frontend/src/components/VisualizationPanel.tsx`
- `frontend/src/components/FileTable.tsx`
- `frontend/src/utils/visualization.ts`

## 9.7. Tests liên quan

- `tests/test_analysis_intelligence.py`
- `tests/test_pyannote_loader.py`

---

# 10. Phụ lục đề xuất form nghiệm thu kỹ thuật

<table border="1" cellspacing="0" cellpadding="0" style="border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; font-size: 0.95em;">
<thead>
<tr>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Hạng mục</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Lệnh/kiểm tra</th>
<th style="border: 1px solid #4b5563; padding: 8px 10px; background: #eef2f7; font-weight: 700; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Kết quả mong đợi</th>
</tr>
</thead>
<tbody>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Python tests</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">python -m pytest tests -q</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Tất cả pass</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Compile backend</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">python -m compileall src -q</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Không lỗi cú pháp</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Frontend build</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">cmd /c &quot;cd frontend &amp;&amp; npm run build&quot;</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Build pass</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Docker config</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">docker compose config --quiet</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Config hợp lệ</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Import-safe visualization</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">fresh process import <code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">src.services.visualization_service</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Không load torch/faster_whisper/librosa/pyannote.audio</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Pyannote no auto-download</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">PYANNOTE_AUTO_DOWNLOAD=false</code></td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Không gọi snapshot_download</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Audio clip</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">GET clip có auth</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">WAV stream, no-store, filename generic</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">V2 evidence</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Generate Analysis</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;"><code style="font-family: Consolas, monospace; font-size: 0.92em; white-space: normal; overflow-wrap: anywhere;">schema_version=analysis_intelligence.v2</code>, facts có evidence_refs</td>
</tr>
<tr>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">Review conflict</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">PATCH với stale revision</td>
<td style="border: 1px solid #6b7280; padding: 8px 10px; text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word;">HTTP 409 + current graph</td>
</tr>
</tbody>
</table>
