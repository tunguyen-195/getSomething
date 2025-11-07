# Service Management Scripts

4 batch scripts để quản lý toàn bộ hệ thống.

## Scripts

1. START_ALL_SERVICES.bat - Khởi động tất cả services
2. STOP_ALL_SERVICES.bat - Dừng tất cả services  
3. RESTART_ALL_SERVICES.bat - Khởi động lại
4. CHECK_SERVICES_STATUS.bat - Kiểm tra status

## Usage

Khởi động: START_ALL_SERVICES.bat
Dừng: STOP_ALL_SERVICES.bat
Check: CHECK_SERVICES_STATUS.bat

Services bao gồm:
- Redis (port 6379)
- Backend (http://localhost:8000)
- Celery Worker
- Frontend (http://localhost:3000)