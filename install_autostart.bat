@echo off
setlocal
echo ========================================================
echo Installing TG-System-Control to Windows Startup...
echo ========================================================

set "TARGET_VBS=%~dp0start_agent_silent.vbs"
set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\TGSystemControl.lnk"

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_VBS%'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'TG-System-Control Background Agent'; $s.Save()"

if exist "%SHORTCUT_PATH%" (
    echo.
    echo [SUCCESS] Auto-start installed successfully!
    echo Location: %SHORTCUT_PATH%
    echo.
    echo Ab har baar jab bhi aapka PC ON hoga, yeh bot background mein
    echo automatically start ho jayega aur Telegram par 'System ONLINE' bhej dega!
) else (
    echo.
    echo [ERROR] Failed to create shortcut.
)

pause
