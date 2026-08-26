# New Machine Setup

Tai lieu nay la runbook canonical de tao mot moi truong development/staging tu
clean clone tren Windows. Tat ca download model/runtime deu do operator chay ro
rang trong buoc cai dat; backend, Celery va UI khong duoc tu download local LLM.

Production offline bundle hien van **BLOCKED**. Khong dung runbook online nay de
tuyen bo mot Git clone la production-portable.

Runbook nay co hai pha:

1. **Bootstrap co mang:** cai toolchain, tao venv, cai wheel, tai model/runtime
   theo manifest va chay hash/preflight.
2. **Runtime offline:** sau khi tat ca gate PASS, dat cac co offline trong `.env`
   va Windows process; backend, Celery, ASR va LLM chi doc artifact local, khong
   tu tai model. Khong xoa artifact sau khi ngat mang.

Neu may dich khong co Internet ngay tu dau, can chuan bi mot goi air-gapped
   rieng gom installer Windows, Python wheelhouse, npm cache va tat ca artifact
   trong muc 6, roi copy vao may dich. Repo Git hien **khong** chua goi nay; muc
   12 la gate trung thuc cho production offline bundle.

## 0. Cai may Windows trang

Mo PowerShell **Run as Administrator** tren may dich, cai Windows Update va
restart truoc. Khong cai Ollama, WSL, Docker hay CUDA Toolkit de chay baseline;
llama-server da kem CUDA runtime trong artifact rieng, con PyTorch dung wheel
`cu121`. Docker Compose chi danh cho profile bridge co sidecar LLM, khong phai
duong chay native canonical.

### 0.1. Driver va phan cung

May dich theo hai anh: `i9-12900K`, 32 GB RAM, `RTX 3060 12 GB`, Windows 11 Pro
25H2 x64, con khoang 844 GB. Cau hinh dat profile `gpu12gb` nhung chua co bang
chung ve driver. Cai NVIDIA Studio/Game Ready driver moi nhat tu NVIDIA, chon
clean installation neu may sach, restart, roi kiem tra:

```powershell
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free `
  --format=csv,noheader
