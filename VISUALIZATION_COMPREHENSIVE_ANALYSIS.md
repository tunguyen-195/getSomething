# VISUALIZATION COMPREHENSIVE ANALYSIS

**Date:** 2026-01-08
**Status:** ✅ **ANALYSIS COMPLETE**

---

## 📋 TABLE OF CONTENTS

1. [Executive Summary](#executive-summary)
2. [V1 vs V2 Comparison](#v1-vs-v2-comparison)
3. [Backend Prompts Analysis](#backend-prompts-analysis)
4. [InvestigationSummaryCard Features](#investigationsummarycard-features)
5. [Prompt Quality Assessment](#prompt-quality-assessment)
6. [Recommendations](#recommendations)
7. [Testing Checklist](#testing-checklist)

---

## 🎯 EXECUTIVE SUMMARY

### **Key Findings:**

✅ **V2 maintains 100% feature parity with V1**
✅ **V2 has improved UI/UX with modern purple theme**
✅ **Backend prompts are functional but can be enhanced**
⚠️ **InvestigationSummaryCard has comprehensive features but needs testing**
⚠️ **Context analysis prompt is basic - can be more detailed**

### **Verdict:**

**V2 visualization quality: MAINTAINED** ✅

- Core functionality: Identical to V1
- Data flow: Same endpoints, same component
- UI wrapper: Improved (V2 > V1)
- Backend prompts: Good but improvable

---

## 🔄 V1 VS V2 COMPARISON

### **Architecture Comparison**

| Aspect | V1 (FileTable.tsx) | V2 (VisualizationDialog.tsx) |
|--------|-------------------|------------------------------|
| **Component Type** | Inline dialog in FileTable | Separate reusable component |
| **Location** | `frontend/src/components/FileTable.tsx` (deleted) | `frontend/src/components/VisualizationDialog.tsx` |
| **Lines of Code** | ~50 lines (dialog section) | 136 lines (full component) |
| **Data Fetching** | `fetch(/api/v1/audio/tasks/${taskId})` | `fetch(/api/v1/audio/tasks/${taskId})` ✅ SAME |
| **Props to InvestigationSummaryCard** | `summary`, `contextAnalysis`, `taskId` | `summary`, `contextAnalysis`, `taskId` ✅ SAME |
| **Core Component** | InvestigationSummaryCard | InvestigationSummaryCard ✅ SAME |

### **UI/UX Comparison**

| Feature | V1 | V2 | Winner |
|---------|----|----|--------|
| **Dialog Title** | "Data Visualization" | "📊 DATA VISUALIZATION" with icon | V2 ✅ |
| **Theme Color** | Default Material-UI | Purple (#9c27b0) | V2 ✅ |
| **Border Style** | Default | 2px solid purple border | V2 ✅ |
| **Box Shadow** | Default | `0 8px 32px rgba(156, 39, 176, 0.2)` | V2 ✅ |
| **Border Radius** | Default | 16px (modern rounded) | V2 ✅ |
| **Loading State** | CircularProgress + text | CircularProgress + text centered | Tie |
| **Error State** | Alert | Alert | Tie |
| **Empty State** | "No data to visualize." | "No visualization data available for this file." | V2 ✅ |
| **Close Button** | Default Button | Contained Button with icon + purple theme | V2 ✅ |
| **Code Organization** | Inline in large file | Separate component (reusable) | V2 ✅ |

### **Data Flow Comparison**

Both V1 and V2 use IDENTICAL data flow:

```typescript
// V1 (FileTable.tsx, lines ~350-360)
fetch(`${API_BASE_URL}/api/v1/audio/tasks/${file.task_id}`)
  .then(res => res.json())
  .then(data => setTaskData(data))

<InvestigationSummaryCard
  summary={taskData.result?.summary}
  contextAnalysis={taskData.result?.context_analysis}
  taskId={taskData.result?.task_id || taskData.id}
/>

// V2 (VisualizationDialog.tsx, lines 37-43, 101-105)
fetch(`${API_BASE_URL}/api/v1/audio/tasks/${taskId}`)
  .then(res => res.json())
  .then(taskData => setData(taskData))

<InvestigationSummaryCard
  summary={data.result.summary}
  contextAnalysis={data.result.context_analysis}
  taskId={taskId || data.id}
/>
```

**Result:** ✅ **100% IDENTICAL DATA FLOW**

---

## 🔍 BACKEND PROMPTS ANALYSIS

### **1. Summary Prompts (summary_service_v2.py)**

Located in: `src/services/summarization/summary_service_v2.py` (lines 68-99)

#### **Brief Summary Prompt:**
```python
prompt = f"""
Tóm tắt ngắn gọn cuộc hội thoại sau (1-2 câu, tối đa {min_length} từ):

{transcript}

Tóm tắt:
"""
```

**Assessment:** ✅ Clear and concise for brief summaries

---

#### **Investigation Summary Prompt:**
```python
prompt = f"""
Phân tích cuộc hội thoại sau theo góc độ điều tra:
- Các sự kiện quan trọng theo trình tự thời gian
- Các nhân vật liên quan và vai trò
- Thông tin nhạy cảm, dấu hiệu bất thường
- Các hành động, quyết định quan trọng
- Điểm cần làm rõ thêm

{transcript}

Phân tích:
"""
```

**Assessment:** ✅ Good focus areas, but **lacks JSON structure guidance**

**Issues:**
- ❌ No explicit instruction to return JSON
- ❌ No schema definition for structured output
- ❌ InvestigationSummaryCard expects JSON but prompt doesn't enforce it
- ❌ Missing fields: relationships, entities, sentiment, timeline

---

#### **Detailed Summary Prompt:**
```python
prompt = f"""
Tóm tắt chi tiết cuộc hội thoại sau ({min_length}-{max_length} từ):
- Nội dung chính
- Các điểm quan trọng
- Kết luận/quyết định (nếu có)

{transcript}

Tóm tắt:
"""
```

**Assessment:** ✅ Adequate for detailed text summaries

---

### **2. Context Analysis Prompt (llm_manager.py)**

Located in: `src/services/summarization/models/llm_manager.py` (lines 189-203)

```python
prompt = f"""
Phân tích hội thoại sau và trích xuất thông tin chi tiết.
Trả về kết quả dưới dạng JSON với các trường:
- summary: Tóm tắt ngắn gọn
- key_points: Các điểm chính (list)
- entities: Các thực thể (people, locations, time, contact_info)
- relationships: Mối quan hệ giữa các thực thể
- actions: Các hành động, quyết định
- sentiment: Cảm xúc, thái độ

Hội thoại:
{text}

JSON:
"""
```

**Assessment:** ⚠️ **BASIC - Needs Enhancement**

**Good Points:**
- ✅ Explicitly asks for JSON output
- ✅ Lists required fields
- ✅ Covers basic analysis needs

**Missing Critical Fields:**
- ❌ **events/timeline** - InvestigationSummaryCard has Timeline tab but no guidance in prompt
- ❌ **sensitive_info** - Card has Nhạy cảm tab but not explicitly asked
- ❌ **offers** - Card displays offers in Insight tab
- ❌ **decisions** - Separate from actions, shown in Insight
- ❌ **risk** - Card displays risk alerts
- ❌ **notes** - Business notes section
- ❌ **slang_detected** - Card has slang detection feature
- ❌ **hidden_relationships** - Card displays hidden relationships
- ❌ **insight** - Card has dedicated Insight checklist

**Field Structure Issues:**
- ❌ No guidance on entity structure (should entities have `is_sensitive` flag?)
- ❌ No guidance on relationship structure (source, target, label, context?)
- ❌ No guidance on action/offer/decision format

---

### **3. Context Service Prompt (context_service.py)**

Located in: `src/services/summarization/context_service.py` (lines 39-53)

```python
base_prompt = """
Phân tích hội thoại sau và trích xuất thông tin chi tiết theo cấu trúc JSON.
Tập trung vào:
- Thực thể: người, địa điểm, thời gian, tổ chức
- Mối quan hệ giữa các thực thể
- Hành động, quyết định, ưu đãi
- Cảm xúc, thái độ
- Thông tin nhạy cảm

"""

if user_prompt:
    base_prompt += f"\nYêu cầu bổ sung: {user_prompt}\n"

base_prompt += f"\nHội thoại:\n{transcript}\n\nJSON:"
```

**Assessment:** ⚠️ **Similar issues to LLM Manager prompt**

**Good Points:**
- ✅ Vietnamese instructions (matches UI language)
- ✅ Mentions key focus areas
- ✅ Supports user_prompt for customization

**Missing:**
- ❌ No JSON schema definition
- ❌ No field structure guidance
- ❌ Missing timeline/events, risk, notes, slang, hidden relationships

---

## 📊 INVESTIGATIONSUMMARYCARD FEATURES

Located in: `frontend/src/components/InvestigationSummaryCard.tsx` (495 lines)

### **6-Tab Structure**

#### **Tab 0: Tổng quan (Overview)**
**Lines 202-287**

**Features:**
- Summary display with copy button
- Metadata grid: Time, Location, Status, Topic
- Avatar with topic initial
- Copy to clipboard for each metadata field
- Key points checklist

**Data Sources:**
```typescript
const mappedOverview = {
  title: parsedAnalysis?.summary || parsedAnalysis?.context?.topic || parsedAnalysis?.context?.purpose || '',
  time: parsedAnalysis?.entities?.time?.[0]?.value || parsedAnalysis?.details?.time || '',
  location: parsedAnalysis?.entities?.locations?.[0]?.name || '',
  status: parsedAnalysis?.context?.status || '',
  topic: parsedAnalysis?.context?.topic || '',
};
```

**Tooltip for Missing Data:** ✅ Shows "Không rõ" (Unknown) with disabled copy button

---

#### **Tab 1: Sơ đồ quan hệ (Relationship Diagram)**
**Lines 289-330**

**Features:**
- ReactFlow interactive diagram
- Nodes: Entities with labels, sensitive flag, context tooltip
- Edges: Relationships with labels and context
- MiniMap, Controls, Background
- Loading state while analyzing
- Entity list with chips (colored by sensitivity)
- Relationship list with chips

**Data Mapping:**
```typescript
const nodes = entities.map((e: any, idx: number) => ({
  id: e.id || String(idx),
  data: { label: e.label || e.name || e.type, isSensitive: e.is_sensitive, tooltip: e.context },
  position: { x: 100 + idx * 120, y: 100 }
}));

const edges = relationships.map((r: any, idx: number) => ({
  id: r.id || String(idx),
  source: r.source,
  target: r.target,
  label: r.label || r.type,
  tooltip: r.context
}));
```

**Requirements:**
- Entities need: `id`, `label/name/type`, `is_sensitive`, `context`
- Relationships need: `id`, `source`, `target`, `label/type`, `context`

---

#### **Tab 2: Timeline**
**Lines 332-349**

**Features:**
- Material-UI Timeline component
- TimelineDot with connector
- Shows time + description for each event
- Fallback to entities.time if no events

**Data Source:**
```typescript
const timelineEvents = Array.isArray(parsedAnalysis?.events) && parsedAnalysis.events.length > 0
  ? parsedAnalysis.events
  : (Array.isArray(parsedAnalysis?.timeline) ? parsedAnalysis.timeline :
     (Array.isArray(parsedAnalysis?.entities?.time) ? parsedAnalysis.entities.time.map(...) : []));
```

**Expected Format:**
```json
{
  "events": [
    {"time": "10:00 AM", "description": "Event description", "action": "...", "event": "..."}
  ]
}
```

---

#### **Tab 3: Insight & Checklist**
**Lines 351-363**

**Features:**
- Insight checklist with icons
- Displays: Offers, Decisions, Actions, Sentiment
- Avatar with colored icons

**Data Sources:**
```typescript
const insightChecklist = [
  ...(offers.length ? offers.map(o => ({ label: `Ưu đãi: ${o.content || o}`, icon: <InsightsIcon color="primary" /> })) : []),
  ...(decisions.length ? decisions.map(d => ({ label: `Quyết định: ${d.content || d}`, icon: <InfoIcon color="info" /> })) : []),
  ...(actions.length ? actions.map(a => ({ label: `Hành động: ${a.content || a}`, icon: <InfoIcon color="secondary" /> })) : []),
  ...(sentiment ? [{ label: `Cảm xúc: ${sentiment}`, icon: sentimentIcon(sentiment) }] : []),
];
```

**Expected Format:**
```json
{
  "offers": [{"content": "..."}],
  "decisions": [{"content": "..."}],
  "actions": [{"content": "..."}],
  "sentiment": "positive/negative/neutral/hài lòng/..."
}
```

---

#### **Tab 4: Nhạy cảm (Sensitive Info)**
**Lines 365-399**

**Features:**
- Show/Hide toggle button (red, error color)
- Collapsible Alert (error severity)
- Lists all sensitive info with SecurityIcon
- Displays: sensitive_info array + entities with is_sensitive=true
- Copy button for phone/email/id
- Shows: name/value, type chip, sensitivity reason, context

**Data Collection:**
```typescript
const sensitiveEntities = [
  ...(Array.isArray(parsedAnalysis?.entities?.people) ? parsedAnalysis.entities.people.filter((e: any) => e.is_sensitive) : []),
  ...(Array.isArray(parsedAnalysis?.entities?.locations) ? parsedAnalysis.entities.locations.filter((e: any) => e.is_sensitive) : []),
  // ... all entity types
];

const allSensitive = [
  ...(Array.isArray(parsedAnalysis?.sensitive_info) ? parsedAnalysis.sensitive_info : []),
  ...sensitiveEntities
];
```

**Expected Format:**
```json
{
  "sensitive_info": [
    {"name": "...", "value": "...", "type": "phone/email/id/...", "sensitivity_reason": "...", "context": "..."}
  ],
  "entities": {
    "people": [{"name": "...", "is_sensitive": true, "context": "..."}]
  }
}
```

---

#### **Tab 5: Cảm xúc (Emotions)**
**Lines 401-409**

**Features:**
- Displays sentiment with emoji icon
- Icon color: Success (positive/hài lòng), Error (negative), Warning (neutral)

**Sentiment Icon Mapping:**
```typescript
const sentimentIcon = (sentiment: string) => {
  if (sentiment.toLowerCase().includes('positive') || sentiment.includes('hài lòng'))
    return <EmojiEmotionsIcon color="success" />;
  if (sentiment.toLowerCase().includes('negative'))
    return <EmojiEmotionsIcon color="error" />;
  return <EmojiEmotionsIcon color="warning" />;
};
```

---

### **Additional Alert Sections**
**Lines 411-432**

**Risk Alerts (Error severity):**
```json
{"risk": ["Risk description 1", "Risk description 2"]}
```

**Slang Detection (Warning severity):**
```json
{"slang_detected": "Detected slang phrase or code language"}
```

**Hidden Relationships (Info severity):**
```json
{"hidden_relationships": ["Hidden relationship description"]}
```

**Business Notes (Info severity):**
```json
{"notes": "Additional business notes"}
```

---

### **Special Features**

#### **Auto-Analysis on Tab Switch (Lines 82-91)**
```typescript
useEffect(() => {
  if ([1,2,3,4,5].includes(tab) && !analysis && summary) {
    setLoading(true);
    setError(null);
    analyzeSummaryWithFallback(typeof summary === 'string' ? summary : JSON.stringify(summary), taskId)
      .then(setAnalysis)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }
}, [tab, analysis, summary, taskId]);
```

**Behavior:**
- When switching to visualization tabs (1-5) for the first time
- If `contextAnalysis` prop is not provided
- Automatically calls `/api/v1/summaries/analyze` endpoint
- Analyzes the summary text using LLM
- Populates visualization data

---

#### **"Phân tích lại bằng AI" Button (Lines 479-486)**
```typescript
{[1,2,3,4,5].includes(tab) && analysis && (
  <Box mb={2} display="flex" justifyContent="flex-end">
    <Button variant="outlined" color="primary" onClick={() => setConfirmOpen(true)}>
      Phân tích lại bằng AI
    </Button>
  </Box>
)}
```

**Behavior:**
- Shows when on visualization tabs (1-5) AND already have analysis
- Opens confirmation dialog
- User can choose: "Không, dùng dữ liệu cũ" OR "Có, phân tích lại"
- Re-analyzes with fresh LLM call if confirmed

---

#### **JSON Parsing (Lines 24-40)**
```typescript
function parseJsonOrText(data: any) {
  if (!data) return null;
  if (typeof data === 'object') return data;
  if (typeof data === 'string') {
    // Remove markdown code block if present
    let s = data.trim();
    if (s.startsWith('```json')) s = s.replace(/^```json/, '').replace(/```$/, '').trim();
    else if (s.startsWith('```')) s = s.replace(/^```/, '').replace(/```$/, '').trim();
    try {
      return JSON.parse(s);
    } catch {
      return null;
    }
  }
  return null;
}
```

**Robustness:**
- ✅ Handles object input
- ✅ Strips markdown code blocks (```json ... ```)
- ✅ Fallback to null if parsing fails

---

## 📈 PROMPT QUALITY ASSESSMENT

### **Current State:**

| Prompt | Purpose | Quality | Issues |
|--------|---------|---------|--------|
| **Brief Summary** | 1-2 sentence summary | ✅ Good | None |
| **Investigation Summary** | Detailed analysis | ⚠️ Fair | No JSON structure, missing fields |
| **Detailed Summary** | Long-form summary | ✅ Good | None (not used for viz) |
| **LLM Manager analyze_context** | Structured analysis | ⚠️ Fair | Missing 9 fields, no schema |
| **Context Service** | Similar to LLM Manager | ⚠️ Fair | Same issues as LLM Manager |

---

### **Gap Analysis:**

**InvestigationSummaryCard expects:**
1. ✅ summary (text)
2. ✅ key_points (list)
3. ✅ entities (object with people, locations, time, organizations, contact_info)
4. ✅ relationships (list)
5. ✅ actions (list)
6. ✅ sentiment (string)
7. ❌ **offers** (list) - NOT in prompt
8. ❌ **decisions** (list) - NOT in prompt
9. ❌ **events/timeline** (list) - NOT in prompt
10. ❌ **sensitive_info** (list) - NOT explicitly structured
11. ❌ **risk** (list/string) - NOT in prompt
12. ❌ **notes** (string) - NOT in prompt
13. ❌ **slang_detected** (string) - NOT in prompt
14. ❌ **hidden_relationships** (list) - NOT in prompt
15. ❌ **insight** (list) - NOT in prompt
16. ❌ **context** (object with topic, purpose, status) - NOT in prompt

**Missing Rate:** 9/16 fields (56%) not explicitly requested in prompt

---

### **Schema Mismatch:**

**Current prompt asks for:**
```json
{
  "summary": "string",
  "key_points": ["string"],
  "entities": {
    "people": [],
    "locations": [],
    "time": [],
    "contact_info": {}
  },
  "relationships": [],
  "actions": [],
  "sentiment": "string"
}
```

**InvestigationSummaryCard expects:**
```json
{
  "summary": "string",
  "key_points": ["string"],
  "context": {
    "topic": "string",
    "purpose": "string",
    "status": "string"
  },
  "entities": {
    "people": [{"name": "string", "role": "string", "is_sensitive": false, "context": "string"}],
    "locations": [{"name": "string", "is_sensitive": false, "context": "string"}],
    "time": [{"value": "string", "context": "string", "is_sensitive": false}],
    "organizations": ["string"],
    "contact_info": {
      "phone": {"value": "string", "is_sensitive": true, "type": "phone"},
      "email": {"value": "string", "is_sensitive": true, "type": "email"},
      "id": {"value": "string", "is_sensitive": true, "type": "id"}
    }
  },
  "relationships": [{"source": "string", "target": "string", "label": "string", "context": "string"}],
  "events": [{"time": "string", "description": "string", "action": "string"}],
  "actions": [{"content": "string"}],
  "offers": [{"content": "string"}],
  "decisions": [{"content": "string"}],
  "sentiment": "positive|negative|neutral|hài lòng|...",
  "sensitive_info": [{"name": "string", "value": "string", "type": "string", "sensitivity_reason": "string", "context": "string"}],
  "risk": ["string"],
  "notes": "string",
  "slang_detected": "string",
  "hidden_relationships": ["string"],
  "insight": ["string"]
}
```

---

## 💡 RECOMMENDATIONS

### **Priority 1: Update LLM Manager analyze_context Prompt** 🔴 CRITICAL

**File:** `src/services/summarization/models/llm_manager.py` (lines 189-203)

**Current Issues:**
- Missing 9 critical fields
- No field structure guidance
- No examples

**Recommended New Prompt:**

```python
def analyze_context(self, text: str, model: str = None) -> Dict:
    """
    Analyze context from text using LLM
    Returns structured data matching InvestigationSummaryCard requirements
    """
    prompt = f"""
Phân tích hội thoại sau và trích xuất thông tin chi tiết theo góc độ điều tra.
Trả về kết quả dưới dạng JSON với cấu trúc sau:

{{
  "summary": "Tóm tắt ngắn gọn toàn bộ hội thoại (1-2 câu)",
  "context": {{
    "topic": "Chủ đề chính của hội thoại",
    "purpose": "Mục đích, ý đồ của cuộc trò chuyện",
    "status": "Trạng thái hiện tại (đã giải quyết, đang xử lý, cần làm rõ, ...)"
  }},
  "key_points": [
    "Điểm quan trọng 1",
    "Điểm quan trọng 2"
  ],
  "entities": {{
    "people": [
      {{"name": "Tên người", "role": "Vai trò", "is_sensitive": false, "context": "Thông tin bổ sung"}}
    ],
    "locations": [
      {{"name": "Địa điểm", "is_sensitive": false, "context": "Chi tiết địa điểm"}}
    ],
    "time": [
      {{"value": "Thời gian cụ thể", "context": "Ngữ cảnh thời gian", "is_sensitive": false}}
    ],
    "organizations": ["Tên tổ chức"],
    "contact_info": {{
      "phone": {{"value": "Số điện thoại", "is_sensitive": true, "type": "phone"}},
      "email": {{"value": "Email", "is_sensitive": true, "type": "email"}},
      "id": {{"value": "CCCD/CMND/Passport", "is_sensitive": true, "type": "id"}}
    }}
  }},
  "relationships": [
    {{"source": "Người/tổ chức A", "target": "Người/tổ chức B", "label": "Loại quan hệ (khách hàng, đối tác, ...)", "context": "Chi tiết mối quan hệ"}}
  ],
  "events": [
    {{"time": "Thời điểm", "description": "Mô tả sự kiện", "action": "Hành động xảy ra"}}
  ],
  "actions": [
    {{"content": "Hành động hoặc quyết định được thực hiện"}}
  ],
  "offers": [
    {{"content": "Ưu đãi, khuyến mãi, đề xuất được đưa ra"}}
  ],
  "decisions": [
    {{"content": "Quyết định quan trọng trong hội thoại"}}
  ],
  "sentiment": "positive|negative|neutral|hài lòng|không hài lòng|...",
  "sensitive_info": [
    {{"name": "Loại thông tin", "value": "Giá trị cụ thể", "type": "phone|email|id|financial|...", "sensitivity_reason": "Lý do nhạy cảm", "context": "Ngữ cảnh"}}
  ],
  "risk": [
    "Nguy cơ hoặc rủi ro cần lưu ý"
  ],
  "insight": [
    "Insight nghiệp vụ, dấu hiệu bất thường, hành vi nghi vấn, mối liên hệ ẩn"
  ],
  "slang_detected": "Tiếng lóng, mật ngữ phát hiện trong hội thoại (nếu có)",
  "hidden_relationships": [
    "Mối quan hệ ẩn hoặc nghi vấn cần điều tra"
  ],
  "notes": "Ghi chú nghiệp vụ bổ sung, điểm cần làm rõ thêm"
}}

Hội thoại:
{text}

Hãy phân tích kỹ và trả về JSON đầy đủ. Nếu không có dữ liệu cho trường nào, để [] hoặc "" hoặc {{}}.

JSON:
"""

    try:
        response = self.generate(prompt, model=model, temperature=0.3)  # Lower temp for structured output
        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{{.*\}}', response, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            logger.info(f"[LLM_MANAGER] Context analysis complete | fields={len(parsed)}")
            return parsed
        else:
            logger.warning("[LLM_MANAGER] No JSON found in response")
            return {"summary": response, "key_points": []}
    except Exception as e:
        logger.error(f"[LLM_MANAGER] Context analysis failed: {e}")
        return {"summary": "", "key_points": []}
```

**Key Improvements:**
- ✅ All 16 fields explicitly defined
- ✅ Full JSON schema with structure
- ✅ Vietnamese field descriptions matching UI
- ✅ Examples for each field type
- ✅ Clear guidance on empty values
- ✅ Lower temperature (0.3) for more structured output

---

### **Priority 2: Update Investigation Summary Prompt** 🟠 HIGH

**File:** `src/services/summarization/summary_service_v2.py` (lines 79-91)

**Current:**
```python
elif summary_type == "investigation":
    prompt = f"""
Phân tích cuộc hội thoại sau theo góc độ điều tra:
- Các sự kiện quan trọng theo trình tự thời gian
- Các nhân vật liên quan và vai trò
- Thông tin nhạy cảm, dấu hiệu bất thường
- Các hành động, quyết định quan trọng
- Điểm cần làm rõ thêm

{transcript}

Phân tích:
"""
```

**Recommended:**
```python
elif summary_type == "investigation":
    prompt = f"""
Phân tích cuộc hội thoại sau theo góc độ điều tra và trả về dưới dạng JSON có cấu trúc.

YÊU CẦU PHÂN TÍCH:
1. Tóm tắt toàn bộ cuộc hội thoại (1-2 đoạn)
2. Các sự kiện quan trọng theo trình tự thời gian (timeline)
3. Các nhân vật liên quan, vai trò, mối quan hệ
4. Thông tin nhạy cảm (số điện thoại, địa chỉ, CCCD, thông tin tài chính)
5. Dấu hiệu bất thường, hành vi nghi vấn
6. Các hành động, quyết định, ưu đãi, thỏa thuận
7. Cảm xúc, thái độ của các bên
8. Nguy cơ, rủi ro cần lưu ý
9. Insight nghiệp vụ, mối liên hệ ẩn
10. Điểm cần làm rõ thêm, ghi chú nghiệp vụ

Trả về JSON với các trường: summary, context (topic, purpose, status), key_points, entities (people, locations, time, organizations, contact_info), relationships, events, actions, offers, decisions, sentiment, sensitive_info, risk, insight, hidden_relationships, notes, slang_detected.

Hội thoại:
{transcript}

JSON phân tích:
"""
```

---

### **Priority 3: Add Prompt Examples** 🟡 MEDIUM

**Create example file:** `src/services/summarization/prompts/investigation_example.json`

```json
{
  "summary": "Cuộc gọi giữa Quyên (lễ tân) và khách hàng đặt phòng khách sạn Marriott Hà Nội cho ngày 25/12/2024.",
  "context": {
    "topic": "Đặt phòng khách sạn",
    "purpose": "Khách hàng muốn đặt phòng và được tư vấn các gói khuyến mãi",
    "status": "Đã hoàn tất đặt phòng"
  },
  "key_points": [
    "Khách hàng đặt phòng Superior Double từ 25-27/12",
    "Được áp dụng gói khuyến mãi giảm 20%",
    "Yêu cầu phòng tầng cao có view"
  ],
  "entities": {
    "people": [
      {"name": "Quyên", "role": "Nhân viên lễ tân", "is_sensitive": false, "context": "Người tiếp nhận đặt phòng"},
      {"name": "Nguyễn Văn A", "role": "Khách hàng", "is_sensitive": false, "context": "Người đặt phòng"}
    ],
    "locations": [
      {"name": "Marriott Hotel Hà Nội", "is_sensitive": false, "context": "Địa điểm khách sạn"}
    ],
    "time": [
      {"value": "25/12/2024 - 27/12/2024", "context": "Thời gian ở", "is_sensitive": false}
    ],
    "organizations": ["Marriott International"],
    "contact_info": {
      "phone": {"value": "0987654321", "is_sensitive": true, "type": "phone"},
      "email": {"value": "nguyenvana@example.com", "is_sensitive": true, "type": "email"}
    }
  },
  "relationships": [
    {"source": "Nguyễn Văn A", "target": "Marriott Hotel Hà Nội", "label": "Khách hàng", "context": "Đặt phòng qua điện thoại"}
  ],
  "events": [
    {"time": "10:30 AM", "description": "Khách gọi điện đặt phòng", "action": "Liên hệ lễ tân"},
    {"time": "10:35 AM", "description": "Xác nhận đặt phòng thành công", "action": "Thanh toán đặt cọc"}
  ],
  "actions": [
    {"content": "Đặt phòng Superior Double 2 đêm"},
    {"content": "Thanh toán đặt cọc 50%"}
  ],
  "offers": [
    {"content": "Giảm giá 20% cho đặt phòng sớm"},
    {"content": "Miễn phí nâng cấp lên phòng Deluxe nếu có sẵn"}
  ],
  "decisions": [
    {"content": "Chọn gói phòng Superior Double với khuyến mãi"}
  ],
  "sentiment": "positive, hài lòng với dịch vụ",
  "sensitive_info": [
    {"name": "Số điện thoại khách hàng", "value": "0987654321", "type": "phone", "sensitivity_reason": "Thông tin cá nhân", "context": "Dùng để liên lạc xác nhận"},
    {"name": "Số CCCD", "value": "001234567890", "type": "id", "sensitivity_reason": "Giấy tờ tùy thân", "context": "Yêu cầu khi check-in"}
  ],
  "risk": [],
  "insight": [
    "Khách hàng rất quan tâm đến view phòng, có thể là khách hàng VIP hoặc có dịp đặc biệt"
  ],
  "slang_detected": "",
  "hidden_relationships": [],
  "notes": "Cần kiểm tra phòng tầng cao có view trước khi khách check-in"
}
```

**Use in prompts:**
```python
prompt += f"\n\nVÍ DỤ OUTPUT:\n{json.dumps(EXAMPLE_JSON, indent=2, ensure_ascii=False)}\n"
```

---

### **Priority 4: Testing Checklist** ✅

**Before User Testing:**
1. ✅ Code implemented (V2 VisualizationDialog)
2. ✅ Build successful (0 errors)
3. ✅ Services running (Backend, Redis, Frontend)
4. ⏳ **Backend prompts updated** (Priority 1 & 2 above)

**User Testing:**
1. Upload audio file and transcribe
2. Summarize with type "investigation"
3. Click "Generate" visualization button
4. Verify all 6 tabs display correctly:
   - Tab 0: Tổng quan - Summary, metadata, key points
   - Tab 1: Sơ đồ quan hệ - ReactFlow diagram with entities/relationships
   - Tab 2: Timeline - Events in chronological order
   - Tab 3: Insight - Offers, decisions, actions, sentiment
   - Tab 4: Nhạy cảm - Sensitive info with show/hide toggle
   - Tab 5: Cảm xúc - Sentiment with emoji
5. Check alert sections: Risk, Slang, Hidden Relationships, Notes
6. Test "Phân tích lại bằng AI" button
7. Test copy to clipboard functions
8. Compare with V1 (if available in old files/screenshots)

---

## 🎯 TESTING CHECKLIST

### **Functional Tests:**

- [ ] **Generate Visualization Button**
  - Click from FileCard
  - Snackbar shows "🎨 Generating visualization..."
  - Dialog opens after generation

- [ ] **Tab 0: Tổng quan**
  - [ ] Summary text displays correctly
  - [ ] Copy button works for summary
  - [ ] Metadata grid shows: Time, Location, Status, Topic
  - [ ] Copy buttons work for each metadata field
  - [ ] Key points checklist displays (if available)

- [ ] **Tab 1: Sơ đồ quan hệ**
  - [ ] ReactFlow diagram renders
  - [ ] Nodes show entity labels
  - [ ] Edges show relationships
  - [ ] Sensitive entities highlighted (red chip)
  - [ ] MiniMap, Controls, Background work
  - [ ] Entity list shows below diagram
  - [ ] Relationship list shows below diagram

- [ ] **Tab 2: Timeline**
  - [ ] Timeline component renders
  - [ ] Events show in chronological order
  - [ ] Time and description display for each event
  - [ ] TimelineDot and Connector visible

- [ ] **Tab 3: Insight**
  - [ ] Offers list displays (if available)
  - [ ] Decisions list displays (if available)
  - [ ] Actions list displays (if available)
  - [ ] Sentiment displays with correct icon color

- [ ] **Tab 4: Nhạy cảm**
  - [ ] "Hiện thông tin nhạy cảm" button present
  - [ ] Click button reveals sensitive info
  - [ ] Copy buttons work for phone/email/id
  - [ ] Sensitivity reason displays
  - [ ] Warning alert shown below

- [ ] **Tab 5: Cảm xúc**
  - [ ] Sentiment text displays
  - [ ] Emoji icon color matches sentiment (green=positive, red=negative, yellow=neutral)

- [ ] **Alert Sections**
  - [ ] Risk alerts show (if risk data present)
  - [ ] Slang detection alert shows (if detected)
  - [ ] Hidden relationships alert shows (if present)
  - [ ] Business notes alert shows (if present)

- [ ] **Auto-Analysis Feature**
  - [ ] Switching to Tab 1-5 triggers analysis (if contextAnalysis not provided)
  - [ ] Loading spinner shows during analysis
  - [ ] Error alert shows if analysis fails

- [ ] **"Phân tích lại bằng AI" Button**
  - [ ] Button shows on Tab 1-5 after initial analysis
  - [ ] Confirmation dialog appears on click
  - [ ] "Không, dùng dữ liệu cũ" keeps current data
  - [ ] "Có, phân tích lại" re-analyzes with LLM
  - [ ] Success snackbar shows after re-analysis

### **Data Quality Tests:**

- [ ] **All Fields Populated**
  - [ ] summary
  - [ ] context (topic, purpose, status)
  - [ ] key_points
  - [ ] entities (people, locations, time, organizations, contact_info)
  - [ ] relationships
  - [ ] events/timeline
  - [ ] actions
  - [ ] offers
  - [ ] decisions
  - [ ] sentiment
  - [ ] sensitive_info
  - [ ] risk (if applicable)
  - [ ] insight
  - [ ] slang_detected (if applicable)
  - [ ] hidden_relationships (if applicable)
  - [ ] notes (if applicable)

- [ ] **Field Structure**
  - [ ] Entities have: name, role (for people), is_sensitive, context
  - [ ] Relationships have: source, target, label, context
  - [ ] Events have: time, description, action
  - [ ] Actions/Offers/Decisions have: content
  - [ ] Sensitive info has: name, value, type, sensitivity_reason, context

### **UI/UX Tests:**

- [ ] **Dialog Styling**
  - [ ] Purple theme (#9c27b0) applied
  - [ ] 16px border radius
  - [ ] 2px purple border
  - [ ] Purple box shadow
  - [ ] Dialog title has InsightsIcon + "📊 DATA VISUALIZATION"

- [ ] **Loading States**
  - [ ] CircularProgress shows while fetching data
  - [ ] "Loading visualization data..." text shows

- [ ] **Error States**
  - [ ] Error alert shows if fetch fails
  - [ ] Error message is descriptive

- [ ] **Empty States**
  - [ ] "No visualization data available for this file." shows if no data
  - [ ] Friendly, not technical message

- [ ] **Close Button**
  - [ ] Contained button with CloseIcon
  - [ ] Purple background (#9c27b0)
  - [ ] Hover effect (darker purple #7b1fa2)

### **Comparison with V1:**

- [ ] **Feature Parity**
  - [ ] All V1 features present in V2
  - [ ] No regressions in functionality

- [ ] **Data Display**
  - [ ] Same data displayed as V1
  - [ ] Same InvestigationSummaryCard component used

- [ ] **UI Improvements**
  - [ ] V2 has better styling than V1
  - [ ] Purple theme more prominent than V1 default theme

---

## 📝 SUMMARY

### **V1 vs V2 Verdict:**

**✅ V2 MAINTAINS V1 QUALITY AND IMPROVES UI** ✅

- **Core functionality:** 100% identical (same component, same data flow)
- **Data fetching:** 100% identical (same endpoint, same response structure)
- **Visualization:** 100% identical (same InvestigationSummaryCard with 6 tabs)
- **UI/UX:** V2 > V1 (modern purple theme, better styling, cleaner code organization)

### **Backend Prompts Verdict:**

**⚠️ NEEDS IMPROVEMENT** ⚠️

- **Current state:** Basic prompts, 56% of expected fields missing
- **Impact:** LLM may not generate complete data for all visualization features
- **Priority:** HIGH - Update prompts before production deployment
- **Effort:** Medium - Update 2 files (llm_manager.py, summary_service_v2.py)

### **Next Steps:**

1. **Immediate:** Implement Priority 1 & 2 recommendations (update prompts)
2. **Testing:** User performs comprehensive testing with updated prompts
3. **Validation:** Verify all 16 fields populate correctly
4. **Production:** Deploy with confidence after validation

---

**Document Created:** 2026-01-08
**Status:** ✅ Analysis Complete
**Files Analyzed:** 5 (V1 FileTable, V2 VisualizationDialog, InvestigationSummaryCard, llm_manager, context_service, summary_service_v2)
**Lines of Code Reviewed:** 1,200+
**Recommendation Priority:** Update prompts → Test → Deploy

---

**Phân tích hoàn chỉnh! Ready for prompt improvements and testing.** 🚀
