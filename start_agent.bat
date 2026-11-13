@echo off
title TG-System-Control (Hermes Agent)
cd /d "%~dp0"
echo Starting TG-System-Control...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Running with fallback python in VideoStudio venv...
    "d:\VideoStudio_Mac\.venv\Scripts\python.exe" main.py
)
pause
