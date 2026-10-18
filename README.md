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

To run the whole pipeline (ATS boards, JobSpy, scoring, digest, email) every day at 7:00 AM, register the task once in PowerShell. The PC must be on or asleep (not shut down). The 10 AM cloud run stays as a fallback and only emails when it finds new roles:

```powershell
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "G:\Projects\Appollo\appollo\scripts\run_local.ps1"'
$trigger  = New-ScheduledTaskTrigger -Daily -At 7:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "Appollo Daily" -Action $action -Trigger $trigger -Settings $settings
```

Logs go to `data\logs\local_YYYY-MM-DD.log`.

## Review loop (applied, skipped, undecided)

You do not have to act on every role. Anything you ignore stays `digested`: it is never shown again and costs nothing.

```powershell
.\.venv\Scripts\python.exe scripts\mark_applied.py --list                          # digested roles still undecided
.\.venv\Scripts\python.exe scripts\mark_applied.py <id-prefix-or-url>               # applied today
.\.venv\Scripts\python.exe scripts\mark_applied.py <ref> --date 2026-10-17          # applied on another day
.\.venv\Scripts\python.exe scripts\mark_applied.py <ref> --skip --reason seniority   # skipped, with a reason
.\.venv\Scripts\python.exe scripts\mark_applied.py --skip-rest                      # skip everything still undecided
.\.venv\Scripts\python.exe scripts\calibration.py                                   # compare the scorer with your decisions
```

Skip reasons are `location`, `seniority`, `pay`, `company`, `not_relevant`, `already_applied_elsewhere`, `other`. Applying writes the role to `applied_history` (so it never returns) and refreshes `data/tracker.md` and `data/tracker.csv`. If you already have a tracker, put it at `data/private/tracker.csv` (or `.xlsx`) and run `scripts\import_tracker.py`.

## Review console (Supabase MCP, read-only)

Once, in a regular terminal (not the IDE panel), add the server for your project only and authenticate. The project ref is the part after `postgres.` in the `DATABASE_URL` user name. Keep this out of the repo (the repo is public); the default local scope does that.

```powershell
claude mcp add --transport http supabase "https://mcp.supabase.com/mcp?project_ref=<your-project-ref>&read_only=true&features=database"
claude /mcp    # choose supabase, then Authenticate, pick the organization that holds the project
```

Then ask Claude Code for "today's jobs". It queries `v_daily_digest` and groups the result as described in `CLAUDE.md`.

More run commands (fetching, scoring, digesting, scheduling) are added here as each step in `docs/BUILD_PLAN.md` lands.