```

Phai thay `RTX 3060`, tong VRAM >= `12000 MiB`, va free VRAM >= `7000 MiB` khi
chay preflight. Neu `nvidia-smi` khong ton tai hoac PyTorch/llama probe fail,
khong tiep tuc voi GPU profile; sua driver roi chay lai gate. CPU fallback la
`-HardwareProfile cpu`, nhung khong co cam ket latency.

### 0.2. Toolchain host

Khong dung phien ban moi nhat khong duoc kiem tra. Cac lenh `winget` sau la
duong cai nhanh; neu catalog da tro sang phien ban khac, agent phai dung
installer chinh thuc co phien ban trong bang va xac nhan bang lenh version:

| Thanh phan | Phien ban baseline | Lenh/nguon cai |
| --- | --- | --- |
| Git | 2.x x64 | `winget install --id Git.Git --exact --source winget` |
| Python | 3.11.9 x64 | `winget install --id Python.Python.3.11 --exact --source winget` |
| Node.js | 22.x x64, npm >= 10 | `winget install --id OpenJS.NodeJS.22 --exact --source winget` |
| Visual Studio Build Tools | 2022, C++ workload | `winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --source winget` |
| PostgreSQL | 17.x x64 | `winget install --id PostgreSQL.PostgreSQL.17 --exact --source winget` |
| Redis-compatible queue | Memurai Developer 4.1.x hoac Redis Windows-compatible | `winget install --id Memurai.MemuraiDeveloper --exact --source winget` |
| FFmpeg | 7.1.1 full build da validate | Tai ban x64 full build tu nguon FFmpeg/Gyan, them `bin` vao `PATH` |

Khi cai Build Tools, chon workload `Desktop development with C++` va Windows
SDK. Neu dung winget, co the mo installer roi chon workload bang giao dien;
khong bo qua MSVC vi `llama-cpp-python==0.3.16` can C++ build phu hop. FFmpeg
khong dung ban `winget` floating neu no da len 8/9; kiem tra:

```powershell
git --version
py -3.11 --version
node --version
npm --version
ffmpeg -version | Select-Object -First 1
ffprobe -version | Select-Object -First 1
psql --version
nvidia-smi
```

PostgreSQL installer can dat password cho user `postgres`; ghi nho password do
de dien vao `.env`, khong ghi vao Git. Memurai phai duoc cau hinh service tu
dong khoi dong va lang nghe `127.0.0.1:6379`. Khong de PostgreSQL/Redis bind ra
Internet.

## 1. Profile da ho tro

Profile tham chieu da duoc verify:

- Windows x86-64.
- Python 3.11.x 64-bit (may tham chieu: 3.11.9).
- Node.js 22.x va npm 10+ (may tham chieu: Node 22.22.2, npm 11.17.0).
- PostgreSQL tren `127.0.0.1:5432`.
- Redis hoac Memurai tren `127.0.0.1:6379`.
- FFmpeg va ffprobe trong `PATH` (may tham chieu: 7.1.1).
- GPU profile: NVIDIA GPU co it nhat 12000 MiB VRAM; profile da do tren RTX
  4070 SUPER 12GB.
- May dich do user cung cap ngay 20/08/2026: Intel Core i9-12900K, 32 GB RAM,
  NVIDIA GeForce RTX 3060 12 GB, Windows 11 Pro 25H2 x64 va khoang 844 GB dia
  trong. Cau hinh nay dat gate dung luong cho profile `gpu12gb`; latency/SLO tren
  RTX 3060 chua duoc benchmark va anh cau hinh khong cho biet NVIDIA driver.
- CPU profile: functional fallback, khong co cam ket latency/SLO.
- It nhat 16 GB dia trong truoc acquisition cho pinned LLM, large-v2, pyannote,
  archive va staging copy; giu toi thieu 4 GB headroom sau khi cai.

Can Visual Studio 2022 Build Tools voi workload `Desktop development with C++`
de build `llama-cpp-python==0.3.16` cho exact GGUF token counting. Generation
van chay out-of-process qua pinned `llama-server.exe`.

Tren may RTX 3060, cap nhat NVIDIA Studio/Game Ready driver truoc khi cai model,
restart Windows, roi chay gate sau trong PowerShell:

```powershell
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free `
  --format=csv,noheader
```

Ket qua phai nhan dung RTX 3060, tong VRAM it nhat 12000 MiB va it nhat 7000 MiB
free truoc khi start llama-server. Khong suy doan tu so driver: hai probe bat
buoc trong `preflight_new_machine.ps1` phai xac nhan ca PyTorch CUDA 12.1 va
llama.cpp CUDA 12.4. Neu mot probe fail, sua/cap nhat driver va restart; khong
dung `-SkipResourceCheck` de che loi may dich.

## 2. Clone va tao cau hinh

```powershell
git clone https://github.com/tunguyen-195/getSomething.git
cd getSomething
git checkout feature/architecture-refactor
git status -sb
Copy-Item .env.example .env
```

Tai thoi diem ban giao, branch can clone la `feature/architecture-refactor`.
Sau khi checkout, agent phai xac nhan `git status -sb` sach truoc khi cai
artifact. Khong copy `.env`, `venv`, `models`, `uploads` hoac database cua may
nguon vao Git clone.

Tao secret development/staging:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Sua `.env` cho service local. Khong commit file nay:

