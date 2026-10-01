-- 002_cap_exempt.sql: tag jobs at H-1B cap-exempt employers (universities, affiliated nonprofits,
-- nonprofit research orgs). Populated from config/companies.yaml (cap_exempt: true) on every run.
alter table public.jobs add column if not exists cap_exempt boolean not null default false;

-- A view may only gain columns at the end, so cap_exempt goes last.
create or replace view public.v_daily_digest with (security_invoker = true) as
select id, rank_score, fit_score, company, title, location, is_nyc_metro, is_remote,
       posted_at, yoe_min, sponsorship_jd, sponsorship_evidence,
       lca_filings, lca_relevant_soc, summary, url, status, cap_exempt
from public.jobs
where status in ('scored','digested') and rank_score is not null
order by is_nyc_metro desc, rank_score desc;
