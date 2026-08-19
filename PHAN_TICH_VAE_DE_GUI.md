# PHÂN TÍCH VẤN ĐỀ GUI - V1/V2 TRÙNG LẶP VÀ TÍNH NĂNG BROKEN

**Ngày:** 2026-01-08
**Trạng thái:** 🔴 CRITICAL - Nhiều tính năng không hoạt động và confusing

---

## 📋 TÓM TẮT EXECUTIVE

Hệ thống GUI hiện tại có **8 vấn đề nghiêm trọng** liên quan đến:
1. V1 và V2 tabs trùng lặp, confusing workflow
2. Upload logic không nhất quán
3. API endpoints inconsistent
4. Data fetching redundant
5. Transcript panel integration broken
6. Summary display conflict
7. Visualization implementation khác nhau
8. Status management không đồng bộ

**Kết quả:** User experience rất tệ, nhiều tính năng không hoạt động đúng.

---

## 🔍 PHÂN TÍCH CHI TIẾT CÁC VẤN ĐỀ

### ❌ VẤN ĐỀ 1: V1/V2 TABS TRÙNG LẶP VÀ CONFUSING

#### **Hiện trạng (App.tsx:624-630):**
```typescript
<Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
  <Tab label="Files (V1)" />  // Tab 0
  <Tab label="Files (V2)" />  // Tab 1
  <Tab label="Transcript" />
  <Tab label="Summary" />
  <Tab label="History" />
</Tabs>
```

#### **Tab 0 - Files (V1):**
- Component: `<FileTable>`
- Features:
  - ✅ Upload button
  - ✅ Download
  - ✅ Play audio
  - ✅ Visualize
  - ✅ "Xử lý" button → calls `/api/v1/audio/process-task/{task_id}`
- Display: Table format
- API: Legacy endpoints

#### **Tab 1 - Files (V2):**
- Component: `<FileCard>`
- Features:
  - ❌ NO upload button
  - ✅ Transcribe button (with dialog)
  - ✅ Summarize button (with dialog)
  - ✅ Visualize button
  - ✅ Inline transcript/summary display
  - ✅ Copy/expand functionality
- Display: Card format
- API: V2 modular endpoints

#### **Vấn đề CRITICAL:**
```typescript
// App.tsx:636-638
<Typography color="text.secondary">
  No files yet. Upload files via Files (V1) tab first,
  then they will appear here for modular processing.
</Typography>
```

**User phải:**
1. Switch to Tab 0 (V1)
2. Upload file
3. Switch to Tab 1 (V2)
4. Mới thấy files và có thể process

**❌ Confusing workflow!** User không hiểu tại sao phải switch tabs để upload.

---

### ❌ VẤN ĐỀ 2: UPLOAD LOGIC KHÔNG NHẤT QUÁN

#### **FileTable.tsx (V1) - Có Upload:**
```typescript
// FileTable.tsx:177-184
<Button variant="outlined" component="label" startIcon={<UploadFileIcon />}>
  Upload
  <input type="file" hidden onChange={handleUpload} accept="audio/*" multiple />
</Button>
```

Upload flow:
1. User select files
2. `handleUpload()` → POST `/api/v1/audio/upload`
3. Auto refresh files list

#### **FileCard.tsx (V2) - KHÔNG có Upload:**
- Không có upload button
- Chỉ có action buttons: Transcribe, Summarize, Visualize
- Phụ thuộc vào V1 để upload files

#### **App.tsx - Upload chỉ qua V1:**
```typescript
// App.tsx:103-133 - fetchFiles()
const res = await fetch(`/api/v1/audio?case_id=${selectedCase.id}`);
```

**Vấn đề:**
- V2 tab không có cách nào upload files
- Phải switch về V1 để upload → BAD UX
- Không có upload progress indicator ở V2

---

### ❌ VẤN ĐỀ 3: API ENDPOINTS INCONSISTENT

#### **V1 Endpoints (FileTable.tsx):**
```
GET  /api/v1/cases/{caseId}/files           // Load files
POST /api/v1/audio/upload                   // Upload
POST /api/v1/audio/process-task/{task_id}   // Process (transcribe + summarize together)
GET  /api/v1/audio/tasks/{task_id}          // Poll status
GET  /api/v1/audio/public/{filename}        // Stream audio
```

#### **V2 Endpoints (App.tsx + FileCard.tsx):**
```
GET  /api/v1/audio?case_id={case_id}                    // Load files
POST /api/v1/audio/v2/transcribe/{task_id}              // Transcribe only
POST /api/v1/audio/v2/summarize/{task_id}               // Summarize only
GET  /api/v1/audio/v2/tasks/{task_id}/status            // Poll status
POST /api/v1/audio/visualize/{task_id}                  // Visualize
```