```dotenv
ENVIRONMENT=development
DEBUG=true
AUTH_ENABLED=true
DEV_AUTH_BYPASS=false
DEV_USER_ID=0
BACKEND_HOST=127.0.0.1
INIT_DB_ON_STARTUP=true
ENABLE_API_DOCS=true
SECRET_KEY=<generated-secret>
INITIAL_ADMIN_PASSWORD=<local-admin-password>

DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/speech_to_information
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

LOCAL_LLM_PROVIDER=llama_cpp_server
LLAMA_SERVER_BASE_URL=http://127.0.0.1:8088
CONTAINER_LLAMA_SERVER_BASE_URL=<container-reachable-llama-server-url>
CONTAINER_LLAMA_SERVER_MODEL_PATH=/models/qwen3/Qwen3-8B-Q4_K_M.gguf
LLAMA_SERVER_MODEL=speechintel-qwen3-8b-q4_k_m
LLAMA_SERVER_MODEL_PATH=models/qwen3/Qwen3-8B-Q4_K_M.gguf
LLAMA_SERVER_CONTEXT_SIZE=12288
LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB=7000
LLAMA_SERVER_API_KEY=
OFFLINE_STRICT=true
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
LLM_SEED=42
```

Profile canonical bat xac thuc. Dang nhap bang user `admin` va
`INITIAL_ADMIN_PASSWORD` sau lan seed database dau tien. Khong bat
`DEV_AUTH_BYPASS` cho clone/run thong thuong. Neu can bypass de debug cuc bo,
phai dat dong thoi `AUTH_ENABLED=false`, `DEV_AUTH_BYPASS=true`,
`DEV_USER_ID=<id-hop-le>` va `BACKEND_HOST=127.0.0.1`; startup se tu choi bypass
thieu mot trong cac rang buoc nay hoac bind ra ngoai loopback.

Khong doi alias hoac dat mot challenger GGUF vao path baseline. Backend va
Celery doc `.env` khi khoi dong, nen phai restart ca hai sau moi thay doi.

`LLAMA_SERVER_BASE_URL` la URL cho tien trinh native tren Windows.
Backend/Celery trong Docker khong duoc dung `127.0.0.1`, vi day la loopback cua
chinh container. Compose bat buoc dung `CONTAINER_LLAMA_SERVER_BASE_URL` tro toi
mot llama-server sidecar ma container thuc su truy cap duoc.
Launcher `scripts/start_llama_server.ps1` hien bind `127.0.0.1`, nen profile
native do la host-only va khong duoc gan nhan la Docker bridge. Bao ve endpoint
container bang firewall va `LLAMA_SERVER_API_KEY`; khong expose cong khai.

Day la co-located/shared-artifact contract, khong phai mot remote URL tuy y.
Backend va Celery mount `./models` thanh `/models` read-only. Sidecar phai mount
cung artifact da verify va tra chinh xac
`/models/qwen3/Qwen3-8B-Q4_K_M.gguf` tai `/props.model_path`; model alias, context,
slot count va SHA-256 cung phai khop. Neu sidecar dung filesystem path khac,
application se fail-closed.

## 3. Python dependencies da pin

Tao venv bang Python 3.11:

```powershell
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install --upgrade pip==25.3
```

Chon dung mot torch profile truoc. GPU profile (`torch 2.1.1+cu121`):

```powershell
venv\Scripts\python.exe -m pip install --no-deps `
  -r requirements-torch-cu121.txt `
  --index-url https://download.pytorch.org/whl/cu121
```

CPU functional profile (`+cpu` wheels):

```powershell
venv\Scripts\python.exe -m pip install --no-deps --force-reinstall `
  torch==2.1.1 torchvision==0.16.1 torchaudio==2.1.1 `
  --index-url https://download.pytorch.org/whl/cpu
```

Sau do cai manifest runtime canonical. `requirements.txt` nap
`requirements-constraints-py311.txt`, nen ca direct dependencies va closure
Pyannote 3.1 deu duoc pin. Khong cai `diart` hoac optional diarizer khac vao
runtime baseline:

```powershell
venv\Scripts\python.exe -m pip install -r requirements.txt
```

Khong dung `pip install .`: `setup.py` chi giu package metadata legacy va co y
fail-closed cho install/build. Sau do verify dependency resolver:

```powershell
venv\Scripts\python.exe -m pip check
```

