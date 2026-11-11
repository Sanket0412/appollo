# Registers (or replaces) the "Appollo Daily" scheduled task for the current user.
# Triggers: 7:00 AM daily, every resume from sleep, every logon (covers restarts).
# Run from a normal (non-admin) PowerShell:  .\scripts\register_task.ps1
$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo "scripts\run_local.ps1"
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $repo `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""

$daily = New-ScheduledTaskTrigger -Daily -At 7:00AM
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user

# Resume from sleep or hibernate (Power-Troubleshooter event 1).
$cls = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$wake = New-CimInstance -CimClass $cls -ClientOnly
$wake.Enabled = $true
$wake.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''Microsoft-Windows-Power-Troubleshooter''] and EventID=1]]</Select></Query></QueryList>'

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10) -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "Appollo Daily" -Action $action -Trigger @($daily, $wake, $logon) `
    -Settings $settings -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName "Appollo Daily" | Select-Object TaskName, State
