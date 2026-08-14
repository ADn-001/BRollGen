@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === B-Roll Engine ^— First-Time Setup ===
echo.

REM ── Find Python 3.10+ ──────────────────────────────────────────────────────
REM :try runs the interpreter and exits 0 only if it is a working Python 3.10+.
REM This beats regex-on-version-string: it catches stale py-launcher registry
REM entries that report a version but have no actual runtime on disk.
set PYTHON_CMD=
call :try "py -3.13"
call :try "py -3.12"
call :try "py -3.11"
call :try "py -3.10"
call :try "py"
call :try "python3"
call :try "python"
if "!PYTHON_CMD!"=="" call :try_path "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "C:\Python313\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "C:\Python312\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "C:\Python311\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "C:\Python310\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "C:\msys64\mingw64\bin\python.exe"
if "!PYTHON_CMD!"=="" call :try_path "C:\msys64\usr\bin\python3.exe"

if "!PYTHON_CMD!"=="" (
    echo ERROR: Python 3.10 or newer not found.
    echo.
    echo Install Python 3.10+ from https://python.org
    echo During install, tick "Add Python to PATH", then re-run this script from
    echo an open Command Prompt:
    echo   cd /d "%~dp0"
    echo   install.bat
    pause & exit /b 1
)

echo Using: !PYTHON_CMD!
!PYTHON_CMD! --version
echo.

REM ── Create / reuse virtual environment ────────────────────────────────────
if exist ".venv\Scripts\activate.bat" (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if errorlevel 1 (
        echo Existing virtual environment is broken -- recreating...
        rmdir /s /q .venv
    ) else (
        echo Virtual environment already exists -- reusing.
    )
)
if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment in .venv ...
    !PYTHON_CMD! -m venv .venv
    if errorlevel 1 (
        echo ERROR: venv creation failed.
        pause & exit /b 1
    )
)

REM All subsequent commands use the venv's Python
set PYTHON="%~dp0.venv\Scripts\python.exe"
set PIP="%~dp0.venv\Scripts\python.exe" -m pip
set PLAYWRIGHT="%~dp0.venv\Scripts\playwright.exe"
set ALEMBIC="%~dp0.venv\Scripts\alembic.exe"

echo.
echo Installing Python dependencies...
%PIP% install --upgrade pip --quiet
%PIP% install -r requirements.txt
if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )

echo.
echo Downloading spaCy language model ^(en_core_web_sm^)...
%PYTHON% -m spacy download en_core_web_sm
if errorlevel 1 ( echo ERROR: spaCy model download failed & pause & exit /b 1 )

echo.
echo Installing Playwright Chromium browser...
%PLAYWRIGHT% install chromium
if errorlevel 1 ( echo WARNING: Playwright install failed -- SerpScraper Playwright fallback will not work. )

echo.
echo Running database migrations...
%ALEMBIC% upgrade head
if errorlevel 1 ( echo ERROR: Alembic migration failed & pause & exit /b 1 )

REM ── Frontend ───────────────────────────────────────────────────────────────
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install from https://nodejs.org
    pause & exit /b 1
)

echo.
echo Installing frontend dependencies...
cd frontend
call npm install
if errorlevel 1 ( echo ERROR: npm install failed & pause & exit /b 1 )

echo Building frontend...
call npm run build
if errorlevel 1 ( echo ERROR: Frontend build failed & pause & exit /b 1 )
cd ..

echo.
echo ============================================================
echo  Setup complete! Run start.bat to launch B-Roll Engine.
echo ============================================================
pause
goto :eof


REM ============================================================================
REM  Subroutines
REM ============================================================================

:try
REM Usage: call :try "py -3.11"   or   call :try "C:\Python311\python.exe"
REM Runs the interpreter with a one-liner that exits 0 only on Python 3.10+.
REM Sets PYTHON_CMD and returns immediately if PYTHON_CMD is already set.
if not "!PYTHON_CMD!"=="" exit /b 0
%~1 -c "import sys; v=sys.version_info; exit(0 if v[0]==3 and v[1]>=10 else 1)" >nul 2>&1
if not errorlevel 1 set PYTHON_CMD=%~1
exit /b 0

:try_path
REM Usage: call :try_path "C:\full\path\python.exe"
REM Checks the file exists before delegating to :try.
if not "!PYTHON_CMD!"=="" exit /b 0
if not exist "%~1" exit /b 0
call :try "%~1"
exit /b 0
