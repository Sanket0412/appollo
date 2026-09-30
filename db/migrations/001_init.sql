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
