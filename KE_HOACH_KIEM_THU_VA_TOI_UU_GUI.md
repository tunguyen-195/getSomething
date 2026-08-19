# KẾ HOẠCH KIỂM THỬ VÀ TỐI ƯU GUI

**Date:** 2026-01-08
**Status:** 📋 **IN PROGRESS**

---

## 📊 MỤC TIÊU

### **Kiểm thử:**
1. ✅ Đảm bảo tất cả tính năng hoạt động đúng
2. ✅ Không có lỗi runtime
3. ✅ User experience mượt mà
4. ✅ Responsive trên các kích thước màn hình

### **Tối ưu GUI:**
1. ✅ Cải thiện visual design (màu sắc, spacing, typography)
2. ✅ Tối ưu user workflow
3. ✅ Giữ nguyên Cherry2 style nhưng hiện đại hóa
4. ✅ Loading states và feedback rõ ràng

---

## 🧪 KẾ HOẠCH KIỂM THỬ TOÀN DIỆN

### **PHASE 1: FUNCTIONAL TESTING**

#### **1.1. Case Management**

**Create Case:**
- [ ] Click "Tạo Case" button → Dialog opens
- [ ] Enter valid title + description → Success message + case appears in list
- [ ] Enter empty title → Warning message "⚠️ Vui lòng nhập tên case"
- [ ] API error (backend down) → Error message + button not stuck
- [ ] Multiple case creation → All cases appear correctly
- [ ] New case auto-selected → Displays in main panel
- [ ] Dialog fields reset after creation
- [ ] Cancel button closes dialog without creating

**Delete Case:**
- [ ] Hover over case → Delete button visible with red color
- [ ] Click delete → Confirmation dialog shows
- [ ] Click Cancel in confirmation → Nothing happens
- [ ] Click OK in confirmation → Case deleted + success message
- [ ] Delete selected case → Next case auto-selected
- [ ] Delete only case → No case selected, UI shows placeholder
- [ ] API error during delete → Error message, case not deleted
- [ ] Delete button event propagation stopped (case not selected on click)

**Case Selection:**
- [ ] Click case → Case selected, highlighted
- [ ] Selected case → Files load for that case
- [ ] Switch case → Files update correctly
- [ ] No case selected → Placeholder message shown

**Case Search:**
- [ ] Click search icon → Search box expands
- [ ] Type search query → Cases filtered in real-time
- [ ] Clear search → All cases shown again
- [ ] Click outside search → Search box collapses
- [ ] Search by title → Works
- [ ] Search by case_code → Works

---

#### **1.2. File Upload (AudioUploader)**

**Upload Flow:**
- [ ] No case selected → Upload disabled with message
- [ ] Select case → Upload enabled
- [ ] Drag-drop file → File appears in list
- [ ] Click "Chọn file âm thanh" → File dialog opens
- [ ] Select audio file → File appears in list
- [ ] Multiple files → All appear in list
- [ ] Non-audio file → Rejected (if validation exists)
- [ ] Remove file from list → File removed

**Upload Options:**
- [ ] Diarization method dropdown → All options (none, whisperx, nemo) available
- [ ] Transcription mode dropdown → Fast/Full modes available
- [ ] Options saved across uploads (session state)

**Upload Execution:**
- [ ] Click "Xử lý File" with no files → Error message
- [ ] Click "Xử lý File" with files → Progress shown
- [ ] Upload progress → Percentage displayed (0-100%)
- [ ] Upload success → Success snackbar + files refresh
- [ ] Upload error → Error snackbar + button re-enabled
- [ ] Multiple files upload → All processed sequentially
- [ ] New files appear in Files tab with "uploaded" status

---

#### **1.3. File Card (FileCard Component)**

**Status Display:**
- [ ] Uploaded status → Badge color: yellow/orange
- [ ] Transcribing status → Badge color: blue + progress indicator
- [ ] Transcribed status → Badge color: green
- [ ] Summarizing status → Badge color: purple + progress indicator
- [ ] Summarized status → Badge color: success green
- [ ] Failed status → Badge color: red with error message

