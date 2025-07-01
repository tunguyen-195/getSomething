# progress.md

## Đã hoàn thành
- Đã chuẩn hóa toàn bộ codebase, loại bỏ src/db, chỉ còn src/database
- Đã sửa toàn bộ import, endpoint, service, test liên quan src.db
- Đã hướng dẫn dọn sạch pycache, khởi động lại môi trường
- Đã kiểm tra lại hoạt động hệ thống, backend đã chạy, API trả về dữ liệu
- **Đã đọc toàn bộ codebase, xác định rõ pipeline backend (audio → transcript → summary → DB → frontend), các component chính frontend (App, FileTable, TranscriptPanel, InvestigationSummaryCard).**
- Đã xác định các vấn đề UI/UX: màu sắc giao diện chưa phù hợp, sidebar list case cần đổi sang tone trắng đơn sắc.
- Đã cài đặt torch==2.1.1+cu121, torchvision==0.16.1+cu121, torchaudio==2.1.1+cu121 (GPU)
- torch.cuda.is_available() = True, torch.version.cuda = 12.1
- **Đã nghiên cứu, so sánh, lựa chọn và lên kế hoạch tích hợp module Speaker Diarization (NeMo, WhisperX) vào pipeline backend, cập nhật tài liệu hướng dẫn sử dụng, so sánh, cấu hình, UI lựa chọn giải pháp.**

## Còn lại
- Đề xuất, thử nghiệm các phương án phối màu UI phù hợp hơn (ưu tiên trắng, xám, xanh navy, tím nhạt, tránh xanh pastel quá sáng).
- Cập nhật lại component sidebar list case theo tone trắng đơn sắc, tăng độ tương phản, dễ đọc.
- Tiếp tục rà soát logic backend, đảm bảo mọi Exception đều được log rõ ràng, bổ sung log resource usage, input/output, trạng thái pipeline.
- Kiểm tra lại validate schema, pipeline xử lý dữ liệu đầu vào, toàn bộ API request/response.
- Sửa lỗi cấu hình middleware (CORS), lỗi 422 Unprocessable Entity khi gửi request tới API.

## Vấn đề/ghi chú
- Lỗi middleware có thể do logic kiểm tra dư thừa trong startup_event hoặc do cache cũ
- Lỗi 422 có thể do frontend gửi sai schema hoặc backend validate chưa đúng
- **Backend có thể bị treo do deadlock, blocking, memory leak hoặc Exception không được log đầy đủ. Cần bổ sung log chi tiết để xác định nguyên nhân.**
- **UI cần cải thiện màu sắc, sidebar list case nên dùng tone trắng đơn sắc, tránh xanh pastel quá sáng.**
