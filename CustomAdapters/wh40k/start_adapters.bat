@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === B-Roll Engine -- Starting All Adapters ===
echo.

REM ── Locate the main app venv ──────────────────────────────────────────────────
set VENV_PY=
if exist "%~dp0..\.venv\Scripts\python.exe"    set VENV_PY="%~dp0..\.venv\Scripts\python.exe"
if "!VENV_PY!"=="" if exist "%~dp0..\..\.venv\Scripts\python.exe" set VENV_PY="%~dp0..\..\.venv\Scripts\python.exe"

if "!VENV_PY!"=="" (
    echo ERROR: Main app virtual environment not found.
    echo Run install.bat in the BRollGen folder first.
    pause & exit /b 1
)

REM ── Verify all adapter files exist before launching anything ──────────────────
set MISSING=0
for %%F in (
    40k_adapter.py
    artvee_adapter.py
    wikimedia_adapter.py
    nasa_adapter.py
    openverse_adapter.py
    openverse_base.py
) do (
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
echo Launching 40k.gallery adapter             ^(port 3000^)...
start "Adapter: 40k.gallery [port 3000]"           cmd /k "!VENV_PY! "%~dp040k_adapter.py""

echo Launching artvee.com adapter              ^(port 3001^)...
start "Adapter: artvee.com [port 3001]"            cmd /k "!VENV_PY! "%~dp0artvee_adapter.py""

echo Launching Wikimedia Commons adapter       ^(port 3002^)...
start "Adapter: Wikimedia Commons [port 3002]"     cmd /k "!VENV_PY! "%~dp0wikimedia_adapter.py""

echo Launching NASA adapter                    ^(port 3003^)...
start "Adapter: NASA [port 3003]"                  cmd /k "!VENV_PY! "%~dp0nasa_adapter.py""

echo Launching All Openverse adapter           ^(port 3005^)...
start "Adapter: All Openverse [port 3005]"         cmd /k "!VENV_PY! "%~dp0openverse_adapter.py""

REM ── Give adapters a moment to bind their ports, then print status ─────────────
echo.
echo Waiting for adapters to start...
timeout /t 4 /nobreak >nul

echo.
echo ============================================================
echo  All adapters launched.
echo.
echo  40k.gallery       http://localhost:3000/health
echo  artvee.com        http://localhost:3001/health
echo  Wikimedia Commons http://localhost:3002/health
echo  NASA              http://localhost:3003/health
echo  All Openverse     http://localhost:3005/health
echo.
echo  Openverse adapters work anonymously (20 results/request max).
echo  For higher limits, set Openverse OAuth2 credentials in Sources UI
echo  as:  client_id:client_secret
echo  Register free at: https://api.openverse.org/v1/auth_tokens/register/
echo  Or set env vars: OPENVERSE_CLIENT_ID and OPENVERSE_CLIENT_SECRET
echo.
echo  Keep this window and the adapter windows open while
echo  B-Roll Engine is running.
echo ============================================================
echo.
pause
