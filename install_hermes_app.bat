@echo off
title Install Official Hermes Agent Desktop App
cd /d "%~dp0"

echo ============================================================
echo   Installing Official Nous Research Hermes Agent Desktop App
echo ============================================================
echo.

set HERMES_DIR=D:\git-data\hermes-agent
if not exist "D:\git-data" (
    set HERMES_DIR=%~dp0..\hermes-agent
)

echo [1/4] Checking repository at: %HERMES_DIR%
if not exist "%HERMES_DIR%" (
    echo Cloning official Hermes Agent repository...
    git clone --depth 1 https://github.com/nousresearch/hermes-agent.git "%HERMES_DIR%"
) else (
    echo Repository already present.
)

echo.
echo [2/4] Setting up isolated Hermes environment and PM toolchain...
pushd "%HERMES_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-hermes.ps1 -RuntimeOnly
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] setup-hermes.ps1 returned code %ERRORLEVEL%. Continuing with build...
)

echo.
echo [3/4] Building standalone Electron Desktop app (Hermes.exe)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ". .\activate.ps1; hermes desktop --build-only"
popd

echo.
echo [4/4] Creating Desktop shortcut with official icon...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$sh = New-Object -ComObject WScript.Shell; " ^
    "$exe = '%HERMES_DIR%\apps\desktop\release\win-unpacked\Hermes.exe'; " ^
    "$ico = '%HERMES_DIR%\apps\desktop\assets\icon.ico,0'; " ^
    "$desk = [Environment]::GetFolderPath('Desktop'); " ^
    "if (Test-Path $exe) { " ^
    "  $sc = $sh.CreateShortcut((Join-Path $desk 'Hermes Agent.lnk')); " ^
    "  $sc.TargetPath = $exe; " ^
    "  $sc.WorkingDirectory = '%HERMES_DIR%'; " ^
    "  $sc.IconLocation = $ico; " ^
    "  $sc.Description = 'Hermes Agent - Official Nous Research Desktop App'; " ^
    "  $sc.Save(); " ^
    "  Write-Host '✅ Desktop shortcut created successfully!'; " ^
    "} else { " ^
    "  Write-Host '⚠️ Hermes.exe not found at:' $exe; " ^
    "}"

echo.
echo ============================================================
echo   Installation Complete!
echo ============================================================
pause
