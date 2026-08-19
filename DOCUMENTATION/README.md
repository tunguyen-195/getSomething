# TÀI LIỆU DỰ ÁN SPEECHTOINFORMATION

Thư mục này chứa toàn bộ tài liệu kỹ thuật, báo cáo phân tích và sơ đồ hệ thống cho dự án SpeechToInformation.

## Cấu trúc Thư mục

```
DOCUMENTATION/
├── README.md                    # File này - Hướng dẫn tổng quan
├── BAO_CAO_TONG_HOP.md         # Báo cáo phân tích thiết kế chi tiết (80KB)
└── DIAGRAMS/                   # Thư mục chứa sơ đồ UML
    ├── README_DIAGRAMS.md      # Hướng dẫn xem và export sơ đồ
    ├── 01_database_erd.puml                   # ERD - Cơ sở dữ liệu
    ├── 02_sequence_transcribe_workflow.puml   # Sequence - Luồng Transcribe
    ├── 03_sequence_summarize_workflow.puml    # Sequence - Luồng Summarize
    ├── 04_component_diagram.puml              # Component - Kiến trúc thành phần
    ├── 05_deployment_diagram.puml             # Deployment - Triển khai hệ thống
    ├── 06_class_diagram_models.puml           # Class - Database Models
    └── GENERATED/                             # Thư mục cho file PNG/SVG (export)
```

## Nội dung Tài liệu

### 1. Báo cáo Tổng hợp (`BAO_CAO_TONG_HOP.md`)

Báo cáo phân tích thiết kế chi tiết và giải pháp kỹ thuật gồm **9 chương**:

**Chương I**: Tổng quan dự án và tầm nhìn chiến lược
- Bối cảnh, nhu cầu
- Mục tiêu tổng quát và cụ thể
- Giá trị cốt lõi của hệ thống

**Chương II**: Kiến trúc hệ thống và nguyên lý vận hành
- Kiến trúc tổng thể (Frontend, API Gateway, Task Queue, AI Services, Data Layer)
- Nguyên lý hoạt động của từng layer
- Luồng dữ liệu (Data Flow)
- Sơ đồ Mermaid: Architecture, Data Flow, Technology Stack

**Chương III**: Phân tích UseCase và luồng nghiệp vụ
- 15+ UseCase chi tiết: Upload, Transcribe, Summarize, Visualize, Case Management, etc.
- Sơ đồ UseCase Diagram (Mermaid)

**Chương IV**: Thiết kế cơ sở dữ liệu
- 20+ bảng: Users, Cases, AudioFiles, Tasks, Transcriptions, AnalysisResults, etc.
- Quan hệ giữa các bảng (1-1, 1-N, N-N)
- Thiết kế JSONB cho Task.result (linh hoạt, mở rộng)
- Entity Relationship Diagram (Mermaid)

**Chương V**: Chi tiết công nghệ đột phá
- Thuật toán Overlap-based Matching cho Speaker Diarization (91-95% accuracy)
- Garbage Text Filtering (loại bỏ 5-10% noise)
- Multi-layer Context Analysis (5 layers)
- Model Manager Pattern (Singleton, Lazy Loading)
- Gevent Pool cho Celery (tăng 30% hiệu suất)
- JSONB Storage (giảm 40% join operations)

**Chương VI**: Năng lực phân tích sâu & toàn diện
- 5 lớp phân tích ngữ cảnh:
  1. Entity Extraction (người, nơi, tổ chức, thời gian, tiền)
  2. Relationship Mining (mối quan hệ trực tiếp, ẩn, ảnh hưởng)
  3. Action & Decision Tracking (cam kết, đề xuất, yêu cầu)
  4. Risk & Anomaly Detection (mâu thuẫn, né tránh, nghi ngờ)
  5. Deep Insights (thông tin hành động, khuyến nghị)
- 3 chế độ tóm tắt: Brief, Detailed, Investigation
- Zero Information Loss (không bỏ sót thông tin quan trọng)

**Chương VII**: Hiệu năng và tối ưu hóa
- Transcription: 10x realtime (5 phút audio → 30 giây xử lý)
- Summarization: 20x realtime
- API Response Time: < 200ms (P95)
- Database Connection Pooling: 20+10
- Redis Caching
- Lazy Model Loading
- Gevent Pool (10 greenlets)

**Chương VIII**: Kế hoạch triển khai và định hướng tương lai
- Development, Staging, Production environments
- Monitoring & Alerting (Prometheus, Grafana)
- Scaling strategies: Horizontal (workers), Vertical (GPU)
- Roadmap: vLLM (5-6x faster), Kubernetes, Multi-region

**Chương IX**: Kết luận và khuyến nghị
- Lợi ích cốt lõi
- ROI analysis
- Khuyến nghị triển khai

### 2. Sơ đồ UML (`DIAGRAMS/`)

Có **6 sơ đồ PlantUML** chi tiết:

1. **Database ERD** (`01_database_erd.puml`)
   - 20+ bảng với đầy đủ quan hệ
   - Primary keys, Foreign keys, Unique constraints
   - Cấu trúc JSONB của Task.result

2. **Transcribe Workflow** (`02_sequence_transcribe_workflow.puml`)
   - Sequence diagram đầy đủ từ user click → hiển thị kết quả
   - Whisper inference, Garbage filtering, Diarization, Overlap matching
   - 8 bước chi tiết

3. **Summarize Workflow** (`03_sequence_summarize_workflow.puml`)
   - Sequence diagram cho summarization
   - 5-layer context analysis
   - LLM interaction với Ollama

4. **Component Diagram** (`04_component_diagram.puml`)
   - Kiến trúc 5 layers: Frontend, API, Task, AI, Data
   - Components và sub-components
   - Dependencies

