@echo off
setlocal
set "PROJECT_DIR=%~dp0"

echo This partial launcher is intentionally disabled.
echo.
echo It cannot verify or start PostgreSQL, Redis, pinned model artifacts, and
echo llama-server in the required order. Starting only Celery, FastAPI, and the
echo frontend can produce a healthy-looking UI with a broken AI runtime.
echo.
echo Follow docs\NEW_MACHINE_SETUP.md and run this gate before starting services:
echo   powershell -ExecutionPolicy Bypass -File scripts\preflight_new_machine.ps1
echo.
echo The canonical backend and frontend commands bind to 127.0.0.1 only.
exit /b 2
