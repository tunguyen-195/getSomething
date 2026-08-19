@echo off
chcp 65001 > nul
echo ╔════════════════════════════════════════════════════════════════════════════╗
echo ║              FORCE CLEAN RESTART FRONTEND                                  ║
echo ╚════════════════════════════════════════════════════════════════════════════╝

set PROJECT_DIR=%~dp0

echo [1/4] Killing all Node.js processes...
taskkill /F /IM node.exe >nul 2>&1
timeout /t 2 /nobreak > nul
echo ✅ All Node processes killed

echo [2/4] Cleaning ALL caches...
cd "%PROJECT_DIR%\frontend"
if exist ".vite" rd /s /q ".vite" >nul 2>&1
if exist ".cache" rd /s /q ".cache" >nul 2>&1
if exist "dist" rd /s /q "dist" >nul 2>&1
if exist "node_modules\.vite" rd /s /q "node_modules\.vite" >nul 2>&1
if exist "node_modules\.cache" rd /s /q "node_modules\.cache" >nul 2>&1
echo ✅ All caches cleaned

echo [3/4] Starting Vite dev server...
start "Frontend - React (CLEAN)" cmd /k "cd /d "%PROJECT_DIR%\frontend" && echo Starting clean Vite server... && npm run dev"
timeout /t 5 /nobreak > nul
echo ✅ Server starting...

echo [4/4] Instructions:
echo ╔════════════════════════════════════════════════════════════════════════════╗
echo ║ Wait 15 seconds for Vite compilation                                      ║
echo ║                                                                            ║
echo ║ Then open browser:                                                         ║
echo ║ 1. Close ALL browser windows                                              ║
echo ║ 2. Open new window                                                         ║
echo ║ 3. F12 → Right-click Reload → "Empty Cache and Hard Reload"              ║
echo ║ 4. Go to http://localhost:3000                                            ║
echo ║ 5. Go to Files (V2) tab                                                   ║
echo ║ 6. Look for "👁️ VIEW RESULTS" section!                                   ║
echo ╚════════════════════════════════════════════════════════════════════════════╝
echo.
pause
