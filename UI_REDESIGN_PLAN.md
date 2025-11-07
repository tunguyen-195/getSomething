# 🍒 Cherry2 UI Redesign - Workflow Separation

## 🎨 Design Vibe (Cherry2 Theme)

**Color Scheme:**
```
Primary:   #d32f2f (Cherry Red) - Main actions, highlights
Secondary: #ffd600 (Bright Yellow) - Accents, borders, attention
Success:   #43a047 (Green) - Completed states
Info:      #1976d2 (Blue) - Information, links
Warning:   #ff9800 (Orange) - Processing states
```

**Typography:** Poppins (bold 700-900), rounded corners 16px, soft shadows with red glow

**Branding:** "Cherry**2**" với gradient animation trên số "2"

---

## 📋 Current Problems

**Workflow hiện tại:**
```
Upload → Process (Transcribe + Summary + Diarization tất cả cùng lúc)
```

**Issues:**
- ❌ Không rõ từng bước xử lý
- ❌ Không chọn được diarization ON/OFF
- ❌ Không có nút riêng Summary và Visualization  
- ❌ Logic gộp chung, khó debug và kiểm soát

---

## 🎯 New Workflow Design

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   UPLOAD    │ →  │  TRANSCRIBE  │ →  │  SUMMARIZE  │ →  │  VISUALIZE   │
│   📁 File    │    │  🎙️ Audio     │    │  📝 AI       │    │  📊 Graph    │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
   Status:            Status:             Status:            Status:
   uploaded           transcribing        summarizing        ready
                      transcribed         summarized
