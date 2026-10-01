# Appollo Build Plan

This is the implementation spec for Claude Code. Standing rules are in `CLAUDE.md` at the repo root.

Work one step at a time. At the end of each step, give Sanket the test commands listed under that step, wait for him to confirm they pass, then commit.

---

## 1. Scope and decisions

**Goal.** Every morning, deliver a ranked list of fresh DS, ML and AI roles in the US, with NYC-area roles first, each with an apply link and the tracker fields filled in. No outbound materials are generated.

| Area | Decision |
|---|---|
| Discovery, primary | Public ATS APIs (Greenhouse, Lever, Ashby, Workday CXS), driven by `config/companies.yaml` |
| Discovery, secondary | JobSpy (Indeed, LinkedIn, Google), local Windows machine only, low volume |
| Freshness | `--window 24h` (default, daily) or `--window 7d` (first run and catch-ups). Fetches add a 2-hour grace buffer so a delayed schedule never leaves a gap; dedup removes overlap |
| Sponsorship history | DOL LCA disclosure files, aggregated per employer, fuzzy-matched with rapidfuzz |
| Sponsorship in JD | Claude Haiku extracts `Available`, `N/A` or `Not Mentioned` with verbatim evidence |
| Storage | Supabase Postgres with pgvector. Accessed with `psycopg` over the Session pooler connection string (IPv4, works from GitHub Actions). No Supabase REST keys are needed by the pipeline |
| Embeddings | Local `fastembed` with `BAAI/bge-small-en-v1.5`, 384 dimensions, free |
| Scoring | `claude-haiku-4-5-20251001` through the Message Batches API, structured JSON |
| Ranking | Fit score plus NYC-metro boost, remote boost, sponsorship and LCA adjustments |
| Output | Supabase view `v_daily_digest`, a local markdown digest, and an optional email via Gmail SMTP |
| Scheduling | GitHub Actions at 10:00 America/New_York for ATS, scoring and digest. Windows Task Scheduler at 9:30 for JobSpy |
| Excluded | Staffing agencies, citizenship or clearance requirements, explicit no-sponsorship JDs, senior titles above Senior (Staff, Principal, Director, Head, VP, Manager), internships |

**Status flow for a job row.**

```
new -> excluded            (prefilter, JD says no sponsorship, or YOE too high; reason in exclude_reason)
new -> not_shortlisted     (embedding similarity below threshold)
new -> shortlisted -> scored -> digested -> applied | skipped
```

---

## 2. Verified facts (checked September 29, 2026) and items still to verify

