# KẾ HOẠCH FIX GUI CHI TIẾT - TỪNG BƯỚC

**Ngày:** 2026-01-08
**Mục tiêu:** Fix toàn bộ GUI issues theo quy trình test-driven

---

## 📋 OVERVIEW

### **Quy trình cho mỗi fix:**
1. ✅ **Plan:** Analyze và plan chi tiết
2. ✅ **Implement:** Code changes
3. ✅ **Test:** Verify thực tế
4. ✅ **Validate:** Check với requirements
5. 🔄 **Iterate:** Nếu chưa đạt → research và fix lại

---

## 🎯 PHASE 1: FIX CRITICAL ISSUES

### **Phase 1.1: Add Upload to V2 Tab** 🔴

#### **Plan:**
- Read AudioUploader component
- Understand props và callbacks
- Integrate vào V2 tab trong App.tsx
- Ensure refresh files list sau khi upload

#### **Implementation:**
File: `frontend/src/App.tsx`
- Line ~632-686 (Tab 1 rendering)
- Add AudioUploader component
- Add onUploadComplete callback
- Style để match V2 design

#### **Test Checklist:**
- [ ] Click V2 tab → See upload section
- [ ] Select audio file → Upload starts
- [ ] Progress indicator visible
- [ ] Upload complete → File appears in list immediately
- [ ] Can upload multiple files
- [ ] Error handling works

#### **Success Criteria:**
✅ V2 tab có upload button hoạt động đầy đủ
✅ Không cần switch về V1 để upload
✅ Files refresh automatically sau upload

---

### **Phase 1.2: Fix View Transcript Button** 🔴

#### **Plan:**
- Locate onViewTranscript callback trong App.tsx
- Add setSelectedFileId before setTab
- Verify TranscriptPanel receives correct fileId

#### **Implementation:**
File: `frontend/src/App.tsx`
- Line 682: `onViewTranscript={() => setTab(2)}`
- Change to:
  ```typescript
  onViewTranscript={() => {
    setSelectedFileId(file.task_id);
    setTab(2);
  }}
  ```

#### **Test Checklist:**
- [ ] Upload file → Transcribe → Complete
- [ ] Click "View Transcript" button in FileCard
- [ ] Transcript tab opens
- [ ] TranscriptPanel shows correct transcript
- [ ] No error in console
- [ ] Can switch back to Files tab

#### **Success Criteria:**
✅ View Transcript button hoạt động 100%
✅ TranscriptPanel load đúng data
✅ No broken behavior

---

### **Phase 1.3: Add Visualization Dialog** 🔴

#### **Plan:**
- Create VisualizationDialog.tsx component
- Reuse InvestigationSummaryCard component
- Add dialog state to App.tsx
- Integrate with FileCard onVisualize

#### **Implementation:**

**Step 1: Create Component**
File: `frontend/src/components/VisualizationDialog.tsx`
- Similar structure to FileTable visualization
- Load task data via API
- Display InvestigationSummaryCard

**Step 2: Add to App.tsx**
- Add state: visualizeDialogOpen, visualizeTaskId
- Add dialog render
- Update FileCard onVisualize callback

#### **Test Checklist:**
- [ ] File transcribed → Click "Generate Visualization"
- [ ] POST request sends
- [ ] Loading indicator shows
- [ ] Dialog opens when complete
- [ ] InvestigationSummaryCard displays correctly
- [ ] Timeline, entity graph, context analysis visible
- [ ] Close dialog works
- [ ] Can open again

#### **Success Criteria:**
✅ Visualization dialog hoạt động như V1
✅ Data hiển thị đầy đủ
✅ UX smooth

---

## 🎯 PHASE 2: REMOVE V1 TAB

### **Phase 2.1: Remove FileTable Component** 🟡

#### **Plan:**
- Remove FileTable.tsx import
- Remove Tab 0 (V1)
- Update tab indices (0→0, 1→0, 2→1, 3→2)
- Rename "Files (V2)" → "Files"

#### **Implementation:**

**Step 1: Remove Import**
File: `frontend/src/App.tsx`
- Line 10: Remove `import FileTable from './components/FileTable';`

**Step 2: Update Tabs**
- Line 624-630: Update tabs array
- Remove Tab label "Files (V1)"
- Rename "Files (V2)" → "Files"

**Step 3: Update Tab Rendering**
- Line 631-686: Update tab conditions
- Change `{tab === 1 &&` → `{tab === 0 &&`
- Change `{tab === 2 &&` → `{tab === 1 &&`
- Change `{tab === 3 &&` → `{tab === 2 &&`
- Change `{tab === 4 &&` → `{tab === 3 &&`

#### **Test Checklist:**
- [ ] App starts without errors
- [ ] Only 1 "Files" tab visible
- [ ] Files tab is default (tab 0)
- [ ] Clicking each tab works
- [ ] All features in Files tab work
- [ ] Transcript tab works
- [ ] History tab works

#### **Success Criteria:**
✅ No V1/V2 confusion
✅ Clean tab structure
✅ All features accessible

---

### **Phase 2.2: Delete FileTable.tsx** 🟡

#### **Plan:**
- Verify không còn reference nào đến FileTable
- Delete file

#### **Implementation:**
- Grep search "FileTable" in codebase
- Ensure no imports
- Delete `frontend/src/components/FileTable.tsx`

