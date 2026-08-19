# Sơ đồ Hệ thống SpeechToInformation

Thư mục này chứa tất cả các sơ đồ UML/PlantUML chi tiết cho hệ thống SpeechToInformation.

## Danh sách Sơ đồ

### 1. Database ERD (`01_database_erd.puml`)
**Entity Relationship Diagram** - Sơ đồ quan hệ thực thể cơ sở dữ liệu

- Tất cả các bảng database (Users, Cases, AudioFiles, Tasks, etc.)
- Các mối quan hệ giữa các bảng (1-1, 1-N, N-N)
- Khóa chính (PK), khóa ngoại (FK), unique constraints
- Cấu trúc JSONB của Task.result
- Notes giải thích thiết kế

**Mục đích**: Hiểu rõ cấu trúc database và quan hệ dữ liệu

### 2. Transcribe Workflow (`02_sequence_transcribe_workflow.puml`)
**Sequence Diagram** - Sơ đồ tuần tự cho workflow chuyển đổi âm thanh

- Luồng xử lý từ khi user click "Start Transcribe"
- Tương tác giữa UI, API, Worker, Whisper, Pyannote
- Chi tiết thuật toán Overlap-based Matching
- Garbage Text Filtering
- Speaker Diarization process
- Lưu kết quả vào database

**Mục đích**: Hiểu rõ quy trình transcription từ đầu đến cuối

### 3. Summarize Workflow (`03_sequence_summarize_workflow.puml`)
**Sequence Diagram** - Sơ đồ tuần tự cho workflow tóm tắt

- Luồng xử lý từ khi user click "Start Summary"
- Multi-layer Context Analysis (5 layers)
- Entity Extraction, Relationship Mining, Action Tracking
- Risk & Anomaly Detection, Deep Insights
- 3 chế độ summary (Brief, Detailed, Investigation)
- LLM interaction với Ollama

**Mục đích**: Hiểu rõ quy trình phân tích và tóm tắt thông minh

### 4. Component Diagram (`04_component_diagram.puml`)
**Component Diagram** - Sơ đồ thành phần hệ thống

- Kiến trúc layers: Frontend, API, Task, AI, Data
- Các components chính và sub-components
- Dependencies giữa các components
- External services (Ollama, AI Models)
- Notes giải thích từng layer

**Mục đích**: Hiểu rõ kiến trúc tổng thể và phân chia components

### 5. Deployment Diagram (`05_deployment_diagram.puml`)
**Deployment Diagram** - Sơ đồ triển khai hệ thống

- Các servers: App Server, Worker Server, DB Server, etc.
- Network zones: Public, DMZ, Application, Data, Monitoring
- Ports, protocols, connections
- Cấu hình cho Development, Staging, Production
- Future: Kubernetes deployment

**Mục đích**: Hiểu rõ cách triển khai hệ thống trên infrastructure

### 6. Class Diagram (`06_class_diagram_models.puml`)
**Class Diagram** - Sơ đồ lớp cho database models

- Tất cả các model classes (User, Case, AudioFile, Task, etc.)
- Attributes, methods, properties
- Inheritance từ BaseModel
- Relationships giữa các classes
- Notes giải thích thiết kế

**Mục đích**: Hiểu rõ cấu trúc ORM models và business logic

## Cách Xem Sơ đồ

### Cách 1: VS Code với PlantUML Extension (Recommended)

1. Cài đặt extensions:
   - **PlantUML** by jebbs
   - **Graphviz (dot) language support** (nếu cần)

2. Cài đặt Java (yêu cầu bởi PlantUML):
   ```bash
   # Windows
   winget install Oracle.JDK.17

   # Linux
   sudo apt install default-jdk

   # macOS
   brew install openjdk@17
   ```

3. Mở file `.puml` trong VS Code

4. Preview:
   - **Alt + D** (Windows/Linux)
   - **Option + D** (macOS)
   - Hoặc click icon "Preview" ở góc phải trên

5. Export to PNG/SVG:
   - Right-click trong editor → "Export Current Diagram"
   - Chọn format (PNG, SVG, PDF, etc.)

### Cách 2: Online PlantUML Editor

1. Truy cập: https://www.plantuml.com/plantuml/uml/

2. Copy toàn bộ nội dung file `.puml`

3. Paste vào editor

4. Click "Submit" để xem sơ đồ

5. Download PNG/SVG từ link phía dưới

### Cách 3: Command Line (plantuml.jar)

1. Download PlantUML:
   ```bash
   wget https://sourceforge.net/projects/plantuml/files/plantuml.jar/download -O plantuml.jar
   ```

2. Generate PNG:
   ```bash
   java -jar plantuml.jar *.puml
   ```

3. Generate SVG:
   ```bash
   java -jar plantuml.jar -tsvg *.puml
   ```

## Cấu trúc Thư mục

```
docs/diagrams/
├── README.md                              # File này
├── 01_database_erd.puml                   # ERD database
├── 02_sequence_transcribe_workflow.puml   # Sequence diagram - Transcribe
├── 03_sequence_summarize_workflow.puml    # Sequence diagram - Summarize
├── 04_component_diagram.puml              # Component diagram
├── 05_deployment_diagram.puml             # Deployment diagram
├── 06_class_diagram_models.puml           # Class diagram - Models
└── generated/                             # (Auto-generated PNG/SVG)
    ├── 01_database_erd.png
    ├── 02_sequence_transcribe_workflow.png
    ├── ...
```

## Quy ước Ký hiệu

### Database ERD
- **PK**: Primary Key (Khóa chính)
- **FK**: Foreign Key (Khóa ngoại)
- **UK**: Unique Key (Khóa duy nhất)
- `1` -- `*`: One-to-Many relationship
- `1` -- `0..1`: One-to-Zero-or-One relationship
- `*` -- `*`: Many-to-Many relationship

### Sequence Diagram
- `->`: Synchronous call (Gọi đồng bộ)
- `-->`: Return (Trả về)
- `..>`: Asynchronous message (Gọi bất đồng bộ)
- `activate/deactivate`: Lifeline activation
- `alt/else/end`: Alternative flows
- `loop/end`: Loops

### Component Diagram
- Rectangle: Component
- Folder: Package
- Database: Database
- `-->`: Dependency
- `..>`: Uses

### Deployment Diagram
- Node: Physical server/device
- Component: Software component
- Artifact: File/executable
- `..>`: Protocol connection

## Tips

### Customize Theme

Thêm vào đầu file `.puml`:

```plantuml
!theme cerulean-outline
' or
!theme blueprint
' or
!theme vibrant
```

### Scale Diagram

```plantuml
scale 1.5
' or
scale 2000 width
' or
scale 1500 height
```

### Change Direction

```plantuml
' Sequence diagram
left to right direction

' Class diagram
top to bottom direction
```

## Tài liệu Tham khảo

- **PlantUML Homepage**: https://plantuml.com/
- **PlantUML Guide**: https://plantuml.com/guide
- **Sequence Diagram**: https://plantuml.com/sequence-diagram
- **Class Diagram**: https://plantuml.com/class-diagram
- **Component Diagram**: https://plantuml.com/component-diagram
- **Deployment Diagram**: https://plantuml.com/deployment-diagram

## Liên hệ

Nếu có thắc mắc về các sơ đồ, vui lòng liên hệ Ban Dự án SpeechToInformation.

---

*Cập nhật: 24/12/2025*
