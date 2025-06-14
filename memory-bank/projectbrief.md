# projectbrief.md

## Tóm tắt dự án
Hệ thống "Speech to Information" là một giải pháp chuyển đổi âm thanh thành văn bản và tóm tắt nội dung, vận hành hoàn toàn offline, hỗ trợ đa ngôn ngữ (ưu tiên tiếng Việt), xử lý song song nhiều file, cung cấp giao diện web hiện đại, API, và khả năng mở rộng mạnh mẽ. Dự án hướng tới việc triển khai trên desktop/server local, không phụ thuộc Internet, tối ưu cho hiệu năng và trải nghiệm người dùng.

## Mục tiêu chính
- Nhận file audio hoặc stream, chuyển thành transcript chính xác
- Tóm tắt nội dung văn bản đầu ra
- Hỗ trợ batch processing, xử lý song song
- Giao diện web hiện đại, realtime, dễ dùng
- Hệ thống logging, monitoring, quản lý task
- Vận hành độc lập, không phụ thuộc dịch vụ ngoài

## Phạm vi
- Xử lý audio: wav, mp3, m4a, ...
- Tích hợp các mô hình: Whisper, Vosk, BART, T5, Mistral-7B, ...
- Backend: FastAPI, Celery, Redis, PostgreSQL
- Frontend: React, Material-UI, WebSocket
- Triển khai: Docker, local, cloud-ready
