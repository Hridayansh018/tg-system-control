@echo off
setlocal
cd /d "%~dp0"
echo Stopping TG-System-Control...

rem 1. Ask the running bot to stop itself (it sends OFFLINE to Telegram, then exits)
if not exist "%~dp0temp" mkdir "%~dp0temp"
echo stop> "%~dp0temp\.stop_request"

rem 2. Wait up to 10 s, then force-stop anything still running from this folder
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$main = (Join-Path '%~dp0' 'main.py');" ^
  "function Find-Bot { Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like ('*' + $main + '*') } };" ^
  "for ($i = 0; $i -lt 10 -and (Find-Bot); $i++) { Start-Sleep -Seconds 1 };" ^
  "$left = @(Find-Bot);" ^
  "$legacy = @(Get-NetTCPConnection -LocalPort 49221 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } | Where-Object { $_.ProcessName -like 'python*' });" ^
  "foreach ($p in $left) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue };" ^
  "foreach ($p in $legacy) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue };" ^
  "if ($left.Count -or $legacy.Count) { Write-Output ('Force-stopped ' + ($left.Count + $legacy.Count) + ' process(es).') } else { Write-Output 'Stopped.' }"

if exist "%~dp0temp\.stop_request" del "%~dp0temp\.stop_request"
echo Done!
