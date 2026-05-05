@echo off
REM ============================================================
REM arrdash Flask Application Launcher
REM Restart Monitor as Background Daemon Thread
REM ============================================================
REM
REM How it works:
REM   1. Runs: python app.py
REM   2. Flask starts and launches RestartMonitor daemon thread
REM   3. RestartMonitor watches .reload file
REM   4. When .reload is touched, Flask gracefully exits (os._exit)
REM   5. This batch file detects exit and restarts (goes to :restart label)
REM   6. Repeat until user presses Ctrl-C
REM
REM Features:
REM   - Single command in terminal (no separate monitor window)
REM   - Automatic restart on .reload file touch
REM   - Clean shutdown (RestartMonitor stops cleanly)
REM   - Works on Windows without bash/shell dependencies
REM ============================================================

setlocal enabledelayedexpansion

REM Get the directory where this batch file is located
cd /d "%~dp0"

echo.
echo ===============================================
echo    arrdash - Flask Application Launcher
echo    Built-in Restart Monitor
echo ===============================================
echo.

:restart
echo [info] Starting Flask application...
python app.py

REM Check exit code
set EXIT_CODE=!errorlevel!

if %EXIT_CODE% equ 0 (
    echo.
    echo [info] Flask exited gracefully (code 0^) - Restarting...
    timeout /t 2 /nobreak
    goto restart
) else (
    echo.
    echo [error] Flask exited with code %EXIT_CODE% - Restarting...
    timeout /t 5 /nobreak
    goto restart
)