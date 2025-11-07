@echo off
echo ========================================
echo  CLEAN START - All Services
echo ========================================
echo.

echo [1/3] Cleaning cache...
call CLEAN_CACHE.bat

echo.
echo [2/3] Waiting 5 seconds...
timeout /t 5 /nobreak > nul

echo.
echo [3/3] Starting all services...
call START_ALL_SERVICES.bat

echo.
echo ========================================
echo  Clean start complete!
echo ========================================