**Action Buttons:**
- [ ] Start Transcribe (uploaded) → TranscribeDialog opens
- [ ] Start Transcribe (transcribing) → Button disabled
- [ ] Start Summary (transcribed) → SummarizeDialog opens
- [ ] Start Summary (summarizing) → Button disabled
- [ ] Generate Visualization → VisualizationDialog opens after processing
- [ ] View Transcript → Switches to Transcript tab with correct file
- [ ] Delete button → (Coming soon message or implementation)

**Inline Results:**
- [ ] Transcript available → Collapsible section shown
- [ ] Expand transcript → Full transcript displayed
- [ ] Copy transcript → Clipboard copy + confirmation
- [ ] Summary available → Collapsible section shown
- [ ] Expand summary → Full summary displayed
- [ ] Copy summary → Clipboard copy + confirmation

**Real-time Updates:**
- [ ] Status polling → Updates every 2 seconds
- [ ] Transcribing → Progress shown
- [ ] Transcribed → Transcript appears automatically
- [ ] Summarized → Summary appears automatically
- [ ] Polling stops after completion/failure

---

#### **1.4. Transcribe Dialog (TranscribeDialog)**

**Dialog Open:**
- [ ] Opens when clicking "Start Transcribe"
- [ ] Filename displayed correctly
- [ ] Default options pre-selected

**Options:**
- [ ] Enable diarization checkbox → Works
- [ ] Diarization method dropdown → Options available when enabled
- [ ] Diarization method disabled → Grayed out when checkbox unchecked
- [ ] Fast mode checkbox → Works
- [ ] Options persist across opens (session state)

**Execution:**
- [ ] Click "Start Transcribe" → Dialog closes + status changes to "transcribing"
- [ ] Click Cancel → Dialog closes, no changes
- [ ] API error → Error snackbar shown
- [ ] Success → Info snackbar: "🎙️ Transcription started!"
- [ ] Polling starts → Status updates automatically

---

#### **1.5. Summarize Dialog (SummarizeDialog)**

**Dialog Open:**
- [ ] Opens when clicking "Start Summary"
- [ ] File info displayed correctly

**Options:**
- [ ] Model dropdown → All models available (gemma2:9b, llama3.1, etc.)
- [ ] Summary type dropdown → Types available (detailed, brief, bullet)
- [ ] Include context checkbox → Works
- [ ] Options persist across opens

**Execution:**
- [ ] Click "Start Summary" → Dialog closes + status changes to "summarizing"
- [ ] Click Cancel → Dialog closes, no changes
- [ ] API error → Error snackbar shown
- [ ] Success → Info snackbar: "📊 Summarization started!"
- [ ] Polling starts → Status updates automatically

---

#### **1.6. Visualization Dialog (VisualizationDialog)**

**Dialog Open:**
- [ ] Opens when clicking "Generate Visualization"
- [ ] Loading indicator shown while fetching data
- [ ] Data loads → InvestigationSummaryCard displayed

**Content Display:**
- [ ] Summary available → Shows in overview tab
- [ ] Context analysis available → Shows in visualization
- [ ] No data → Shows "No visualization data available"
- [ ] API error → Shows error alert

