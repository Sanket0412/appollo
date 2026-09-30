# Appollo — Progress Tracker

Living status of the build described in [BUILD_PLAN.md](./BUILD_PLAN.md). Update this file at the end of every step: flip the status, add a dated changelog line, and note anything that deviated from the plan or needs Sanket's input.

## Repo audit (2026-09-29)

Baseline before Step 1 starts. The repo is a bare scaffold: folders and files exist per the target layout, but almost every file is 0 bytes.

- Empty (scaffold only): `CLAUDE.md`, `README.md`, `requirements.txt`, `config/search.yaml`, `config/companies.yaml`, all of `pipeline/**/*.py`, `scripts/mark_applied.py`, `scripts/run_local.ps1`, `data/private/resume.md`, `.github/workflows/daily-job-scan.yml`.
- Has content: `.gitignore` (correct — ignores `.env`, `data/`, `.venv/`), `.env.example` and `.env` (both use the **old** `SUPABASE_URL` / `SUPABASE_KEY` REST-key format — Step 1 replaces this with `DATABASE_URL`, a direct Postgres connection string).
- `.venv/` exists with pip only; no project dependencies installed yet.
- Not yet created: `db/migrations/`, `requirements-local.txt`, `config/employer_aliases.yaml`, `pipeline/text_utils.py`, `scripts/migrate.py`, `scripts/check_db.py`, `scripts/build_companies.py`, `scripts/import_tracker.py`, `pipeline/export/emailer.py`, `tests/` beyond `__init__.py`.
- `CLAUDE.md` is currently empty even though the build plan refers to it as already holding "standing rules" — needs Sanket's input on what those rules should say (tone/scope for Claude Code in this repo, review-console notes from Step 12, etc.).

## Step status

| # | Step | Status | Blocked on |
|---|---|---|---|
| 1 | Foundation, database and migrations | Built — awaiting test confirmation | Sanket to confirm the test output below looks right |
| 2 | LCA loader | Built — awaiting test confirmation | Sanket to confirm the top-20 list and per-file date ranges look right |
| 3 | Employer matching and `companies.yaml` | Not started | Step 2 |
| 4 | ATS fetchers | Not started | Step 3 (for real slugs); live field verification for Lever/Ashby/Workday |
| 5 | Prefilter, dedup, run orchestrator | Not started | Step 4 |
| 6 | JobSpy fetcher and local schedule | Not started | Step 5 |
| 7 | Embeddings and shortlist | Not started | Step 5; Sanket's resume text in `data/private/resume.md` |
| 8 | Haiku rubric via Batches API | Not started | Step 7; `ANTHROPIC_API_KEY` |
| 9 | Ranking and digest | Not started | Step 8 |
| 10 | Tracker import/export and mark_applied | Not started | Step 9; Sanket's existing tracker file |
| 11 | GitHub Actions | Not started | Step 9; GitHub Secrets configured by Sanket |
| 12 | Review console and assisted apply | Not started | Step 11; Supabase MCP server details |

Status values: `Not started`, `In progress`, `Built — awaiting test confirmation`, `Done`, `Blocked`.

## Open items needing Sanket's input

See [DECISIONS.md](./DECISIONS.md) for the three open questions from the build plan (§9), plus:
- Content for `CLAUDE.md` standing rules.
- `DATABASE_URL` (Supabase Session pooler connection string) for `.env`.
- Resume text for `data/private/resume.md`.
- DOL LCA `.xlsx` files downloaded into `data/lca/` (FY2025 Q1–Q4, FY2026 Q3).
- Existing tracker file (for `import_tracker.py` at Step 10).

## Changelog

- **2026-09-29** — Repo audited. `docs/BUILD_PLAN.md` and `docs/progress.md` created. No implementation started yet.
- **2026-09-29** — Step 1 built: `requirements.txt`/`requirements-local.txt` (pinned to resolved versions), `config/search.yaml`, `db/migrations/001_init.sql`, `pipeline/settings.py`, `pipeline/db.py`, `pipeline/log.py`, `scripts/migrate.py`, `scripts/check_db.py`, `README.md`. Fixed `.env`: renamed `SUPABASE_URL` to `DATABASE_URL`, percent-encoded the `@` in the password, dropped the unused `SUPABASE_KEY` line. Ran all four Step 1 test commands against the real Supabase database — pgvector installed, all five tables created at 0 rows, second migration run is a no-op. Awaiting Sanket's confirmation before committing.
- **2026-09-29** — Step 2 built: `pipeline/text_utils.py` (`normalize_company`, pulled ahead from Step 4 since the loader needs it), `pipeline/sponsorship/lca_loader.py`, `tests/test_text_utils.py`. Verified live against the actual files in `data/lca/`: column names match the FY2026 Q3 record layout PDF exactly (all 5 files), and `CASE_STATUS`/`VISA_CLASS`/`WAGE_UNIT_OF_PAY` string values match what the loader filters on. Ran the loader end to end: 1,034,048 raw rows across 5 files, 1,023,639 after CASE_NUMBER dedup, 921,635 certified H-1B rows, 83,668 employers written to `lca_employers`. Top 20 NY/NJ employers by relevant-SOC filings are recognizable big tech/finance names (Amazon, Google, Microsoft, Meta, JPMorgan Chase, Citibank, etc.).
  - **Finding on FY2025 file coverage** (Sanket asked to confirm this): the FY2025 Q1–Q4 files are each a single non-overlapping quarter, not cumulative — Q1 covers 2024-10-01 to 2024-12-31, Q2 covers 2025-01-01 to 2025-03-31, Q3 covers 2025-04-01 to 2025-06-30, Q4 covers 2025-07-01 to 2025-09-30. FY2025 Q4 alone does **not** cover the full fiscal year; all four quarterly files are needed for full FY2025 coverage, which matches BUILD_PLAN.md §2's "partly verified" note and is why all four are already downloaded. FY2026 Q3, by contrast, spans 2025-10-01 to 2026-06-30 in one file, confirming it is cumulative year-to-date as documented.
