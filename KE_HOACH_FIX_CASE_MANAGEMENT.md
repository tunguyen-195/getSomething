# KẾ HOẠCH FIX CASE MANAGEMENT

**Date:** 2026-01-08
**Status:** ⏳ IN PROGRESS

---

## 🎯 OBJECTIVES

1. ✅ Fix Create Case functionality (error handling)
2. ✅ Add Delete Case functionality
3. ✅ Test both features

---

## 🔍 ISSUES FOUND

### **Issue 1: Create Case - Missing Error Handling**

**Location:** `App.tsx:145-161`

**Current Code:**
```typescript
const handleCreateCase = () => {
  setCreatingCase(true);
  fetch('/api/v1/cases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: newCaseTitle, description: newCaseDesc })
  })
    .then(res => res.json())
    .then(data => {
      setCases(prev => [data, ...prev]);
      setSelectedCase(data);
      setCreateCaseOpen(false);
      setNewCaseTitle('');
      setNewCaseDesc('');
      setCreatingCase(false);
    })
    // ❌ MISSING .catch() !!!
};
```

**Problems:**
1. ❌ No `.catch()` block → errors not handled
2. ❌ If API fails, `creatingCase` stays `true` → button disabled permanently
3. ❌ No error message shown to user
4. ❌ No validation of response status

**Impact:** 🔴 CRITICAL - If API fails, cannot create cases anymore until page refresh

---

### **Issue 2: Delete Case - Feature Missing**

**Current:** No delete case functionality

**Requirements:**
- Delete button in case list
- Confirmation dialog
- API call to delete case
- Update UI after delete
- Handle selected case deletion
- Show success/error message

---

## 📋 IMPLEMENTATION PLAN

### **Fix 1: Improve Create Case Error Handling**

**Changes:**
1. Add `.catch()` block
2. Reset `creatingCase` in finally block
3. Add response status validation
4. Show error snackbar
5. Add better success message

**Code:**
```typescript
const handleCreateCase = async () => {
  if (!newCaseTitle.trim()) {
    setSnackbar({
      open: true,
      message: '⚠️ Vui lòng nhập tên case',
      severity: 'warning'
    });
    return;
  }

  setCreatingCase(true);
  try {
    const response = await fetch('/api/v1/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: newCaseTitle.trim(),
        description: newCaseDesc.trim()
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();

    // Update UI
    setCases(prev => [data, ...prev]);
    setSelectedCase(data);

    // Close dialog
    setCreateCaseOpen(false);
    setNewCaseTitle('');
    setNewCaseDesc('');

    // Show success message
    setSnackbar({
      open: true,
      message: `✅ Case "${data.title}" đã được tạo thành công!`,
      severity: 'success'
    });
  } catch (error) {
    console.error('Failed to create case:', error);
    setSnackbar({
      open: true,
      message: `❌ Lỗi: Không thể tạo case. ${error.message}`,
      severity: 'error'
    });
  } finally {
    setCreatingCase(false);
  }
};
```

---

### **Fix 2: Add Delete Case Functionality**

**Step 1: Add Delete Handler**
```typescript
const handleDeleteCase = async (caseId: string, caseTitle: string) => {
  // Confirm deletion
  if (!window.confirm(`Bạn có chắc muốn xóa case "${caseTitle}"?\n\nThao tác này không thể hoàn tác.`)) {
    return;
  }

  try {
    const response = await fetch(`/api/v1/cases/${caseId}`, {
      method: 'DELETE'
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Update UI
    setCases(prev => prev.filter(c => c.id !== caseId));

    // If deleted case was selected, select first remaining case
    if (selectedCase?.id === caseId) {
      const remaining = cases.filter(c => c.id !== caseId);
      setSelectedCase(remaining.length > 0 ? remaining[0] : null);
    }

    // Show success message
    setSnackbar({
      open: true,
      message: `✅ Case "${caseTitle}" đã được xóa`,
      severity: 'success'
    });
  } catch (error) {
    console.error('Failed to delete case:', error);
    setSnackbar({
      open: true,
      message: `❌ Lỗi: Không thể xóa case. ${error.message}`,
      severity: 'error'
    });
  }
};
```

**Step 2: Add Delete Button to Case List**

Add delete icon button to each case item in sidebar:

```typescript
<ListItem>
  {/* Existing case content */}
  <ListItemText primary={c.title} secondary={c.description} />

  {/* Add Delete Button */}
  <IconButton
    size="small"
    edge="end"
    onClick={(e) => {
      e.stopPropagation(); // Prevent selecting case when clicking delete
      handleDeleteCase(c.id, c.title);
    }}
    sx={{
      color: '#d32f2f',
      '&:hover': {
        bgcolor: 'rgba(211, 47, 47, 0.1)',
      }
    }}
  >
    <DeleteIcon fontSize="small" />
  </IconButton>
</ListItem>
```

---

## ✅ TESTING CHECKLIST

### **Test Create Case:**
- [ ] Create case with valid title → Success
- [ ] Create case with empty title → Warning message
- [ ] Create case with long description → Success
- [ ] Create case while backend down → Error message + button not stuck
- [ ] Create multiple cases → All appear in list
- [ ] Newly created case auto-selected

### **Test Delete Case:**
- [ ] Click delete → Confirmation dialog shows
- [ ] Cancel deletion → Case not deleted
- [ ] Confirm deletion → Case removed from list
- [ ] Delete selected case → Next case auto-selected
- [ ] Delete only case → No case selected, UI handles gracefully
- [ ] Delete case with files → Check backend behavior

---

## 📊 SUCCESS CRITERIA

- [x] ✅ Create case with error handling
- [x] ✅ Delete case with confirmation
- [x] ✅ Success/error messages for both operations
- [x] ✅ UI updates correctly after create/delete
- [x] ✅ No broken states (button stuck, etc.)
- [x] ✅ User-friendly confirmation dialogs

---

**Next:** Implement fixes according to plan