**Dialog Actions:**
- [ ] Close button → Dialog closes
- [ ] Styled with purple theme (#9c27b0) consistently

---

#### **1.7. Transcript Panel (TranscriptPanel)**

**Tab Navigation:**
- [ ] Click "View Transcript" in FileCard → Tab switches + file loads
- [ ] Select different file → Transcript updates
- [ ] No file selected → Placeholder message

**Content Display:**
- [ ] Plain transcript → Displayed correctly
- [ ] Diarized transcript → Speaker labels shown
- [ ] Timestamps → Formatted correctly
- [ ] Long transcript → Scrollable
- [ ] Copy functionality → Works (if implemented)

---

#### **1.8. Tab Navigation**

**Tab Structure:**
- [ ] Tab 0: Files → Shows upload + file cards
- [ ] Tab 1: Transcript → Shows TranscriptPanel
- [ ] Tab 2: History → Shows placeholder
- [ ] Tab count: 3 tabs (no duplicate V1/V2, no duplicate Summary)

**Tab Switching:**
- [ ] Click tab → Content switches
- [ ] Tab state persists within case
- [ ] Switch case → Tabs reset to default (Tab 0)

---

### **PHASE 2: UI/UX TESTING**

#### **2.1. Visual Consistency**

**Colors:**
- [ ] Primary: Green (#43a047) → Used consistently for main actions
- [ ] Secondary: Red (#d32f2f) → Used for destructive actions + branding
- [ ] Accent: Yellow (#ffd600) → Used for highlights + Cherry2 branding
- [ ] Info: Blue (#1976d2) → Used for info messages
- [ ] Error: Red → Used for errors
- [ ] Success: Green → Used for success messages

**Typography:**
- [ ] Font family: Poppins/Inter/Roboto → Consistent
- [ ] Heading sizes → Hierarchy clear
- [ ] Body text → Readable (14-16px)
- [ ] Button text → Bold (600-700 weight)
- [ ] Caption text → Smaller but readable

**Spacing:**
- [ ] Component margins → Consistent
- [ ] Padding → Comfortable (not cramped)
- [ ] Gap between elements → Visual breathing room
- [ ] Border radius → Consistent (8-16px)

**Shadows & Borders:**
- [ ] Cards → Subtle shadow
- [ ] Dialogs → Prominent shadow
- [ ] Borders → Consistent color + width
- [ ] Selected items → Clear visual indication

---

#### **2.2. User Feedback**

**Loading States:**
- [ ] Upload → Progress percentage shown
- [ ] Transcribing → CircularProgress + status text
- [ ] Summarizing → CircularProgress + status text
- [ ] Loading data → Skeleton or spinner
- [ ] Button disabled during processing

**Success Messages:**
- [ ] Case created → "✅ Case '{title}' đã được tạo thành công!"
- [ ] Case deleted → "✅ Case '{title}' đã được xóa"
- [ ] Upload complete → "✅ Upload successful!"
- [ ] Transcription complete → "✅ Transcription completed!"
- [ ] Summarization complete → "✅ Summarization completed!"
- [ ] Snackbar auto-hide after 6 seconds

**Error Messages:**
- [ ] Create case error → "❌ Lỗi: Không thể tạo case. {details}"
- [ ] Delete case error → "❌ Lỗi: Không thể xóa case. {details}"
- [ ] Upload error → Error message displayed
- [ ] Transcribe error → "❌ Task failed: {error}"
- [ ] Error messages informative (not just "Error")

**Warnings:**
- [ ] Empty title → "⚠️ Vui lòng nhập tên case"
- [ ] No case selected → Warning before upload
- [ ] No files selected → Warning before process

**Confirmations:**
- [ ] Delete case → Confirmation dialog with case name
- [ ] Destructive actions → Always confirm
- [ ] Cancel available → User can back out

---

#### **2.3. Responsiveness**

**Desktop (1920x1080):**
- [ ] Sidebar width → 320px comfortable
- [ ] Main content → Centered, max-width 900px
- [ ] All elements visible → No overflow
- [ ] Text readable → Good size

**Laptop (1366x768):**
- [ ] Sidebar → Collapsible
- [ ] Content → Responsive width
- [ ] Scrollable → When needed
- [ ] No horizontal scroll

**Tablet (768x1024):**
- [ ] Sidebar → Overlay or hidden
- [ ] Touch targets → Large enough (44x44px min)
- [ ] Buttons → Adequate spacing
- [ ] Dialogs → Fit screen

**Mobile (375x667):**
- [ ] Sidebar → Drawer
- [ ] Content → Single column
- [ ] Touch-friendly → All interactions
- [ ] Font sizes → Readable on small screen

---

#### **2.4. Accessibility**

**Keyboard Navigation:**
- [ ] Tab key → Moves through interactive elements
- [ ] Enter → Activates buttons
- [ ] Escape → Closes dialogs
- [ ] Arrow keys → Navigate lists (if applicable)

**Screen Reader:**
- [ ] Buttons → Descriptive labels
- [ ] Icons → Alt text or aria-label
- [ ] Status → Announced when changed
- [ ] Errors → Announced clearly

**Visual:**
- [ ] Contrast ratio → WCAG AA (4.5:1 for text)
- [ ] Focus indicators → Visible
- [ ] Color not only indicator → Icons/text also
- [ ] Text size → Adjustable without breaking layout

---

### **PHASE 3: PERFORMANCE TESTING**

**Load Time:**
- [ ] Initial load → < 3 seconds
- [ ] Bundle size → Reasonable (currently 692KB)
- [ ] Fonts load → Progressive enhancement
- [ ] Images optimized → If any

**Runtime Performance:**
- [ ] File list rendering → Fast for 100+ files
- [ ] Polling → Doesn't block UI
- [ ] Scroll → Smooth (60fps)
- [ ] Animations → Smooth

**Memory:**
- [ ] No memory leaks → Polling intervals cleared
- [ ] Long session → Stable memory usage
- [ ] Multiple uploads → No accumulation

---

### **PHASE 4: INTEGRATION TESTING**

**End-to-End Workflows:**

**Workflow 1: Complete Processing Flow**
1. [ ] Create new case → Success
2. [ ] Upload audio file → File appears with "uploaded" status
3. [ ] Start transcribe → Status changes to "transcribing"
4. [ ] Wait for completion → Status changes to "transcribed", transcript appears
5. [ ] Start summary → Status changes to "summarizing"
6. [ ] Wait for completion → Status changes to "summarized", summary appears
7. [ ] Generate visualization → Visualization dialog opens with data
8. [ ] View transcript → Transcript tab shows correct content
9. [ ] Delete case → Case removed after confirmation

**Workflow 2: Multiple Files**
1. [ ] Create case → Success
2. [ ] Upload 3 files → All appear
3. [ ] Transcribe all 3 → All statuses update correctly
4. [ ] Summarize all 3 → All summaries appear
5. [ ] Switch between files → Correct data shown
6. [ ] Delete case → All files cleaned up

**Workflow 3: Error Recovery**
1. [ ] Upload file → Success
2. [ ] Start transcribe → Success
3. [ ] Simulate backend error → Error snackbar shown
4. [ ] Retry transcribe → Works
5. [ ] Complete workflow → Success

---

## 🎨 ĐÁNH GIÁ VÀ TỐI ƯU UI/UX

### **CURRENT STATE ASSESSMENT**

#### **✅ Strengths (Keep These):**
1. **Cherry2 Branding:**
   - Logo animation (gradient "2")
   - Color scheme (red #d32f2f, yellow #ffd600, green #43a047)
   - Overall theme consistency

2. **Clear Information Hierarchy:**
   - Sidebar for cases (left)
   - Main panel for content (center)
   - Tabs for different views

3. **Action-Oriented Design:**
   - Clear buttons for main actions
   - Status badges easily visible
   - Inline results accessible

4. **Feedback System:**
   - Snackbar messages for actions
   - Loading indicators
   - Status badges with colors

---

#### **⚠️ Issues Identified (Need Improvement):**

**1. Visual Density Issues:**
- **Problem:** Too much information cramped together
- **Examples:**
  - File cards have many buttons
  - AudioUploader has many options in one row
  - Sidebar case items have long text + icons
- **Impact:** Overwhelming, hard to focus

**2. Inconsistent Spacing:**
- **Problem:** Some areas too tight, others too loose
- **Examples:**
  - Case list items varying padding
  - Button groups inconsistent gaps
  - Dialog content spacing
- **Impact:** Visual inconsistency

**3. Color Overuse:**
- **Problem:** Too many bright colors competing
- **Examples:**
  - Primary green, secondary red, accent yellow all prominent
  - Multiple badge colors (yellow, blue, green, purple, red)
  - Border colors mixing with backgrounds
- **Impact:** Visual fatigue, hard to focus

**4. Typography Hierarchy:**
- **Problem:** Not enough contrast between heading levels
- **Examples:**
  - H5 and H6 too similar
  - Body1 and Body2 barely different
  - Button text sometimes too bold
- **Impact:** Unclear information hierarchy

**5. Button Overload:**
- **Problem:** Too many action buttons visible at once
- **Examples:**
  - FileCard: Transcribe, Summarize, Visualize, View, Delete all visible
  - AudioUploader: Create case, upload, options all in one row
- **Impact:** Decision paralysis

**6. Lack of Visual Grouping:**
- **Problem:** Related items not clearly grouped
- **Examples:**
  - Upload options scattered
  - File card actions not organized
  - Tab content lacks structure
- **Impact:** Cognitive load

**7. Inefficient Workflows:**
- **Problem:** Too many clicks for common tasks
- **Examples:**
  - Must click View Transcript to see full transcript
  - Dialog for every action (good for safety, but can be streamlined)
  - No bulk actions
- **Impact:** Slow workflow

---

### **IMPROVEMENT PLAN**

#### **Priority 1: Visual Hierarchy & Spacing (CRITICAL)**

**Changes:**
1. **Consistent Spacing System:**
   ```
   - xs: 4px (0.5 spacing units)
   - sm: 8px (1 spacing unit)
   - md: 16px (2 spacing units)
   - lg: 24px (3 spacing units)
   - xl: 32px (4 spacing units)
   - xxl: 48px (6 spacing units)
   ```

2. **Card Redesign:**
   - Increase padding: `p: 3` → `p: 4`
   - Add consistent margin: `mb: 2` → `mb: 3`
   - Group related actions together
   - Use dividers between sections

3. **Button Spacing:**
   - Consistent gap in button groups: `gap: 2`
   - Adequate padding in buttons: `px: 3, py: 1.5`
   - Clear visual separation between primary/secondary actions

---

#### **Priority 2: Color Rationalization (HIGH)**

**Changes:**
1. **Reduce Color Usage:**
   - **Primary (Green):** Main positive actions only
   - **Secondary (Red):** Destructive actions + branding elements only
   - **Accent (Yellow):** Highlights + Cherry2 logo only
   - **Info (Blue):** Informational elements
   - **Neutral (Gray):** Most UI elements, backgrounds

2. **Status Badge Colors:**
   - **Uploaded:** Gray (neutral, waiting)
   - **Processing:** Blue (info, in progress)
   - **Success:** Green (completed)
   - **Error:** Red (failed)
   - Remove purple, orange, etc.

3. **Background Colors:**
   - Use subtle grays for backgrounds (#f8fafc, #f5f5f5)
   - Avoid bright colored backgrounds unless for emphasis
   - Paper background: White or very light gray

---

#### **Priority 3: Button Organization (HIGH)**

**Changes:**
1. **FileCard Actions:**
   ```
   Primary Actions (always visible):
   - Start Transcribe (if uploaded)
   - Start Summary (if transcribed)

   Secondary Actions (in menu/dropdown):
   - Generate Visualization
   - View Transcript
   - Download
   - Delete

   Use IconButton with Tooltip for secondary actions
   ```

2. **AudioUploader:**
   ```
   Layout:
   Row 1: Case selector (if not provided)
   Row 2: Diarization method | Transcription mode
   Row 3: Upload area (drag-drop)
   Row 4: File list (if files selected)
   Row 5: Process button
   ```

3. **Dialog Actions:**
   - Always: Cancel (left) | Confirm (right)
   - Consistent button sizes and styles
   - Destructive actions in red, others in primary color

---

#### **Priority 4: Visual Grouping (MEDIUM)**

**Changes:**
1. **Use Paper/Card for Grouping:**
   ```
   - Upload section: Separate Paper with border
   - Options section: Paper with light background
   - Results section: Collapsible Accordion or Card
   ```

2. **Dividers:**
   - Use Divider component between sections
   - Consistent styling (light gray, 1px)

3. **Section Headers:**
   - Clear typography (h6 or subtitle1)
   - Adequate spacing above/below
   - Optional icon for visual clarity

---

#### **Priority 5: Workflow Optimization (LOW)**

**Changes:**
1. **Inline Actions:**
   - Show transcript inline (already implemented) ✅
   - Show summary inline (already implemented) ✅
   - Add "Quick View" for visualization (modal)

2. **Batch Operations:**
   - Select multiple files (checkbox)
   - Bulk transcribe/summarize
   - Bulk delete

3. **Keyboard Shortcuts:**
   - Ctrl+N: New case
   - Ctrl+U: Upload
   - Ctrl+T: Transcribe selected
   - Ctrl+S: Summarize selected

---

#### **Priority 6: Responsive Improvements (LOW)**

**Changes:**
1. **Mobile Layout:**
   - Hamburger menu for sidebar
   - Bottom navigation for tabs
   - Simplified file cards (fewer actions visible)
   - Touch-optimized buttons (min 44x44px)

2. **Tablet Layout:**
   - Sidebar toggleable
   - Adaptive grid (2 columns → 1 column)
   - Dialogs full-screen on small screens

---

## 📋 IMPLEMENTATION CHECKLIST

### **Step 1: Visual Hierarchy & Spacing**
- [ ] Define spacing constants in theme
- [ ] Update Card components with consistent padding
- [ ] Update button groups with consistent gaps
- [ ] Add dividers between sections
- [ ] Test on different screen sizes

### **Step 2: Color Rationalization**
- [ ] Update status badge colors (gray, blue, green, red only)
- [ ] Review all color usage, remove unnecessary colors
- [ ] Update backgrounds to neutral grays
- [ ] Ensure sufficient contrast (WCAG AA)
- [ ] Test in both light/dark modes

### **Step 3: Button Organization**
- [ ] Redesign FileCard actions (primary visible, secondary in menu)
- [ ] Reorganize AudioUploader layout
- [ ] Standardize dialog buttons
- [ ] Add tooltips to IconButtons
- [ ] Test all button interactions

### **Step 4: Visual Grouping**
- [ ] Wrap related sections in Paper components
- [ ] Add section headers
- [ ] Insert dividers between major sections
- [ ] Test visual clarity

### **Step 5: Testing**
- [ ] Run all functional tests (Phase 1)
- [ ] Run all UI/UX tests (Phase 2)
- [ ] Run performance tests (Phase 3)
- [ ] Run integration tests (Phase 4)
- [ ] Fix any bugs found

### **Step 6: User Feedback**
- [ ] Demo to user
- [ ] Collect feedback
- [ ] Iterate on improvements
- [ ] Final approval

---

## 🎯 SUCCESS CRITERIA

### **Functional:**
- [ ] All features work without errors
- [ ] No TypeScript or runtime errors
- [ ] Polling works correctly
- [ ] Real-time updates functional

### **Visual:**
- [ ] Consistent spacing throughout
- [ ] Clear visual hierarchy
- [ ] Color usage rationalized
- [ ] Typography clear and readable

### **UX:**
- [ ] Actions clear and discoverable
- [ ] Feedback immediate and informative
- [ ] Workflow efficient
- [ ] Responsive on all devices

### **Performance:**
- [ ] Load time < 3 seconds
- [ ] Smooth scrolling and animations
- [ ] No memory leaks
- [ ] Efficient polling

---

## 📊 NEXT STEPS

### **Immediate (Today):**
1. Create detailed UI improvement specifications
2. Start implementing Priority 1 & 2 changes
3. Test changes incrementally

### **Short-term (This Week):**
1. Complete all priority improvements
2. Run comprehensive testing
3. Fix bugs
4. User demo and feedback

### **Long-term (Next Sprint):**
1. Implement workflow optimizations
2. Add batch operations
3. Improve mobile experience
4. Performance optimization

---

**Document created:** 2026-01-08
**Status:** 📋 Planning complete, ready for implementation
**Next action:** Create UI improvement specifications and start implementation
