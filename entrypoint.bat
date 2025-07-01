@echo off
REM Start Redis (nếu chạy local)
start "" "C:\path\to\redis-server.exe"

REM Start Celery worker
start "" cmd /k "cd /d D:\Workspace\SpeechToInfomation && venv\Scripts\activate && celery -A src.worker.worker worker --loglevel=info --pool=threads"

REM Start FastAPI backend
start "" cmd /k "cd /d D:\Workspace\SpeechToInfomation && venv\Scripts\activate && uvicorn src.main:app --reload"

REM Start frontend
start "" cmd /k "cd /d D:\Workspace\SpeechToInfomation\frontend && npm run dev"