@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === B-Roll Engine ^— Adapter Setup ===
echo.

REM ── Locate the main app venv (handles 1 or 2 levels above this folder) ──────
set VENV_PY=
if exist "%~dp0..\.venv\Scripts\python.exe"    set VENV_PY="%~dp0..\.venv\Scripts\python.exe"
if "!VENV_PY!"=="" if exist "%~dp0..\..\.venv\Scripts\python.exe" set VENV_PY="%~dp0..\..\.venv\Scripts\python.exe"

if "!VENV_PY!"=="" (
    echo ERROR: Main app virtual environment not found.
    echo Run install.bat in the BRollGen folder first, then re-run this script.
    pause & exit /b 1
)

echo Found venv: !VENV_PY!
!VENV_PY! --version
echo.

REM ── Install adapter dependencies into the main app venv ──────────────────────
REM flask / requests / beautifulsoup4 are already in the main requirements.txt.
REM This step is a safety net in case adapters were set up before the main install.
echo Installing adapter dependencies...
!VENV_PY! -m pip install --quiet flask>=3.0.0 requests>=2.32.0 beautifulsoup4>=4.12.0
if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )

REM ── Verify Playwright Chromium is installed ───────────────────────────────────
echo.
echo Verifying Playwright Chromium...
set PLAYWRIGHT_EXE=
if exist "%~dp0..\.venv\Scripts\playwright.exe"       set PLAYWRIGHT_EXE="%~dp0..\.venv\Scripts\playwright.exe"
if "!PLAYWRIGHT_EXE!"=="" if exist "%~dp0..\..\.venv\Scripts\playwright.exe" set PLAYWRIGHT_EXE="%~dp0..\..\.venv\Scripts\playwright.exe"

if "!PLAYWRIGHT_EXE!"=="" (
    echo WARNING: playwright.exe not found in venv.
    echo Run install.bat first to get Playwright installed.
) else (
    !PLAYWRIGHT_EXE! install chromium
    if errorlevel 1 ( echo WARNING: Playwright chromium install had issues. )
)

REM ── Confirm adapter files are present ─────────────────────────────────────────
echo.
echo Checking adapter files...
set MISSING=0
for %%F in (40k_adapter.py artvee_adapter.py loc_adapter.py) do (
    if exist "%%F" (
        echo   [OK] %%F
    ) else (
        echo   [MISSING] %%F
        set MISSING=1
    )
)

if "!MISSING!"=="1" (
    echo.
    echo WARNING: One or more adapter files are missing from this folder.
    echo Make sure all adapter .py files are in: %~dp0
)

echo.
echo ============================================================
echo  Adapter setup complete.
echo  Run start_adapters.bat to launch all adapters.
echo ============================================================
pause
