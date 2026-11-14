# Registers TG-System-Control as a Windows scheduled task that starts at logon WITH
# administrator rights (no UAC prompt at each boot). Needed for:
#   - /block and the input lock while the bot clicks/types (Windows BlockInput)
#   - clicking/typing into admin windows (Task Manager, admin terminals, installers)
# Run via install_autostart_admin.bat (it asks for admin once).

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $root 'start_agent_silent.vbs'
$taskName = 'TGSystemControl'
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$vbs`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'TG-System-Control Telegram remote control (admin)' -Force | Out-Null
Write-Host "[OK] Scheduled task '$taskName' installed (runs at logon as administrator)."

# The normal Startup-folder shortcut would start a second, non-admin copy -> remove it.
$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'TGSystemControl.lnk'
if (Test-Path $startup) { Remove-Item $startup -Force; Write-Host "[OK] Removed the non-admin Startup shortcut." }

# Stop a running non-admin bot (graceful stop flag first), then start the admin one now.
$tempDir = Join-Path $root 'temp'
if (-not (Test-Path $tempDir)) { New-Item -ItemType Directory -Path $tempDir | Out-Null }
$main = Join-Path $root 'main.py'
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -like "*$main*" })
# v1 bots (started with a relative "main.py") are found by the port they kept open
$legacyIds = @(Get-NetTCPConnection -LocalPort 49221 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess })
$running += @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $legacyIds -and $_.Name -like 'python*' })
if ($running.Count) {
    Set-Content -Path (Join-Path $tempDir '.stop_request') -Value 'stop'
    for ($i = 0; $i -lt 10 -and @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $running.ProcessId }).Count; $i++) { Start-Sleep 1 }
    foreach ($p in $running) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "[OK] Stopped the previous bot."
}
Start-ScheduledTask -TaskName $taskName
Write-Host "[OK] Bot started as administrator. You should get SYSTEM ONLINE in Telegram shortly."