```

**Each step independent & optional!**

---

## 🏗️ New UI Layout

### Main Screen Structure

```
┌────────────────────────────────────────────────────────────────┐
│ 🍒 Cherry2 Logo        [Search...]         🌓 Theme    [@User] │
├──────────┬─────────────────────────────────────────────────────┤
│ SIDEBAR  │ MAIN CONTENT AREA                                   │
│          │                                                     │
│ Cases    │ ┌───────────────────────────────────────────────┐ │
│ ┌──────┐ │ │ 📤 UPLOAD ZONE                                │ │
│ │Case 1│ │ │ Drag & Drop or Click to Upload                │ │
│ └──────┘ │ │ Supported: MP3, WAV, M4A, OGG                 │ │
│ ┌──────┐ │ └───────────────────────────────────────────────┘ │
│ │Case 2│ │                                                     │
│ └──────┘ │ ┌───────────────────────────────────────────────┐ │
│          │ │ 📂 FILES IN THIS CASE                         │ │
│ [+ New]  │ ├───────────────────────────────────────────────┤ │
│          │ │ ┌─────────────────────────────────────────┐   │ │
│          │ │ │ 🎵 audio1.mp3         Status: uploaded  │   │ │
│          │ │ │ Duration: 5:23       Size: 12.4 MB      │   │ │
│          │ │ │                                         │   │ │
│          │ │ │ Actions:                                │   │ │
│          │ │ │ [🎙️ Transcribe] [📝 Summary] [📊 Viz]   │   │ │
│          │ │ └─────────────────────────────────────────┘   │ │
│          │ │                                                 │ │
│          │ │ ┌─────────────────────────────────────────┐   │ │
│          │ │ │ 🎵 audio2.mp3    Status: transcribed ✅ │   │ │
│          │ │ │ Speakers: 2      Duration: 3:45         │   │ │
│          │ │ │                                         │   │ │
│          │ │ │ Actions:                                │   │ │
│          │ │ │ [🔄 Re-transcript] [📝 Summary] [📊 Viz]│   │ │
│          │ │ └─────────────────────────────────────────┘   │ │
│          │ └───────────────────────────────────────────────┘ │
│          │                                                     │
│          │ ┌───────────────────────────────────────────────┐ │
│          │ │ 📄 SELECTED FILE: audio2.mp3                 │ │
│          │ ├───────────────────────────────────────────────┤ │
│          │ │ Tabs: [📝 Transcript] [📋 Summary] [📊 Viz]  │ │
│          │ │                                               │ │
│          │ │ [Content Area - Shows selected tab content]  │ │
│          │ │                                               │ │
│          │ └───────────────────────────────────────────────┘ │
└──────────┴─────────────────────────────────────────────────────┘
```

---

## 🎨 File Card Design (Cherry2 Style)

```
┌─────────────────────────────────────────────────────┐
│ 🎵 meeting_recording.mp3                            │
├─────────────────────────────────────────────────────┤
│                                                     │
│ ⏱️  Duration: 5:23    💾 Size: 12.4 MB              │
│ 👥 Speakers: 2       📅 2025-11-07 14:30            │
│                                                     │
│ Status: ● TRANSCRIBED ✅                            │
│                                                     │
│ ┌─────────────────────────────────────────────────┐│
│ │ ACTIONS                                         ││
│ ├─────────────────────────────────────────────────┤│
│ │                                                 ││
│ │  🎙️  TRANSCRIBE                                 ││
│ │     ├─ ✅ Done (2 speakers detected)             ││
│ │     └─ [⚙️ Settings] [🔄 Re-run]                 ││
│ │                                                 ││
│ │  📝 SUMMARIZE                                   ││
│ │     ├─ ⏳ Not started                            ││
│ │     └─ [▶️ Start] [Model: Gemma2 9B ▼]          ││
│ │                                                 ││
│ │  📊 VISUALIZE                                   ││
│ │     ├─ ⏳ Not started                            ││
│ │     └─ [▶️ Generate]                             ││
│ │                                                 ││
│ └─────────────────────────────────────────────────┘│
│                                                     │
│ [🔽 View Transcript] [🗑️ Delete] [⚙️ More]          │
└─────────────────────────────────────────────────────┘
```

**Status Indicators (với màu Cherry2):**
- 🔵 **uploaded** - Blue ring, waiting to process
- 🟡 **transcribing** - Yellow spinner + Cherry red glow
- 🟢 **transcribed** - Green checkmark
- 🟠 **summarizing** - Orange spinner
- 🟣 **summarized** - Purple badge
- 🔴 **failed** - Red X with retry button

---

## 🎬 Action Dialogs

### 1. Transcribe Dialog (Cherry2 Styled)

```
┌────────────────────────────────────────────────────┐
│ 🎙️ TRANSCRIBE AUDIO                               │
├────────────────────────────────────────────────────┤
│                                                    │
│ File: meeting_recording.mp3                       │
│ Duration: 5:23                                    │
│                                                    │
│ ┌────────────────────────────────────────────────┐│
│ │ OPTIONS                                        ││
│ ├────────────────────────────────────────────────┤│
│ │                                                ││
│ │ 👥 SPEAKER DIARIZATION                         ││
│ │    ☑️ Enable (detect multiple speakers)        ││
│ │                                                ││
│ │    Method: [▼ Pyannote (Recommended)]          ││
│ │    Options: • Pyannote (Best quality)          ││
│ │             • SimpleVAD (Faster)               ││
│ │             • None (Single speaker)            ││
│ │                                                ││
│ │ ⚡ PROCESSING MODE                             ││
│ │    ☑️ Fast Mode (Skip heavy post-processing)   ││
│ │       ~10x faster, good for quick preview      ││
│ │                                                ││
│ └────────────────────────────────────────────────┘│
│                                                    │
│ ⏱️ Estimated time: ~32 seconds                     │
│                                                    │
│ [❌ Cancel]                  [🎙️ Start Transcribe] │
└────────────────────────────────────────────────────┘
```

### 2. Summarize Dialog

```
┌────────────────────────────────────────────────────┐
│ 📝 SUMMARIZE TRANSCRIPT                            │
├────────────────────────────────────────────────────┤
│                                                    │
│ Transcript: 3,245 words                           │
│ Speakers: 2 detected                              │
│                                                    │
│ ┌────────────────────────────────────────────────┐│
│ │ AI MODEL SELECTION                             ││
│ ├────────────────────────────────────────────────┤│
│ │                                                ││
│ │ [▼ Gemma 2 9B (Recommended)]                   ││
│ │                                                ││
│ │ Available Models:                              ││
│ │ • Gemma2 9B      - Most powerful, detailed     ││
│ │ • DeepSeek R1 7B - Language analysis expert    ││
│ │ • Mistral 7B     - Balanced performance        ││
│ │ • Llama 3.2 3B   - Fast, lightweight           ││
│ │                                                ││
│ ├────────────────────────────────────────────────┤│
│ │ SUMMARY TYPE                                   ││
│ │ ○ Brief (Key points only)                      ││
│ │ ● Detailed (Full analysis)                     ││
│ │ ○ Investigation (For police work)              ││
│ │                                                ││
│ ├────────────────────────────────────────────────┤│
│ │ OPTIONS                                        ││
│ │ ☑️ Context Analysis (entities, actions)        ││
│ │ ☑️ Key Points Extraction                       ││
│ │ ☑️ Privacy & Sensitive Info Detection          ││
│ │                                                ││
│ └────────────────────────────────────────────────┘│
│                                                    │
│ ⏱️ Estimated time: ~15 seconds                     │
│                                                    │
│ [❌ Cancel]                     [📝 Start Summary] │
└────────────────────────────────────────────────────┘
```

### 3. Visualization Panel

```
┌────────────────────────────────────────────────────────┐
│ 📊 VISUALIZATION                                       │
├────────────────────────────────────────────────────────┤
│                                                        │
│ Type: [Timeline ▼] [Entity Graph] [Relationship Map]  │
│                                                        │
│ ┌────────────────────────────────────────────────────┐│
│ │                                                    ││
│ │  [Interactive Visualization Area]                 ││
│ │                                                    ││
│ │  Timeline View:                                   ││
│ │  ━━━━━●━━━━━━━━●━━━━━●━━━━━━→                    ││
│ │  00:00  00:45     02:15  03:30  05:23            ││
│ │         │         │      │                        ││
│ │         Event 1   Event2 Event3                   ││
│ │                                                    ││
│ │  Entity Graph:                                    ││
│ │       (Person A) ──relates to──> (Person B)      ││
│ │           │                          │            ││
│ │        at Location X              at Event Y      ││
│ │                                                    ││
│ └────────────────────────────────────────────────────┘│
│                                                        │
│ Controls:                                             │
│ [🔍 Zoom] [⬅️ Pan] [🔄 Reset] [💾 Export PNG/JSON]     │
│                                                        │
│ [❌ Close]                        [🔄 Regenerate]      │
└────────────────────────────────────────────────────────┘
```

---

## 🔧 Backend API Endpoints (New)

### 1. Transcribe Endpoint
```
POST /api/v1/audio/transcribe/{task_id}
Body: {
  "enable_diarization": true,
  "diarization_method": "pyannote" | "simple_vad" | "none",
  "fast_mode": true
}
Response: {
  "task_id": "uuid",
  "status": "processing" | "completed",
  "transcript": "Full text...",
  "segments": [
    {
      "start": 0.0,
      "end": 5.2,
      "text": "Hello...",
      "speaker": "SPEAKER_00"
    }
  ],
  "num_speakers": 2,
  "duration": 323.5,
  "processing_time": 32.1
}
```

### 2. Summarize Endpoint  
```
POST /api/v1/audio/summarize/{task_id}
Body: {
  "model_name": "gemma2:9b",
  "summary_type": "detailed",
  "include_context_analysis": true
}
Response: {
  "summary": "Summary text...",
  "key_points": ["Point 1", "Point 2"],
  "context_analysis": {
    "entities": {...},
    "actions": [...],
    "privacy_summary": "..."
  }
}
```

### 3. Visualize Endpoint
```
POST /api/v1/audio/visualize/{task_id}
Body: {
  "visualization_type": "timeline" | "entity_graph" | "all"
}
Response: {
  "nodes": [{id, type, label}],
  "edges": [{source, target, label}],
  "timeline": [{time, event}],
  "entity_types": ["person", "location", "time"],
  "main_events": [...]
}
```

---

## 📊 Task Status Flow

```
uploaded 
   ↓
