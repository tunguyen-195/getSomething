# HƯỚNG DẪN TESTING CHI TIẾT

**Date:** 2026-01-08
**Frontend URL:** http://localhost:3002
**Backend URL:** http://localhost:8000
**Status:** ✅ Tất cả services đang running

---

## 📋 CHUẨN BỊ

### **Services Đang Chạy:**
- ✅ Backend (FastAPI): http://localhost:8000
- ✅ Redis: Port 6379
- ✅ Frontend (Vite): http://localhost:3002

### **Trước Khi Test:**
1. Mở browser (Chrome/Firefox recommended)
2. Truy cập: http://localhost:3002
3. Mở Developer Console (F12)
4. Chuẩn bị 2-3 audio files để test upload

---

## 🧪 PHASE 1: FUNCTIONAL TESTING

### **1.1. CASE MANAGEMENT**

#### **Test 1.1.1: Create Case**

**Steps:**
1. Click button "Tạo Case" (màu xanh) ở sidebar
2. Nhập tên case: "Test Case 001"
3. Nhập mô tả: "Case for functional testing"
4. Click "Tạo"

**Expected:**
- ✅ Dialog đóng
- ✅ Snackbar hiện: "✅ Case 'Test Case 001' đã được tạo thành công!"
- ✅ Case mới xuất hiện đầu danh sách sidebar
- ✅ Case mới được auto-selected (highlighted)
- ✅ Main panel hiển thị "Case: Test Case 001"

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.1.2: Create Case - Empty Title Validation**

**Steps:**
1. Click "Tạo Case"
2. Để trống tên case
3. Nhập mô tả bất kỳ
4. Click "Tạo"

**Expected:**
- ✅ Snackbar hiện: "⚠️ Vui lòng nhập tên case"
- ✅ Dialog không đóng
- ✅ No case created

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.1.3: Delete Case**

**Precondition:** Có ít nhất 2 cases trong list

**Steps:**
1. Hover chuột lên case bất kỳ
2. Delete icon (màu đỏ) xuất hiện bên phải
3. Click delete icon
4. Confirmation dialog hiện: "Bạn có chắc muốn xóa case..."
5. Click "OK"

**Expected:**
- ✅ Dialog confirmation hiện đúng tên case
- ✅ Sau khi click OK:
  - Case biến mất khỏi list
  - Snackbar: "✅ Case '{tên}' đã được xóa"
  - Case khác được auto-selected

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.1.4: Delete Case - Cancel**

**Steps:**
1. Hover và click delete trên case
2. Click "Cancel" trong confirmation dialog

**Expected:**
- ✅ Dialog đóng
- ✅ Case KHÔNG bị xóa
- ✅ No changes

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.1.5: Case Selection**

**Steps:**
1. Click vào case khác trong sidebar
2. Observe UI changes

