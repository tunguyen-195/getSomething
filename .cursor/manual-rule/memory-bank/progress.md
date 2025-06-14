# Progress

## What Works
- Project structure and initial setup are in place.
- Core Memory Bank documentation initialized.
- API endpoints (bao gồm /cases) hoạt động đúng khi truy cập qua prefix /api/v1.
- Đã tự động fix lỗi frontend gọi sai API URL, đảm bảo frontend-backend đồng bộ.

## What's Left to Build
- Implement and document all major features (speech-to-text, information extraction, summarization, UI, API, etc.).
- Set up automated testing and CI/CD pipelines.
- Complete user and developer documentation.

## Current Status
- Memory Bank initialized and ready for use.
- Đã phát hiện và xác nhận lỗi 404 khi truy cập /cases là do nhầm lẫn prefix API (cần truy cập /api/v1/cases).
- Đã tự động sửa frontend để gọi đúng API backend.

## Known Issues
- No major issues at this stage; pending further development.
- Cần chú ý khi test API phải dùng đúng prefix (ví dụ: /api/v1/cases thay vì /cases). 