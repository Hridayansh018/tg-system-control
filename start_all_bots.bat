@echo off
setlocal
cd /d "%~dp0"
title Start both bots

rem Starts TG-System-Control silently; it starts the Video Studio bot by itself (STUDIO_AUTOSTART=true in .env)
rem and each bot posts its green ONLINE notice when ready (about 30-40 seconds).
echo Starting TG-System-Control (and the Video Studio bot)...
wscript.exe "%~dp0start_agent_silent.vbs"
echo Started. Watch Telegram for the ONLINE messages. Stop both with stop_all_bots.bat or /stopall.
