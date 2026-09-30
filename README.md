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

More run commands (fetching, scoring, digesting, scheduling) are added here as each step in `docs/BUILD_PLAN.md` lands.
