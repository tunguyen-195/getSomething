# New Machine Setup

Tai lieu nay dung de cai du an tren mot may moi hoan toan tu Git.

Pull-ready target hien tai la **Lite RTX2050**. Profile nay dung `faster_whisper_ct2`
`medium/cuda/int8` va `PROCESSING_RUNNER=single_job_db_lease`, khong bat buoc Redis,
Celery, Cherry full offline, PhoWhisper offline, hay Pyannote.

Full/offline Cherry/PhoWhisper la optional profile rieng. Cai model theo
[MODEL_SETUP.md](MODEL_SETUP.md) neu can.

## 1. Yeu cau chung

Bat buoc de chay Docker pull-ready:

- Git
- Docker Desktop
- Docker Compose plugin
- NVIDIA Container Toolkit neu muon dung GPU trong container

Neu chay local khong Docker moi can them:

- Python 3.10 hoac 3.11
- Node.js 18+
- FFmpeg va ffprobe
- PostgreSQL 13+
- Redis hoac Memurai chi can cho full/Celery. Lite RTX2050 khong can Redis/Celery.

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
copy .env.lite.example .env
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

Giu cac gia tri Lite quan trong:

```env
APP_EDITION=lite
PROCESSING_RUNNER=single_job_db_lease
ASR_PROVIDER=faster_whisper_ct2
ASR_PROFILE=balanced
WHISPER_MODEL=medium
WHISPER_MODEL_PATH=models/whisper
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=int8
DEFAULT_LANGUAGE=vi
ASR_GUARD_ENABLED=true
```

Khong doi `DEFAULT_LANGUAGE` sang `auto` cho file Viet/Anh-Viet. `auto` co the
nhan nham thanh ngon ngu khac tren audio ngan, nhieu, hoac co code-switch. Khi
can test audio khong ro ngon ngu, chon `Tu dong` trong UI va xem warning ASR.

Neu can bat Summary/LLM, dung OpenRouter server-side. Chi them key vao `.env` tren may chay, khong commit:

```env
ANALYSIS_LLM_PROVIDER=openrouter
ANALYSIS_LLM_BASE_URL=https://openrouter.ai/api/v1
ANALYSIS_LLM_MODEL=google/gemini-2.5-flash
ANALYSIS_LLM_FALLBACK_MODEL=openai/gpt-5-mini
ANALYSIS_LLM_API_KEY=<openrouter-api-key>
ANALYSIS_LLM_HTTP_REFERER=http://localhost:3000
ANALYSIS_LLM_APP_TITLE=SpeechToInformation Lite
```

`google/gemini-2.5-flash` la mac dinh vi phu hop transcript dai, tieng Viet va chi phi. Neu `ANALYSIS_LLM_API_KEY` de trong, workflow transcribe/visualize deterministic van chay, nhung Summary bi disable va API tra `llm_not_configured`.

Kiem tra nhanh OpenRouter sau khi them key:

```powershell
docker compose --env-file .env run --rm backend python3 scripts/check_llm_provider.py
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
.\START_DOCKER_LITE.bat
```

Script nay:

- build backend/frontend image;
- tai va verify public `faster-whisper medium` trong container;
- mount `models/`, `storage/audio/`, `uploads/`, `logs/`, `data/` lam du lieu runtime tren host;
- start backend, frontend, Postgres va Redis.

Neu muon chay thu cong:

```powershell
docker compose --env-file .env --profile setup build backend frontend model_sync
docker compose --env-file .env --profile setup run --rm model_sync
docker compose --env-file .env up -d --build
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

Sau khi sua code, build lai image de container nhan code moi:

```powershell
docker compose up -d --build
```

Neu can full/Celery worker optional:

```powershell
docker compose --profile full up -d --build
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

### 5.3. Chuan bi PostgreSQL

Dat `DATABASE_URL` trong `.env` theo DB local, vi du:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/speech_to_information
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

### 5.5. Tai/cache model Lite

Tai public faster-whisper medium vao cache local:

```powershell
python scripts\precache_lite_models.py --model medium
python scripts\verify_models.py --profile lite_rtx2050
```

`verify_models.py` is offline-first and checks pinned file metadata from
`docs/model_artifacts.required.json`. Strict hash verification may take a few
seconds while reading `model.bin`.

Neu may offline, copy cache public `models/whisper` da chuan bi san vao repo root, roi verify lai.

### 5.6. Start service

Cach nhanh:

```powershell
.\START_LITE_RTX2050.bat
```

`START_ALL_SERVICES.bat` van ton tai de tuong thich nguoc va se goi Lite starter.

Cach thu cong, moi lenh mot terminal:

```powershell
.\venv\Scripts\python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

```powershell
cd frontend
npm run dev
```

## 6. Models va du lieu runtime

Repo khong commit model nang, public model cache, audio upload, log, cache hoac generated data.

Thu muc runtime:

- `models/`
- `storage/audio/`
- `uploads/`
- `logs/`
- `data/`

Model contract chinh thuc nam o:

- [MODEL_SETUP.md](MODEL_SETUP.md)
- [model_artifacts.required.json](model_artifacts.required.json)

Pull-ready Lite bat buoc co `faster_whisper_medium` de uu tien transcript tieng Viet. `faster_whisper_small` chi la fallback nhanh. Full/offline Cherry/PhoWhisper can copy thu cong cac artifact khong
tai duoc theo manifest rieng va khong block Lite setup.

Verify:

```powershell
python scripts\verify_models.py --profile lite_rtx2050
python scripts\check_lite_runtime.py --gpu-smoke --offline-models-only
```

Neu workflow can full/offline model, copy manual bundle vao `models/` tren may moi va cau hinh path trong `.env`.

### 6.1. Optional Pyannote diarization

Pyannote diarization la tuy chon. Neu khong co token/model, app van chay va backend se fallback sang
`SimpleVAD` khi nguoi dung bat Diarization. Fallback nay co speaker label de hien thi UI, nhung do chinh xac
kem Pyannote va can review lai.

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

5. Neu can gui model sang may offline, pack thanh zip:

```powershell
python scripts\pack_pyannote_model.py
```

Huong dan copy/extract chi tiet nam trong [PYANNOTE_DIARIZATION_TRANSFER.md](PYANNOTE_DIARIZATION_TRANSFER.md).

6. Verify:

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

Lite runtime smoke:

```powershell
python scripts\verify_models.py --profile lite_rtx2050
python scripts\check_lite_runtime.py --gpu-smoke --offline-models-only
```

Cherry import smoke chi dung sau khi cai private full/offline bundle:

```powershell
python scripts\verify_models.py --profile full_offline
python -c "from src.services.cherry_summarizer import check_cherry_core_available; from src.services.transcription.cherry_transcription_service import get_cherry_transcriber; from src.audio_processing.vad.silero_adapter import SileroVADAdapter; print('ok')"
```

Docker config:

```powershell
docker compose config --quiet
```

Docker build:

```powershell
docker compose build backend frontend
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
