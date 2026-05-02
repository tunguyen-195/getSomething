# New Machine Setup

Tai lieu nay dung de cai du an tren mot may moi hoan toan tu Git.

## 1. Yeu cau chung

Bat buoc:

- Git
- Python 3.10 hoac 3.11
- Node.js 18+
- FFmpeg va ffprobe

Neu chay local khong Docker:

- PostgreSQL 13+
- Redis hoac Memurai

Neu chay Docker:

- Docker Desktop
- Docker Compose plugin
- NVIDIA Container Toolkit neu muon dung GPU trong container

## 2. Clone source

```powershell
git clone https://github.com/tunguyen-195/getSomething.git
cd getSomething
# Chi dung khi test PR hien tai. Sau khi merge, dung main va bo qua dong nay.
git checkout feature/architecture-refactor-pr
```

Kiem tra source:

```powershell
git status -sb
```

Mot clone sach nen khong co file modified/untracked.

## 3. Tao file cau hinh

```powershell
copy .env.example .env
```

Sua `.env` toi thieu:

```env
ENVIRONMENT=development
DEBUG=true
AUTH_ENABLED=false
INIT_DB_ON_STARTUP=true
ENABLE_API_DOCS=true

SECRET_KEY=<strong-random-secret>
INITIAL_ADMIN_PASSWORD=<admin-password>
POSTGRES_PASSWORD=<postgres-password>
```

Tao secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Ghi nho:

- `.env` khong duoc commit.
- `.env.example` la mau an toan de commit.
- Neu `AUTH_ENABLED=true`, login admin la `admin` va password la `INITIAL_ADMIN_PASSWORD` tai lan seed DB dau tien.

## 4. Chay bang Docker Compose

Day la cach de tai lap nhanh nhat tren may moi.

```powershell
docker compose up --build
```

Mo cac URL:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs dev: http://localhost:8000/docs

Dung service:

```powershell
docker compose down
```

Xoa ca volume DB/Redis neu muon tao lai tu dau:

```powershell
docker compose down -v
```

## 5. Chay local tren Windows

### 5.1. Cai Python dependencies

```powershell
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-torch-cu121.txt --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

Neu may khong co GPU NVIDIA/CUDA, co the cai torch CPU rieng theo huong dan PyTorch va van giu `requirements.txt` cho cac package con lai.

### 5.2. Cai frontend

```powershell
cd frontend
npm install
cd ..
```

### 5.3. Chuan bi PostgreSQL va Redis

Dat `DATABASE_URL` trong `.env` theo DB local, vi du:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/speech_to_information
REDIS_HOST=localhost
REDIS_PORT=6379
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

Tao database neu chua co:

```powershell
createdb -U postgres speech_to_information
```

Neu khong co `createdb` trong PATH, tao database bang pgAdmin.

### 5.4. Init database

```powershell
python -m src.database.scripts.init_db
```

Hoac de app tu init khi startup trong dev:

```env
INIT_DB_ON_STARTUP=true
```

Production nen dat `INIT_DB_ON_STARTUP=false` va chay migration/init bang quy trinh deploy rieng.

### 5.5. Start service

Cach nhanh:

```powershell
.\START_ALL_SERVICES.bat
```

Cach thu cong, moi lenh mot terminal:

```powershell
.\venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

```powershell
.\venv\Scripts\python.exe -m celery -A src.worker.worker worker --pool=solo --loglevel=info
```

```powershell
cd frontend
npm run dev
```

## 6. Models va du lieu runtime

Repo khong commit model nang, audio upload, log, cache hoac generated data.

Thu muc runtime:

- `models/`
- `storage/audio/`
- `uploads/`
- `logs/`
- `data/`

Neu workflow can model offline, copy model vao `models/` tren may moi va cau hinh path trong `.env`.

### 6.1. Optional Pyannote diarization

Pyannote diarization la tuy chon. Neu khong co token/model, app van chay, nhung speaker diarization bang Pyannote se
unavailable va workflow se tiep tuc voi fallback/no diarization.

De tai model:

1. Tren Hugging Face, accept conditions cho `pyannote/speaker-diarization-community-1`.
2. Neu muon fallback 3.1 hoat dong, accept conditions tuong ung cho `pyannote/speaker-diarization-3.1`.
3. Set `.env`:

```env
HF_TOKEN=<your-hugging-face-token>
PYANNOTE_MODEL_ID=pyannote/speaker-diarization-community-1
PYANNOTE_FALLBACK_MODEL_ID=pyannote/speaker-diarization-3.1
PYANNOTE_CACHE_DIR=models/pyannote
PYANNOTE_AUTO_DOWNLOAD=false
```

4. Tai model vao local snapshot:

```powershell
python download_pyannote_model.py
```

5. Verify:

```powershell
python -c "from src.services.transcription.models.pyannote_manager import get_pyannote_manager; print(get_pyannote_manager().is_available())"
```

Khong commit `models/`, Hugging Face cache, audio upload, log, cache hoac generated data.

## 7. Auth, cookie, CSRF

Dev local de de test:

```env
AUTH_ENABLED=false
COOKIE_SECURE=false
```

Production:

```env
ENVIRONMENT=production
DEBUG=false
AUTH_ENABLED=true
ENABLE_API_DOCS=false
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
SECRET_KEY=<strong-random-secret>
```

Neu frontend/backend khac site that su, can dung HTTPS, CORS origin chinh xac va cau hinh cookie domain/samesite phu hop.

## 8. Verification sau khi cai

Backend tests:

```powershell
python -m pytest tests -q
python -m compileall src -q
```

Frontend build:

```powershell
cd frontend
npm run build
cd ..
```

Cherry import smoke:

```powershell
python -c "from src.services.cherry_summarizer import check_cherry_core_available; from src.services.transcription.cherry_transcription_service import get_cherry_transcriber; from src.audio_processing.vad.silero_adapter import SileroVADAdapter; print('ok')"
```

Docker config:

```powershell
docker compose config --quiet
```

Docker backend build:

```powershell
docker compose build backend
```

## 9. Loi thuong gap

### Docker Desktop chua chay

Loi:

```text
dockerDesktopLinuxEngine pipe missing
```

Cach xu ly: mo Docker Desktop va doi engine san sang, sau do chay lai lenh Docker.

### Frontend khong goi duoc API

- Local dev dung Vite proxy `/api` sang backend port 8000.
- Docker frontend dung nginx proxy `/api/` sang service `backend:8000`.
- Kiem tra backend co chay tai http://localhost:8000 hay khong.

### Khong dang nhap duoc

- Neu `AUTH_ENABLED=false`, UI co the chay mode dev khong auth.
- Neu `AUTH_ENABLED=true`, dung username `admin` va password `INITIAL_ADMIN_PASSWORD`.
- Neu da init DB truoc khi doi `INITIAL_ADMIN_PASSWORD`, password cu van nam trong DB. Tao lai DB hoac doi password bang script/admin flow.

### Upload bi reject

He thong reject:

- File rong.
- File qua `MAX_UPLOAD_SIZE`.
- Extension khong nam trong `ALLOWED_EXTENSIONS`.
- Ten file co traversal nhu `../x.wav`.
- Noi dung khong phai audio hop le.

## 10. Checklist truoc khi push release

```powershell
python -m pytest tests -q
python -m compileall src -q
cd frontend
npm run build
cd ..
docker compose config --quiet
git diff --cached --check
git ls-files node_modules storage/audio __pycache__ *.pyc
```

Lenh `git ls-files ...` phai khong in ra file nao.