#### **Test Checklist:**
- [ ] App compiles without errors
- [ ] No broken imports
- [ ] No TypeScript errors

#### **Success Criteria:**
✅ File deleted safely
✅ No side effects

---

## 🎯 PHASE 3: REMOVE SUMMARY TAB

### **Phase 3.1: Remove Summary Tab** 🟡

#### **Plan:**
- Remove Tab 2 (Summary) từ tabs array
- Remove tab 3 rendering code (lines 707-718)
- Update tab indices lại

#### **Implementation:**

**Step 1: Update Tabs Array**
File: `frontend/src/App.tsx`
- Line 624-630: Remove "Summary" tab
- Keep: Files, Transcript, History (3 tabs total)

**Step 2: Remove Rendering Code**
- Lines 707-718: Delete Summary tab rendering
- Update remaining tab conditions

**Step 3: Update Tab Indices**
- Files: tab 0 (unchanged)
- Transcript: tab 1 (unchanged)
- History: tab 2 (was 4, now 2)

#### **Test Checklist:**
- [ ] 3 tabs visible: Files, Transcript, History
- [ ] No "Summary" tab
- [ ] Summary still visible inline in FileCard
- [ ] Can expand/collapse summary in FileCard
- [ ] All tabs work correctly

#### **Success Criteria:**
✅ No duplicate summary display
✅ Summary accessible in Files tab
✅ Clean navigation

---

## 🎯 PHASE 4: FINAL TESTING & VALIDATION

### **Phase 4.1: End-to-End Testing** ✅

#### **Complete User Workflow Test:**

**Test Scenario 1: New File Upload → Transcribe → Summarize**
1. [ ] Open app → Select case
2. [ ] Go to Files tab
3. [ ] Upload audio file
4. [ ] File appears in list (status: uploaded)
5. [ ] Click "Start Transcribe"
6. [ ] Configure options in dialog
7. [ ] Click "Start Transcribe"
8. [ ] Status changes: transcribing
9. [ ] Wait for completion
10. [ ] Status changes: transcribed
11. [ ] Transcript appears inline (collapsed)
12. [ ] Expand transcript → content visible
13. [ ] Click "View Transcript" button
14. [ ] Transcript tab opens with full content
15. [ ] Return to Files tab
16. [ ] Click "Start Summary"
17. [ ] Configure model and options
18. [ ] Click "Start Summary"
19. [ ] Status changes: summarizing
20. [ ] Wait for completion
21. [ ] Status changes: summarized
22. [ ] Summary appears inline (collapsed)
23. [ ] Expand summary → content visible
24. [ ] Copy summary → clipboard works

**Test Scenario 2: Visualization**
1. [ ] File must be transcribed
2. [ ] Click "Generate Visualization"
3. [ ] API call sends
4. [ ] Loading indicator
5. [ ] Dialog opens
6. [ ] InvestigationSummaryCard displays
7. [ ] Timeline visible
8. [ ] Entity graph visible
9. [ ] Context analysis visible
10. [ ] Close dialog
11. [ ] Can reopen

**Test Scenario 3: Multiple Files**
1. [ ] Upload 3 files simultaneously
2. [ ] All 3 appear in list
3. [ ] Start transcribe on file 1
4. [ ] Start transcribe on file 2
5. [ ] Both show "transcribing"
6. [ ] Both complete independently
7. [ ] Transcripts appear for both
8. [ ] Summarize both
9. [ ] Summaries appear for both
10. [ ] No conflicts

**Test Scenario 4: Error Handling**
1. [ ] Upload invalid file → error message
2. [ ] Start transcribe on already transcribing → disabled
3. [ ] Network error during polling → graceful handling
4. [ ] Refresh page during transcription → polling resumes

**Test Scenario 5: UI/UX**
1. [ ] Dark mode toggle works
2. [ ] All buttons have proper states (disabled/enabled)
3. [ ] Progress indicators visible
4. [ ] Snackbar notifications appear
5. [ ] Animations smooth
6. [ ] Responsive layout
7. [ ] No console errors

#### **Success Criteria:**
✅ All 5 test scenarios pass 100%
✅ No bugs found
✅ Performance good
✅ UX smooth

---

## 📊 PROGRESS TRACKING

### **Phase Status:**
- [ ] Phase 1.1: Add Upload to V2 ⏳
- [ ] Phase 1.2: Fix View Transcript ⏳
- [ ] Phase 1.3: Add Visualization Dialog ⏳
- [ ] Phase 2.1: Remove V1 Tab ⏳
- [ ] Phase 2.2: Delete FileTable ⏳
- [ ] Phase 3.1: Remove Summary Tab ⏳
- [ ] Phase 4.1: Final Testing ⏳

### **Overall Progress:**
```
[░░░░░░░░░░░░░░░░░░░░] 0% Complete
```

---

## 🔄 ITERATION LOG

### **Iteration 1: [Date]**
- **What:** [Description]
- **Result:** [Pass/Fail]
- **Issues:** [Any problems found]
- **Next Steps:** [What to do next]

---

## 📝 NOTES

### **Important Discoveries:**
- [To be filled during implementation]

### **Gotchas:**
- [To be filled during implementation]

### **Future Improvements:**
- [To be filled during implementation]

---

**Tài liệu này track chi tiết từng bước fix GUI**
**Start Date:** 2026-01-08
**Status:** ⏳ IN PROGRESS
