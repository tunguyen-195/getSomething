# Speech To Information

Ung dung FastAPI + React de upload audio, chuyen giong noi thanh van ban, tom tat,
phan tich ngu canh va truc quan hoa ket qua dieu tra.

## Tai lieu cai dat

Huong dan day du de clone va chay tren may moi nam tai:

- [docs/NEW_MACHINE_SETUP.md](docs/NEW_MACHINE_SETUP.md)
- [docs/MODEL_SETUP.md](docs/MODEL_SETUP.md)
- [docs/DEPLOY_LITE_RTX2050_WIN11.md](docs/DEPLOY_LITE_RTX2050_WIN11.md)

Doc nay bao gom:

- Cach chay nhanh Lite RTX2050.
- Cach chay local tren Windows theo profile Lite RTX2050 pull-ready.
- Cach tao `.env`, database, Redis, frontend.
- Cach bat/tat auth, tai khoan admin ban dau.
- Cach verify build/test/model sau khi cai.
- Luu y model/audio/runtime data khong commit len Git; model khong tai duoc thi copy thu cong tu bundle noi bo va verify.

## Cach chay nhanh Lite RTX2050 bang Docker

```powershell
git clone https://github.com/tunguyen-195/getSomething.git
cd getSomething
# Chi dung khi test PR hien tai. Sau khi merge, dung main va bo qua dong nay.
git checkout feature/architecture-refactor-pr
copy .env.lite.example .env
```

Sua `.env` toi thieu:

```env
SECRET_KEY=<generate-with-python-secrets>
INITIAL_ADMIN_PASSWORD=<your-admin-password>
POSTGRES_PASSWORD=<your-db-password>
```

Neu can bat Summary/LLM qua OpenRouter, them key vao `.env` tren may chay:

```env
ANALYSIS_LLM_PROVIDER=openrouter
ANALYSIS_LLM_BASE_URL=https://openrouter.ai/api/v1
ANALYSIS_LLM_MODEL=google/gemini-2.5-flash
ANALYSIS_LLM_FALLBACK_MODEL=openai/gpt-5-mini
ANALYSIS_LLM_API_KEY=<openrouter-api-key>
ANALYSIS_LLM_HTTP_REFERER=http://localhost:3000
ANALYSIS_LLM_APP_TITLE=SpeechToInformation Lite
```

Khong commit `.env` hoac API key. Neu thieu key, nut Summary bi tat va API tra `llm_not_configured`.
Kiem tra nhanh provider sau khi them key:

```powershell
docker compose --env-file .env run --rm backend python3 scripts/check_llm_provider.py
```

Generate `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Khoi dong Docker Lite. Script se build image, tai/verify public
`faster-whisper medium` theo manifest pinned, roi start backend/frontend/db/redis:

```powershell
.\START_DOCKER_LITE.bat
```

Neu khong dung Docker va muon chay local Python/Node, chuan bi model public Lite
truoc. Mac dinh Lite dung `faster-whisper medium` thay vi `small` de uu tien
transcript tieng Viet:

```powershell
python scripts\precache_lite_models.py --model medium
python scripts\verify_models.py --profile lite_rtx2050
```

`verify_models.py` uses pinned revision/hash metadata from
`docs/model_artifacts.required.json`; strict hash verification may take a few
seconds while reading `model.bin`.

Khoi dong local Lite:

```powershell
.\START_LITE_RTX2050.bat
```

Mo:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API docs dev: http://localhost:8000/docs

Sau khi sua code, build lai container:

```powershell
docker compose up -d --build
```

Neu can full/Celery worker optional:

```powershell
docker compose --profile full up -d --build
```

## Cach chay local tren Windows

Can cai truoc:

- Python 3.10 hoac 3.11
- Node.js 18+
- PostgreSQL 13+
- FFmpeg/ffprobe trong `PATH`
- Redis hoac Memurai chi can cho full/Celery; Lite RTX2050 khong can Redis/Celery.

```powershell
git clone https://github.com/tunguyen-195/getSomething.git
cd getSomething
# Chi dung khi test PR hien tai. Sau khi merge, dung main va bo qua dong nay.
git checkout feature/architecture-refactor-pr
copy .env.lite.example .env
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements-torch-cu121.txt --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
cd frontend
npm install
cd ..
python -m src.database.scripts.init_db
python scripts\precache_lite_models.py --model medium
python scripts\verify_models.py --profile lite_rtx2050
```

Chay cac service Lite:

```powershell
.\START_LITE_RTX2050.bat
```

`START_ALL_SERVICES.bat` van ton tai de tuong thich nguoc va se goi Lite starter. Hoac chay tung service:

```powershell
.\venv\Scripts\python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8000
cd frontend
npm run dev
```

Verify Lite GPU/model:

```powershell
python scripts\check_lite_runtime.py --gpu-smoke --offline-models-only
```

Full Cherry/PhoWhisper offline khong phai pull-ready default. Neu can full/offline, copy cac artifact khong tai duoc theo
[docs/MODEL_SETUP.md](docs/MODEL_SETUP.md) roi chay:

```powershell
python scripts\verify_models.py --profile full_offline
```

Khong commit model weights, public model cache, hoac bundle copy thu cong vao Git.

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
