@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === B-Roll Engine ^— Starting All Adapters ===
echo.

REM ── Locate the main app venv ──────────────────────────────────────────────────
set VENV_PY=
if exist "%~dp0..\.venv\Scripts\python.exe"    set VENV_PY="%~dp0..\.venv\Scripts\python.exe"
if "!VENV_PY!"=="" if exist "%~dp0..\..\.venv\Scripts\python.exe" set VENV_PY="%~dp0..\..\.venv\Scripts\python.exe"

if "!VENV_PY!"=="" (
    echo ERROR: Main app virtual environment not found.
    echo Run install.bat in the BRollGen folder, then install_adapters.bat here.
    pause & exit /b 1
)

REM ── Verify all adapter files exist before launching anything ──────────────────
set MISSING=0
for %%F in (40k_adapter.py artvee_adapter.py loc_adapter.py) do (
    if not exist "%%F" (
        echo ERROR: %%F not found in %~dp0
        set MISSING=1
    )
)
if "!MISSING!"=="1" (
    echo.
    echo Place all adapter .py files in the same folder as this script.
    pause & exit /b 1
)

REM ── Launch each adapter in its own titled console window ──────────────────────
echo Launching 40k.gallery adapter     ^(port 3000^)...
start "Adapter: 40k.gallery [port 3000]" cmd /k "!VENV_PY! "%~dp040k_adapter.py""

echo Launching artvee.com adapter      ^(port 3001^)...
start "Adapter: artvee.com [port 3001]" cmd /k "!VENV_PY! "%~dp0artvee_adapter.py""

echo Launching loc.gov adapter         ^(port 3002^)...
start "Adapter: loc.gov [port 3002]"    cmd /k "!VENV_PY! "%~dp0loc_adapter.py""

REM ── Give adapters a moment to bind their ports, then print status ─────────────
echo.
echo Waiting for adapters to start...
timeout /t 4 /nobreak >nul

echo.
echo ============================================================
echo  All adapters launched.
echo.
echo  40k.gallery   http://localhost:3000/health
echo  artvee.com    http://localhost:3001/health
echo  loc.gov       http://localhost:3002/health
echo.
echo  Keep this window and the three adapter windows open while
echo  B-Roll Engine is running. Close them to stop the adapters.
echo ============================================================
echo.
pause
