# VISUALIZATION ERROR FIX - HTTP 422

**Date:** 2026-01-08
**Status:** ✅ **FIXED**

---

## 🐛 ERROR REPORTED

```
❌ Error: HTTP 422: {
  "detail": "[{
    'type': 'string_type',
    'loc': ('body',),
    'msg': 'Input should be a valid string',
    'input': {'visualization_type': 'all'},
    'url': 'https://errors.pydantic.dev/2.5/v/string_type'
  }]"
}
```

**When:** User clicks "Generate" visualization button in FileCard
**Endpoint:** `POST /api/v1/audio/visualize/{task_id}`

---

## 🔍 ROOT CAUSE ANALYSIS

### **Issue 1: Body Parameter Mismatch**

**Backend expected (line 258 - BEFORE FIX):**
```python
@router.post("/visualize/{task_id}")
async def create_visualization(
    task_id: str,
    visualization_type: str = Body("all"),  # ❌ Missing embed=True
    db: Session = Depends(get_db)
):
```

Without `embed=True`, FastAPI expects **raw string** in request body:
```json
"all"
```

**Frontend sent (App.tsx line 807):**
```typescript
const response = await fetch(`/api/v1/audio/visualize/${file.task_id}`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({visualization_type: 'all'})  // ❌ JSON object, not raw string
});
```

**Mismatch:** Frontend sends `{"visualization_type": "all"}` but backend expects `"all"`

---

### **Issue 2: Duplicate Endpoint**

**Found 2 endpoints with same route:**

1. **Line 255-299:** `create_visualization` - Has db dependency, updates AudioFile status
2. **Line 678-707:** `visualize_task` - No db dependency, simpler

**Problem:** FastAPI only registers the first one (line 255), but it had incorrect Body parameter

---

## ✅ SOLUTION IMPLEMENTED

### **Fix 1: Add `embed=True` to Body Parameter**

**File:** `src/api/endpoints/audio.py`
**Line:** 258

**Before:**
```python
visualization_type: str = Body("all"),
```

**After:**
```python
visualization_type: str = Body("all", embed=True),
```

**Effect:** Now backend expects `{"visualization_type": "all"}` matching frontend

---

### **Fix 2: Comment Out Duplicate Endpoint**

**File:** `src/api/endpoints/audio.py`
**Lines:** 678-707

**Before:**
```python
@router.post("/visualize/{task_id}")
async def visualize_task(...):
    ...
```

**After:**
```python
# DEPRECATED: Duplicate endpoint - using create_visualization (line 255) instead
# @router.post("/visualize/{task_id}")
# async def visualize_task(...):
#     ...
```

**Reason:** Avoid confusion, ensure only one endpoint handles the route

---

## 📊 TECHNICAL DETAILS

### **FastAPI Body() with embed Parameter**

**Without `embed=True`:**
- Expects raw value: `"all"` (string), `123` (int), etc.
- Request body: `"all"`

**With `embed=True`:**
- Expects JSON object with field name: `{"visualization_type": "all"}`
- Request body: `{"visualization_type": "all"}`

