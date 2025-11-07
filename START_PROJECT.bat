@echo off
chcp 65001 > nul
echo ================================================================================
echo    STARTING SPEECH TO INFORMATION PROJECT
echo ================================================================================
echo [1/7] Checking Python...
venv\Scripts\python.exe --version
echo [2/7] Starting Backend...
start "Backend" cmd /k "venv\Scripts\python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"
timeout /t 3 > nul
echo [3/7] Starting Celery...
start "Celery" cmd /k "venv\Scripts\python.exe -m celery -A src.worker worker --loglevel=info --pool=solo"
timeout /t 2 > nul
echo [4/7] Starting Flower...
start "Flower" cmd /k "venv\Scripts\python.exe -m celery -A src.worker flower --port=5555"
timeout /t 2 > nul
echo [5/7] Starting Frontend...
cd frontend
start "Frontend" cmd /k "npm run dev"
cd ..
timeout /t 3 > nul
echo ================================================================================
echo ALL SERVICES STARTED!
echo - Frontend: http://localhost:5173
echo - Backend:  http://localhost:8000
echo - API Docs: http://localhost:8000/docs
echo - Flower:   http://localhost:5555
echo ================================================================================
start http://localhost:5173
pause