Neu can bootstrap khi van con Internet nhung muon chuyen sang offline sau do,
giu mot wheelhouse ben ngoai repo:

```powershell
New-Item -ItemType Directory -Force C:\stt-wheelhouse | Out-Null
venv\Scripts\python.exe -m pip download --dest C:\stt-wheelhouse `
  -r requirements-torch-cu121.txt `
  --index-url https://download.pytorch.org/whl/cu121
venv\Scripts\python.exe -m pip download --dest C:\stt-wheelhouse `
  -r requirements.txt
```

Tren may air-gapped, thay hai lenh cai online bang `--no-index
--find-links C:\stt-wheelhouse`. Phai co ca wheel CUDA va tat ca closure cua
`requirements-constraints-py311.txt`; neu wheel thieu, dung lai va bo sung tu
may co mang, khong cho pip tu truy cap Internet.

Exact staging gate kiem tra:

| Package | Version |
| --- | --- |
| torch / torchvision / torchaudio | 2.1.1 / 0.16.1 / 2.1.1, dung suffix profile |
| llama-cpp-python | 0.3.16 |
| huggingface-hub | 0.36.0 |
| pyannote.audio | 3.1.1 |
| faster-whisper | 1.2.1 |
| ctranslate2 | 4.6.0 |
| celery / redis | 5.3.4 / 5.0.1 |

## 4. Frontend reproducible install

Repo co `frontend/package-lock.json`; clean clone phai dung `npm ci`, khong dung
`npm install`:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

## 5. PostgreSQL va Redis

Start PostgreSQL va Redis/Memurai truoc. Tao database neu chua co:

```powershell
createdb -h 127.0.0.1 -U postgres speech_to_information
```

Neu `createdb` khong o trong `PATH`, tao database bang pgAdmin. Sau khi hai port
5432/6379 san sang:

```powershell
venv\Scripts\python.exe -m src.database.scripts.init_db
```

Kiem tra service truoc khi init:

```powershell
Get-Service postgresql* | Select-Object Status,Name
Get-Service Memurai,Redis -ErrorAction SilentlyContinue | Select-Object Status,Name
Test-NetConnection 127.0.0.1 -Port 5432
Test-NetConnection 127.0.0.1 -Port 6379
```

Neu `createdb` khong co trong `PATH`, dung SQL Shell/pgAdmin tao database
`speech_to_information`, sau do dat URL PostgreSQL dung username/password that
trong `.env`. `INIT_DB_ON_STARTUP=true` chi tao schema/admin lan dau; khong phai
co che cai PostgreSQL.

## 6. Operator-run model acquisition

Tat ca model download trong muc nay la lenh cai dat do operator chu dong chay.
Application startup va task runtime van bi cam download.

Khong can dong goi Qwen3, llama.cpp hay faster-whisper: cac artifact nay tai
duoc tu nguon chinh thuc bang installer da pin va co hash gate ben duoi. Chi
pyannote duoc dong goi rieng vi Hugging Face yeu cau chap nhan gated terms va
read token. Goi pyannote phai duoc giu trong Google Drive rieng tu, chi chia se
cho operator duoc uy quyen; no khong duoc commit vao Git.

Tren may nguon, tao hai file ban giao pyannote ngoai repo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_gated_pyannote.ps1 `
  -OutputDirectory E:\research\STT\temp\gated-models
```

Upload ca hai file `pyannote-3.1-offline-gated-20260826.zip` va
`pyannote-3.1-offline-gated-20260826.manifest.json` len cung mot folder Drive.
Tren may dich, tai ca hai vao cung folder, vi du `D:\STT-gated-models`, roi tai
root cua repo clone chay:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restore_gated_pyannote.ps1 `
  -BundleDirectory D:\STT-gated-models
