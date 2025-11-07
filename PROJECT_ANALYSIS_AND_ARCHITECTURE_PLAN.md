# PHÂN TÍCH TOÀN DIỆN DỰ ÁN & KẾ HOẠCH TÁI CẤU TRÚC

Ngày: 2025-11-07
Branch: feature/asr-improvement
Mục tiêu: Module hóa kiến trúc, tách biệt workflows, tối ưu performance

## 1. TÌNH TRẠNG HIỆN TẠI

### Backend Structure:
- audio_service.py: 1307 lines - TOO BIG
- transcribe_service.py: Riêng biệt ✓
- visualization_service.py: Riêng biệt ✓
- worker/tasks.py: Chỉ 1 task async

### Frontend Structure:
- App.tsx: 531 lines - Chưa tích hợp components mới
- FileCard.tsx, TranscribeDialog.tsx, SummarizeDialog.tsx: Mới, chưa dùng

### Workflow Hiện Tại KHÔNG TÁCH BIỆT:
Upload → process_task_with_diarization() → Load + Enhance + Diarize + Transcribe + Analyze + Summarize

VẤN ĐỀ:
- Tất cả trong 1 hàm → KHÔNG linh hoạt
- LLM luôn chạy → lãng phí thời gian
- User không chọn được từng bước

## 2. VẤN ĐỀ NGHIÊM TRỌNG

### Architecture:
- Monolithic Service (audio_service.py 1307 lines)
- Tight Coupling (Transcribe + Summarize gộp chung)
- Performance Bottleneck (Load tất cả models)

### Frontend:
- Components chưa integrate
- Không có status polling
- Không có workflow separation

### Performance:
- LLM Always Called (+30-60s)
- Models Loaded Together
- Pyannote Not Portable (.cache)
- Transcript Content Wrong (VAD filter)

## 3. ĐÃ LÀM TỐT

✓ Backend Endpoints Mới: /transcribe/{task_id}, /summarize-task/{task_id}, /visualize/{task_id}
✓ Services Mới: transcribe_service.py, visualization_service.py
✓ Frontend Components: FileCard, Dialogs
✓ Tech Stack: FastAPI, Celery, React+TS, Whisper v3-turbo, Pyannote 3.1

## 4. KIẾN TRÚC MỤC TIÊU

### Nguyên Tắc:
1. Separation of Concerns
2. Single Responsibility
3. Loose Coupling
4. Lazy Loading
5. Progressive Enhancement

### Module Structure:
services/
├── audio/ (upload, storage)
├── transcription/ (transcribe, diarization, models/)
├── summarization/ (summary, context, models/)
├── visualization/ (entity, graph, timeline)
└── task/ (CRUD, status)

## 5. KẾ HOẠCH THỰC HIỆN

### Phase 1: Refactor Backend (3-4h)
- Tách Audio Service
- Module hóa Transcription (Whisper/Pyannote managers)
- Module hóa Summarization (LLM manager)
- Celery Tasks riêng biệt

### Phase 2: Update API (1h)
- Cleanup endpoints
- Status management

### Phase 3: Frontend Integration (2-3h)
- Update App.tsx
- Complete VisualizationPanel
- Error handling

### Phase 4: Testing (2-3h)
- Unit tests
- Integration tests
- Performance testing

### Phase 5: Documentation (1h)

## 6. KẾT QUẢ MONG ĐỢI

Performance:
- Transcribe only: 60s → 20s (3x faster)
- Transcribe + Diarize: 90s → 35s (2.5x faster)
- Memory: 8GB → 4GB (50% less)

Benefits:
✅ Modularity
✅ Flexibility
✅ Scalability
✅ Testability
✅ Portability

## 7. CHECKLIST

Must Have (P0):
- [ ] Module hóa services
- [ ] Separate Celery tasks
- [ ] Fix Pyannote local loading
- [ ] Fix transcript content
- [ ] Frontend integration
- [ ] Status polling

## 8. NEXT ACTIONS

1. ✅ Đọc và confirm plan
2. Phase 1 - Refactor Backend
3. Branch: feature/architecture-refactor
4. Commit từng phase
5. Merge khi stable

Thời gian: 10-12h (2-3 ngày)
Priority: Backend → API → Frontend → Testing