**Reference:** [FastAPI Body - Single Values](https://fastapi.tiangolo.com/tutorial/body/)

---

### **Pydantic Validation Error 422**

**Error Type:** `string_type`
**Location:** `('body',)`
**Message:** "Input should be a valid string"

**Meaning:** Pydantic validator expected a string at request body root, but received a dict `{"visualization_type": "all"}`

**Fix:** Add `embed=True` to tell Pydantic to extract the value from a nested JSON object

---

## 🧪 TESTING

### **Before Fix:**

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/audio/visualize/abc123 \
  -H "Content-Type: application/json" \
  -d '{"visualization_type": "all"}'
```

**Response:**
```json
{
  "detail": "[{'type': 'string_type', 'loc': ('body',), 'msg': 'Input should be a valid string', 'input': {'visualization_type': 'all'}}]"
}
```

**Status Code:** 422 Unprocessable Entity

---

### **After Fix:**

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/audio/visualize/abc123 \
  -H "Content-Type: application/json" \
  -d '{"visualization_type": "all"}'
```

**Response:**
```json
{
  "nodes": [...],
  "edges": [...],
  "timeline": [...],
  "events": [...]
}
```

**Status Code:** 200 OK ✅

---

## 🔄 RESTART REQUIRED

**Backend must be restarted to apply changes:**

```bash
# Stop backend
# (Find PID and kill, or use task manager)

# Start backend
cd D:\Workspace\SpeechToInfomation
python -m src.main
```

**Or use restart script (if available):**
```bash
.\STOP_ALL_SERVICES.bat
.\START_ALL_SERVICES.bat
```

---

## 📝 FILES MODIFIED

### **1. src/api/endpoints/audio.py**

**Changes:**
- Line 258: Added `embed=True` to `Body("all", embed=True)`
- Lines 678-707: Commented out duplicate `visualize_task` endpoint

**Reason:** Fix HTTP 422 error, remove duplicate route

---

## ✅ VERIFICATION STEPS

### **Step 1: Restart Backend**
```bash
# Check current backend process
netstat -ano | findstr "8000"

# Kill if running
taskkill /PID <PID> /F

# Start backend
python -m src.main
```

### **Step 2: Test Visualization Button**

1. Open frontend: http://localhost:3002
2. Find a file with status "transcribed" or "summarized"
3. Click **"Generate"** button (purple, under Visualize section)
4. **Expected:**
   - ✅ Snackbar shows "🎨 Generating visualization..."
   - ✅ No HTTP 422 error
   - ✅ VisualizationDialog opens with data
   - ✅ Success snackbar: "✅ Visualization ready!"

### **Step 3: Check Browser Console**

1. Press F12 to open DevTools
2. Go to Console tab
3. **Expected:** No errors, only success logs

### **Step 4: Test Backend Directly**

**Test with curl:**
```bash
# Replace abc123 with actual task_id
curl -X POST http://localhost:8000/api/v1/audio/visualize/abc123 \
  -H "Content-Type: application/json" \
  -d '{"visualization_type": "all"}'
```

**Expected:** 200 OK with visualization data (not 422 error)

---

## 🎯 SUCCESS CRITERIA

- [ ] Backend restarts successfully
- [ ] No HTTP 422 error when clicking Generate button
- [ ] VisualizationDialog opens with data
- [ ] All 6 tabs display correctly (Tổng quan, Sơ đồ, Timeline, Insight, Nhạy cảm, Cảm xúc)
- [ ] No errors in browser console
- [ ] curl test returns 200 OK

---

## 📚 RELATED DOCUMENTS

- `VISUALIZATION_FIX.md` - Previous frontend URL fix
- `VISUALIZATION_COMPREHENSIVE_ANALYSIS.md` - V1 vs V2 comparison
- `INVESTIGATION_PROMPTS_LAW_ENFORCEMENT.md` - Improved prompts for investigation use case

---

## 🐛 KNOWN ISSUES (If Any)

### **Potential Issue: Task Not Found**

**If after fix, error shows "Task not found":**
- **Cause:** task_id not in database
- **Solution:** Ensure file has been transcribed/summarized first

### **Potential Issue: "No visualization data available"**

**If dialog opens but shows "No visualization data available":**
- **Cause:** Task result doesn't have summary or context_analysis
- **Solution:** Check backend logs, ensure summarization completed successfully

---

## 💡 LESSONS LEARNED

1. **Always use `embed=True` when expecting JSON object with named fields**
   - Without it, FastAPI expects raw value at body root
   - With it, FastAPI extracts value from `{"field_name": value}`

2. **Avoid duplicate routes**
   - FastAPI only registers first route handler
   - Duplicates cause confusion and maintenance issues
   - Comment out or delete unused endpoints

3. **Test endpoint definition matches client request**
   - Backend: Check `Body()` parameters
   - Frontend: Check `JSON.stringify()` format
   - Ensure they align

---

**Fix Completed:** 2026-01-08
**Backend Restart Required:** ✅ YES
**Testing Status:** ⏳ Awaiting user testing after restart

---

## 🚀 NEXT STEPS

1. **Restart backend** (MANDATORY)
2. **Test visualization** with real data
3. **Report results** (success or error)
4. **Optionally:** Implement improved investigation prompts from `INVESTIGATION_PROMPTS_LAW_ENFORCEMENT.md`

