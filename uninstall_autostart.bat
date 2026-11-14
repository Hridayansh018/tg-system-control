@echo off
echo Removing TG-System-Control from Windows Startup...
set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TGSystemControl.lnk"

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [SUCCESS] Startup shortcut removed.
) else (
    echo Startup shortcut was not found.
)

schtasks /Query /TN TGSystemControl >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    schtasks /Delete /TN TGSystemControl /F >nul 2>&1
    if errorlevel 1 (
        echo Removing the admin scheduled task needs administrator rights - asking now...
        powershell -NoProfile -Command "Start-Process schtasks -Verb RunAs -Wait -ArgumentList '/Delete','/TN','TGSystemControl','/F'"
    )
    schtasks /Query /TN TGSystemControl >nul 2>&1
    if errorlevel 1 (echo [SUCCESS] Admin scheduled task removed.) else (echo [WARNING] Scheduled task is still there.)
)
pause
