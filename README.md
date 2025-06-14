# Speech to Information System v2.0

Hệ thống xử lý âm thanh thành văn bản và tóm tắt nội dung, chạy hoàn toàn offline với khả năng xử lý đa luồng và quản lý tác vụ.

## Tính năng chính

- Chuyển đổi âm thanh thành văn bản (Speech-to-Text) với độ chính xác cao
- Hỗ trợ đa ngôn ngữ, đặc biệt là tiếng Việt
- Tóm tắt nội dung tự động
- Chạy hoàn toàn offline, không cần kết nối internet
- Xử lý nhiều file âm thanh cùng lúc
- Giao diện web hiện đại với React
- Hỗ trợ theo dõi tiến trình real-time
- Quản lý và lưu trữ kết quả

## Kiến trúc hệ thống

```
[Frontend Layer]
├── React + TypeScript
├── Material-UI
└── WebSocket Client
    ↓
[API Layer]
├── FastAPI
├── WebSocket Server
└── REST Endpoints
    ↓
[Task Queue Layer]
├── Celery
├── Redis
└── Worker Pool
    ↓
[Processing Layer]
├── Audio Processing Workers
├── Speech-to-Text Workers
└── Summarization Workers
    ↓
[Storage Layer]
├── PostgreSQL
└── File Storage
```

## Yêu cầu hệ thống

### Backend
- Python 3.10+
- CUDA 11.8+ (nếu dùng GPU)
- RAM: 16GB+ (khuyến nghị)
- Ổ cứng: 20GB+ trống
- Redis Server
- PostgreSQL 13+

### Frontend
- Node.js 18+
- npm 8+

## Cài đặt

### 1. Clone repository
```bash
git clone https://github.com/your-username/speech-to-information.git
cd speech-to-information
```

### 2. Cài đặt Backend

Tạo và kích hoạt môi trường ảo:
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

Cài đặt dependencies:
```bash
pip install -r requirements.txt
```

### 3. Cài đặt Frontend

```bash
cd frontend
npm install
```

### 4. Cài đặt Database

```bash
# Cài đặt PostgreSQL
# Windows: https://www.postgresql.org/download/windows/
# Linux: sudo apt-get install postgresql
# Mac: brew install postgresql

# Cài đặt Redis
# Windows: https://github.com/microsoftarchive/redis/releases
# Linux: sudo apt-get install redis-server
# Mac: brew install redis
```

### 5. Cấu hình

1. Tạo file `.env` từ `.env.example`
2. Cập nhật các biến môi trường cần thiết
3. Khởi tạo database:
```bash
python scripts/init_db.py
```

### 6. Chạy hệ thống

1. Khởi động Redis:
```bash
# Windows
redis-server
# Linux/Mac
sudo service redis-server start
```

2. Khởi động Celery workers:
```bash
celery -A src.worker worker --loglevel=info
```

3. Khởi động Backend:
```bash
uvicorn src.main:app --reload
```

4. Khởi động Frontend:
```bash
cd frontend
npm run dev
```

Truy cập http://localhost:3000 để sử dụng hệ thống.

## Sử dụng

1. **Upload Files**:
   - Kéo thả hoặc chọn nhiều file âm thanh
   - Hỗ trợ các định dạng: wav, mp3, m4a, ...

2. **Xử lý**:
   - Chọn ngôn ngữ cho từng file
   - Thiết lập các tùy chọn xử lý
   - Bắt đầu xử lý

3. **Theo dõi**:
   - Xem tiến trình real-time
   - Nhận thông báo khi hoàn thành
   - Xem log chi tiết

4. **Kết quả**:
   - Xem và tải kết quả
   - Xuất ra nhiều định dạng
   - Tìm kiếm và lọc kết quả

## API Documentation

API documentation có sẵn tại http://localhost:8000/docs sau khi khởi động backend.

## Contributing

Mọi đóng góp đều được hoan nghênh! Vui lòng đọc [CONTRIBUTING.md](CONTRIBUTING.md) để biết thêm chi tiết.

## License

MIT License 

# Speech to Information Backend

## Mô tả
Dự án FastAPI chuyển đổi giọng nói thành văn bản và tóm tắt nội dung, hỗ trợ upload audio, batch, quản lý task, lấy kết quả.

## Yêu cầu
- Python 3.11+
- pip
- (Tùy chọn) Docker, docker-compose

## Cài đặt
```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## Cấu hình môi trường
Tạo file `.env` ở thư mục gốc với nội dung mẫu:
```env
SECRET_KEY=your-super-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/speech_to_info
DATABASE_TEST_URL=postgresql://postgres:postgres@localhost:5432/speech_to_info_test
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
WHISPER_MODEL=large-v3
VOSK_MODEL_PATH=models/vosk-model-vn-0.4
T5_MODEL_PATH=models/t5-base
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE=100000000
ALLOWED_EXTENSIONS=["wav", "mp3", "m4a", "ogg"]
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
LOKI_URL=http://localhost:3100
FRONTEND_URL=http://localhost:3000
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
API_V1_STR=/api/v1
PROJECT_NAME=Speech to Information
BACKEND_CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000"]
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc
METRICS_PORT=9090
```

## Chạy test
```bash
pytest tests/test_system.py -v
```

## Chạy server FastAPI
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
Truy cập [http://localhost:8000/docs](http://localhost:8000/docs) để thử các endpoint.

## Các endpoint chính
- `GET /api/health`: Kiểm tra trạng thái server
- `POST /api/audio/upload`: Upload 1 file audio
- `POST /api/audio/batch`: Upload nhiều file audio
- `POST /api/tasks`: Tạo task xử lý
- `GET /api/tasks/{task_id}`: Lấy trạng thái task
- `GET /api/results/{task_id}`: Lấy kết quả task

## Lưu ý
- Kết quả hiện tại là mock, muốn xử lý thực tế hãy cập nhật các service trong `src/services/`.
- Nếu dùng Docker, xem thêm file `docker-compose.yml`. 

uvicorn src.main:app --reload                   