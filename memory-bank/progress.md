# progress.md

## Đã hoàn thành
- Đã chuẩn hóa toàn bộ codebase, loại bỏ src/db, chỉ còn src/database
- Đã sửa toàn bộ import, endpoint, service, test liên quan src.db
- Đã hướng dẫn dọn sạch pycache, khởi động lại môi trường
- Đã kiểm tra lại hoạt động hệ thống, backend đã chạy, API trả về dữ liệu

## Còn lại
- Sửa lỗi cấu hình middleware (CORS)
- Sửa lỗi 422 Unprocessable Entity khi gửi request tới API
- Kiểm tra lại validate schema, pipeline xử lý dữ liệu đầu vào
- Rà soát lại toàn bộ logic API, frontend-backend

## Vấn đề/ghi chú
- Lỗi middleware có thể do logic kiểm tra dư thừa trong startup_event hoặc do cache cũ
- Lỗi 422 có thể do frontend gửi sai schema hoặc backend validate chưa đúng
