# activeContext.md

## Trọng tâm hiện tại
- Đã chuẩn hóa toàn bộ codebase, loại bỏ src/db, chỉ còn src/database
- Đã sửa toàn bộ import, đảm bảo không còn lỗi ModuleNotFoundError
- Đã hướng dẫn dọn cache, xóa pycache, khởi động lại môi trường
- Đã kiểm tra hoạt động hệ thống, ghi nhận các lỗi mới (middleware, 422)

## Thay đổi gần đây
- Sửa lỗi import schema, model, service, endpoint liên quan src.db → src.database
- Đã xóa hoàn toàn src/db và các file liên quan
- Đã hướng dẫn dọn sạch pycache, khởi động lại môi trường

## Bước tiếp theo
- Nghiên cứu lại logic middleware để sửa lỗi cấu hình CORS
- Nghiên cứu lại logic xử lý dữ liệu đầu vào để sửa lỗi 422 Unprocessable Entity
- Kiểm tra lại toàn bộ pipeline API, validate schema, request/response