[Click Transcribe]
   ↓
transcribing (⏳ yellow spinner)
   ↓
transcribed (✅ green badge)
   ↓
[Click Summarize]
   ↓
summarizing (⏳ orange spinner)
   ↓
summarized (🟣 purple badge)
   ↓
[Click Visualize]
   ↓
visualization_ready (📊 ready to view)
```

---

## 🎨 Cherry2 Component Styling

```tsx
// Button styles (Cherry2 theme)
<Button
  variant="contained"
  sx={{
    bgcolor: '#d32f2f',
    color: '#fff',
    fontWeight: 700,
    borderRadius: '8px',
    textTransform: 'none',
    boxShadow: '0 4px 12px rgba(211, 47, 47, 0.3)',
    border: '2px solid #ffd600',
    '&:hover': {
      bgcolor: '#b71c1c',
      boxShadow: '0 6px 20px rgba(211, 47, 47, 0.5)',
    }
  }}
>
  Start Transcribe
</Button>

// Card styles (Cherry2 theme)
<Card
  sx={{
    borderRadius: '16px',
    boxShadow: '0 4px 24px rgba(211, 47, 47, 0.08)',
    border: '1px solid rgba(255, 214, 0, 0.3)',
    transition: 'all 0.3s',
    '&:hover': {
      boxShadow: '0 8px 32px rgba(211, 47, 47, 0.15)',
      transform: 'translateY(-4px)',
    }
  }}
