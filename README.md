# Speech To Information

Ung dung FastAPI + React de upload audio, chuyen giong noi thanh van ban, tom tat,
phan tich ngu canh va truc quan hoa ket qua dieu tra.

## Tai lieu cai dat

Huong dan day du de clone va chay tren may moi nam tai:

- [docs/NEW_MACHINE_SETUP.md](docs/NEW_MACHINE_SETUP.md)

Doc nay bao gom:

- Cach chay nhanh bang Docker Compose.
- Cach chay local tren Windows.
- Cach tao `.env`, database, Redis, frontend.
- Cach bat/tat auth, tai khoan admin ban dau.
- Cach verify build/test sau khi cai.
- Luu y model/audio/runtime data khong commit len Git.

## Cach chay nhanh bang Docker

```powershell
git clone https://github.com/tunguyen-195/getSomething.git
cd getSomething
# Chi dung khi test PR hien tai. Sau khi merge, dung main va bo qua dong nay.
git checkout feature/architecture-refactor-pr
copy .env.example .env
```

Sua `.env` toi thieu:

```env
SECRET_KEY=<generate-with-python-secrets>
INITIAL_ADMIN_PASSWORD=<your-admin-password>
POSTGRES_PASSWORD=<your-db-password>
```

Generate `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Khoi dong:

```powershell
docker compose up --build
```

Mo:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs dev: http://localhost:8000/docs

## Cach chay local tren Windows

Can cai truoc:

- Python 3.10 hoac 3.11
- Node.js 18+
- PostgreSQL 13+
- Redis hoac Memurai
- FFmpeg/ffprobe trong `PATH`

```powershell
git clone https://github.com/tunguyen-195/getSomething.git
cd getSomething
# Chi dung khi test PR hien tai. Sau khi merge, dung main va bo qua dong nay.
git checkout feature/architecture-refactor-pr
copy .env.example .env
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements-torch-cu121.txt --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
cd frontend
npm install
cd ..
python -m src.database.scripts.init_db
```

Chay cac service:

```powershell
.\START_ALL_SERVICES.bat
```

Hoac chay tung service:

```powershell
.\venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
.\venv\Scripts\python.exe -m celery -A src.worker.worker worker --pool=solo --loglevel=info
cd frontend
npm run dev
```

## Auth va tai khoan admin

Mac dinh dev co the dat:

```env
AUTH_ENABLED=false
INIT_DB_ON_STARTUP=true
```

Khi bat auth:

```env
AUTH_ENABLED=true
INITIAL_ADMIN_PASSWORD=<your-admin-password>
```

Tai khoan admin mac dinh duoc seed khi init DB:

- Username: `admin`
- Password: gia tri `INITIAL_ADMIN_PASSWORD`

Production phai dat:

```env
ENVIRONMENT=production
DEBUG=false
AUTH_ENABLED=true
ENABLE_API_DOCS=false
COOKIE_SECURE=true
SECRET_KEY=<strong-random-secret>
```

## Optional Pyannote diarization

Pyannote diarization can chuan bi rieng vi model gated tren Hugging Face. App van chay neu thieu token/model, nhung
Pyannote diarization se unavailable.

```env
HF_TOKEN=<your-hugging-face-token>
PYANNOTE_MODEL_ID=pyannote/speaker-diarization-community-1
PYANNOTE_FALLBACK_MODEL_ID=pyannote/speaker-diarization-3.1
PYANNOTE_CACHE_DIR=models/pyannote
PYANNOTE_AUTO_DOWNLOAD=false
```

Can accept conditions cho `pyannote/speaker-diarization-community-1` tren Hugging Face. Neu muon fallback 3.1 hoat
dong, cung accept/license `pyannote/speaker-diarization-3.1`.

Tai model vao local snapshot:

```powershell
python download_pyannote_model.py
```

Verify:

```powershell
python -c "from src.services.transcription.models.pyannote_manager import get_pyannote_manager; print(get_pyannote_manager().is_available())"
```

## Verification

```powershell
python -m pytest tests -q
python -m compileall src -q
cd frontend
npm run build
cd ..
docker compose config --quiet
```

Neu Docker Desktop dang chay:

```powershell
docker compose build backend
```

## Thu muc runtime khong nam trong Git

Nhung thu muc/file sau duoc tao lai tren may moi hoac tai rieng:

- `node_modules/`, `frontend/node_modules/`
- `venv/`
- `storage/audio/`
- `uploads/`
- `logs/`
- `models/`
- `data/`

Audio, model, log va cache khong nen commit len Git.
