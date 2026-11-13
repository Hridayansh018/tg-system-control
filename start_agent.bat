@echo off
title TG-System-Control (Hermes Agent)
cd /d "%~dp0"

echo ============================================================
echo   Starting TG-System-Control (Pre-Flight Subsystem Check)
echo ============================================================
echo.
echo [1/2] Verifying Python runtime and required packages...

set PYTHON_CMD=python
if exist "d:\VideoStudio_Mac\.venv\Scripts\python.exe" (
    set PYTHON_CMD="d:\VideoStudio_Mac\.venv\Scripts\python.exe"
)

%PYTHON_CMD% setup_check.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Required packages or configurations failed verification.
    echo Please resolve the errors above before launching.
    pause
    exit /b 1
)

echo.
echo [2/2] Launching Daemon (Zero-Latency Warm-Up in progress)...
echo Telegram will be pinged ONLY when all scripts, packages, and engines are primed.
echo.

%PYTHON_CMD% -u main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Agent terminated with error code %ERRORLEVEL%.
    pause
)
