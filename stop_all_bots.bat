@echo off
setlocal
cd /d "%~dp0"
title Stop both bots

rem Clean shutdown of BOTH bots - each posts a red OFFLINE notice in its Telegram chat.
rem 1) Video Studio bot (stop flag -> announces OFFLINE -> exits)   2) TG-System-Control (stop_agent.bat)
set "PYTHON_CMD="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_CMD (
    python -c "import requests, PIL" >nul 2>&1 && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    if exist "D:\VideoStudio_Mac\.venv\Scripts\python.exe" set "PYTHON_CMD=D:\VideoStudio_Mac\.venv\Scripts\python.exe"
)
if not defined PYTHON_CMD set "PYTHON_CMD=python"

echo Stopping the Video Studio bot...
"%PYTHON_CMD%" "%~dp0stop_all_bots.py"
echo.
echo Stopping TG-System-Control...
call "%~dp0stop_agent.bat"
echo.
echo Both bots are stopped. Start them again with start_all_bots.bat