```

Script verify hash cua ZIP, rang buoc no voi manifest trong clone, extract vao
`<repo-root>\models\pyannote`, sau do verify lai nam artifact va ba `refs/main`.
Khong extract ZIP truc tiep vao repo root vi se tao sai path `pyannote` thay vi
`models\pyannote`. Goi khong chua `HF_TOKEN`, `.env` hoac credential.

### 6.1. Qwen3 va llama.cpp

Lenh sau la hanh dong download ro rang cua operator. Script doc hai manifest,
tai dung immutable revision/release, giu hai ZIP runtime, extract chi cac file
duoc khai bao, verify size va SHA-256, va tu choi ghi de file sai neu khong co
`-Force`.

GPU 12GB:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_local_llm_staging.ps1 `
  -HardwareProfile gpu12gb
```

CPU fallback:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_local_llm_staging.ps1 `
  -HardwareProfile cpu
```

Pinned artifacts:

- Model: `Qwen/Qwen3-8B-GGUF` revision
  `7c41481f57cb95916b40956ab2f0b139b296d974`.
- File: `models/qwen3/Qwen3-8B-Q4_K_M.gguf`.
- Runtime: `ggml-org/llama.cpp` release `b10331`, commit label `7ba604f1c`.
- Packages: `llama-b10331-bin-win-cuda-12.4-x64.zip` va
  `cudart-llama-bin-win-cuda-12.4-x64.zip`.

Khong goi installer tu backend startup, Celery task, frontend hoac request path.

### 6.2. Bang artifact can co truoc khi offline

| Artifact | Bat buoc baseline | Vi tri sau cai | Kich thuoc manifest xap xi |
| --- | --- | --- | ---: |
| Qwen3-8B Q4_K_M | Co | `models/qwen3/Qwen3-8B-Q4_K_M.gguf` | 5.03 GB |
| llama.cpp b10331 CUDA 12.4 | Co | `models/runtimes/llama.cpp/b10331/windows-cuda-12.4-x64` | ~1.77 GB sau extract |
| faster-whisper large-v2 | Co cho transcription legacy | `models/whisper/models--Systran--faster-whisper-large-v2/snapshots/<revision>` | 3.09 GB |
| pyannote 3.1 + segmentation + wespeaker | Co neu bat diarization | `models/pyannote/models--.../snapshots/<revision>` | ~31 MB trong manifest, chua tinh cache phu |
| Silero VAD/PhoWhisper/Cherry models | Khong cho baseline `TRANSCRIPTION_ENGINE=legacy` | chi cai neu chon `TRANSCRIPTION_ENGINE=cherry` | tuy model |

Khong tai `large-v3`, `large-v3-turbo`, PhoWhisper, BART/T5, Vosk hoac Ollama
neu muc tieu la baseline trong runbook nay. Cac model do la challenger/legacy
khac va co the lam day VRAM, thay doi ket qua hoac tao download ngoai y muon.
`TRANSCRIPTION_ENGINE=legacy` su dung faster-whisper large-v2; `pyannote` la
duong diarization duy nhat da pin cho baseline.

### 6.3. faster-whisper large-v2 va pyannote 3.1

Baseline ASR la `Systran/faster-whisper-large-v2` tai revision immutable
`f0fe81560cb8b68660e564f55dd99207059c092e`. Script tai bon file trong
`config/models/faster-whisper-large-v2.manifest.json`, verify size/SHA-256, va
tao `refs/main` tro chinh xac den revision nay.

Neu da restore gated bundle o dau muc 6, chi tai large-v2 cong khai:

```powershell
venv\Scripts\python.exe scripts\install_audio_models_staging.py `
  --include large-v2
```

Pyannote la gated model. Neu khong dung private bundle, truoc khi chay operator
phai dang nhap Hugging Face va
chap nhan dieu kien truy cap tren hai trang:

- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0

Tao read token chi co quyen can thiet, dat no trong process environment (khong
ghi vao `.env`, command history, log hoac Git), sau do chay:

