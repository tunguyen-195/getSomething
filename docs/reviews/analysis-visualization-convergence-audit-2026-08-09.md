# Analysis / Data Visualization Convergence Audit - 2026-08-09

## Verdict

**BLOCK việc gộp UI cơ học.** Runtime hiện chỉ có một top-level tab `Analysis`, nhưng “Data Visualization” vẫn tồn tại như một action/dialog và nhiều pipeline backend khác nhau. Phải hợp nhất ownership của run, persistence và canonical data trước khi xóa UI thừa.

## Findings

### Critical

1. **Nhiều pipeline cùng sinh và ghi analysis**
   - Summarize sinh `context`, sau đó chạy thêm LLM extraction để tạo `visualization_data`: `src/services/summarization/summary_service_v2.py:128`, `src/services/summarization/summary_service_v2.py:284`, `src/services/summarization/summary_service_v2.py:313`.
   - `/api/v1/summaries/analyze` chạy context analysis riêng và ghi `Task.result.context_analysis`: `src/api/endpoints/summary.py:102`, `src/api/endpoints/summary.py:148`.
   - V1 và V2 có endpoint visualize riêng: `src/api/endpoints/audio.py:417`, `src/api/endpoints/audio_v2.py:271`.
   - Celery có `tasks.visualize`: `src/worker/tasks/visualize_task.py:12`.
   - `generate_visualization()` tự ghi DB, rồi endpoint/worker ghi lần nữa: `src/services/visualization_service.py:311`, `src/api/endpoints/audio_v2.py:293`, `src/worker/tasks/visualize_task.py:57`.

2. **Double-trigger và request-thread blocking vẫn khả thi**
   - Main App không truyền `processingTaskId` vào FileTable: `frontend/src/App.tsx:779`.
   - Nút Visualize không chặn `status === visualizing`: `frontend/src/components/FileTable.tsx:281`.
   - Backend không có idempotency key/active-run guard.
   - `visualize_v2` là `async def` nhưng gọi service/LLM đồng bộ, bypass Celery và có thể block event loop: `src/api/endpoints/audio_v2.py:271`, `src/api/endpoints/audio_v2.py:291`.
   - Polling completion có thể overwrite state của case mới do closure giữ `selectedCase`: `frontend/src/App.tsx:403`, `frontend/src/App.tsx:437`.

### High

3. **VisualizationDialog không render đúng artifact và có thể kích hoạt Analyze lần nữa**
   - Dialog không dùng `visualization_data`, mà truyền `summary/context_analysis` vào card: `frontend/src/components/VisualizationDialog.tsx:101`.
   - Card tự POST `/summaries/analyze` khi chuyển sub-tab và chưa có analysis: `frontend/src/components/InvestigationSummaryCard.tsx:83`.
   - Tab change đi thẳng `setTab`, bỏ qua confirm/dedupe handler: `frontend/src/components/InvestigationSummaryCard.tsx:215`, `frontend/src/components/InvestigationSummaryCard.tsx:228`.
   - Local `analysis` state không sync khi prop mới về: `frontend/src/components/InvestigationSummaryCard.tsx:76`.

4. **Analysis tab hiện tại bỏ qua artifact giàu nhất và làm mất provenance**
   - File eligible khi có summary hoặc visualization, nhưng thống kê chỉ đọc `visualization_data`: `frontend/src/components/AnalysisPanel.tsx:119`, `frontend/src/components/AnalysisPanel.tsx:130`.
   - Regex fallback đã tắt: `frontend/src/components/AnalysisPanel.tsx:164`.
   - `context_analysis` không nằm trong interface; `caseId` được nhận nhưng không dùng: `frontend/src/components/AnalysisPanel.tsx:46`, `frontend/src/components/AnalysisPanel.tsx:116`.
   - Exact values dedupe chỉ theo `value`, làm mất file/speaker/segment/time/owner/evidence: `frontend/src/components/AnalysisPanel.tsx:170`.

