# activeContext.md

## Trọng tâm hiện tại
- Đã nghiên cứu toàn bộ logic backend (FastAPI, Celery, service, worker) và frontend (React, UI quản lý file, transcript, summary).
- Đã xác định các vấn đề UI/UX cần cải thiện: màu sắc giao diện (color scheme), sidebar list case nên dùng tone trắng đơn sắc, màu xanh pastel hiện tại chưa phù hợp.
- Đã hoàn thành nghiên cứu, lựa chọn và lên kế hoạch tích hợp module Speaker Diarization (NeMo, WhisperX) vào pipeline backend, cho phép UI lựa chọn giải pháp hoặc tắt/bật tính năng này.
- Tiếp tục rà soát, đề xuất phương án tối ưu UI/UX, chuẩn bị cập nhật các thay đổi về màu sắc, trải nghiệm người dùng.

## Thay đổi gần đây
- Đã đọc toàn bộ codebase, xác định rõ pipeline backend (audio → transcript → summary → lưu DB → trả về frontend), các component chính frontend (App, FileTable, TranscriptPanel, InvestigationSummaryCard).
- Đã ghi nhận các vấn đề còn tồn tại về logging, pipeline, validate schema, CORS, lỗi 422, cần bổ sung log chi tiết toàn bộ pipeline.
- Đã bổ sung tài liệu, hướng dẫn sử dụng, so sánh, tích hợp module Speaker Diarization (NeMo, WhisperX) vào README.md và memory-bank.

## Bước tiếp theo
- Đề xuất, thử nghiệm các phương án phối màu UI phù hợp hơn (ưu tiên trắng, xám, xanh navy, tím nhạt, tránh xanh pastel quá sáng).
- Cập nhật lại component sidebar list case theo tone trắng đơn sắc, tăng độ tương phản, dễ đọc.
- Tiếp tục rà soát logic backend, đảm bảo mọi Exception đều được log rõ ràng, bổ sung log resource usage, input/output, trạng thái pipeline.
- Kiểm tra lại validate schema, pipeline xử lý dữ liệu đầu vào, toàn bộ API request/response.
- Triển khai, kiểm thử thực tế pipeline Speaker Diarization (NeMo, WhisperX), tối ưu hiệu năng, log lỗi rõ ràng, cho phép frontend lựa chọn giải pháp.
