@echo off
echo Cleaning Python cache and temporary files...
echo.

echo [1/5] Removing __pycache__ directories...
for /d /r %%i in (__pycache__) do @if exist "%%i" rd /s /q "%%i" 2>nul
echo Done: __pycache__ cleaned

echo.
echo [2/5] Removing .pyc files...
del /s /q *.pyc 2>nul
echo Done: .pyc files removed

echo.
echo [3/5] Removing .pyo files...
del /s /q *.pyo 2>nul
echo Done: .pyo files removed

echo.
echo [4/5] Clearing Celery cache...
rd /s /q celerybeat-schedule 2>nul
echo Done: Celery cache cleared

echo.
echo [5/5] Clearing logs (optional)...
del /q app.log 2>nul
del /q celery_worker.log 2>nul
echo Done: Logs cleared

echo.
echo ========================================
echo Cache cleaned successfully!
echo ========================================
echo.
echo Next steps:
echo 1. Run: STOP_ALL_SERVICES.bat
echo 2. Wait 5 seconds
echo 3. Run: START_ALL_SERVICES.bat
echo.
pause
