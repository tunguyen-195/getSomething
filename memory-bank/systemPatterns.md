# systemPatterns.md

## Kiến trúc tổng quan
- Modular, tách biệt frontend/backend/worker
- Xử lý bất đồng bộ với Celery + Redis
- API RESTful + WebSocket cho realtime
- Lưu trữ kết quả và trạng thái task trong PostgreSQL
- Batch processing, fallback model, caching, logging, monitoring

## Pipeline tổng thể
- Backend: Nhận file audio → Lưu storage → Tạo task → Worker xử lý (transcribe, summarize, **speaker diarization: NeMo/WhisperX/None**) → Lưu kết quả DB → Trả về API
- Frontend: React App → Quản lý case, upload file, theo dõi tiến trình realtime, hiển thị transcript, summary, visualize entity/timeline, **cho phép lựa chọn bật/tắt và chọn giải pháp speaker diarization (NeMo/WhisperX)**
- Các component UI chính: App, FileTable (quản lý file), TranscriptPanel (hiển thị transcript), InvestigationSummaryCard (tóm tắt, phân tích nội dung)

## Design Patterns
- Task Queue (Celery)
- Repository pattern (database)
- Service layer (business logic)
- Observer pattern (WebSocket update)
- Factory pattern (model selection)

## Quan hệ thành phần
- Frontend ↔ API ↔ Worker ↔ Database
- API quản lý task, worker xử lý, frontend realtime

## Vấn đề UI/UX
- Màu sắc giao diện hiện tại (xanh pastel) chưa phù hợp, cần chuyển sang tone trắng/xám/navy/tím nhạt
- Sidebar list case nên dùng tone trắng đơn sắc, tăng độ tương phản, dễ đọc
