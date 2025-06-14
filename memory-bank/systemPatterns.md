# systemPatterns.md

## Kiến trúc tổng quan
- Modular, tách biệt frontend/backend/worker
- Xử lý bất đồng bộ với Celery + Redis
- API RESTful + WebSocket cho realtime
- Lưu trữ kết quả và trạng thái task trong PostgreSQL
- Batch processing, fallback model, caching, logging, monitoring

## Design Patterns
- Task Queue (Celery)
- Repository pattern (database)
- Service layer (business logic)
- Observer pattern (WebSocket update)
- Factory pattern (model selection)

## Quan hệ thành phần
- Frontend ↔ API ↔ Worker ↔ Database
- API quản lý task, worker xử lý, frontend realtime
