# KIỂM TRA SCRIPTS QUẢN LÝ DỊCH VỤ

**Ngày:** 2026-01-08
**Mục đích:** Xác minh tính đúng đắn của các scripts start/stop services

---

## 📋 CÁC SCRIPTS HIỆN TẠI

### 1. START_ALL_SERVICES.bat
- ✅ Comprehensive nhất (có checking, verification)
- ✅ Kiểm tra Redis trước khi start
- ✅ Kiểm tra ports trước khi start
- ✅ Verify services sau khi start
- ❌ **SAI:** Celery concurrency = 1 (nên là 4)
- ❌ **THIẾU:** --logfile=celery.log
- ❌ **SAI:** -A src.worker (nên là -A src.worker.worker)
- ✅ Backend host: 0.0.0.0 (đúng)
- ❌ **THIẾU:** Không quản lý PostgreSQL

### 2. QUICK_START.bat
- ✅ Đơn giản, nhanh gọn
- ✅ Kiểm tra Redis
- ❌ **SAI:** Celery concurrency = 1 (nên là 4)
- ❌ **THIẾU:** --logfile=celery.log
- ❌ **SAI:** -A src.worker (nên là -A src.worker.worker)
- ✅ Backend host: 0.0.0.0 (đúng)
- ❌ **THIẾU:** Không quản lý PostgreSQL

### 3. START_SIMPLE.bat
- ✅ Rất đơn giản
- ❌ **THIẾU:** Không kiểm tra Redis
- ❌ **SAI:** Celery concurrency = 1 (nên là 4)
- ❌ **THIẾU:** --logfile=celery.log
- ❌ **SAI:** -A src.worker (nên là -A src.worker.worker)
- ❌ **SAI:** Backend host không chỉ định (default 127.0.0.1)
- ❌ **THIẾU:** Không quản lý PostgreSQL

### 4. STOP_ALL_SERVICES.bat
- ✅ Comprehensive
- ✅ Stop Frontend (ports 3000/5173)
- ✅ Stop Celery Worker
- ✅ Stop Backend (port 8000)
- ✅ Stop Redis Server
- ✅ Final cleanup check
- ❌ **THIẾU:** Không stop PostgreSQL (nếu đang chạy)

---

## ❌ CÁC VẤN ĐỀ PHÁT HIỆN

### Vấn đề 1: Celery Concurrency SAI
**Hiện tại:** Tất cả scripts dùng `--concurrency=1`
**Nên là:** `--concurrency=4` (cho gevent pool)

**Ảnh hưởng:**
- Chỉ xử lý 1 task đồng thời → CHẬM
- Không tận dụng được gevent pool
- Task queue sẽ bị tắc nghẽn nếu có nhiều file upload

### Vấn đề 2: Thiếu Celery Logfile
**Hiện tại:** Không có `--logfile=celery.log`
**Nên thêm:** `--logfile=celery.log`

**Ảnh hưởng:**
- Khó debug khi có lỗi
- Không có log file để kiểm tra lịch sử

### Vấn đề 3: Celery Module Path SAI
**Hiện tại:** `-A src.worker`
**Nên là:** `-A src.worker.worker`

**Ảnh hưởng:**
- Có thể start nhưng không load đúng tasks
- Import errors tiềm ẩn

### Vấn đề 4: Backend Host Binding
**START_SIMPLE.bat:** Không chỉ định `--host`
**Ảnh hưởng:**
- Chỉ bind 127.0.0.1 → Frontend không connect được nếu chạy trên máy khác
- Không accessible từ network

### Vấn đề 5: Thiếu PostgreSQL Management
**Tất cả scripts:** Không kiểm tra hay quản lý PostgreSQL

**Ảnh hưởng:**
- Nếu PostgreSQL không chạy → Backend sẽ fail
- Không có cách tự động start/stop PostgreSQL

---

## ✅ COMMAND CHÍNH XÁC

