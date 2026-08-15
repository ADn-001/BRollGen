@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === B-Roll Engine -- Stop ===
echo.

REM Ports to kill: main app + all adapters
REM Kills by listening port so it works whether they were launched
REM by start.bat / start_adapters.bat (visible windows) or by the
REM backend auto-launch (hidden subprocess with CREATE_NO_WINDOW).

set STOPPED=0
set ALREADY_DOWN=0

call :kill_port 7420 "Main app (uvicorn)"
call :kill_port 3000 "40k.gallery adapter"
call :kill_port 3001 "artvee.com adapter"
call :kill_port 3002 "Wikimedia Commons adapter"
call :kill_port 3003 "NASA adapter"
call :kill_port 3005 "All Openverse adapter"

echo.
if !STOPPED! GTR 0 (
    echo Stopped !STOPPED! process(es^).
) else (
    echo Nothing was running on any of the registered ports.
)
echo.
pause
exit /b 0


REM ── Subroutine: kill whatever is LISTENING on %1 ──────────────────────────
:kill_port
set _PORT=%1
set _NAME=%~2
set _FOUND=0

for /f "tokens=5" %%A in (
    'netstat -ano 2^>nul ^| findstr /r ":%_PORT% " ^| findstr "LISTENING"'
) do (
    if "%%A" NEQ "" if "%%A" NEQ "0" (
        set _FOUND=1
        set _PID=%%A
    )
)

if "!_FOUND!"=="1" (
    REM /T kills the process tree so any children (e.g. uvicorn workers) go too
    taskkill /PID !_PID! /T /F >nul 2>&1
    if !errorlevel! EQU 0 (
        echo [OK]  %-30s port %_PORT%  PID !_PID! stopped.
        set /a STOPPED+=1
    ) else (
        echo [ERR] %-30s port %_PORT%  PID !_PID! -- could not stop (already gone?^)
    )
) else (
    echo [--]  %-30s port %_PORT%  not running.
    set /a ALREADY_DOWN+=1
)
exit /b 0