#### **Conflict:**
| Feature | V1 Endpoint | V2 Endpoint | Status |
|---------|-------------|-------------|--------|
| Load files | `/api/v1/cases/{caseId}/files` | `/api/v1/audio?case_id={case_id}` | ⚠️ Different |
| Process | `/api/v1/audio/process-task` (all-in-one) | `/api/v1/audio/v2/transcribe` + `/v2/summarize` (modular) | ⚠️ Different |
| Status | `/api/v1/audio/tasks/{task_id}` | `/api/v1/audio/v2/tasks/{task_id}/status` | ⚠️ Different |
| Upload | Via FileTable | ❌ No endpoint in V2 UI | ❌ Missing |

**Vấn đề:**
- 2 endpoints load files khác nhau → có thể return data format khác nhau
- V1 "Xử lý" button có thể conflict với V2 modular approach
- Status polling từ 2 sources khác nhau → inconsistent

---

### ❌ VẤN ĐỀ 4: DATA FETCHING REDUNDANT

#### **App.tsx - fetchFiles():**
```typescript
// App.tsx:104-129
const fetchFiles = async () => {
  const res = await fetch(`/api/v1/audio?case_id=${selectedCase.id}`);
  const data = await res.json();
  const mappedFiles = data.map((f: any) => ({
    task_id: f.task_id || f.id,
    filename: f.filename,
    status: f.status || 'uploaded',
    transcript: f.transcript,
    summary: f.summary,
    // ... more fields
  }));
  setFiles(mappedFiles);
};
```

#### **FileTable.tsx - reloadFiles():**
```typescript
// FileTable.tsx:50-66
const reloadFiles = () => {
  fetch(`${API_BASE_URL}/api/v1/cases/${caseId}/files`)
    .then(res => res.json())
    .then(data => setFiles(data));
};
```

**Vấn đề:**
- 2 components fetch từ 2 endpoints khác nhau
- `files` state trong App.tsx khác `files` state trong FileTable.tsx
- Khi upload ở V1, V2 không auto refresh → phải manual reload
- Redundant API calls

---

### ❌ VẤN ĐỀ 5: TRANSCRIPT PANEL INTEGRATION BROKEN

#### **TranscriptPanel.tsx:**
```typescript
// TranscriptPanel.tsx:25
fetch(`${API_BASE_URL}/api/v1/audio/files/${fileId}/transcript`)
```

Expects `fileId` as prop.

#### **App.tsx - Tab 2 (Transcript):**
```typescript
// App.tsx:688-706
{tab === 2 && selectedFileId ? (
  <TranscriptPanel fileId={selectedFileId} />
) : tab === 2 ? (
  // Fallback: show selectedCase.transcripts (old format)
  <Box>
    {selectedCase.transcripts.map((t, idx) => (
      <Accordion key={idx}>
        <Typography>{t}</Typography>
      </Accordion>
    ))}
  </Box>
) : null}
```

#### **FileTable.tsx (V1) - Sets selectedFileId:**
```typescript
// FileTable.tsx:27-29
interface FileTableProps {
  onSelectFile?: (fileId: string) => void;  // ✅ Can set selectedFileId
}

// Used in App.tsx:631
<FileTable caseId={selectedCase.id} onSelectFile={setSelectedFileId} />
```

#### **FileCard.tsx (V2) - Does NOT set selectedFileId:**
```typescript
// FileCard.tsx:47
interface FileCardProps {
  onViewTranscript: () => void;  // ❌ Only switches tab, doesn't set fileId
}

// App.tsx:682
onViewTranscript={() => setTab(2)}  // ❌ Missing: setSelectedFileId(file.task_id)
```

**Vấn đề:**
- ✅ V1: Click file → sets `selectedFileId` → TranscriptPanel works
- ❌ V2: Click "View Transcript" → switches tab but NO `selectedFileId` → TranscriptPanel shows fallback (old format)
- V2 "View Transcript" button **KHÔNG HOẠT ĐỘNG ĐÚNG**

---

### ❌ VẤN ĐỀ 6: SUMMARY DISPLAY CONFLICT

#### **Old Format (selectedCase.summaries):**
```typescript
// App.tsx:707-718 - Tab 3
{selectedCase && selectedCase.summaries && selectedCase.summaries.length > 0 ? (
  <Box>
    {selectedCase.summaries.map((s, idx) => (
      <SummaryAccordionItem summary={s} idx={idx} />
    ))}
  </Box>
) : (
  <Typography>Chưa có tóm tắt nào</Typography>
)}
```

Data structure: `Case.summaries: string[]`

#### **New Format (file.summary):**
```typescript
// FileCard.tsx:539-618 - Inline display
{file.summary && (
  <Box mt={3}>
    <Typography variant="h6" fontWeight={700}>📊 Summary Result</Typography>
    <Collapse in={summaryExpanded}>
      <Box>{file.summary}</Box>
    </Collapse>
  </Box>
)}
```