```powershell
$env:HF_TOKEN='<hugging-face-read-token>'
venv\Scripts\python.exe scripts\install_audio_models_staging.py `
  --include large-v2 `
  --include pyannote `
  --accept-pyannote-terms
Remove-Item Env:HF_TOKEN
```

Pinned pyannote graph:

- `pyannote/speaker-diarization-3.1` revision
  `84fd25912480287da0247647c3d2b4853cb3ee5d`.
- `pyannote/segmentation-3.0` revision
  `e66f3d3b9eb0873085418a7b813d3b369bf160bb`.
- `pyannote/wespeaker-voxceleb-resnet34-LM` revision
  `837717ddb9ff5507820346191109dc79c958d614`.

Installer chi copy file khai bao trong manifest, verify hash truoc khi publish,
va tao `refs/main` cho ca ba pyannote repositories. Neu token chua duoc cap gated
access, script fail ro rang; khong chuyen sang floating revision.

## 7. New-machine preflight

Chay sau khi DB/Redis da start va truoc khi start app:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\preflight_new_machine.ps1 `
  -HardwareProfile gpu12gb `
  -OutputPath docs\evals\runs\new-machine-preflight.json
```

CPU fallback doi tham so thanh `cpu`. Script tra JSON, exit non-zero neu mot gate
bat buoc fail, va kiem tra:

- Python 3.11, hai dependency manifests, exact critical package versions va `pip check`.
- Node/npm, `frontend/node_modules`, FFmpeg/ffprobe.
- `.env` provider/path/alias/offline flags.
- PostgreSQL, Redis va port 8088/8000/3000.
- Model/runtime size, SHA-256 va executable probe.
- large-v2/pyannote pinned snapshots, SHA-256 va tat ca `refs/main` selectors.
- GPU >=12 GB va >=6500 MiB free VRAM, hoac CPU version probe khong yeu cau GPU.

Khong start app khi report co `status=FAIL`.

Preflight phai duoc chay lai sau moi thay doi `.env`, driver, model, Python venv
hoac service. Bao cao JSON la artifact ban giao, khong chi dua vao mot lenh
`--version`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\preflight_new_machine.ps1 `
  -HardwareProfile gpu12gb `
  -OutputPath docs\evals\runs\new-machine-preflight.json
if ($LASTEXITCODE -ne 0) { throw 'Preflight FAIL; do not start services.' }
```

`entrypoint.bat` co chu y fail-fast vi khong the tu khoi dong va xac minh day du
PostgreSQL, Redis, model artifacts va llama-server. Dung cac lenh canonical ben
duoi sau khi preflight PASS.

## 8. Thu tu start bat buoc

Khong dung `START_ALL_SERVICES.bat` cho pinned LLM staging vi script do chua start
llama-server. Mo moi lenh trong mot terminal rieng, theo dung thu tu:

1. PostgreSQL va Redis/Memurai.
2. llama-server.
3. FastAPI backend.
4. Celery solo worker, concurrency 1.
5. React/Vite frontend.

Tat ca terminal native deu phai dung thu muc repo. Khong dung `START_ALL_SERVICES.bat`
cho profile nay vi no khong start llama-server va khong chay day du preflight.

Docker Compose hien la profile development bridge, khong phai offline production
bundle. Truoc khi dung Compose, provision va verify mot pinned llama-server
endpoint container-reachable, sau do dat `CONTAINER_LLAMA_SERVER_BASE_URL`.
Compose fail-closed neu bien nay rong. Compose truyen cung
provider/model/offline/GPU-lease contract cho backend va Celery, va mac dinh
`TRANSCRIPTION_ENGINE=legacy` giong `.env.example`; no khong con ep `auto`.

Kiem tra config va connectivity tu chinh backend container truoc khi start stack:

```powershell
$env:CONTAINER_LLAMA_SERVER_BASE_URL='https://<secured-llama-server>'
$env:CONTAINER_LLAMA_SERVER_MODEL_PATH='/models/qwen3/Qwen3-8B-Q4_K_M.gguf'
$env:LLAMA_SERVER_API_KEY='<non-empty-api-key>'
powershell -ExecutionPolicy Bypass -File scripts\preflight_compose_runtime.ps1 `
  -OutputPath docs\evals\runs\compose-runtime-preflight.json
```

