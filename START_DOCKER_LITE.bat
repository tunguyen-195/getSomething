@echo off
setlocal
set "ROOT=%~dp0"
pushd "%ROOT%" >nul

if not exist ".env" (
  if exist ".env.lite.example" (
    copy ".env.lite.example" ".env" >nul
    echo Created .env from .env.lite.example.
    echo Review SECRET_KEY, POSTGRES_PASSWORD, INITIAL_ADMIN_PASSWORD, and API keys before production use.
  ) else (
    echo Missing .env and .env.lite.example.
    exit /b 1
  )
)

docker compose version >nul 2>&1
if errorlevel 1 (
  echo Docker Compose is not available. Install Docker Desktop and enable the Compose plugin.
  exit /b 1
)

echo Building Docker images...
docker compose --env-file .env --profile setup build backend frontend model_sync
if errorlevel 1 exit /b 1

echo Preparing Lite model cache inside Docker...
echo Strict model verification may take a moment while hashing model.bin.
docker compose --env-file .env --profile setup run --rm model_sync
if errorlevel 1 (
  echo Model setup failed. If this machine is offline, copy a prepared models\whisper cache into this repo and run:
  echo   docker compose --env-file .env --profile setup run --rm model_sync
  exit /b 1
)

echo Starting SpeechToInformation Lite Docker services...
docker compose --env-file .env up -d --build
if errorlevel 1 exit /b 1

echo.
echo Frontend: http://localhost:3000
echo Backend:  http://localhost:8000
echo Health:   http://localhost:8000/api/v1/health
echo.
docker compose --env-file .env ps

popd >nul
endlocal
