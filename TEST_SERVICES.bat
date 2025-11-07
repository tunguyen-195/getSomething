@echo off
chcp 65001 > nul
echo ================================================================================
echo    TESTING ALL SERVICES
echo ================================================================================

echo [1/5] Testing Python...
venv\Scripts\python.exe --version
if errorlevel 1 (
    echo FAILED: Python not working
    pause
    exit /b 1
)
echo OK

echo.
echo [2/5] Testing Backend import...
venv\Scripts\python.exe -c "from src.main import app; print('OK')"
if errorlevel 1 (
    echo FAILED: Backend cannot be imported
    pause
    exit /b 1
)

echo.
echo [3/5] Testing Celery import...
venv\Scripts\python.exe -c "from src.worker import celery_app; print('OK')"
if errorlevel 1 (
    echo FAILED: Celery cannot be imported
    pause
    exit /b 1
)

echo.
echo [4/5] Testing Database...
venv\Scripts\python.exe -c "from src.database.init_db import init_db; print('OK')"
if errorlevel 1 (
    echo FAILED: Database module error
    pause
    exit /b 1
)

echo.
echo [5/5] Testing Transcriber...
venv\Scripts\python.exe -c "from src.speech_to_text.transcriber import Transcriber; print('OK')"
if errorlevel 1 (
    echo FAILED: Transcriber module error
    pause
    exit /b 1
)

echo.
echo ================================================================================
echo ALL TESTS PASSED! Services are ready to start.
echo ================================================================================
echo.
echo You can now run: START_PROJECT.bat
pause