Preflight tu choi URL thieu, `localhost`, `127.0.0.1`, `::1`, API key rong,
model path khong phai absolute Linux path, mount khong read-only, hoac
provider/model projection sai. Connectivity gate goi application client tu
backend container de verify local SHA-256, remote `/props.model_path`, context,
slot count va model alias. Dung `-ConfigOnly` chi de validate Compose truoc khi
image duoc build; no khong thay the connectivity gate.

### 8.1. llama-server GPU

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_llama_server.ps1
```

### 8.2. llama-server CPU functional fallback

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$server='models\runtimes\llama.cpp\b10331\windows-cuda-12.4-x64\bin\llama-server.exe'
$model='models\qwen3\Qwen3-8B-Q4_K_M.gguf'
& $server `
  --model $model `
  --alias speechintel-qwen3-8b-q4_k_m `
  --host 127.0.0.1 `
  --port 8088 `
  --ctx-size 4096 `
  --n-gpu-layers 0 `
  --parallel 1 `
  --flash-attn off `
  --reasoning off `
  --jinja `
  --offline `
  --no-webui `
  --metrics `
  --slots
```

### 8.3. Backend, Celery, frontend

```powershell
venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
venv\Scripts\python.exe -m celery -A src.worker.worker worker `
  --pool=solo --concurrency=1 --loglevel=info `
  --without-heartbeat --without-gossip --without-mingle
```

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 3000
```

## 9. API, schema va Celery smoke

Health va model identity:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/health
Invoke-RestMethod http://127.0.0.1:8088/v1/models
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Structured-output smoke dung contract cua llama.cpp `b10331`:

```powershell
$body = @{
  model = 'speechintel-qwen3-8b-q4_k_m'
  messages = @(@{
    role = 'user'
    content = 'Tra ve JSON co truong status bang OK.'
  })
  temperature = 0
  max_tokens = 32
  reasoning_effort = 'none'
  response_format = @{
    type = 'json_object'
    schema = @{
      type = 'object'
      additionalProperties = $false
      properties = @{ status = @{ type = 'string'; const = 'OK' } }
      required = @('status')
    }
  }
} | ConvertTo-Json -Depth 10

$response = Invoke-RestMethod `
  -Uri http://127.0.0.1:8088/v1/chat/completions `
  -Method Post `
  -ContentType application/json `
  -Body $body
$parsed = $response.choices[0].message.content | ConvertFrom-Json
if ($parsed.status -ne 'OK') { throw 'Structured LLM smoke failed.' }
```

Celery phai dang chay va tra dung runtime contract:

```powershell
venv\Scripts\python.exe scripts\probe_celery_worker_contract.py --timeout 30 --json
```

Synthetic production-path benchmark smoke:

```powershell
venv\Scripts\python.exe scripts\benchmark_summary_runtime.py `
  --provider llama_cpp_server `
  --base-url http://127.0.0.1:8088 `
  --models speechintel-qwen3-8b-q4_k_m `
  --max-cases 1 `
  --warmup 0 `
  --repetitions 1 `
  --load-states warm `
  --output docs\evals\runs\new-machine-summary-smoke.json
```

Benchmark nay chi la runtime/contract gate; khong phai bang chung chat luong tom
tat dieu tra.

## 10. Full UI smoke

Mo `http://127.0.0.1:3000` va chay mot flow day du:

1. Upload mot audio test khong nhay cam.
2. Tao transcription va doi task sang completed.
3. Mo transcript, tao `investigation` summary.
4. Xac nhan Summary va Analysis hien du lieu cua cung task, khong co fallback
   sang Ollama/model khac, khong co download trong backend/Celery log.
