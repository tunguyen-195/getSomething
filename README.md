# Speech to Information System v2.0

Hệ thống xử lý âm thanh thành văn bản và tóm tắt nội dung, chạy hoàn toàn offline với khả năng xử lý đa luồng và quản lý tác vụ.

## Tính năng chính

- Chuyển đổi âm thanh thành văn bản (Speech-to-Text) với độ chính xác cao
- Hỗ trợ đa ngôn ngữ, đặc biệt là tiếng Việt
- Tóm tắt nội dung tự động
- Chạy hoàn toàn offline, không cần kết nối internet
- Xử lý nhiều file âm thanh cùng lúc
- **Phân biệt người nói (Speaker Diarization) với hai giải pháp tùy chọn: NeMo hoặc WhisperX, cho phép bật/tắt và chọn giải pháp ngay trên giao diện**
- Giao diện web hiện đại với React
- Hỗ trợ theo dõi tiến trình real-time
- Quản lý và lưu trữ kết quả

## Kiến trúc hệ thống

```
[Frontend Layer]
├── React + TypeScript
├── Material-UI
├── WebSocket Client
├── Speaker Diarization Option (UI)
    ↓
[API Layer]
├── FastAPI
├── WebSocket Server
├── REST Endpoints
├── Nhận options: bật/tắt diarization, chọn giải pháp (NeMo/WhisperX)
    ↓
[Task Queue Layer]
├── Celery
├── Redis
└── Worker Pool
    ↓
[Processing Layer]
├── Audio Processing Workers
├── Speech-to-Text Workers
├── Speaker Diarization Pipeline (modular: NeMo/WhisperX/None)
├── Summarization Workers
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

2. **Tùy chọn Speaker Diarization (Phân biệt người nói)**:
   - Trên giao diện upload, có thể bật/tắt tính năng phân biệt người nói
   - Nếu bật, chọn giải pháp: **NeMo** (độ chính xác cao, cần GPU mạnh) hoặc **WhisperX** (dễ tích hợp, hoạt động tốt offline)

3. **Xử lý**:
   - Chọn ngôn ngữ cho từng file
   - Thiết lập các tùy chọn xử lý khác
   - Bắt đầu xử lý

4. **Theo dõi**:
   - Xem tiến trình real-time
   - Nhận thông báo khi hoàn thành
   - Xem log chi tiết

5. **Kết quả**:
   - Nếu bật diarization: transcript sẽ được phân đoạn theo từng người nói (Speaker 1, 2...)
   - Nếu không: transcript thông thường
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
WHISPER_MODEL=large-v2
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

## Speaker Diarization (Phân biệt người nói)

### Tổng quan
- Hệ thống hỗ trợ hai giải pháp phân biệt người nói: **NeMo** (NVIDIA) và **WhisperX** (kết hợp Whisper + pyannote).
- Cho phép bật/tắt và chọn giải pháp ngay trên giao diện người dùng.
- Pipeline backend được xây dựng dạng module, dễ mở rộng, có thể thêm giải pháp mới trong tương lai.

### So sánh nhanh
| Giải pháp   | Độ chính xác | Yêu cầu phần cứng | Dễ tích hợp | Offline |
|-------------|--------------|-------------------|-------------|---------|
| NeMo        | Rất cao      | GPU mạnh (NVIDIA) | Trung bình  | Có      |
| WhisperX    | Tốt          | CPU/GPU           | Rất dễ      | Có      |

### Cài đặt & cấu hình
- Đảm bảo đã cài đặt các dependency cho NeMo, WhisperX, pyannote.audio (xem hướng dẫn trong docs hoặc README chi tiết).
- Tải các model về local để đảm bảo chạy offline.
- Cấu hình pipeline trong backend: chọn default, cho phép override qua API/UI.

### Sử dụng trên UI
- Khi upload audio, chọn "Phân biệt người nói" và chọn giải pháp mong muốn.
- Kết quả transcript sẽ được phân đoạn theo từng người nói (Speaker 1, 2...).

### Tích hợp backend
- Pipeline xử lý audio sẽ tự động gọi module tương ứng (NeMo/WhisperX/None) dựa trên lựa chọn của người dùng.
- Kết quả trả về frontend sẽ bao gồm thông tin speaker cho từng đoạn transcript nếu bật diarization.

## Tối ưu hóa GPU cho Whisper (faster-whisper)

- **device**: Ưu tiên "cuda" nếu có GPU, fallback "cpu" nếu không.
- **compute_type**: 
  - "float16" (tối ưu tốc độ, cần GPU hỗ trợ)
  - "int8_float16" (tiết kiệm VRAM, tốc độ cao, độ chính xác gần như không đổi)
  - "int8" (cho CPU)
- **batch_size**: Càng lớn càng tận dụng GPU tốt (8, 16, 32 tuỳ VRAM, RAM hệ thống ≥ VRAM)
- **beam_size**: 1 (tối đa tốc độ), 5 (mặc định, cân bằng chính xác/tốc độ)

### Cách chỉnh tham số
- Sửa trực tiếp trong `src/core/config.py`:
  - `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPER_BATCH_SIZE`, `WHISPER_BEAM_SIZE`
- Hoặc đặt biến môi trường khi chạy:
  - `WHISPER_DEVICE=cuda WHISPER_COMPUTE_TYPE=float16 WHISPER_BATCH_SIZE=16 WHISPER_BEAM_SIZE=1 python ...`

### Lưu ý production
- Luôn kiểm tra log để biết model đang chạy trên thiết bị nào, compute_type gì, batch_size bao nhiêu.
- Nếu GPU utilization thấp, thử tăng batch_size, giảm beam_size, hoặc chạy nhiều tiến trình song song.
- Đảm bảo RAM hệ thống ≥ VRAM để tránh bottleneck khi batch lớn.
- Nếu có nhiều GPU, có thể chỉnh device index (chưa hỗ trợ multi-GPU tự động, cần chỉnh thủ công).

## Tối ưu cho Windows 11 + RTX 4070 SUPER
- Worker pool song song, batch nhỏ, chỉ dùng GPU NVIDIA
- Tích hợp speech enhancement (LLaSE-G1, SepALM, WavLM, SpecAugment)
- Tích hợp LLM-based error correction (RobustGER, Whisper-LM, chain-of-correction)
- Benchmark tự động WER/CER/noise, log chi tiết, alert khi hiệu năng thấp
- Monitoring Prometheus/Grafana, alert khi RAM/VRAM cao

celery -A src.worker.worker worker --loglevel=info
celery -A src.worker.worker worker --loglevel=info --pool=solo
uvicorn src.main:app --reload                   
celery -A src.worker.worker worker --loglevel=info --pool=threads
npm run dev