**Expected:**
- ✅ Case được selected (highlighted với border vàng #ffd600)
- ✅ Main panel cập nhật title: "Case: {tên case}"
- ✅ Files tab cập nhật nội dung cho case mới

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.1.6: Case Search**

**Steps:**
1. Click search icon (🔍) ở sidebar
2. Search box expand
3. Nhập từ khóa tìm kiếm (e.g., "Test")
4. Observe case list filtering

**Expected:**
- ✅ Search box expand với animation smooth
- ✅ Case list filter real-time khi gõ
- ✅ Chỉ cases match keyword hiển thị
- ✅ Click clear (X) → reset filter

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **1.2. FILE UPLOAD**

#### **Test 1.2.1: Upload - No Case Selected**

**Steps:**
1. Refresh page (hoặc no case selected state)
2. Try upload file

**Expected:**
- ✅ Upload area disabled
- ✅ Message: "Vui lòng chọn vụ việc trước khi..."

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.2.2: Upload - Drag and Drop**

**Precondition:** Case selected

**Steps:**
1. Drag audio file vào upload area
2. File appears in file list
3. Click "Xử lý File"
4. Observe progress

**Expected:**
- ✅ Drag-over state shows (border color changes)
- ✅ File appears with name + size
- ✅ Upload progress shown (0-100%)
- ✅ Success snackbar: "✅ Upload successful!"
- ✅ File appears trong Files tab với status "uploaded"

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.2.3: Upload - Click Browse**

**Steps:**
1. Click "Chọn file âm thanh" button
2. File dialog opens
3. Select audio file
4. Process upload

**Expected:**
- ✅ Same results as drag-drop test
- ✅ File uploads successfully

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.2.4: Upload - Multiple Files**

**Steps:**
1. Add 3 audio files (drag or browse)
2. All 3 appear in list
3. Remove 1 file (click delete icon)
4. Upload remaining 2 files

**Expected:**
- ✅ All 3 files show in list
- ✅ Delete icon removes file from list
- ✅ Both remaining files upload successfully
- ✅ Progress updates for each file

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.2.5: Upload Options**

**Steps:**
1. Select diarization method: "WhisperX (Pyannote)"
2. Select transcription mode: "⚡ Fast Mode"
3. Upload 1 file
4. Check if options were applied (check in file card later)

**Expected:**
- ✅ Options dropdowns work
- ✅ Selections persist during session
- ✅ Options apply to upload

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **1.3. FILE CARD & PROCESSING**

#### **Test 1.3.1: File Card Display**

**Precondition:** 1 file uploaded

**Steps:**
1. Observe file card in Files tab

**Expected:**
- ✅ Filename displayed
- ✅ Status badge: "uploaded" (yellow/gray)
- ✅ Buttons visible:
  - "Start Transcribe" (enabled)
  - "Start Summary" (disabled - grayed out)
  - Other actions

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.3.2: Transcribe Process**

**Steps:**
1. Click "Start Transcribe" on uploaded file
2. TranscribeDialog opens
3. Configure options:
   - ☑ Enable diarization
   - Select: WhisperX
   - ☐ Fast mode (unchecked for better quality)
4. Click "Start Transcribe"
5. Observe status updates

**Expected:**
- ✅ Dialog opens with filename
- ✅ Options configurable
- ✅ Click "Start Transcribe":
  - Dialog closes
  - Status badge → "transcribing" (blue)
  - Info snackbar: "🎙️ Transcription started!"
  - Progress indicator/spinner shown
- ✅ Auto-polling every 2 seconds
- ✅ When complete:
  - Status → "transcribed" (green)
  - Success snackbar: "✅ Transcription completed!"
  - Transcript appears inline (collapsed)

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________
**Time taken:** _____ seconds

---

#### **Test 1.3.3: View Inline Transcript**

**Precondition:** File transcribed

**Steps:**
1. Find "Transcript" collapsible section trong file card
2. Click to expand
3. Observe transcript content
4. Click copy icon
5. Paste vào notepad

**Expected:**
- ✅ Transcript section visible
- ✅ Click expand → full transcript shown
- ✅ Diarization labels shown (if enabled): [Speaker 1], [Speaker 2]
- ✅ Copy button works
- ✅ Paste shows full transcript text

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.3.4: View Transcript Tab**

**Steps:**
1. Click "View Transcript" button trong file card
2. Tab switches to "Transcript"
3. Full transcript panel shown

**Expected:**
- ✅ Tab switches automatically (Tab 0 → Tab 1)
- ✅ Full transcript displayed in TranscriptPanel
- ✅ Better formatting than inline view
- ✅ Scrollable if long

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.3.5: Summarize Process**

**Precondition:** File transcribed

**Steps:**
1. Click "Start Summary" button
2. SummarizeDialog opens
3. Configure:
   - Model: "gemma2:9b"
   - Summary type: "detailed"
   - ☑ Include context analysis
4. Click "Start Summary"
5. Observe status updates

**Expected:**
- ✅ Dialog opens
- ✅ Options work
- ✅ Click "Start Summary":
  - Dialog closes
  - Status → "summarizing" (purple)
  - Info snackbar: "📊 Summarization started!"
- ✅ Polling updates status
- ✅ When complete:
  - Status → "summarized" (green)
  - Success snackbar: "✅ Summarization completed!"
  - Summary appears inline (collapsed)

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________
**Time taken:** _____ seconds

---

#### **Test 1.3.6: View Inline Summary**

**Precondition:** File summarized

**Steps:**
1. Expand "Summary" section trong file card
2. Read summary content
3. Click copy
4. Paste to verify

**Expected:**
- ✅ Summary section visible
- ✅ Content formatted nicely
- ✅ Key points highlighted
- ✅ Copy works

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.3.7: Generate Visualization**

**Precondition:** File summarized

**Steps:**
1. Click "Generate Visualization" button
2. Wait for processing
3. VisualizationDialog opens
4. Explore tabs:
   - Tổng quan
   - Sơ đồ quan hệ
   - Timeline
   - Insight
   - Nhạy cảm
   - Cảm xúc

**Expected:**
- ✅ Info snackbar: "🎨 Generating visualization..."
- ✅ Processing occurs (may take time)
- ✅ Dialog opens with purple theme (#9c27b0)
- ✅ InvestigationSummaryCard shown
- ✅ All tabs functional
- ✅ Data displayed correctly
- ✅ Success snackbar: "✅ Visualization ready!"

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.3.8: Real-time Status Polling**

**Steps:**
1. Start transcribe on a file
2. Open browser DevTools → Network tab
3. Observe API calls

**Expected:**
- ✅ Polling requests every 2 seconds to `/api/v1/audio/v2/tasks/{id}/status`
- ✅ Status updates in real-time
- ✅ Polling stops when status = completed/failed
- ✅ No excessive polling (not faster than 2s)

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **1.4. TAB NAVIGATION**

#### **Test 1.4.1: Tab Structure**

**Steps:**
1. Count visible tabs
2. Click each tab
3. Verify content

**Expected:**
- ✅ Exactly 3 tabs visible:
  - Tab 0: "Files"
  - Tab 1: "Transcript"
  - Tab 2: "History"
- ✅ NO "V1" or "V2" labels
- ✅ NO duplicate "Summary" tab

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 1.4.2: Tab Switching**

**Steps:**
1. Start on Files tab
2. Click Transcript tab
3. Click History tab
4. Click Files tab again

**Expected:**
- ✅ Each click switches tab immediately
- ✅ Content updates correctly
- ✅ No lag or errors

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

## 🎨 PHASE 2: UI/UX TESTING

### **2.1. VISUAL CONSISTENCY**

#### **Test 2.1.1: Color Scheme**

**Check:**
- [ ] Primary green (#43a047) used for positive actions
- [ ] Secondary red (#d32f2f) used for delete + branding
- [ ] Accent yellow (#ffd600) used for highlights + Cherry2 logo
- [ ] Info blue (#1976d2) used for info messages
- [ ] Consistent throughout app

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.1.2: Typography**

**Check:**
- [ ] Headings clearly larger than body text
- [ ] Hierarchy clear (H5 > H6 > Body1 > Body2)
- [ ] Font: Poppins/Inter/Roboto
- [ ] Readable sizes (not too small)

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.1.3: Spacing**

**Check:**
- [ ] Cards have adequate padding
- [ ] Buttons have proper spacing between them
- [ ] Not cramped or too loose
- [ ] Consistent margins/gaps

**Observations:** _______________________

---

#### **Test 2.1.4: Shadows & Borders**

**Check:**
- [ ] Cards have subtle shadows
- [ ] Dialogs have prominent shadows
- [ ] Borders consistent (1-2px)
- [ ] Border radius consistent (8-16px)

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **2.2. USER FEEDBACK**

#### **Test 2.2.1: Loading States**

**Check during upload/transcribe/summarize:**
- [ ] Upload: Progress percentage shown
- [ ] Transcribing: CircularProgress + status text
- [ ] Summarizing: CircularProgress + status text
- [ ] Button disabled during processing
- [ ] Clear indication of what's happening

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.2.2: Success Messages**

**Trigger each action and verify snackbar:**
- [ ] Create case: "✅ Case '{title}' đã được tạo thành công!"
- [ ] Delete case: "✅ Case '{title}' đã được xóa"
- [ ] Upload complete: "✅ Upload successful!"
- [ ] Transcription complete: "✅ Transcription completed!"
- [ ] Summarization complete: "✅ Summarization completed!"
- [ ] Auto-hide after 6 seconds

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.2.3: Error Messages**

**Simulate errors (backend down, wrong input, etc.):**
- [ ] Create case error: Shows error with details
- [ ] Delete case error: Shows error with details
- [ ] Upload error: Shown
- [ ] Transcribe error: Shown
- [ ] Messages informative (not just "Error")

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.2.4: Confirmation Dialogs**

**Check:**
- [ ] Delete case shows confirmation with case name
- [ ] Confirmation text clear
- [ ] Cancel button works
- [ ] OK/Confirm button works

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **2.3. RESPONSIVENESS**

#### **Test 2.3.1: Desktop (Full Width)**

**Window size: ~1920x1080**

**Check:**
- [ ] Sidebar width: ~320px comfortable
- [ ] Main content: Centered, max-width ~900px
- [ ] All elements visible
- [ ] No overflow
- [ ] Text readable

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.3.2: Laptop (Medium Width)**

**Window size: ~1366x768**

**Check:**
- [ ] Sidebar collapsible
- [ ] Content responsive
- [ ] Scrollable when needed
- [ ] No horizontal scroll

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.3.3: Tablet (Resize to ~800px width)**

**Check:**
- [ ] Sidebar behavior (overlay or hidden)
- [ ] Touch targets adequate (if touchscreen)
- [ ] Buttons spaced properly
- [ ] Dialogs fit screen

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.3.4: Mobile (Resize to ~400px width)**

**Check:**
- [ ] Sidebar becomes drawer
- [ ] Content single column
- [ ] All interactions usable
- [ ] Font sizes readable

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **2.4. ACCESSIBILITY**

#### **Test 2.4.1: Keyboard Navigation**

**Steps:**
1. Press Tab key repeatedly
2. Navigate through all interactive elements
3. Press Enter on buttons

**Check:**
- [ ] Tab moves through elements in logical order
- [ ] Focus indicators visible
- [ ] Enter activates buttons
- [ ] Escape closes dialogs

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

#### **Test 2.4.2: Contrast**

**Use browser DevTools Accessibility panel:**
- [ ] Text contrast ratio ≥ 4.5:1 (WCAG AA)
- [ ] Buttons/icons sufficient contrast
- [ ] Status badges readable

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

## 🚀 PHASE 3: INTEGRATION TESTING

### **Test 3.1: Complete Processing Workflow**

**Full end-to-end test:**

**Steps:**
1. Create new case: "E2E Test Case"
2. Upload audio file
3. Start transcribe (enable diarization)
4. Wait for completion → verify transcript
5. Start summary (detailed, with context)
6. Wait for completion → verify summary
7. Generate visualization → verify dialog
8. View transcript tab → verify display
9. Delete case → verify deletion

**Expected:**
- [ ] All steps complete without errors
- [ ] Data flows correctly between steps
- [ ] No UI glitches
- [ ] Everything functional

**Results:** [ ] PASS / [ ] FAIL
**Time taken:** _____ minutes
**Notes:** _______________________

---

### **Test 3.2: Multiple Files Workflow**

**Steps:**
1. Create case
2. Upload 3 files simultaneously
3. Transcribe all 3 (stagger by 10 seconds each)
4. Observe parallel processing
5. Summarize all 3 after transcription
6. Verify all results

**Expected:**
- [ ] All 3 files upload successfully
- [ ] All 3 transcribe (may be parallel if backend supports)
- [ ] Status updates correctly for each
- [ ] All summaries complete
- [ ] No conflicts or errors

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

### **Test 3.3: Error Recovery**

**Steps:**
1. Upload file
2. Start transcribe
3. Stop backend (simulate crash)
4. Observe error handling
5. Restart backend
6. Retry transcribe

**Expected:**
- [ ] Error shown when backend unavailable
- [ ] UI doesn't crash
- [ ] After backend restart, retry works
- [ ] No stuck states

**Results:** [ ] PASS / [ ] FAIL
**Notes:** _______________________

---

## 📊 BROWSER CONSOLE CHECK

**Open DevTools Console (F12) and check for:**

- [ ] No JavaScript errors
- [ ] No 404 errors (missing resources)
- [ ] No CORS errors
- [ ] No TypeScript errors
- [ ] Warnings acceptable (e.g., Vite CJS deprecation)

**Errors Found:** _______________________

---

## 🐛 BUGS FOUND

**List all bugs/issues discovered:**

### **Bug #1:**
- **Severity:** [ ] Critical / [ ] High / [ ] Medium / [ ] Low
- **Component:** _______________________
- **Steps to reproduce:**
  1. _______________________
  2. _______________________
  3. _______________________
- **Expected:** _______________________
- **Actual:** _______________________
- **Screenshot/Error:** _______________________

### **Bug #2:**
(Add more as needed)

---

## ✅ UI/UX IMPROVEMENT NOTES

**Visual Issues:**
- _______________________
- _______________________
- _______________________

**Spacing Issues:**
- _______________________
- _______________________

**Color Issues:**
- _______________________
- _______________________

**Typography Issues:**
- _______________________

**Workflow Issues:**
- _______________________
- _______________________

---

## 📝 SUMMARY

**Total Tests:** ~50+ test cases

**Results:**
- ✅ PASS: _____ / _____
- ❌ FAIL: _____ / _____
- ⚠️ Partial: _____ / _____

**Critical Bugs:** _____ bugs
**High Priority Bugs:** _____ bugs
**Medium Priority Bugs:** _____ bugs
**Low Priority Bugs:** _____ bugs

**Overall Status:** [ ] READY FOR PRODUCTION / [ ] NEEDS FIXES

**Recommended Actions:**
1. _______________________
2. _______________________
3. _______________________

---

## 🎯 NEXT STEPS

**Based on test results:**

**If PASS (> 90%):**
- [ ] Proceed with UI/UX improvements (Priority 1 & 2)
- [ ] Deploy to staging
- [ ] User acceptance testing

**If FAIL (< 90%):**
- [ ] Fix critical bugs first
- [ ] Re-test failed cases
- [ ] Iterate until stable

---

**Testing completed:** ___________ (date/time)
**Tester:** ___________
**Browser:** ___________ (version)
**Screen resolution:** ___________