>
```

---

## 🚀 Implementation Plan

### Phase 1: Backend API ✅ (Priority: CRITICAL)
- [ ] Create `/api/v1/audio/transcribe/{task_id}` endpoint
- [ ] Separate transcribe logic (copy from process_task, remove summary)
- [ ] Update `/api/v1/audio/summarize/{task_id}` (make it work on existing transcript)
- [ ] Create `/api/v1/audio/visualize/{task_id}` endpoint
- [ ] Add status tracking: uploaded → transcribing → transcribed → summarizing → summarized

### Phase 2: React Components ✅ (Priority: HIGH)
- [ ] `FileCard.tsx` - New card design với action buttons
- [ ] `TranscribeDialog.tsx` - Dialog với diarization options
- [ ] `SummarizeDialog.tsx` - Dialog với AI model selection
- [ ] `VisualizationPanel.tsx` - Panel với interactive viz
- [ ] `ActionButton.tsx` - Reusable button component với Cherry2 style
- [ ] `StatusBadge.tsx` - Status indicator với colors

### Phase 3: State Management (Priority: MEDIUM)
- [ ] Add file-level state tracking (which step completed)
- [ ] Add polling mechanism cho async operations
- [ ] Add error handling cho từng step
- [ ] Add progress indicators

### Phase 4: Testing (Priority: HIGH)
- [ ] Test upload flow
- [ ] Test transcribe với/không diarization
- [ ] Test summarize với different models
- [ ] Test visualization rendering
- [ ] Test error cases

---

## 📝 Success Criteria

✅ User có thể upload file mà không auto-process  
✅ User có thể click "Transcribe" riêng với options  
✅ User có thể chọn có/không diarization  
✅ User có thể click "Summarize" riêng với AI model selection  
✅ User có thể click "Visualize" để xem graph  
✅ Từng bước có status indicator rõ ràng  
✅ Có thể re-run bất kỳ step nào  
✅ UI giữ nguyên Cherry2 theme (red, yellow, green accents)  

---

**Ready to implement?** 🍒🚀