@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ????????????????????????????????????????????????????????????????????????????
echo          Speech to Information System - Stop All Services
echo ????????????????????????????????????????????????????????????????????????????
echo.

echo [1/5] Stopping Frontend (Node.js on port 3000/5173)...
REM Kill by window title first
taskkill /F /FI "WINDOWTITLE eq Frontend - React*" 2>NUL
REM Kill by port 3000 (Vite default)
for /f "tokens=5" %%a in ('netstat -ano ^| find ":3000" ^| find "LISTENING"') do (
    echo   Killing process on port 3000: PID %%a
    taskkill /F /PID %%a 2>NUL
)
REM Kill by port 5173 (Vite alternative)
for /f "tokens=5" %%a in ('netstat -ano ^| find ":5173" ^| find "LISTENING"') do (
    echo   Killing process on port 5173: PID %%a
    taskkill /F /PID %%a 2>NUL
)
echo [OK] Frontend stopped
echo.

echo [2/5] Stopping Celery Worker...
REM Kill by window title
taskkill /F /FI "WINDOWTITLE eq Celery Worker*" 2>NUL
REM Kill celery processes by finding python.exe with celery in command line using wmic
for /f "skip=1 tokens=2 delims==" %%a in ('wmic process where "name='python.exe' and commandline like '%%celery%%'" get processid /format:list 2^>NUL') do (
    if not "%%a"=="" (
        echo   Killing Celery process: %%a
        taskkill /F /PID %%a 2>NUL
    )
)
echo [OK] Celery Worker stopped
echo.

echo [3/5] Stopping Backend (Uvicorn on port 8000)...
REM Kill by window title
taskkill /F /FI "WINDOWTITLE eq Backend - FastAPI*" 2>NUL
REM Kill by port 8000 (most reliable method)
for /f "tokens=5" %%a in ('netstat -ano ^| find ":8000" ^| find "LISTENING"') do (
    echo   Killing process on port 8000: PID %%a
    taskkill /F /PID %%a 2>NUL
)
REM Kill uvicorn processes by finding python.exe with uvicorn in command line
for /f "skip=1 tokens=2 delims==" %%a in ('wmic process where "name='python.exe' and commandline like '%%uvicorn%%'" get processid /format:list 2^>NUL') do (
    if not "%%a"=="" (
        echo   Killing Uvicorn process: %%a
        taskkill /F /PID %%a 2>NUL
    )
)
echo [OK] Backend stopped
echo.

echo [4/5] Stopping Redis Server...
REM Kill by window title
taskkill /F /FI "WINDOWTITLE eq Redis Server*" 2>NUL
REM Kill by process name
taskkill /F /IM redis-server.exe 2>NUL
REM Kill by port 6379
for /f "tokens=5" %%a in ('netstat -ano ^| find ":6379" ^| find "LISTENING"') do (
    echo   Killing Redis on port 6379: PID %%a
    taskkill /F /PID %%a 2>NUL
)
echo [OK] Redis stopped
echo.

echo [5/5] Final cleanup - checking for remaining processes on our ports...
REM Double-check ports are free
set "ports_clear=1"
for /f "tokens=5" %%a in ('netstat -ano ^| find ":8000" ^| find "LISTENING"') do (
    echo   WARNING: Process still on port 8000: PID %%a
    taskkill /F /PID %%a 2>NUL
    set "ports_clear=0"
)
for /f "tokens=5" %%a in ('netstat -ano ^| find ":3000" ^| find "LISTENING"') do (
    echo   WARNING: Process still on port 3000: PID %%a
    taskkill /F /PID %%a 2>NUL
    set "ports_clear=0"
)
if "!ports_clear!"=="1" (
    echo [OK] All ports are clear
) else (
    echo [OK] Cleanup completed
)
echo.

echo ????????????????????????????????????????????????????????????????????????????
echo                       ALL SERVICES STOPPED
echo ????????????????????????????????????????????????????????????????????????????
echo.
echo All services have been terminated.
echo You can restart them by running: QUICK_START.bat or START_ALL_SERVICES.bat
echo.
pause
