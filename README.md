# Appollo

Appollo is a personal daily job-discovery pipeline. It finds fresh Data Scientist, ML Engineer and AI Engineer roles every day from public ATS APIs (plus light, local-only JobSpy searches), filters them, checks employer H-1B filing history against DOL LCA data, scores fit with Claude Haiku, and delivers a ranked list of apply links.

The full build spec lives in [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md); current status is tracked in [`docs/progress.md`](docs/progress.md).

## Setup

```powershell
git clone https://github.com/Sanket0412/appollo.git
cd appollo
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
copy .env.example .env
# then fill in DATABASE_URL (Supabase Session pooler URI) in .env
```

## Database

```powershell
.\.venv\Scripts\python.exe scripts\migrate.py    # applies db/migrations/*.sql
.\.venv\Scripts\python.exe scripts\check_db.py   # sanity check: server version, pgvector, row counts
```

## Local JobSpy run (Indeed and LinkedIn)

JobSpy runs only on this machine; it refuses to run when `GITHUB_ACTIONS=true`. It reads public search pages and never logs in to any account. Only Indeed and LinkedIn work reliably (Glassdoor and ZipRecruiter return 403, Google returns nothing, checked 2026-10-16). A run takes about 15 minutes.

```powershell
.\.venv\Scripts\python.exe -m pipeline.run --sources jobspy --window 24h --dry-run   # fetch only, nothing written
.\.venv\Scripts\python.exe -m pipeline.run --sources jobspy --window 24h             # stores rows; the 10 AM cloud run scores them
```

A real run may append new boards to `config/companies.yaml` as `source: discovered`. Review and commit that file yourself.

To run it every day at 9:30 AM, register the task once in PowerShell:

```powershell
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "G:\Projects\Appollo\appollo\scripts\run_local.ps1"'
$trigger  = New-ScheduledTaskTrigger -Daily -At 9:30am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "Appollo JobSpy" -Action $action -Trigger $trigger -Settings $settings
```

Logs go to `data\logs\local_YYYY-MM-DD.log`.

More run commands (fetching, scoring, digesting, scheduling) are added here as each step in `docs/BUILD_PLAN.md` lands.
