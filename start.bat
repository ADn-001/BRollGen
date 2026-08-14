@echo off
setlocal
cd /d "%~dp0"

echo === B-Roll Engine ===

REM ── Require venv (must run install.bat first) ──────────────────────────────
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    echo Run install.bat first.
    pause & exit /b 1
)

set PYTHON="%~dp0.venv\Scripts\python.exe"
set ALEMBIC="%~dp0.venv\Scripts\alembic.exe"
set UVICORN="%~dp0.venv\Scripts\uvicorn.exe"

REM ── Apply any pending DB migrations ───────────────────────────────────────
echo Applying database migrations...
%ALEMBIC% upgrade head
if errorlevel 1 (
    echo ERROR: Database migration failed. Re-run install.bat.
    pause & exit /b 1
)

REM ── Always rebuild frontend to pick up latest changes ─────────────────────
echo Building frontend...
cd frontend
call npm run build
if errorlevel 1 ( echo ERROR: Frontend build failed & pause & exit /b 1 )
cd ..

echo.
echo Starting B-Roll Engine at http://127.0.0.1:7420
echo Press Ctrl+C to stop.
echo.

start "" "http://127.0.0.1:7420"
cd backend
%UVICORN% main:app --host 127.0.0.1 --port 7420
