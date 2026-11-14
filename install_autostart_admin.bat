@echo off
rem Installs TG-System-Control to start at logon WITH administrator rights (one UAC prompt now,
rem none at boot). Needed for /block, the input lock, and controlling admin windows.
cd /d "%~dp0"
echo Requesting administrator permission...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','\"%~dp0install_autostart_admin.ps1\"'"
echo.
echo If you clicked "Yes", the bot now runs as administrator and starts at every logon.
echo Start it again any time (no UAC prompt): schtasks /Run /TN TGSystemControl
pause
