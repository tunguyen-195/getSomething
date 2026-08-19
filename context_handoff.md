# Context Handoff - SpeechToInformation System
>
> **Last Updated**: 2026-01-18 02:05
> **Status**: In Progress - Needs PostgreSQL start then final testing

---

## 🎯 Current Objective

**FIX**: Sorting (Case/File) + Summary display + Vietnamese LLM integration
**TEST**: Full E2E verification with Vietnamese audio file

---

## ✅ Changes Completed

### 1. Vietnamese LLM Integration (Llama.cpp)

**Files Modified:**

- `src/services/summarization/summary_service_v2.py` (lines 37-130)
  - Added support for `vistral` and `qwen3` model types
  - Uses `LlamaCppAdapter` for fast GPU inference
  - Fallback to Ollama if llama.cpp fails

- `frontend/src/components/SummarizeDialog.tsx` (lines 12-39)
  - Updated model dropdown:
    - 🇻🇳 Vistral 7B (Vietnamese, Llama.cpp - Fast) - **DEFAULT**
    - 🌏 Qwen3 8B (32K Context, Llama.cpp)
    - 🔍 Forensic Analysis (Vistral + Template)
    - Gemma 2 9B (Ollama Fallback)

**Models Location:** `E:\research\Cherry2\cherry_core\models\`

- `vistral/vistral-7b-chat-Q4_K_M.gguf` (4.4GB)
- `qwen3/Qwen_Qwen3-8B-Q4_K_M.gguf` (5GB)

### 2. Summary/Transcript Display Improvements

**File:** `frontend/src/components/TaskListItem.tsx` (lines 158-160, 217)

- Summary preview: maxHeight 60px → 120px, 5-line clamp
- Transcript: maxHeight 200px → 600px

### 3. Sorting Implementation

**Backend:** `src/api/endpoints/cases.py` (lines 14-34)

- Case-insensitive title sorting: `text("lower(title) ASC/DESC")`
- NULL handling: `nullslast()` for created_at
- Imports added: `func`, `text` from sqlalchemy

**Frontend:** `frontend/src/App.tsx`

- State: `caseSortBy`, `caseOrder`, `sortMenuAnchor` (lines 98-100)
- Sort Menu UI with 4 options (lines 544-588)
- useEffect triggers refetch on sort change (lines 122-124)

---

## 🧪 Browser Test Results (Verified)

| Feature | Status |
|---------|--------|
| Sorting (A-Z) | ✅ PASS |
| Sorting (Mới nhất) | ✅ PASS |
| Case Creation | ✅ PASS |
| Summarize Dialog | ✅ PASS (Vistral default) |

---

## ⚠️ Current Blocker

**PostgreSQL not running** - Backend fails to start.

**Fix:**

```powershell
# Run as Administrator:
net start postgresql-x64-16
# Or use services.msc to start PostgreSQL service
```

Then restart services:

```powershell
.\venv\Scripts\Activate.ps1
.\START_ALL_SERVICES.bat
```

---

## 📋 Remaining Tasks

1. [ ] Start PostgreSQL service
2. [ ] Restart backend
3. [ ] Run E2E test with Vietnamese audio:
   - File: `storage/audio/Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3`
   - Test: Upload → Transcribe → Summarize (Vistral) → Visualize
4. [ ] Verify sorting works in UI with multiple cases
5. [ ] Final walkthrough update

---

## 📁 Key Files to Review

| File | Purpose |
|------|---------|
| `src/services/summarization/summary_service_v2.py` | Main summary logic with LlamaCpp |
| `src/cherry_core/adapters/llm/llamacpp_adapter.py` | LlamaCpp model loading |
| `src/cherry_core/config.py` | Model paths, LLM settings |
| `src/api/endpoints/cases.py` | Sorting logic |
| `frontend/src/App.tsx` | Frontend state, sort menu |
| `frontend/src/components/SummarizeDialog.tsx` | Model selection UI |
| `frontend/src/components/TaskListItem.tsx` | Display limits |

---

## 🔧 Test Scripts

```bash
# E2E Full Test
python scripts/e2e_full_test.py

# Sorting Verification
python scripts/check_sorting.py

# System Verification
python scripts/verify_system_v2.py
```

---

## 📖 Artifacts Location

```
C:\Users\Admin\.gemini\antigravity\brain\6e79221c-e6cb-4288-b554-21699a572bf1\
├── task.md              # Task checklist
├── implementation_plan.md
├── walkthrough.md       # Detailed changes + browser test recording
```

---

## 🚀 Next Conversation Quick Start

```
1. Đọc file này (context_handoff.md)
2. Kiểm tra PostgreSQL đã chạy chưa
3. Chạy START_ALL_SERVICES.bat
4. Test E2E với file audio tiếng Việt
5. Xác minh Sort hoạt động trong UI
```
