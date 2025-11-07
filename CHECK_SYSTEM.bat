@echo off
chcp 65001 > nul
echo SYSTEM HEALTH CHECK
echo ===================
echo [Python]
venv\Scripts\python.exe --version
echo [Key Packages]
venv\Scripts\python.exe -c "import fastapi, torch; print('FastAPI OK, PyTorch:', torch.__version__, 'CUDA:', torch.cuda.is_available())"
echo [Services]
netstat -ano | findstr ":8000.*LISTENING" >nul && echo Backend: Running || echo Backend: Stopped
netstat -ano | findstr ":5173.*LISTENING" >nul && echo Frontend: Running || echo Frontend: Stopped
netstat -ano | findstr ":6379.*LISTENING" >nul && echo Redis: Running || echo Redis: Stopped
echo [Model]
if exist "models\whisper\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo" (echo Whisper model: Found) else (echo Whisper model: Not found)
pause