5. **Deployment Diagram** (`05_deployment_diagram.puml`)
   - Deployment architecture với 6+ servers
   - Network zones: Public, DMZ, Application, Data, Monitoring
   - Dev/Staging/Production configs

6. **Class Diagram** (`06_class_diagram_models.puml`)
   - 20+ database model classes
   - Inheritance từ BaseModel
   - Attributes, methods, relationships

## Cách Xem Sơ đồ UML

### LỖI "Failed to generate SVG" - CÁCH KHẮC PHỤC

Nếu bạn gặp lỗi:
```
Failed to generate SVG file.
Command: java -jar "..." "01_database_erd.puml" -tsvg -o "..."
```

**Nguyên nhân**: Extension PlantUML không tìm thấy Java hoặc PlantUML JAR không hoạt động.

**Giải pháp**:

#### Bước 1: Cài đặt Java (bắt buộc)

PlantUML yêu cầu Java Runtime. Kiểm tra Java đã cài chưa:

```bash
java -version
```

Nếu chưa có, cài đặt:

**Windows**:
```bash
# Sử dụng winget
winget install Oracle.JDK.17

# Hoặc download từ: https://www.oracle.com/java/technologies/downloads/
```

**Linux**:
```bash
sudo apt update
sudo apt install default-jdk
```

**macOS**:
```bash
brew install openjdk@17
```

Sau khi cài, restart VS Code.

#### Bước 2: Cài đúng Extension PlantUML

1. Gỡ extension hiện tại: `justuskarlsson.plan-uml`
2. Cài extension chính thức: **PlantUML** by **jebbs**
   - ID: `jebbs.plantuml`
   - Link: https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml

#### Bước 3: Cấu hình Extension (nếu cần)

Mở VS Code Settings (`Ctrl+,`) và tìm `plantuml`:

```json
{
  "plantuml.server": "https://www.plantuml.com/plantuml",
  "plantuml.render": "PlantUMLServer"
}
```

Hoặc sử dụng local JAR:

```json
{
  "plantuml.render": "Local",
  "plantuml.jarPath": "path/to/plantuml.jar"
}
```

#### Bước 4: Xem Sơ đồ

Mở file `.puml` trong VS Code:

1. **Preview**: Nhấn `Alt + D` (Windows/Linux) hoặc `Option + D` (macOS)
2. **Export PNG/SVG**: Right-click → "Export Current Diagram"

### Phương pháp Thay thế: Online PlantUML Editor

Nếu vẫn gặp vấn đề, dùng online editor:

1. Truy cập: https://www.plantuml.com/plantuml/uml/
2. Copy toàn bộ nội dung file `.puml`
3. Paste vào editor
4. Click "Submit" để xem sơ đồ
5. Download PNG/SVG từ link phía dưới

### Lưu ý Export

Sau khi export thành công, lưu file PNG/SVG vào:
```
DOCUMENTATION/DIAGRAMS/GENERATED/
```

## Hướng dẫn Sử dụng Tài liệu

### Cho Developer
1. Đọc **Chương II** (Kiến trúc) để hiểu tổng thể hệ thống
2. Xem **Component Diagram** và **Deployment Diagram**
3. Đọc **Chương V** (Công nghệ đột phá) để hiểu thuật toán core
4. Tham khảo **Database ERD** và **Class Diagram** khi code

### Cho Product Owner / BA
1. Đọc **Chương I** (Tổng quan) để hiểu mục tiêu và giá trị
2. Xem **UseCase Diagram** và **Chương III** (UseCase)
3. Đọc **Chương VI** (Năng lực phân tích) để hiểu khả năng hệ thống

### Cho DevOps / Infrastructure
1. Xem **Deployment Diagram** để hiểu kiến trúc triển khai
2. Đọc **Chương VII** (Hiệu năng) để hiểu resource requirements
3. Đọc **Chương VIII** (Kế hoạch triển khai) cho scaling strategy

### Cho Stakeholders
1. Đọc **Chương I** (Tổng quan)
2. Đọc **Chương VI** (Năng lực phân tích sâu)
3. Đọc **Chương IX** (Kết luận và khuyến nghị)

## Thông tin Kỹ thuật

### Công nghệ Sử dụng

**Backend**:
- FastAPI (Python 3.11+)
- Celery (Gevent Pool)
- Redis (Message Broker + Cache)
- PostgreSQL 14+ (JSONB, GIN Indexes)

**Frontend**:
- React 18+ (TypeScript)
- Material-UI (Cherry2 Theme)
- Vite (Build Tool)

**AI Models**:
- Whisper Large V3 (faster-whisper)
- Pyannote.audio 3.x
- Ollama (Gemma2:9B, DeepSeek R1, Llama3.2, Mistral)

**Infrastructure**:
- Docker + Docker Compose
- Nginx (Load Balancer)
- Prometheus + Grafana (Monitoring)
- (Future) Kubernetes, vLLM

### Yêu cầu Hệ thống

**Development**:
- CPU: 4 cores
- RAM: 16GB
- GPU: NVIDIA (8GB VRAM, CUDA 11.8+)
- Storage: 50GB SSD

**Production**:
- App Server: 8 cores, 32GB RAM
- Worker Server: 16 cores, 64GB RAM, NVIDIA GPU (16GB VRAM)
- DB Server: 8 cores, 32GB RAM, 500GB SSD
- Redis Server: 4 cores, 8GB RAM

## Liên hệ

Nếu có thắc mắc về tài liệu, vui lòng liên hệ Ban Dự án SpeechToInformation.

---

**Cập nhật lần cuối**: 24/12/2025

**Phiên bản**: 1.0.0

**Tác giả**: Ban Dự án SpeechToInformation
