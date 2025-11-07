@echo off
echo Stopping all services...
taskkill /F /FI "WINDOWTITLE eq Backend*" 2>nul
taskkill /F /FI "WINDOWTITLE eq Frontend*" 2>nul
taskkill /F /FI "WINDOWTITLE eq Celery*" 2>nul
taskkill /F /FI "WINDOWTITLE eq Flower*" 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| find ":8000" ^| find "LISTENING"') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5173" ^| find "LISTENING"') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| find ":5555" ^| find "LISTENING"') do taskkill /F /PID %%a 2>nul
echo All services stopped!
pause
