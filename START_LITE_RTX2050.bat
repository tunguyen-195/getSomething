@echo off
setlocal
set "ROOT=%~dp0"
pushd "%ROOT%" >nul

if not exist ".env" (
  if exist ".env.lite.example" (
    copy ".env.lite.example" ".env" >nul
    echo Created .env from .env.lite.example. Review SECRET_KEY, database, and API keys before production use.
  ) else (
    echo Missing .env and .env.lite.example.
    exit /b 1
  )
)

if not exist "venv\Scripts\python.exe" (
  echo Missing venv\Scripts\python.exe. Run:
  echo   python -m venv venv
  echo   .\venv\Scripts\activate
  echo   pip install -r requirements-torch-cu121.txt --index-url https://download.pytorch.org/whl/cu121
  echo   pip install -r requirements.txt
  exit /b 1
)

if not exist "frontend\node_modules" (
  echo Missing frontend\node_modules. Run:
  echo   cd frontend
  echo   npm install
  echo   cd ..
  exit /b 1
)

echo Checking Lite model cache...
echo Strict model verification may take a moment while hashing model.bin.
venv\Scripts\python.exe scripts\verify_models.py --profile lite_rtx2050
if errorlevel 1 (
  echo Missing public Lite model cache. Downloading faster-whisper medium for Vietnamese quality...
  venv\Scripts\python.exe scripts\precache_lite_models.py --model medium
  if errorlevel 1 (
    echo Failed to download public Lite model. If this machine is offline, copy a prepared models\whisper cache into this repo and run:
    echo   venv\Scripts\python.exe scripts\verify_models.py --profile lite_rtx2050
    exit /b 1
  )
  venv\Scripts\python.exe scripts\verify_models.py --profile lite_rtx2050
  if errorlevel 1 (
    echo Lite model verification still failed. See docs\MODEL_SETUP.md.
    exit /b 1
  )
)

echo Starting SpeechToInformation Lite RTX2050 services...
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:3000

start "STI Lite Backend" cmd /k "cd /d ""%ROOT%"" && call venv\Scripts\activate.bat && python -m uvicorn src.main:app --host 0.0.0.0 --port 8000"
start "STI Lite Frontend" cmd /k "cd /d ""%ROOT%frontend"" && npm run dev"

popd >nul
endlocal
