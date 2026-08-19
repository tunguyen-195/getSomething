# Cherry2 Developer Guide

> **Mục đích:** Hướng dẫn naming conventions và common pitfalls cho các phiên làm việc tiếp theo.

---

## 🔤 Naming Conventions

### Task Result Fields

| Canonical Name | Aliases (Legacy) | Vị trí trong Task | Mô tả |
|----------------|-----------------|-------------------|-------|
| `transcription` | `transcript`, `text` | `task.result.transcription` | Full transcript text |
| `diarization` | `speaker_segments` | `task.result.diarization` | Speaker-separated segments |
| `summary` | `forensic_summary` | `task.result.summary` | Text summary from LLM |
| `visualization_data` | `viz_data`, `visualization` | `task.result.visualization_data` | Visualization JSON |

> ⚠️ **CRITICAL:** Khi đọc task result, luôn check cả canonical name và aliases:
>
> ```python
> transcript = result.get('transcription') or result.get('transcript') or result.get('text')
> ```

### AudioFile Status Values

| Status | Meaning |
|--------|---------|
| `pending` | File mới upload, chưa xử lý |
| `processing` | Đang transcribe |
| `transcribed` | ✅ Hoàn thành transcribe |
| `summarizing` | Đang generate summary |
| `summarized` | ✅ Hoàn thành summary |
| `visualizing` | Đang generate visualization |
| `visualized` | ✅ Hoàn thành visualization |
| `failed` | ❌ Có lỗi |

### API Response Fields

| Field | Type | Note |
|-------|------|------|
| `task_id` | string | UUID của task |
| `status` | string | Một trong các status ở trên |
| `result` | object/string | ⚠️ Có thể là JSON string hoặc dict! |
| `error` | string | Error message nếu failed |

---

## ⚠️ Common Pitfalls

### 1. Task Result có thể là String hoặc Dict

```python
# ❌ WRONG - sẽ crash nếu result là string
transcript = task['result']['transcription']

# ✅ CORRECT - handle cả hai trường hợp
result = task.get('result', {})
if isinstance(result, str):
    import json
    try:
        result = json.loads(result)
    except:
        result = {}
transcript = result.get('transcription')
```

### 2. Transcript có nhiều tên khác nhau

```python
# ✅ CORRECT - check tất cả aliases
transcript = (
    result.get('transcription') or 
    result.get('transcript') or 
    result.get('text')
)
```

### 3. Frontend vs Backend Status Mismatch

Frontend hiển thị "Transcribed" dựa trên `audioFile.status`, nhưng backend có thể không có `result.transcription` nếu:

- Task đã được transcribe bởi version cũ
- Data migration chưa hoàn thành

```python
# ✅ CORRECT - luôn validate trước khi xử lý
if not transcript:
    raise HTTPException(400, "Task must be transcribed first")
```

### 4. Celery Task Storage vs AudioFile

| Storage | Data |
|---------|------|
| `celery_taskmeta` | `task_id`, `result` (JSON string), `status` |
| `audio_files` | `id`, `task_id` (FK), `status`, `filename` |

⚠️ `celery_taskmeta.result` là **JSON string**, cần `json.loads()` trước khi dùng.

---

## 📁 Key Files Reference

### Backend

| File | Purpose |
|------|---------|
| `src/api/endpoints/audio.py` | REST API endpoints |
| `src/services/visualization_service.py` | Visualization generation |
| `src/services/summarization/summary_service_v2.py` | LLM summarization |
| `src/services/transcription/cherry_transcription_service.py` | ASR transcription |
| `src/task_manager.py` | Celery task storage (get_task, save_result) |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/App.tsx` | Main app, API calls |
| `frontend/src/components/FileCard.tsx` | File display với actions |
| `frontend/src/components/VisualizationPanel.tsx` | Visualization display |

---

## 🔧 Debugging Tips

### Check Task Data

```bash
# Trong Python/IPython
from src.task_manager import get_task
import json

task = get_task("your-task-id")
result = json.loads(task['result']) if isinstance(task['result'], str) else task['result']
print(result.keys())
```

### Check AudioFile Status

```sql
SELECT id, filename, status, task_id FROM audio_files WHERE task_id = 'your-task-id';
```

---

## 📝 Changelog

| Date | Change |
|------|--------|
| 2026-01-17 | Created guide with naming conventions and common pitfalls |