5. Xac nhan model alias trong log/artifact la
   `speechintel-qwen3-8b-q4_k_m` va cac failure hien ro thay vi silent fallback.

Full transcription smoke chi duoc danh `PASS` khi preflight da verify large-v2 va
pyannote. Neu gated access hoac artifact chua san sang, ghi
`BLOCKED_ASR_ARTIFACT`; khong bat auto download de lam cho smoke xanh gia tao.

## 11. Dung service

Dung theo thu tu nguoc: frontend, Celery, backend, llama-server, sau do DB/Redis.
Trong tung terminal co the dung `Ctrl+C`. Neu can tim PID theo port:

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 3000,8000,8088
```

Khong dung lenh kill theo ten rong neu may dang chay cac project Python/Node khac.

## 12. Production offline bundle: BLOCKED

Production clone-only/offline deployment chua san sang vi Git ignore `models/`
va `venv/`, trong khi bundle van thieu pinned Python runtime/wheelhouse, Node
runtime/cache, FFmpeg, database/queue runtime, ASR/diarization artifacts, license
surface va startup profile day du.

Nguon kiem tra:

- `docs/runbooks/portable-local-llm-deployment.md`
- `docs/runbooks/offline-release-bundle.md`
- `config/release/benchmark-candidate.bundle.json`

Gate hien tai du kien exit non-zero va `release_ready=false`:

```powershell
venv\Scripts\python.exe scripts\verify_offline_release_bundle.py `
  --json `
  --output docs\evals\runs\offline-bundle\latest.json
```

Khong override gate, khong goi staging installer trong production startup, va
khong mo outbound network de che lap mot component con thieu.

## 13. Khoa runtime offline sau bootstrap

Sau khi cac model/runtime da hash-verify va preflight PASS:

1. Xoa `HF_TOKEN` khoi process/user environment; khong luu token trong `.env`.
2. Bao dam `.env` co `OFFLINE_STRICT=true`, `HF_HUB_OFFLINE=1`,
   `TRANSFORMERS_OFFLINE=1`, `WHISPER_USE_LOCAL=true` va
   `LOCAL_LLM_PROVIDER=llama_cpp_server`.
3. Giu `LLAMA_SERVER_BASE_URL=http://127.0.0.1:8088`; khong thay bang endpoint
   Internet/Ollama. `LLAMA_SERVER_API_KEY` co the de rong cho host loopback, hoac
   dat secret neu co sidecar/container.
4. Restart llama-server, backend, Celery sau khi doi `.env`; chay lai preflight.
5. Trong log phai khong co dong download HF/model. Neu model thieu, task phai
   fail ro rang `offline strict`, khong tu fallback sang tai Internet.

Neu can chung minh khong co outbound runtime, block outbound cua `python.exe`,
`llama-server.exe` va Node dev server bang Windows Firewall sau bootstrap, nhung
van cho phep loopback 127.0.0.1. Chay lai health/model/Celery smoke; khong block
PostgreSQL/Redis loopback.

### 13.1. Air-gapped transfer checklist

Tren may co mang, copy vao USB/lan noi bo cac nhom sau va ghi checksum:

- Git clone o commit da push va cac file manifest/config.
- Bo cai Windows: Python 3.11, Git, Node 22, VS Build Tools, PostgreSQL 17,
  Memurai/Redis, FFmpeg 7.1.1, NVIDIA driver.
- `C:\stt-wheelhouse` gom wheel CUDA + runtime closure va `frontend` npm cache.
- Toan bo `models/qwen3`, `models/runtimes/llama.cpp`,
  `models/whisper`, `models/pyannote` da hash-verify.
- File `.env` tao moi tren may dich, khong copy secret cua may nguon.

Do repo chua dong goi cac nhom installer/wheelhouse tren, che do air-gapped
thuc su van nam ngoai release boundary va phai dung gate muc 12. Che do duoc
ho tro ngay la bootstrap co mang mot lan, sau do runtime offline.