Data structure: `File.summary: string`

**Vấn đề:**
- 2 format khác nhau: Case-level vs File-level
- Tab 3 (Summary) hiển thị old format
- FileCard hiển thị new format inline
- User không biết xem ở đâu
- **Trùng lặp và confusing!**

---

### ❌ VẤN ĐỀ 7: VISUALIZATION IMPLEMENTATION KHÁC NHAU

#### **FileTable.tsx (V1) - Dialog Modal:**
```typescript
// FileTable.tsx:150-171
const handleOpenVisualize = (file: FileInfo) => {
  setOpenFileId(file.id);
  fetch(`${API_BASE_URL}/api/v1/audio/tasks/${file.task_id}`)
    .then(data => setTaskData(data));
};

// FileTable.tsx:388-407 - Dialog
<Dialog open={!!openFileId}>
  <InvestigationSummaryCard
    summary={taskData.result?.summary}
    contextAnalysis={taskData.result?.context_analysis}
  />
</Dialog>
```

#### **FileCard.tsx (V2) - POST API Call:**
```typescript
// App.tsx:664-680
onVisualize={async () => {
  const response = await fetch(`/api/v1/audio/visualize/${file.task_id}`, {
    method: 'POST',
    body: JSON.stringify({visualization_type: 'all'})
  });
  setSnackbar({message: '✅ Visualization completed!'});
  await fetchFiles();
}}
```

**Vấn đề:**
- V1: Fetch existing data → show in dialog
- V2: Generate new visualization → refresh files
- 2 approaches hoàn toàn khác nhau
- V2 không có dialog để xem visualization data
- User không biết visualization ở đâu sau khi generate

---

### ❌ VẤN ĐỀ 8: STATUS MANAGEMENT KHÔNG ĐỒNG BỘ

#### **FileTable.tsx (V1) - Polling:**
```typescript
// FileTable.tsx:74-88
useEffect(() => {
  const interval = setInterval(() => {
    files.forEach(file => {
      if (file.task_id) {
        fetch(`/api/v1/audio/tasks/${file.task_id}`)  // Poll every 3s
          .then(data => setFiles(prev => prev.map(f => f.id === file.id ? {...f, status: data.status} : f)));
      }
    });
  }, 3000);
}, [files]);
```

#### **App.tsx (V2) - Polling:**
```typescript
// App.tsx:214-318
const startPolling = (taskId: string, initialStatus: string) => {
  const pollInterval = setInterval(async () => {
    const response = await fetch(`${API_V2_BASE}/tasks/${taskId}/status`);  // Poll every 2s
    const statusData = await response.json();
    setFiles(prev => prev.map(f => {
      if (f.task_id === taskId) {
        return { ...f, status: currentStatus, transcript: statusData.transcript, summary: statusData.summary };
      }
      return f;
    }));
  }, 2000);
};
```

**Vấn đề:**
- 2 polling mechanisms chạy độc lập
- V1: Poll all files every 3s from `/api/v1/audio/tasks/`
- V2: Poll specific task every 2s from `/api/v1/audio/v2/tasks/{id}/status`
- Conflict: Cùng update `files` state → có thể overwrite lẫn nhau
- Different intervals: 2s vs 3s → race conditions

---

## 📊 BẢNG TỔNG HỢP VẤN ĐỀ

| Feature | V1 (FileTable) | V2 (FileCard) | Status | Impact |
|---------|----------------|---------------|--------|--------|
| **Upload** | ✅ Có button | ❌ Không có | 🔴 Critical | User bắt buộc dùng V1 |
| **Transcribe** | ⚠️ Qua "Xử lý" (all-in-one) | ✅ Modular với dialog | 🟡 Confusing | 2 cách khác nhau |
| **Summarize** | ⚠️ Qua "Xử lý" (all-in-one) | ✅ Modular với dialog | 🟡 Confusing | 2 cách khác nhau |
| **View Transcript** | ✅ Sets selectedFileId | ❌ Broken | 🔴 Critical | V2 không hoạt động |
| **View Summary** | ⚠️ Tab 3 (old format) | ✅ Inline display | 🟡 Duplicate | 2 chỗ khác nhau |
| **Visualize** | ✅ Dialog modal | ❌ No UI after generate | 🔴 Critical | V2 không xem được |
| **Status Polling** | ✅ 3s interval | ✅ 2s interval | 🟡 Conflict | Race conditions |
| **Data Fetching** | `/api/v1/cases/{id}/files` | `/api/v1/audio?case_id={id}` | 🟡 Inconsistent | 2 endpoints khác nhau |

---

