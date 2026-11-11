# Full daily pipeline on this machine: ATS boards + JobSpy, then score, digest and email.
# Registered as the "Appollo Daily" scheduled task (see scripts/register_task.ps1). Triggers: 7:00 AM daily,
# every wake from sleep, and every logon (covers restarts). Logs go to data\logs.
# Pass -Force to ignore the "already succeeded recently" guard.
param([switch]$Force)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$logDir = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("local_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
$marker = Join-Path $logDir "last_success.txt"

# Wake, logon and startup triggers can fire several times a day; one good run per 6 hours is enough.
if (-not $Force -and (Test-Path $marker)) {
    $age = (Get-Date) - (Get-Item $marker).LastWriteTime
    if ($age.TotalHours -lt 6) { exit 0 }
}

# Give Wi-Fi and DNS time to come back after wake or boot.
Start-Sleep -Seconds 45

# cmd does the redirect so the log is plain UTF-8 text; PowerShell's *>> writes UTF-16 and wraps stderr lines as errors.
$env:PYTHONUTF8 = "1"
cmd /c "`"$repo\.venv\Scripts\python.exe`" -m pipeline.run --sources ats,jobspy --window 24h --score --digest --email >> `"$log`" 2>&1"
$code = $LASTEXITCODE
if ($code -eq 0) { Set-Content -Path $marker -Value (Get-Date -Format "o") }
exit $code
