@echo off
title TG-System-Control (Hermes Agent)
cd /d "%~dp0"

echo ============================================================
echo   Starting TG-System-Control (Pre-Flight Subsystem Check)
echo ============================================================
echo.
echo [1/2] Verifying Python runtime and required packages...

rem Python selection: project .venv, then python on PATH (if it has the packages),
rem then the legacy VideoStudio venv, then plain python (setup_check explains what's missing).
set "PYTHON_CMD="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_CMD (
    python -c "import requests, PIL" >nul 2>&1 && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    if exist "D:\VideoStudio_Mac\.venv\Scripts\python.exe" set "PYTHON_CMD=D:\VideoStudio_Mac\.venv\Scripts\python.exe"
)
if not defined PYTHON_CMD set "PYTHON_CMD=python"
echo Using: %PYTHON_CMD%

"%PYTHON_CMD%" "%~dp0setup_check.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Required packages or configuration failed verification.
    echo Please resolve the errors above before launching.
    pause
    exit /b 1
)

echo.
echo [2/2] Launching daemon...
echo Telegram is pinged only after all subsystems are warmed up.
echo.

"%PYTHON_CMD%" -u "%~dp0main.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Agent terminated with error code %ERRORLEVEL%.
    pause
)
