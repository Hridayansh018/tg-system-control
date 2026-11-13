@echo off
echo Stopping tg-system-control background instances...
wmic process where "CommandLine like '%%tg-system-control%%'" call terminate 2>nul
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tg-system-control*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Done!
