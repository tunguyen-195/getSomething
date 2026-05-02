@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ????????????????????????????????????????????????????????????????????????????
echo          Speech to Information System - Start All Services
echo ????????????????????????????????????????????????????????????????????????????
echo.

set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

REM Local development defaults. Production must use .env / Docker secrets.
if not defined ENVIRONMENT set ENVIRONMENT=development
if not defined DEBUG set DEBUG=true
if not defined AUTH_ENABLED set AUTH_ENABLED=false
if not defined INIT_DB_ON_STARTUP set INIT_DB_ON_STARTUP=true
if not defined ENABLE_API_DOCS set ENABLE_API_DOCS=true
if not defined SECRET_KEY set SECRET_KEY=local-dev-only-change-before-production-123456789
if not defined INITIAL_ADMIN_PASSWORD set INITIAL_ADMIN_PASSWORD=local-dev-admin-change-me

REM ============================================================
REM [1/6] Checking PostgreSQL
REM ============================================================
echo [1/6] Checking PostgreSQL...
REM Check if PostgreSQL service is running (common service names)
sc query postgresql-x64-15 2>nul | find "RUNNING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] PostgreSQL service is running
) else (
    sc query postgresql-x64-14 2>nul | find "RUNNING" >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo [OK] PostgreSQL service is running
    ) else (
        REM Check if PostgreSQL is listening on port 5432
        netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
        if %ERRORLEVEL% EQU 0 (
            echo [OK] PostgreSQL is running on port 5432
        ) else (
            echo [WARNING] PostgreSQL may not be running
            echo           Database connection may fail
            echo           Check: sc query postgresql* or netstat -ano ^| findstr :5432
            echo [INFO] Continuing anyway - services may fail if PostgreSQL is not available
        )
    )
)
echo.

REM ============================================================
REM [2/6] Checking Redis/Memurai
REM ============================================================
echo [2/6] Checking Redis/Memurai...
netstat -ano | findstr ":6379" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Redis/Memurai is already running on port 6379
) else (
    echo [CHECK] Checking for Redis server executable...
    REM Try to find redis-server.exe or memurai.exe
    where redis-server.exe >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo [START] Starting Redis server...
        start "Redis Server" /MIN redis-server
        timeout /t 3 /nobreak > nul
        echo [OK] Redis server started
    ) else (
        where memurai.exe >nul 2>&1
        if %ERRORLEVEL% EQU 0 (
            echo [INFO] Memurai found but not running on port 6379
            echo        Please start Memurai manually or as a Windows service
        ) else (
            echo [WARNING] Redis/Memurai not detected on port 6379
            echo           Redis/Memurai executable not found in PATH
            echo           Please ensure Redis/Memurai is installed and running
        )
        echo [INFO] Continuing anyway - services may fail if Redis is not available
    )
)
echo.

REM ============================================================
REM [3/6] Starting Backend (FastAPI)
REM ============================================================
echo [3/6] Starting Backend (FastAPI on port 8000)...
REM Check if port 8000 is already in use
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [WARNING] Port 8000 is already in use!
    echo           Backend may not start properly
    echo           Consider stopping existing services first
) else (
    echo [INFO] Port 8000 is available
)
start "Backend - FastAPI" cmd /k "cd /d "%PROJECT_DIR%" && echo [Backend] Starting FastAPI on http://localhost:8000 && venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000"
echo [OK] Backend starting on http://localhost:8000
timeout /t 5 /nobreak > nul
echo.

REM ============================================================
REM [4/6] Starting Celery Worker
REM ============================================================
echo [4/6] Starting Celery Worker (Gevent Pool)...
REM Check if gevent is installed (optional check)
start "Celery Worker (Gevent)" cmd /k "cd /d "%PROJECT_DIR%" && echo [Celery] Installing gevent if needed... && venv\Scripts\pip install -q gevent && echo [Celery] Starting Celery Worker (Gevent Pool) && venv\Scripts\python.exe -m celery -A src.worker.worker worker --pool=gevent --concurrency=4 --loglevel=info --logfile=celery.log --without-heartbeat --without-gossip --without-mingle"
echo [OK] Celery Worker starting
timeout /t 3 /nobreak > nul
echo.

REM ============================================================
REM [5/6] Starting Frontend (React + Vite)
REM ============================================================
echo [5/6] Starting Frontend (React + Vite on port 3000)...
REM Check if port 3000 is already in use
netstat -ano | findstr ":3000" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [WARNING] Port 3000 is already in use!
    echo           Frontend may not start properly
    echo           Vite will try to use next available port (3001, 3002, etc.)
) else (
    echo [INFO] Port 3000 is available
)
REM Check if node_modules exists
if not exist "%PROJECT_DIR%\frontend\node_modules" (
    echo [WARNING] node_modules not found!
    echo           Frontend may fail to start
    echo           Run: cd frontend && npm install
)
start "Frontend - React" cmd /k "cd /d "%PROJECT_DIR%\frontend" && echo [Frontend] Starting React + Vite on http://localhost:3000 && npm run dev"
echo [OK] Frontend starting on http://localhost:3000
timeout /t 5 /nobreak > nul
echo.

REM ============================================================
REM [6/6] Verifying Services
REM ============================================================
echo [6/6] Verifying Services...
echo [INFO] Waiting for services to initialize...
timeout /t 10 /nobreak > nul
echo.

REM Check if services are listening on their ports
set "all_ok=1"

echo [VERIFY] Checking service status...
echo.

REM Check Backend (port 8000)
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Backend is listening on port 8000
) else (
    echo [WARNING] Backend may not be running on port 8000
    set "all_ok=0"
)

REM Check Frontend (port 3000 or 5173)
netstat -ano | findstr ":3000" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Frontend is listening on port 3000
) else (
    netstat -ano | findstr ":5173" | findstr "LISTENING" >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo [OK] Frontend is listening on port 5173 (Vite default)
    ) else (
        echo [WARNING] Frontend may not be running
        set "all_ok=0"
    )
)

REM Check Redis (port 6379)
netstat -ano | findstr ":6379" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Redis/Memurai is listening on port 6379
) else (
    echo [WARNING] Redis/Memurai may not be running on port 6379
    set "all_ok=0"
)

REM Check PostgreSQL (port 5432)
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] PostgreSQL is listening on port 5432
) else (
    echo [WARNING] PostgreSQL may not be running on port 5432
    set "all_ok=0"
)

echo.

REM ============================================================
REM Summary
REM ============================================================
echo ????????????????????????????????????????????????????????????????????????????
if "!all_ok!"=="1" (
    echo                    ALL SERVICES STARTED SUCCESSFULLY
) else (
    echo                    SERVICES STARTED (WITH WARNINGS)
)
echo ????????????????????????????????????????????????????????????????????????????
echo.
echo Service URLs:
echo   Backend:  http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo   API v2:   http://localhost:8000/api/v1/audio/v2/
echo   Frontend: http://localhost:3000 (or check Vite output for actual port)
echo.
echo Windows opened:
if "!all_ok!"=="1" (
    echo   - Backend (FastAPI + Uvicorn) - Port 8000
    echo   - Celery Worker (Background tasks) - Gevent Pool
    echo   - Frontend (React + Vite) - Port 3000
) else (
    echo   - Backend (FastAPI + Uvicorn)
    echo   - Celery Worker (Background tasks)
    echo   - Frontend (React + Vite)
    echo.
    echo   NOTE: Some services may not be fully started yet.
    echo         Check the individual windows for status.
)
echo.
echo To stop all services, run: STOP_ALL_SERVICES.bat
echo.
echo Press any key to exit this window (services will keep running)...
pause > nul