### Backend (FastAPI):
```batch
venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Celery Worker (Gevent Pool):
```batch
venv\Scripts\python.exe -m celery -A src.worker.worker worker --pool=gevent --concurrency=4 --loglevel=info --logfile=celery.log --without-heartbeat --without-gossip --without-mingle
```

### Frontend (React + Vite):
```batch
cd frontend && npm run dev
```

### Redis (nếu chưa có):
```batch
redis-server
```
hoặc
```batch
memurai
```

### PostgreSQL:
```batch
REM Check if PostgreSQL service is running
sc query postgresql-x64-15 | find "RUNNING" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Starting PostgreSQL service...
    net start postgresql-x64-15
)
```

---

## 🔧 CẦN SỬA

### Tất cả Start Scripts:
1. ✏️ Đổi `--concurrency=1` → `--concurrency=4`
2. ✏️ Thêm `--logfile=celery.log`
3. ✏️ Đổi `-A src.worker` → `-A src.worker.worker`
4. ✏️ Đảm bảo `--host 0.0.0.0` cho Backend
5. ✏️ Thêm PostgreSQL check/start

### START_ALL_SERVICES.bat (Ưu tiên):
Đây là script chính, nên fix đầu tiên.

---

## 📊 SO SÁNH TRƯỚC/SAU

### Celery Command:

**TRƯỚC (SAI):**
```batch
venv\Scripts\python.exe -m celery -A src.worker worker --pool=gevent --concurrency=1 --loglevel=info
```

**SAU (ĐÚNG):**
```batch
venv\Scripts\python.exe -m celery -A src.worker.worker worker --pool=gevent --concurrency=4 --loglevel=info --logfile=celery.log --without-heartbeat --without-gossip --without-mingle
```

**Thay đổi:**
- `src.worker` → `src.worker.worker` (đúng module path)
- `--concurrency=1` → `--concurrency=4` (tận dụng gevent)
- Thêm `--logfile=celery.log` (logging)
- Giữ nguyên `--without-heartbeat --without-gossip --without-mingle` (tối ưu)

---

## 🎯 KHUYẾN NGHỊ

### Ưu tiên 1: Fix START_ALL_SERVICES.bat
Script này comprehensive nhất, nên fix đầu tiên và dùng làm script chính.

### Ưu tiên 2: Fix QUICK_START.bat
Script nhanh gọn, dùng cho development.

### Ưu tiên 3: Fix START_SIMPLE.bat hoặc XÓA
Script này quá đơn giản và thiếu nhiều check → Có thể xóa hoặc update.

### Ưu tiên 4: Thêm PostgreSQL Management
Thêm check và start PostgreSQL service vào tất cả scripts.

---

## 📝 DỊCH VỤ CẦN QUẢN LÝ

### Core Services (Bắt buộc):
1. **PostgreSQL** (Database) - Port 5432
2. **Redis/Memurai** (Message Broker) - Port 6379
3. **Backend (FastAPI)** - Port 8000
4. **Celery Worker** - Background tasks
5. **Frontend (React + Vite)** - Port 3000/5173

### Thứ tự Start (Đúng):
1. PostgreSQL (Database trước)
2. Redis (Message broker)
3. Backend (API server)
4. Celery (Worker needs backend to be ready)
5. Frontend (UI cuối cùng)

### Thứ tự Stop (Ngược lại):
1. Frontend
2. Celery Worker
3. Backend
4. Redis
5. PostgreSQL (cuối cùng)

---

## ✅ KẾT LUẬN

**Trạng thái hiện tại:** ⚠️ SCRIPTS CÓ LỖI
- Celery concurrency sai → Hiệu suất thấp
- Thiếu PostgreSQL management → Dễ fail
- Thiếu logging → Khó debug

**Cần làm:**
1. Fix Celery parameters trong tất cả scripts
2. Thêm PostgreSQL check/start
3. Thêm --logfile cho Celery
4. Test lại tất cả scripts sau khi fix

**Ưu tiên:** FIX NGAY để tránh hiệu suất thấp và khó debug.

---

**Tài liệu này xác định các vấn đề cần fix trong scripts quản lý dịch vụ**
