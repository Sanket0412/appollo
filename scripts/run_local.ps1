# Full daily pipeline on this machine: ATS boards + JobSpy, then score, digest and email.
# Registered as the "Appollo Daily" scheduled task (7:00 AM). Logs go to data\logs.
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$logDir = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("local_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
# cmd does the redirect so the log is plain UTF-8 text; PowerShell's *>> writes UTF-16 and wraps stderr lines as errors.
$env:PYTHONUTF8 = "1"
cmd /c "`"$repo\.venv\Scripts\python.exe`" -m pipeline.run --sources ats,jobspy --window 24h --score --digest --email >> `"$log`" 2>&1"
exit $LASTEXITCODE
