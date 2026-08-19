# PROMPT FIX - NO MARKDOWN SYNTAX

**Date:** 2026-01-08
**Status:** ✅ COMPLETED

## Vấn Đề

Summary hiển thị trên web có markdown syntax (###, ***, ---) trông xấu vì không được render.

## Giải Pháp

Đã update investigation prompt để output **plain text** thay vì markdown.

## Files Modified

### src/services/summarization/summary_service_v2.py (Lines 76-179)

**Changes:**
- KHÔNG dùng markdown: ###, ***, ---, -, *
- Dùng số thứ tự: 1. 2. 3.
- Dùng xuống dòng để tổ chức
- Format template rõ ràng: "Họ tên đầy đủ: [...]"

**Example Output Format:**

```
1. TÓM TẮT TOÀN DIỆN
Cuộc gọi giữa khách hàng Quyên và nhân viên khách sạn...

2. THÔNG TIN NHÂN THÂN
Họ tên đầy đủ: Quyên (khách hàng)
Số điện thoại: 0987654321 (Quyên)
Địa chỉ: G.R.P.Marius Hotel Hà Nội
Email: quyen@example.com

3. THÔNG TIN TÀI CHÍNH
Số tiền giao dịch: 6.000.000 VND (tiền phòng 2 phòng x 1 đêm)
Phương thức thanh toán: Chuyển khoản
...
```

## Testing

### Backend Status
Backend đang chạy: http://localhost:8000
(Có reload loop do file changes, nhưng vẫn có thể respond requests)

### Test Steps
1. Upload audio file
2. Click Transcribe
3. Click Summarize (chọn type "investigation")
4. Kiểm tra kết quả:
   - ✅ KHÔNG còn ###, ***, ---
   - ✅ Format rõ ràng với số thứ tự
   - ✅ Thông tin nhân thân đầy đủ
   - ✅ Dễ đọc trên web

## Expected Result

**Before (với markdown):**
```
### 2. THÔNG TIN NHÂN THÂN
**Họ tên:** Quyên
- **Số điện thoại:** 0987654321
- **Email:** quyen@example.com
```
Hiển thị xấu trên web (raw markdown)

**After (plain text):**
```
2. THÔNG TIN NHÂN THÂN
Họ tên đầy đủ: Quyên (khách hàng)
Số điện thoại: 0987654321 (Quyên)
Email: quyen@example.com
```
Hiển thị đẹp, dễ đọc

## Backend Restart

Backend đã restart với prompt mới.
Có thể cần đợi 1-2 phút để reload loop ổn định.

## Summary

✅ Fixed investigation prompt - no markdown
✅ Plain text format with clear structure
✅ Backend restarted
⏳ Ready for testing

Test ngay tại: http://localhost:3002
