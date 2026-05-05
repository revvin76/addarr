@echo off
REM ============================================================================
REM Flask Restart Monitor for Windows
REM ============================================================================
REM This script monitors the .reload file and restarts Flask when it's touched.
REM
REM Usage: Run this in a SEPARATE command prompt while Flask is running:
REM   restart_monitor.bat
REM
REM Setup:
REM   Terminal 1: start.cmd (runs Flask normally)
REM   Terminal 2: restart_monitor.bat (monitors and restarts Flask)
REM ============================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set RELOAD_FILE=%CD%\.reload
set PORT=5000
set FLASK_CHECK_COUNT=0

echo.
echo ============================================================================
echo Flask Restart Monitor - Windows
echo ============================================================================
echo Monitoring: %RELOAD_FILE%
echo Port: %PORT%
echo.
echo This script will:
echo 1. Watch for changes to .reload file
echo 2. Find Flask process listening on port %PORT%
echo 3. Kill it gracefully
echo 4. Wait 2 seconds for Flask to restart
echo.
echo ============================================================================
echo.

REM Initialize by checking if .reload exists
if exist "%RELOAD_FILE%" (
    for /f %%A in ('powershell -Command "(Get-Item '%RELOAD_FILE%').LastWriteTime.Ticks"') do set LAST_MTIME=%%A
) else (
    set LAST_MTIME=0
)

echo [%date% %time%] Monitor started. Waiting for reload signal...
echo.

:monitor_loop
timeout /t 1 /nobreak >nul

REM Check if .reload file exists and has been modified
if exist "%RELOAD_FILE%" (
    for /f %%A in ('powershell -Command "(Get-Item '%RELOAD_FILE%').LastWriteTime.Ticks"') do set CURRENT_MTIME=%%A

    if not "!CURRENT_MTIME!"=="!LAST_MTIME!" (
        REM File was modified!
        echo.
        echo [%date% %time%] ===================================================
        echo [%date% %time%] ^^ RELOAD SIGNAL DETECTED ^^
        echo [%date% %time%] ===================================================

        REM Find Flask PID listening on the port
        for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%PORT%.*LISTENING"') do (
            set FLASK_PID=%%A
        )

        if defined FLASK_PID (
            echo [%date% %time%] Found Flask process on port %PORT% (PID: !FLASK_PID!)
            echo [%date% %time%] Stopping Flask process...

            REM Kill the process
            taskkill /PID !FLASK_PID! /F >nul 2>&1

            if errorlevel 1 (
                echo [%date% %time%] WARNING: Could not kill PID !FLASK_PID! ^(may already be stopped^)
            ) else (
                echo [%date% %time%] Flask process killed.
            )

            echo [%date% %time%] Waiting 2 seconds...
            timeout /t 2 /nobreak >nul

            echo [%date% %time%] Ready for restart ^(Flask should restart in Terminal 1^)
            echo [%date% %time%] ===================================================
            echo.

            set FLASK_CHECK_COUNT=0
        ) else (
            echo [%date% %time%] WARNING: No Flask process found on port %PORT%
            echo [%date% %time%]          If Flask crashed, restart it manually in Terminal 1
            echo.
        )

        set LAST_MTIME=!CURRENT_MTIME!
    )
) else (
    set LAST_MTIME=0
)

goto monitor_loop

:end
echo [%date% %time%] Monitor stopped.
pause