| Item | Status | Detail |
|---|---|---|
| Haiku 4.5 model id and price | Verified | Model id `claude-haiku-4-5` (dated `claude-haiku-4-5-20251001`). $1 input and $5 output per million tokens; Batch API is 50% off, i.e. $0.50 and $2.50 |
| DOL LCA FY2026 Q3 | Verified | Released August 14, 2026. Covers determinations October 1, 2025 through June 30, 2026. FY2026 files are cumulative year-to-date. The file name on the DOL page is spelled `LCA_Dislclosure_Data_FY2026_Q3.xlsx` (DOL's typo) |
| DOL LCA FY2025 | Partly verified | A third-party source says FY2022 to FY2025 files each cover a single quarter. The loader dedupes by `CASE_NUMBER`, so it is correct either way |
| GitHub Actions timezone | Verified | Since March 2026, `on.schedule` entries accept `timezone: "America/New_York"` next to `cron` |
| Greenhouse `first_published` | Verified | Exists and is the right freshness field. `updated_at` gets bulk-restamped across whole boards, so never use it for freshness. It may only appear on the per-job detail endpoint; check the list response first |
| Supabase keys | Verified | New keys are `sb_publishable_...` and `sb_secret_...`; legacy anon and service_role keys are being deprecated by the end of 2026. The pipeline avoids this by using a direct Postgres connection |
| Anthropic structured outputs parameter | To verify at Step 8 | Use native JSON-schema structured outputs if the current SDK supports it for Haiku 4.5; otherwise force a single tool call with the schema as `input_schema` |
| Lever, Ashby and Workday response fields | To verify at Step 4 | Confirm field names with a live request before writing parsers |
| Supabase MCP server URL and flags | To verify at Step 12 | |
| All library versions | To verify at each step | Pin after a clean install |

---

## 3. Environment and secrets

**Local `.env` (gitignored).** Replace the scaffolded `.env.example` with this at Step 1 and keep `.env` in sync.

```dotenv
# Supabase Postgres, Session pooler URI (Project > Connect > Session pooler). URL-encode special characters in the password.
DATABASE_URL=

# Claude Console API key, needed from Step 8
ANTHROPIC_API_KEY=

# Local path to plain-text resume (gitignored). In CI the resume comes from the RESUME_TEXT secret instead.
RESUME_TEXT_PATH=data/private/resume.md

# Optional email digest (Gmail app password requires 2-Step Verification)
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=
DIGEST_TO=
```

**GitHub Secrets (added at Step 11).** `DATABASE_URL`, `ANTHROPIC_API_KEY`, `RESUME_TEXT`, and optionally `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `DIGEST_TO`.

**Dependencies.** Split so CI stays lean and JobSpy stays local.

`requirements.txt`
```
requests
tenacity
pyyaml
pydantic>=2
python-dotenv
psycopg[binary]>=3
pgvector
numpy
pandas
pyarrow
python-calamine
rapidfuzz
beautifulsoup4
fastembed
anthropic
pytest
ruff
```

`requirements-local.txt`
```
-r requirements.txt
python-jobspy
```

Install locally with `.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt`. Pin exact versions once each step's imports work.

---

## 4. Final repository layout

Changes from the scaffold are marked NEW.

```
appollo/
├── CLAUDE.md
├── README.md
├── LICENSE
├── requirements.txt
├── requirements-local.txt                 NEW
├── .env.example
├── config/
│   ├── companies.yaml
│   ├── search.yaml
│   └── employer_aliases.yaml              NEW  manual LCA name overrides
├── db/migrations/
│   └── 001_init.sql                       NEW
├── docs/
│   └── BUILD_PLAN.md                      NEW  this file
├── pipeline/
│   ├── run.py
│   ├── settings.py
│   ├── db.py
│   ├── models.py
│   ├── text_utils.py                      NEW  normalization, HTML to text, US and NYC location parsing
│   ├── fetchers/ (base, greenhouse, lever, ashby, workday, jobspy_fetcher)
│   ├── filters/ (prefilter, dedup)
│   ├── sponsorship/ (lca_loader, employer_match)
│   ├── score/ (embed, rubric, batch, rank)
│   └── export/ (digest, tracker_md, emailer NEW)
├── scripts/
│   ├── migrate.py                         NEW  applies db/migrations in order
│   ├── check_db.py                        NEW
│   ├── build_companies.py                 NEW  seeds companies.yaml from LCA plus slug probing
│   ├── import_tracker.py                  NEW
│   ├── mark_applied.py
│   └── run_local.ps1
├── tests/ (with fixtures/)
├── data/                                  gitignored: lca/, cache/, private/, digests/, logs/
└── .github/workflows/daily-job-scan.yml
```

---

## 5. Step-by-step build

### Step 1. Foundation, database and migrations

**Build**
- `requirements.txt`, `requirements-local.txt`, new `.env.example`.
- `pipeline/settings.py` loads `.env` with python-dotenv, loads `config/search.yaml`, and exposes a frozen settings object. Missing required variables raise a clear error naming the variable. `is_ci()` returns True when `GITHUB_ACTIONS=true`. `resume_text()` reads `RESUME_TEXT` if set, else the file at `RESUME_TEXT_PATH`.
- `pipeline/db.py` provides a `get_conn()` context manager using `psycopg.connect(DATABASE_URL)` with `pgvector.psycopg.register_vector`, plus small helpers for executing SQL and bulk upserts.
- `scripts/migrate.py` creates `schema_migrations(version text primary key, applied_at timestamptz)`, then applies each `db/migrations/*.sql` file not yet recorded, in filename order, each in its own transaction.
- `scripts/check_db.py` prints the server version, whether `vector` is installed, and the row count of every Appollo table.
- `db/migrations/001_init.sql` exactly as below.
- A minimal `README.md` covering what Appollo is, setup, and run commands (expand in later steps).
- A logging helper. In CI, log only counts and stage names, never titles, companies, URLs or resume text. Locally, log normally to console and `data/logs/`.

**`db/migrations/001_init.sql`**

```sql
-- 001_init.sql: core schema for Appollo
create extension if not exists vector;

-- Every job seen, including excluded ones (kept so they are never re-evaluated)
create table if not exists public.jobs (
  id                  text primary key,          -- sha1(company_norm|title_norm|location_norm)
  source              text not null,             -- greenhouse|lever|ashby|workday|jobspy_indeed|jobspy_linkedin|jobspy_google
  ats_job_id          text,
  company             text not null,
  company_norm        text not null,
  title               text not null,
  location            text,
  is_remote           boolean not null default false,
  is_us               boolean not null default true,
  is_nyc_metro        boolean not null default false,
  url                 text not null,             -- apply or posting URL
  posted_at           timestamptz,
  description         text,                      -- nulled for excluded rows to save space
  embedding           vector(384),
  similarity          real,
  yoe_min             int,
  yoe_text            text,
  seniority           text,
  sponsorship_jd      text check (sponsorship_jd in ('Available','N/A','Not Mentioned')),
  sponsorship_evidence text,
  lca_filings         int,
  lca_relevant_soc    int,
  lca_match_name      text,
  lca_match_score     real,
  fit_score           int,
  rank_score          real,
  summary             text,
  red_flags           jsonb not null default '[]'::jsonb,
  status              text not null default 'new'
                      check (status in ('new','excluded','not_shortlisted','shortlisted','scored','digested','applied','skipped')),
  exclude_reason      text,
  digested_at         timestamptz,
  applied_at          date,
  first_seen_at       timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create unique index if not exists jobs_source_ats_id_uidx on public.jobs (source, ats_job_id) where ats_job_id is not null;
create index if not exists jobs_status_idx on public.jobs (status);
create index if not exists jobs_posted_at_idx on public.jobs (posted_at desc);
create index if not exists jobs_company_norm_idx on public.jobs (company_norm);

-- Aggregated DOL LCA history per employer
create table if not exists public.lca_employers (
  employer_norm        text primary key,
  employer_raw         text not null,            -- most frequent raw spelling
  filings_total        int not null,             -- certified H-1B cases, all SOC codes
  filings_relevant_soc int not null,             -- SOC codes in search.yaml lca.relevant_soc
  positions_total      int,
  ny_nj_filings        int,
  states               text[],
  median_wage_relevant numeric,                  -- annualized, relevant SOC only
  last_decision_date   date,
  source_files         text[],
  loaded_at            timestamptz not null default now()
);

-- Prior applications from Sanket's existing tracker (no URLs, so matched on names)
create table if not exists public.applied_history (
  id           bigserial primary key,
  company_norm text not null,
  title_norm   text not null,
  applied_at   date,
  source       text not null default 'tracker',
  unique (company_norm, title_norm)
);

-- One row per pipeline run, for monitoring
create table if not exists public.runs (
  id          bigserial primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  sources     text[],
  window_arg  text,
  counts      jsonb not null default '{}'::jsonb,
  status      text not null default 'running' check (status in ('running','ok','failed')),
  error       text
);

-- Message Batches in flight, so a timed-out batch can be collected later
create table if not exists public.score_batches (
  batch_id   text primary key,
  created_at timestamptz not null default now(),
  status     text not null default 'in_progress',
  job_ids    text[] not null
);

-- Keep updated_at current
create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists jobs_touch on public.jobs;
create trigger jobs_touch before update on public.jobs for each row execute function public.touch_updated_at();

-- Lock the REST API out entirely: RLS on, no policies. The pipeline connects as postgres, which bypasses RLS.
alter table public.jobs            enable row level security;
alter table public.lca_employers   enable row level security;
alter table public.applied_history enable row level security;
alter table public.runs            enable row level security;
alter table public.score_batches   enable row level security;

-- Today's list for the review console (security_invoker so the REST API cannot read it either)
create or replace view public.v_daily_digest with (security_invoker = true) as
select id, rank_score, fit_score, company, title, location, is_nyc_metro, is_remote,
       posted_at, yoe_min, sponsorship_jd, sponsorship_evidence,
       lca_filings, lca_relevant_soc, summary, url, status
from public.jobs
where status in ('scored','digested') and rank_score is not null
order by is_nyc_metro desc, rank_score desc;

-- Tracker view with the exact original columns plus the two LCA columns
create or replace view public.v_tracker with (security_invoker = true) as
select company            as "Company Name",
       title              as "Job Title",
       coalesce(yoe_min::text, yoe_text, '') as "Years of Exp required",
       coalesce(sponsorship_jd, 'Not Mentioned') as "Sponsorship Status",
       applied_at         as "Date of Application",
       summary            as "One-line summary of the role",
       lca_filings        as "LCA filings (FY25 to FY26)",
       lca_relevant_soc   as "Relevant SOC filings"
from public.jobs
where status = 'applied'
order by applied_at desc;
```

**Test**
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-local.txt
.\.venv\Scripts\python.exe scripts\migrate.py
.\.venv\Scripts\python.exe scripts\check_db.py
.\.venv\Scripts\python.exe scripts\migrate.py   # second run applies nothing
```
Pass when `check_db.py` shows `vector` installed and all five tables with 0 rows, and the second migrate run reports nothing to apply.

---

### Step 2. LCA loader

**Build** `pipeline/sponsorship/lca_loader.py`, runnable as `python -m pipeline.sponsorship.lca_loader`.

- Input is every file in `data/lca/` matching `LCA_*Dis*_Data_FY*.xlsx` (globbed, because of DOL's typo). Sanket downloads these manually from https://www.dol.gov/agencies/eta/foreign-labor/performance, i.e. FY2025 Q1 through Q4 and FY2026 Q3, plus the FY2026 Q3 record layout PDF.
- Verify column names against the FY2026 Q3 record layout before coding. Expected columns are `CASE_NUMBER`, `CASE_STATUS`, `VISA_CLASS`, `EMPLOYER_NAME`, `SOC_CODE`, `WORKSITE_STATE`, `TOTAL_WORKER_POSITIONS`, `WAGE_RATE_OF_PAY_FROM`, `WAGE_UNIT_OF_PAY`, `DECISION_DATE`. Fail loudly with the list of missing columns if any differ.
- Read with `pandas.read_excel(engine="calamine", usecols=...)`. Cache each file as parquet in `data/cache/lca/` keyed by file name and size, so re-runs are fast.
- Concatenate, then drop duplicate `CASE_NUMBER` rows (keeps the latest decision). This makes cumulative FY2026 and single-quarter FY2025 files safe to combine.
- Keep `CASE_STATUS == "Certified"` and `VISA_CLASS == "H-1B"` (case-insensitive, trimmed).
- `SOC_CODE` may look like `15-2051.00`; compare on the first 7 characters against `search.yaml > lca.relevant_soc`.
- Annualize wages (Hour x 2080, Week x 52, Bi-Weekly x 26, Month x 12, Year x 1).
- Group by `normalize_company(EMPLOYER_NAME)` from `pipeline/text_utils.py` and compute every `lca_employers` column. `employer_raw` is the most frequent raw spelling in the group.
- Replace the table contents in one transaction (truncate then bulk insert with `COPY`).
- Print totals locally, i.e. files read, rows kept, employers written, and the top 20 employers by `filings_relevant_soc` in NY or NJ.

**`normalize_company` rules** (in `text_utils.py`, shared by everything). Lowercase, replace `&` with `and`, strip punctuation, remove a leading `the`, remove trailing legal suffixes repeatedly (`inc`, `incorporated`, `llc`, `l l c`, `ltd`, `limited`, `corp`, `corporation`, `co`, `company`, `lp`, `llp`, `plc`, `pc`, `na`, `usa`, `us`, `holdings`, `group`), collapse whitespace.

**Test**
```powershell
.\.venv\Scripts\python.exe -m pipeline.sponsorship.lca_loader
.\.venv\Scripts\python.exe -m pytest tests\test_text_utils.py -q
```
Pass when the loader finishes, the top 20 list contains recognizable large NY and NJ tech and finance employers, and `normalize_company("Google LLC") == normalize_company("GOOGLE, L.L.C.") == "google"`.

---

### Step 3. Employer matching and companies.yaml

**Revised 2026-09-29, after live testing.** The original plan probed ATS slug guesses for the top LCA
filers by volume. Live testing showed this doesn't work: LCA filing volume does not predict ATS
choice. The heaviest H-1B filers (Amazon, Google, Microsoft, JPMorgan, Citibank) run Workday or
proprietary systems, not Greenhouse/Lever/Ashby, so a 2,103-candidate probe ordered by filing volume
returned a ~0% real hit rate at the top (its one "hit," LinkedIn, was a Greenhouse sandbox board with
job titles like `123123`) and only surfaced real boards (~8-10% hit rate) once it reached mid-size
companies buried deep in the ranking, at a projected cost of several hours of live network probing for
a small yield. See `docs/DECISIONS.md` for the full writeup. `pipeline/sponsorship/employer_match.py`
itself (LCA sponsorship-history lookup) is unaffected by this; only the discovery mechanism for
`companies.yaml` changed. Discovery is now three sources instead of one prober:

**Build**
- `pipeline/sponsorship/employer_match.py` with `match_employer(company: str) -> LcaMatch | None`. Order is alias override from `config/employer_aliases.yaml`, then exact `employer_norm` match, then `rapidfuzz.process.extractOne(scorer=token_sort_ratio, score_cutoff=search.yaml lca.fuzzy_threshold)` over all employer names loaded once into memory. Cache results per `company_norm` for the run. An alias may map to a list of LCA employer names (large companies often file under several legal entities); when it does, sum `filings_total`, `filings_relevant_soc` and `ny_nj_filings` across every entity found. Returns matched name, score, source (`alias`/`exact`/`fuzzy`), the summed counts, and which underlying entities they came from.
- `pipeline/ats_discovery.py`, shared by sources B/C/G below: `parse_ats_url(url) -> dict | None` recognizes Greenhouse, Lever, Ashby and Workday URLs and extracts `{ats, slug}` or, for Workday, `{ats: workday, host, tenant, board}`; `looks_like_test_board(job_titles) -> bool` flags sandbox/test boards (digits-only titles, "test", "sandbox", "bug bash"); a `BLOCKLISTED_BOARDS` set for known-bad boards found by hand (e.g. LinkedIn's Greenhouse sandbox slug); `validate_board(ats, ref) -> bool` does one live fetch and requires at least 3 open jobs and a pass through `looks_like_test_board`.
- **Source B, curated big NYC employers (manual, one-time).** Take the top 40 employers from the `ny_nj_filings` ranking that are not staffing firms (`search.yaml` blocklist) or large offshore IT consultancies/staff-aug firms (Cognizant, TCS, Infosys, Wipro, HCL, LTIMindtree, Genpact, etc.; large product/consulting companies like Deloitte, EY, Accenture, Capgemini stay per `docs/DECISIONS.md` #1). For each, find the official careers site by hand (web search) and identify the ATS: Greenhouse/Lever/Ashby get a slug, Workday gets host/tenant/board verified with one live CXS request, anything else goes in `data/private/unresolved_companies.txt` with the ATS name if known. Add as `source: manual`. Show Sanket the list before writing it.
- **Source C, `scripts/seed_from_hn.py`, HN "Who is hiring."** Uses the public HN Algolia API (verify the exact endpoint live first) to find the `--months N` (default 1) most recent "Ask HN: Who is hiring?" threads by author `whoishiring`, fetches each thread's full comment tree in one call, extracts board URLs from top-level comments via `parse_ats_url`, validates each with `validate_board` (rejecting the blocklist and test-looking boards), skips staffing-blocklist names and anything already in `companies.yaml` under any source, and appends new entries as `source: hn`. Rate limited to 1 request/second. Reports counts added / no-ATS-link / already-present. Supports `--dry-run`.
- **Source G (Step 6), auto-discovery from JobSpy.** When a JobSpy result's `job_url_direct` matches `parse_ats_url`, validate it the same way and add as `source: discovered` unless staffing-blocklisted. Log how many were discovered per run. Built alongside the JobSpy fetcher in Step 6, not here.
- `companies.yaml` structure: a flat list, every entry tagged `source: manual | hn | discovered`, with a comment header and a manual section at the top Sanket can add to by hand at any time. No script may remove or modify a `manual` entry; discovery (`hn`, `discovered`) may only add, never overwrite an `hn` entry.

```yaml
# Appollo company board list. Every entry needs a source: manual | hn | discovered.
# ats: greenhouse | lever | ashby | workday
# Workday entries need host, tenant and board from the careers URL, e.g.
# https://intel.wd1.myworkdayjobs.com/External -> host intel.wd1.myworkdayjobs.com, tenant intel, board External

# --- Manual: add companies here by hand any time; no script ever removes or edits these. ---
- {name: Ramp, ats: greenhouse, slug: ramp, source: manual}
- {name: Intel, ats: workday, host: intel.wd1.myworkdayjobs.com, tenant: intel, board: External, source: manual}

# --- HN "Who is hiring" (scripts/seed_from_hn.py). Discovery may add here, never overwrite. ---

# --- Auto-discovered from JobSpy results (Step 6). ---
```

**Test**
```powershell
.\.venv\Scripts\python.exe scripts\seed_from_hn.py --dry-run
.\.venv\Scripts\python.exe -m pytest tests\test_employer_match.py tests\test_ats_discovery.py -q
```
Pass when the dry run reports realistic added/no-ATS-link/already-present counts with no test-board false positives, and the match/discovery tests cover exact, alias (including multi-entity summing), fuzzy hit, fuzzy miss, URL parsing for all four ATS, and test-board rejection. Sanket reviews the Step 3B curated list and the dry-run output before anything is committed.

---

### Step 4. ATS fetchers

**Build**
- `pipeline/models.py` (Pydantic v2) with `CompanyConfig`, `RawJob` (source, ats_job_id, company, title, location, is_remote, url, posted_at, description_html or description_text) and `Job` (the normalized row matching the `jobs` table).
- `pipeline/fetchers/base.py` provides a shared `requests.Session` with User-Agent `appollo/0.1 (+https://github.com/Sanket0412/appollo)`, a 20-second timeout, tenacity retries with exponential backoff on connection errors, 429 and 5xx (honor `Retry-After`), a per-host minimum interval of 1 second, and a JSON file cache in `data/cache/http/` with a 6-hour TTL (a no-op in CI is fine).
- Each fetcher exposes `fetch(company: CompanyConfig, since: datetime) -> list[RawJob]` and applies the title regexes from `search.yaml` before any per-job detail request, so descriptions are fetched only for relevant titles.
- **Greenhouse.** `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`. Use `first_published` for `posted_at`; if it is not in the list payload, fetch `GET .../jobs/{id}` only for title-matched jobs. The `content` field is HTML-escaped HTML; unescape, then convert to text. Never use `updated_at` for freshness.
- **Lever.** `GET https://api.lever.co/v0/postings/{slug}?mode=json`. Expected fields are `id`, `text` (title), `categories.location`, `workplaceType`, `createdAt` (epoch milliseconds), `hostedUrl`, `applyUrl`, `descriptionPlain`, `lists`, `additionalPlain`. Verify live first.
- **Ashby.** `GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true`. Expected fields under `jobs` are `id`, `title`, `location`, `secondaryLocations`, `isRemote`, `workplaceType`, `publishedAt`, `jobUrl`, `applyUrl`, `descriptionPlain`, `isListed`. Skip unlisted jobs. Verify live first.
- **Workday.** `POST https://{host}/wday/cxs/{tenant}/{board}/jobs` with `{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "<term>"}` for each term in `search.yaml > workday_search_terms`, paginating until `offset >= total`. Parse `postedOn` text (`Posted Today` = 0 days, `Posted Yesterday` = 1, `Posted N Days Ago` = N, `Posted 30+ Days Ago` = 30) into an approximate `posted_at`. Fetch detail from `GET https://{host}/wday/cxs/{tenant}/{board}{externalPath}` for the description. Verify live first.
- `pipeline/text_utils.py` gains `html_to_text()` (BeautifulSoup, preserve line breaks) and `parse_location(raw) -> (is_us, is_remote, is_nyc_metro)` driven by `search.yaml > locations`.
- Save one real response per ATS into `tests/fixtures/` (strip anything unneeded) and write parser tests against them.

**Test**
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fetchers.py -q
.\.venv\Scripts\python.exe -m pipeline.run --sources ats --window 7d --limit-companies 5 --dry-run
```
Pass when fixture tests pass and the dry run prints, per ATS, companies fetched, jobs returned, title matches and newest `posted_at`, without writing to the database.

---

### Step 5. Prefilter, dedup and the run orchestrator

**Build**
- `pipeline/filters/prefilter.py` with `evaluate(job) -> (keep: bool, reason: str | None)`. Checks run in this order, and the first failure wins.
  1. Title include regexes (at least one must match).
  2. Title exclude regexes (none may match).
  3. Location must be US or remote-US (`is_us`).
  4. Posting age within window plus grace (`posted_at` missing counts as fresh for JobSpy only, stale for ATS).
  5. Staffing company blocklist (on `company_norm`) and staffing description patterns.
  6. Hard-exclude description regexes (citizenship, clearance, explicit no sponsorship).
  7. Company or title already in `applied_history` (exact `company_norm` plus fuzzy `title_norm` at 90 or above).
- `pipeline/filters/dedup.py`. `canonical_id = sha1(f"{company_norm}|{title_norm}|{location_norm}")`, where `title_norm` lowercases, strips punctuation, and removes tokens such as `remote`, `hybrid`, `-` suffixes and requisition numbers. Source priority is ATS over JobSpy; when an ATS copy arrives for an existing JobSpy row, overwrite `source`, `url`, `description` and `ats_job_id`. Otherwise `on conflict (id) do nothing` for new inserts.
- `pipeline/run.py` CLI.

```
python -m pipeline.run --sources ats[,jobspy] --window 24h|7d
                       [--score] [--digest] [--email]
                       [--limit-companies N] [--dry-run]
```

Stages are fetch, normalize, prefilter, dedup and upsert (excluded rows are stored with `status='excluded'`, `exclude_reason`, and `description = null`), then LCA join for kept rows (writes `lca_filings`, `lca_relevant_soc`, `lca_match_name`, `lca_match_score`), then optional scoring (Steps 7 and 8), then optional digest (Step 9). Each run writes a `runs` row with counts per stage and a final status. One failing company must not fail the run; log it and continue. The window maps to hours via `search.yaml > windows` plus `grace_hours`.

**Test**
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prefilter.py tests\test_dedup.py -q
.\.venv\Scripts\python.exe -m pipeline.run --sources ats --window 7d
.\.venv\Scripts\python.exe -m pipeline.run --sources ats --window 7d
```
Pass when the second run inserts 0 new rows, `runs` has two `ok` rows, and a spot check in the Supabase Table Editor shows sensible `exclude_reason` values. Tests must include true positives and false positives for each red-flag regex (for example "we are happy to sponsor" must not be excluded).

---

### Step 6. JobSpy fetcher and the local schedule

**Build**
- `pipeline/fetchers/jobspy_fetcher.py`. Raise immediately if `settings.is_ci()`. Call `jobspy.scrape_jobs` with `site_name` from `search.yaml > jobspy.sites`, one call per search term, `location="Jersey City, NJ"` with `distance=50` plus one US-wide remote call (`is_remote=True`), `hours_old` from the window, `results_wanted` from config (default 40 per call), `country_indeed="USA"`, and `linkedin_fetch_description=True`. Sleep 10 to 20 seconds between calls. Map rows to `RawJob` with source `jobspy_<site>`. Prefer `job_url_direct` over `job_url` when present. Log a warning when LinkedIn returns zero rows (it fails quietly when throttled).
- `scripts/run_local.ps1`

```powershell
# scripts/run_local.ps1: local JobSpy run, called by Windows Task Scheduler at 9:30 AM
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd"
& "$repo\.venv\Scripts\python.exe" -m pipeline.run --sources jobspy --window 24h *>> "data\logs\local_$stamp.log"
```

- README section for registering the scheduled task (run once in PowerShell).

```powershell
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "G:\Projects\Appollo\appollo\scripts\run_local.ps1"'
$trigger  = New-ScheduledTaskTrigger -Daily -At 9:30am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "Appollo JobSpy" -Action $action -Trigger $trigger -Settings $settings
```

The local run fetches and stores only. The 10 AM cloud run scores everything new from both sources.

**Test**
```powershell
.\.venv\Scripts\python.exe -m pipeline.run --sources jobspy --window 24h
Start-ScheduledTask -TaskName "Appollo JobSpy"
Get-Content data\logs\local_*.log -Tail 30
```
Pass when rows with `source` like `jobspy_%` appear, ATS duplicates were merged, and the scheduled task log shows a completed run.

---

### Step 7. Embeddings and shortlist

**Build** `pipeline/score/embed.py`.
- Load `fastembed.TextEmbedding("BAAI/bge-small-en-v1.5")` once. Cache the model under `data/cache/fastembed` locally and `~/.cache/fastembed` in CI (the workflow caches it).
- Embed the resume once per run (the model's 512-token limit truncates it, which is fine). Embed each `status='new'` job as `title + company + first 2,000 characters of description`.
- Store `embedding` and cosine `similarity`. Mark `shortlisted` if similarity is at least `scoring.min_similarity`, keeping at most `scoring.max_per_run` rows ordered by NYC metro first, then similarity. Everything else becomes `not_shortlisted`.

**Test**
```powershell
.\.venv\Scripts\python.exe -m pipeline.run --sources ats --window 7d --score --no-llm
```
`--no-llm` stops after the embedding stage. Pass when the top 10 shortlisted titles by similarity look relevant to Sanket's resume, and irrelevant titles that slipped through the regexes fall below the threshold. Adjust `min_similarity` if needed and report the value chosen.

---

### Step 8. Haiku rubric through the Batches API

**Build**
- `pipeline/score/rubric.py` holds the system prompt, the JSON schema and a Pydantic `ScoreResult`. The resume goes in the system prompt (it is too short for prompt caching to apply to Haiku, so do not bother). The description is truncated to 12,000 characters.

System prompt:

```text
You are a strict technical recruiter screening jobs for one candidate.
Score the job against the candidate's resume and return only JSON that matches the schema.

Rules
- years_required_min is the smallest number of years the posting states as required ("3-5 years" -> 3, "5+ years" -> 5). If no number is stated, null.
- sponsorship_jd is "N/A" when the posting explicitly says it will not sponsor, requires US citizenship or permanent residency, or requires a security clearance.
  It is "Available" when the posting explicitly offers visa sponsorship or immigration support.
  Otherwise it is "Not Mentioned".
- sponsorship_evidence is a verbatim quote from the posting that supports sponsorship_jd, or "" when Not Mentioned. Never paraphrase and never infer.
- one_line_summary describes the role itself in at most 25 words: team, what the person builds, core stack.
- seniority is the level the posting targets.
- Score honestly. A perfect skills match with a 10-year requirement is still a poor experience fit.

<resume>
{resume_text}
</resume>
```

Schema:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["years_required_min","years_required_text","seniority","sponsorship_jd","sponsorship_evidence",
               "skills_match","experience_fit","domain_fit","seniority_fit","location_fit",
               "total","one_line_summary","red_flags"],
  "properties": {
    "years_required_min":  {"type": ["integer","null"]},
    "years_required_text": {"type": "string"},
    "seniority":           {"type": "string", "enum": ["intern","entry","mid","senior","staff_plus","unclear"]},
    "sponsorship_jd":      {"type": "string", "enum": ["Available","N/A","Not Mentioned"]},
    "sponsorship_evidence":{"type": "string"},
    "skills_match":        {"type": "integer", "minimum": 0, "maximum": 40},
    "experience_fit":      {"type": "integer", "minimum": 0, "maximum": 20},
    "domain_fit":          {"type": "integer", "minimum": 0, "maximum": 15},
    "seniority_fit":       {"type": "integer", "minimum": 0, "maximum": 15},
    "location_fit":        {"type": "integer", "minimum": 0, "maximum": 10},
    "total":               {"type": "integer", "minimum": 0, "maximum": 100},
    "one_line_summary":    {"type": "string"},
    "red_flags":           {"type": "array", "items": {"type": "string"}}
  }
}
```

The user message contains company, title, location and the description. In Python, recompute `total` as the sum of the five parts and ignore the model's `total` if they differ. Validate every result with `ScoreResult`; one retry on invalid JSON, then leave the row `shortlisted` for the next run.

- `pipeline/score/batch.py`
  1. First collect any `score_batches` still `in_progress` from earlier runs.
  2. Build one request per shortlisted job with `custom_id = job.id` (sha1 hex, 40 characters, within the 64-character limit), model from `search.yaml > scoring.model`, `max_tokens` 800, temperature 0.
  3. Submit with `client.messages.batches.create`, record it in `score_batches`, and poll `retrieve` every 30 seconds for up to `scoring.batch_wait_minutes`.
  4. When it ends, stream `results`, write scores, and set `status='scored'` (or `excluded` with reason `jd_no_sponsorship` when `sponsorship_jd == 'N/A'`, or `yoe_too_high` when `years_required_min > scoring.max_yoe_required`).
  5. If the wait expires and `scoring.fallback_sync` is true, cancel the batch and score the remaining jobs with regular `messages.create` calls, sequentially.
- Verify first whether the current `anthropic` SDK supports native structured outputs for Haiku 4.5 and use it if so; otherwise force a single tool call whose `input_schema` is the schema above.
- Print estimated cost per run from the `usage` fields (batch prices $0.50 input and $2.50 output per million tokens, sync $1 and $5).

**Test**
```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_rubric.py -q
.\.venv\Scripts\python.exe -m pipeline.run --sources ats --window 7d --score --max-score 5
```
Pass when 5 jobs get valid scores, the sponsorship evidence is a verbatim substring of the description (assert this in code and log violations), and the printed cost is a fraction of a cent. Sanket should spot-check two results by reading the postings.

---

### Step 9. Ranking and digest

**Revised 2026-10-01 (see `docs/DECISIONS.md`).** The ranking formula below is superseded. The digest is ordered by posting recency, newest first, within NYC metro / Remote US / Elsewhere US, with core fit as the same-day tiebreak; only jobs with core fit >= `digest.min_core_fit` (50) are included. `fit_score` stores core fit (max 85); recency is computed live.

**Build**
- `pipeline/score/rank.py` computes `rank_score` for `scored` rows.

```
rank = fit_score                                     (0 to 100)
     + 15  if is_nyc_metro
     + 5   if is_remote and not is_nyc_metro
     + 10  if sponsorship_jd == 'Available'
     + 8   if lca_relevant_soc >= 10
     + 4   if 1 <= lca_filings and lca_relevant_soc < 10
     + 5   if posted within the last 24 hours
```

LCA history can only raise rank, never lower it (no penalty for a job with no LCA signal at all). All weights live in `search.yaml > ranking` so Sanket can tune them without code changes.

**"No LCA match" is not the same fact as "matched, zero relevant filings."** `employer_match.py` either finds the employer (alias, exact or fuzzy) or it doesn't. Keep `lca_filings`/`lca_relevant_soc` as `NULL` on the job row when there was no match at all, and only write `0` when the employer was matched but has zero relevant-SOC filings. The digest markdown and `v_daily_digest` must render `NULL` as "No filing history" rather than `0`, since a real 0 is a (mildly) informative fact about a matched employer and a `NULL` just means we have no data.

- `pipeline/export/digest.py` selects `scored` rows not yet digested, takes the top `digest.max_jobs` by rank, groups them into NYC metro, Remote US and Elsewhere US (rank order within each), and writes `data/digests/YYYY-MM-DD.md` locally. Each entry shows company, title, location, posted age, YOE required, sponsorship status with evidence, LCA filings and relevant SOC filings (or "No filing history"), the one-line summary, and the apply link. Then set `status='digested'` and `digested_at`.
- `pipeline/export/emailer.py` sends the same digest as plain text plus a simple HTML table through `smtp.gmail.com:465` (SSL) when all three `GMAIL_*` variables are set; otherwise skip quietly. Subject like `Appollo, 14 new roles, Tue Sep 29`. Never write the digest to CI logs or artifacts (public repo).

**Test**
```powershell
.\.venv\Scripts\python.exe -m pipeline.run --sources ats --window 24h --score --digest --email
```
Pass when the digest file opens with NYC-metro roles, no `N/A` sponsorship roles appear, the email arrives (if configured), and those rows are now `digested`.

---

### Step 10. Tracker import, tracker export and mark_applied

**Build**
- `scripts/import_tracker.py <path>` accepts the tracker as `.md` (pipe table), `.csv` or `.xlsx` from `data/private/`, requires the six original column names, and upserts `applied_history` using `normalize_company` and `title_norm`. It reports rows imported and rows skipped with reasons.
- `scripts/mark_applied.py <job_id_or_prefix_or_url> [--skip] [--date YYYY-MM-DD]` sets `status='applied'` and `applied_at` (today in America/New_York by default) or `status='skipped'`, and inserts into `applied_history` when applied. It refuses ambiguous prefixes.
- `pipeline/export/tracker_md.py` writes `data/private/tracker.md` from `v_tracker` plus imported history rows, with exactly the original six columns followed by the two LCA columns.

**Test**
```powershell
.\.venv\Scripts\python.exe scripts\import_tracker.py data\private\tracker.md
.\.venv\Scripts\python.exe scripts\mark_applied.py <some_digested_id>
.\.venv\Scripts\python.exe -m pipeline.export.tracker_md
```
Pass when the tracker file has the correct column headers in order and includes the newly applied job, and a re-run of the pipeline does not surface any imported or applied job again.

---

### Step 11. GitHub Actions

**Build** `.github/workflows/daily-job-scan.yml`

```yaml
name: daily-job-scan

on:
  schedule:
    - cron: "0 10 * * *"
      timezone: "America/New_York"     # supported since March 2026
  workflow_dispatch:
    inputs:
      window:
        description: "Posting age window"
        type: choice
        options: ["24h", "7d"]
        default: "24h"

permissions:
  contents: read

concurrency:
  group: daily-job-scan
  cancel-in-progress: false

jobs:
  scan:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - uses: actions/cache@v4
        with:
          path: ~/.cache/fastembed
          key: fastembed-bge-small-en-v1.5
      - run: pip install -r requirements.txt
      - name: Run pipeline
        run: python -m pipeline.run --sources ats --window ${{ inputs.window || '24h' }} --score --digest --email
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          RESUME_TEXT: ${{ secrets.RESUME_TEXT }}
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          DIGEST_TO: ${{ secrets.DIGEST_TO }}
          FASTEMBED_CACHE_PATH: ~/.cache/fastembed
```

Verify current major versions of the three actions before committing. GitHub delays scheduled runs under load; the 2-hour grace buffer covers that. Also add a `tests` workflow that runs `pytest` on push (no secrets needed, fixture-based tests only).

**Test.** Add the secrets in the repo under Settings, Secrets and variables, Actions. Trigger `daily-job-scan` manually with `window=24h` from the Actions tab. Pass when the run is green, its log shows counts only, a new `runs` row is `ok`, and the digest email arrives.

---

### Step 12. Review console and assisted apply

**Build**
- Connect the Supabase MCP to Claude Code in read-only mode, scoped to this project. Verify the current server URL and flags in Supabase's docs, then give Sanket the exact `claude mcp add` command.
- Fill in the Review console section of `CLAUDE.md` if anything changed, and add example prompts to the README (for example "show today's digest", "why did X score low", "show everything from Datadog this week").
- Assisted apply needs no code. Document the flow in the README, i.e. open the apply URL, optionally let Claude in Chrome (with "ask before acting" on) fill fields on the ATS page, stop before Submit and at any CAPTCHA, Sanket reviews and submits, then runs `mark_applied.py`.

**Test.** In Claude Code, ask "show today's digest". Pass when it returns the grouped list from `v_daily_digest` without writing to the database.

---

## 6. `config/search.yaml` (write this at Step 1, tune later)

```yaml
windows:            # --window value -> hours
  24h: 24
  7d: 168
grace_hours: 2      # added to every fetch window; dedup removes overlap

titles:
  include:          # case-insensitive regexes; at least one must match
    - '\bdata scien(ce|tist)'
    - '\bmachine learning\b'
    - '\bml\s*(engineer|scientist|ops|platform|infrastructure)\b'
    - '\bmlops\b'
    - '\b(ai|a\.i\.)\s*(/\s*ml\s*)?(engineer|scientist|developer)\b'
    - '\bapplied (ai|ml|scientist|science)\b'
    - '\b(gen(erative)?\s*ai|llm|nlp)\b'
    - '\bdeep learning\b'
    - '\bresearch (engineer|scientist)\b.*\b(ml|ai|machine learning)\b'
    - '\bdecision scien'
  exclude:          # none may match
    - '\bintern(ship)?\b'
    - '\bco-?op\b'
    - '\bstaff\b'
    - '\bprincipal\b'
    - '\bdistinguished\b'
    - '\bdirector\b'
    - '\bhead of\b'
    - '\bvp\b|\bvice president\b'
    - '\bmanager\b'
    - '\bpostdoc'
    - '\bprofessor\b'
    - '\bsales\b'

locations:
  us_states: [AL, AK, AZ, AR, CA, CO, CT, DE, DC, FL, GA, HI, ID, IL, IN, IA, KS, KY, LA, ME, MD, MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ, NM, NY, NC, ND, OH, OK, OR, PA, RI, SC, SD, TN, TX, UT, VT, VA, WA, WV, WI, WY]
  us_keywords: ['united states', 'usa', 'u.s.', 'us-remote', 'remote - us', 'remote, us', 'remote (us)', 'anywhere in the us']
  non_us_keywords: ['canada', 'toronto', 'vancouver', 'united kingdom', 'london', 'ireland', 'dublin', 'india', 'bangalore', 'bengaluru', 'hyderabad', 'germany', 'berlin', 'france', 'paris', 'netherlands', 'amsterdam', 'poland', 'spain', 'singapore', 'australia', 'mexico', 'brazil', 'israel', 'emea', 'apac', 'latam']
  remote_keywords: ['remote', 'anywhere', 'distributed']
  nyc_metro:        # substring match, case-insensitive
    - 'new york'
    - 'nyc'
    - 'manhattan'
    - 'brooklyn'
    - 'queens'
    - 'bronx'
    - 'staten island'
    - 'long island city'
    - 'jersey city'
    - 'hoboken'
    - 'newark'
    - 'weehawken'
    - 'secaucus'
    - 'harrison, nj'
    - 'fort lee'
    - 'edison'
    - 'princeton'
    - 'iselin'
    - 'white plains'
    - 'stamford'
    - 'greenwich'
  unclear_remote_policy: keep   # remote with no country: keep and let Haiku judge location_fit

red_flags:          # hard exclude when found in the description, case-insensitive
  - 'must be (a )?u\.?s\.? citizen'
  - 'u\.?s\.? citizen(ship)? (is )?required'
  - 'citizenship is required'
  - '(active|current|ability to obtain)\s+(a\s+)?(secret|top secret|ts/sci|public trust)'
  - 'security clearance (is )?required'
  - '(will|can|do) not (provide |offer )?sponsor'
  - 'unable to (provide |offer )?sponsor'
  - 'not (able|eligible) to sponsor'
  - 'no (visa |h-?1b )?sponsorship'
  - 'sponsorship (is )?not (available|provided|offered)'
  - 'without (the need for )?(current or future )?(visa )?sponsorship'
  - '(green card|gc) holders? only'
  - '\busc(/gc)? only\b'

staffing:
  company_blocklist:   # compared against normalize_company(); extend as needed
    - robert half
    - teksystems
    - insight global
    - randstad
    - adecco
    - kforce
    - apex systems
    - aerotek
    - kelly services
    - manpowergroup
    - motion recruitment
    - jobot
    - cybercoders
    - harnham
    - hays
    - beacon hill staffing
    - vaco
    - akkodis
    - modis
    - collabera
    - mindlance
    - diverse lynx
    - dice
  description_patterns:
    - 'on behalf of (our|a) client'
    - 'our client (is|has)'
    - '\bw-?2 (only|contract)\b'
    - '\bc2c\b|corp[- ]to[- ]corp'
    - '\bstaffing (agency|firm|partner)\b'

lca:
  relevant_soc: ['15-2051', '15-1221', '15-1252']   # Data Scientists, Computer and Information Research Scientists, Software Developers
  fuzzy_threshold: 90

workday_search_terms: ['data scientist', 'machine learning', 'AI engineer', 'applied scientist']

jobspy:
  sites: [indeed, linkedin, google, glassdoor, zip_recruiter]
  search_terms: ['data scientist', 'machine learning engineer', 'AI engineer', 'applied scientist']
  results_wanted: 40
  distance_miles: 50

scoring:
  model: claude-haiku-4-5-20251001
  min_similarity: 0.55          # tune at Step 7
  max_per_run: 60
  max_yoe_required: 6
  batch_wait_minutes: 25
  fallback_sync: true

ranking:
  # LCA history can only raise rank, never lower it. No-match is neutral, not penalized.
  nyc_metro_bonus: 15
  remote_bonus: 5
  sponsorship_available_bonus: 10
  lca_strong_bonus: 8           # lca_relevant_soc >= lca_strong_threshold
  lca_strong_threshold: 10
  lca_some_bonus: 4
  fresh_24h_bonus: 5

digest:
  max_jobs: 30
```

---

## 7. Tests to have by the end

| File | Covers |
|---|---|
| `tests/test_text_utils.py` | `normalize_company`, `title_norm`, `html_to_text`, `parse_location` (US, non-US, remote, NYC metro) |
| `tests/test_employer_match.py` | alias, exact, fuzzy hit, fuzzy miss |
| `tests/test_fetchers.py` | each ATS parser against its fixture, Workday `postedOn` parsing, Greenhouse freshness uses `first_published` |
| `tests/test_prefilter.py` | every title and red-flag regex with positive and negative cases, staffing exclusion, window math with grace |
| `tests/test_dedup.py` | canonical id stability, ATS overriding JobSpy |
| `tests/test_rubric.py` | schema validation, total recomputation, evidence substring check |
| `tests/test_rank.py` | ranking weights from config |
| `tests/test_jobspy_guard.py` | fetcher raises when `GITHUB_ACTIONS=true` |

All tests run offline, with no network and no database.

---

## 8. Expected monthly cost

| Item | Estimate |
|---|---|
| Haiku scoring, about 40 to 60 jobs per day at about 4.5K input and 400 output tokens, batch pricing | About $2 to $6 |
| Sync fallback, if batches are slow | Up to double the above on those days |
| Supabase free tier, GitHub Actions on a public repo, fastembed, DOL data, Gmail SMTP | $0 |
| **Total** | **About $2 to $8 per month** |

Set a monthly spend limit in the Claude Console as a backstop.

---

## 9. Open decisions for Sanket

1. Whether IT consulting and outsourcing firms that file many LCAs (large offshore-delivery consultancies) count as staffing agencies. Default is to keep large product and consulting companies and exclude names on the staffing blocklist only.
2. Whether the default title exclusions are right, especially `lead` (currently allowed) and `manager` (currently excluded).
3. Whether the email digest is wanted. It is built as optional and turns on only when the Gmail secrets exist.