## 🎯 ĐÁNH GIÁ MỨC ĐỘ NGHIÊM TRỌNG

### 🔴 CRITICAL (Không hoạt động):
1. **V2 không có upload** → Phải dùng V1
2. **V2 "View Transcript" broken** → selectedFileId không được set
3. **V2 Visualization không có UI** → Generate xong không xem được

### 🟡 MAJOR (Confusing/Duplicate):
4. **2 tabs V1/V2 trùng lặp** → User không biết dùng cái nào
5. **Summary hiển thị 2 chỗ** → Tab 3 vs inline trong FileCard
6. **2 API endpoints load files** → Data inconsistent
7. **Status polling conflict** → Race conditions

### 🟢 MINOR (Có workaround):
8. **Process button V1 vs Modular V2** → User có thể dùng cả 2

---

## 💡 NGUYÊN NHÂN GỐC RẮC

### **Architecture Transition Incomplete:**
Hệ thống đang trong quá trình chuyển đổi từ **V1 (monolithic)** sang **V2 (modular)** nhưng:
- ❌ Chưa hoàn tất migration
- ❌ Vẫn giữ cả V1 và V2 chạy song song
- ❌ Không có plan rõ ràng để deprecate V1
- ❌ User experience không được ưu tiên

### **Code Structure Issues:**
- State management phân tán (App.tsx, FileTable.tsx)
- API endpoints không consistent
- Component coupling chặt
- Không có shared state management (Redux/Context)

---

## 📋 CHECKLIST TÍNH NĂNG BROKEN

### ❌ Broken Features:
- [ ] V2: Upload files (không có button)
- [ ] V2: View Transcript button (không set selectedFileId)
- [ ] V2: View Visualization after generate (không có UI)
- [ ] Tab 3: Summary display (old format, có thể empty)
- [ ] Data sync giữa V1 và V2 (phải manual refresh)

### ⚠️ Confusing Features:
- [ ] 2 tabs V1/V2 (user không biết dùng cái nào)
- [ ] Process workflow (V1: all-in-one, V2: modular)
- [ ] Summary locations (Tab 3 vs inline)
- [ ] Status updates (2 polling mechanisms)

### ✅ Working Features:
- [x] V1: Upload
- [x] V1: Process (transcribe + summarize)
- [x] V1: View transcript (via selectedFileId)
- [x] V1: Visualize (dialog)
- [x] V2: Transcribe (with dialog)
- [x] V2: Summarize (with dialog)
- [x] V2: Inline transcript/summary display
- [x] Dark mode toggle
- [x] Case management

---

## 🔄 DATA FLOW ANALYSIS

### **Current Flow (Broken):**
```
User action: Upload file
↓
V1 Tab (FileTable) → POST /api/v1/audio/upload
↓
FileTable.reloadFiles() → GET /api/v1/cases/{id}/files
↓
FileTable local state updates
↓
❌ App.tsx fetchFiles() NOT called → V2 doesn't know about new file
↓
User switches to V2 Tab
↓
❌ V2 shows "No files yet" until manual refresh
```

### **Expected Flow (Should be):**
```
User action: Upload file
↓
V2 Tab (Upload component) → POST /api/v1/audio/upload
↓
App.tsx fetchFiles() → GET /api/v1/audio?case_id={id}
↓
App.tsx files state updates
↓
✅ V2 FileCard automatically shows new file
↓
User clicks "Transcribe"
↓
TranscribeDialog opens → User selects options
↓
POST /api/v1/audio/v2/transcribe/{task_id}
↓
Polling starts → GET /api/v1/audio/v2/tasks/{task_id}/status
↓
✅ FileCard status updates in real-time
↓
✅ Transcript displayed inline when complete
```

---

## 📝 KẾT LUẬN

### **Trạng thái hiện tại:** 🔴 **CRITICAL**

Hệ thống GUI có nhiều vấn đề nghiêm trọng:
1. User workflow rất confusing (phải switch giữa V1 và V2)
2. Nhiều tính năng không hoạt động (View Transcript, Visualization trong V2)
3. Code architecture không consistent (2 state management systems)
4. Data sync issues (2 endpoints, 2 polling mechanisms)

### **Tác động:**
- ❌ Bad user experience
- ❌ Broken features
- ❌ Maintenance nightmare
- ❌ Không scale được

### **Cần làm ngay:**
1. Fix V2 "View Transcript" button (set selectedFileId)
2. Add upload button vào V2 tab
3. Add visualization UI cho V2
4. Hoặc: Remove V1 tab hoàn toàn, chỉ giữ V2

---

**Tài liệu này phân tích chi tiết tất cả vấn đề trong GUI hiện tại**
**Date:** 2026-01-08
**Next:** Tạo plan sửa lỗi và recommendations
