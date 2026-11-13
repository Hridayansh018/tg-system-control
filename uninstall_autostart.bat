@echo off
echo Removing TG-System-Control from Windows Startup...
set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TGSystemControl.lnk"

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [SUCCESS] Auto-start removed successfully!
) else (
    echo Auto-start shortcut was not found.
)
pause