5. **Persistence không có analysis run production-grade**
   - Artifact/status nằm trong mutable `Task.result` JSON và một `Task.status`: `src/database/models/models.py:468`.
   - Status trộn transcription, summary và visualization lifecycle: `src/services/task_service.py:24`.
   - Không có `analysis_run_id`, source revision set, idempotency key, active/superseded run, manifest, atomic publish pointer hoặc append-only audit.
   - `Summary` table không sở hữu per-file analysis: `src/database/models/models.py:495`.

6. **Fact, insight, hypothesis và risk đang bị trộn**
   - Hypothesis được render trực tiếp thành alert “Nguy cơ/rủi ro”: `frontend/src/components/InvestigationSummaryCard.tsx:150`, `frontend/src/components/InvestigationSummaryCard.tsx:452`.
   - Facts xuất hiện lặp ở keypoints và insights: `frontend/src/components/InvestigationSummaryCard.tsx:143`, `frontend/src/components/InvestigationSummaryCard.tsx:152`.
   - Evidence chỉ là tooltip, không link tới file/segment/audio: `frontend/src/components/InvestigationSummaryCard.tsx:115`.
   - Repo đã có ranh giới contract tốt hơn trong `src/services/investigation/contracts.py:257`, `src/services/investigation/contracts.py:308`, `src/services/investigation/contracts.py:354`, `src/services/investigation/reasoning_contracts.py:18`, `src/services/investigation/reasoning_contracts.py:62`, `src/services/investigation/reasoning_contracts.py:105`.

### Medium

7. **Nhiều component trùng/dead**
   - `AnalysisPanel`, `InvestigationSummaryCard`, `VisualizationPanel`, `VisualizationDashboard` đều triển khai entities/timeline/events theo schema khác nhau.
   - `VisualizationPanel` và `VisualizationDashboard` không nằm trên main entrypoint; `VisualizationDialog` vẫn được App sử dụng.

8. **Blank-page fix chưa giải quyết kiến trúc duplicate pipeline**
   - Root cause cũ là render object `slang_detected`; formatter tests hiện PASS.
   - Tuy nhiên duplicate POST/write, stale state và request-thread inference vẫn còn trong source path.

## Runtime evidence

- `http://127.0.0.1:3000` trả `200`, title `Cherry2`.
- Playwright snapshot trên authenticated session hiển thị đúng một top-level tab `Analysis` và nội dung hiện chỉ gồm các stat/card cơ bản: Người, Địa điểm, Sự kiện, Timeline.
- Duplicate surface cần xóa là `Visualize` action + `VisualizationDialog` + các generation endpoint/worker song song, không phải tạo thêm/xóa nhầm top-level tab.
- Fresh reload mất session đăng nhập nên chưa tái hiện lại authenticated blank-page trên snapshot mới; đây là residual runtime uncertainty.

## Feature decision matrix

| Surface hiện tại | Quyết định |
|---|---|
| `AnalysisPanel` | Thay bằng typed Analysis Workspace; giữ ý tưởng case-wide overview nhưng thêm file scope và provenance |
| `InvestigationSummaryCard` | Tách thành presentational sections; giữ timeline/relation/evidence/copy; bỏ auto POST và hypothesis-as-risk |
| `VisualizationDialog` | Xóa sau compatibility cutover |
| `VisualizationPanel` | Archive/remove; chỉ giữ ý tưởng All files / selected file |
| `VisualizationDashboard` | Không dùng trực tiếp; tái sử dụng layout ideas sau khi đổi sang canonical contract |
| FileTable Visualize action | Đổi thành `Open Analysis` / `Run Analysis` với một run state duy nhất |
| `visualization_service` LLM generation | Xóa; visualization chỉ là deterministic projection/layout từ verified InvestigationRun |
| Summary analysis extraction | Xóa pipeline riêng; SummaryProjection và AnalysisProjection dùng cùng released claim ledger |

## Residual risks

- Hai security integration tests của visualize/analyze đang bị chặn vì test DB thiếu bảng `users`; endpoint convergence/auth chưa có bằng chứng PASS.
- T4 verification và T5 reasoning chưa hoàn tất; UI không được phép hiển thị T3 candidate như fact.
- Worktree frontend/backend đang có nhiều thay đổi chưa commit của người dùng; implementation phải tách commit và không overwrite các thay đổi đó.
