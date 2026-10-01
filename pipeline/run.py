"""Pipeline CLI.

python -m pipeline.run --sources ats[,jobspy] --window 24h|7d|14d
                       [--score [--no-llm] [--max-score N]] [--digest [--no-mark]] [--email]
                       [--limit-companies N] [--dry-run]

Stages: fetch, normalize, prefilter, dedup, upsert, then an LCA join for kept rows, then (--score)
the embedding shortlist, then the Haiku rubric via the Batches API (--max-score N caps it).
--no-llm stops after the embedding stage. --digest ranks, writes data/digests/ and marks rows digested
(--no-mark to preview), --email sends it.
JobSpy (Step 6) isn't built yet; --sources jobspy logs a warning and is a no-op.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import yaml

from pipeline.db import get_conn
from pipeline.export import digest as digest_stage
from pipeline.export import emailer
from pipeline.fetchers import ashby, greenhouse, lever, workday
from pipeline.filters import prefilter
from pipeline.filters.dedup import ATS_SOURCES, canonical_id, source_priority
from pipeline.log import get_logger
from pipeline.models import CompanyConfig, Job, RawJob
from pipeline.score import batch as score_batch
from pipeline.score import embed
from pipeline.settings import REPO_ROOT, get_settings, is_ci
from pipeline.sponsorship.employer_match import match_employer
from pipeline.text_utils import normalize_company, parse_location

COMPANIES_PATH = REPO_ROOT / "config" / "companies.yaml"

FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workday": workday.fetch,
}

log = get_logger("run")


def load_companies() -> list[CompanyConfig]:
    with COMPANIES_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    return [CompanyConfig(**c) for c in raw]


def compute_since(window: str) -> datetime:
    settings = get_settings()
    cfg = settings.search_config
    # Never look further back than the hard age cap, whatever the window plus grace add up to.
    hours = min(cfg["windows"][window] + cfg["grace_hours"], cfg["max_posting_age_days"] * 24)
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def normalize(raw: RawJob, locations_config: dict, geo_config: dict | None = None) -> Job:
    company_norm = normalize_company(raw.company)
    is_us, is_remote_parsed, is_nyc_metro = parse_location(raw.location, locations_config, raw.description_text, geo_config)
    return Job(
        id=canonical_id(company_norm, raw.title, raw.location),
        source=raw.source,
        ats_job_id=raw.ats_job_id,
        company=raw.company,
        company_norm=company_norm,
        title=raw.title,
        location=raw.location,
        is_remote=raw.is_remote or is_remote_parsed,
        is_us=is_us,
        is_nyc_metro=is_nyc_metro,
        url=raw.url,
        posted_at=raw.posted_at,
        description=raw.description_text,
    )


def apply_lca(job: Job) -> Job:
    match = match_employer(job.company)
    if match is None:
        return job
    return job.model_copy(
        update={
            "lca_filings": match.filings_total,
            "lca_relevant_soc": match.filings_relevant_soc,
            "lca_match_name": match.matched_name,
            "lca_match_score": match.match_score,
        }
    )


def sync_cap_exempt(conn, companies: list[CompanyConfig]) -> int:
    """Makes jobs.cap_exempt match companies.yaml: true for jobs at cap_exempt companies, false otherwise.

    Runs every time (one cheap statement), so it also backfills rows stored before the flag existed and
    follows a company being added to or removed from the cap-exempt list.
    """
    exempt = sorted({normalize_company(c.name) for c in companies if c.cap_exempt})
    with conn.cursor() as cur:
        cur.execute(
            "update public.jobs set cap_exempt = (company_norm = any(%s)) "
            "where cap_exempt is distinct from (company_norm = any(%s))",
            (exempt, exempt),
        )
        changed = cur.rowcount
    conn.commit()
    return changed


def load_applied_history(conn) -> prefilter.AppliedHistory:
    with conn.cursor() as cur:
        cur.execute("select company_norm, title_norm from public.applied_history")
        rows = cur.fetchall()
    return prefilter.AppliedHistory(rows)


UPSERT_SQL = """
insert into public.jobs
    (id, source, ats_job_id, company, company_norm, title, location, is_remote, is_us,
     is_nyc_metro, url, posted_at, description, lca_filings, lca_relevant_soc,
     lca_match_name, lca_match_score, status, exclude_reason)
values
    (%(id)s, %(source)s, %(ats_job_id)s, %(company)s, %(company_norm)s, %(title)s, %(location)s,
     %(is_remote)s, %(is_us)s, %(is_nyc_metro)s, %(url)s, %(posted_at)s, %(description)s,
     %(lca_filings)s, %(lca_relevant_soc)s, %(lca_match_name)s, %(lca_match_score)s,
     %(status)s, %(exclude_reason)s)
on conflict (id) do update set
    source = excluded.source,
    url = excluded.url,
    description = excluded.description,
    ats_job_id = excluded.ats_job_id
where jobs.source not in ('greenhouse', 'lever', 'ashby', 'workday')
  and excluded.source in ('greenhouse', 'lever', 'ashby', 'workday')
returning (xmax = 0) as inserted
"""


def _refresh_lca(cur, job: Job) -> None:
    """Rows stored before an alias or LCA reload have stale NULL LCA fields; fill them when we now match."""
    if job.lca_match_name is None:
        return
    cur.execute(
        "update public.jobs set lca_filings = %s, lca_relevant_soc = %s, lca_match_name = %s, lca_match_score = %s "
        "where source = %s and ats_job_id = %s and lca_match_name is null",
        (job.lca_filings, job.lca_relevant_soc, job.lca_match_name, job.lca_match_score, job.source, job.ats_job_id),
    )


def upsert_job(conn, job: Job) -> str:
    """Returns 'inserted', 'updated' (ATS overwrote a JobSpy row) or 'unchanged'."""
    description = None if job.status == "excluded" else job.description
    with conn.cursor() as cur:
        if job.ats_job_id is not None:
            # The same ATS posting can get a different canonical id if its location text changes
            # (e.g. the Workday detail fallback appended a country); never insert it twice.
            cur.execute(
                "select 1 from public.jobs where source = %s and ats_job_id = %s", (job.source, job.ats_job_id)
            )
            if cur.fetchone() is not None:
                _refresh_lca(cur, job)
                return "unchanged"
        cur.execute(
            UPSERT_SQL,
            {
                "id": job.id,
                "source": job.source,
                "ats_job_id": job.ats_job_id,
                "company": job.company,
                "company_norm": job.company_norm,
                "title": job.title,
                "location": job.location,
                "is_remote": job.is_remote,
                "is_us": job.is_us,
                "is_nyc_metro": job.is_nyc_metro,
                "url": job.url,
                "posted_at": job.posted_at,
                "description": description,
                "lca_filings": job.lca_filings,
                "lca_relevant_soc": job.lca_relevant_soc,
                "lca_match_name": job.lca_match_name,
                "lca_match_score": job.lca_match_score,
                "status": job.status,
                "exclude_reason": job.exclude_reason,
            },
        )
        row = cur.fetchone()
    if row is None:
        return "unchanged"
    return "inserted" if row[0] else "updated"


def dedup_batch(jobs: list[Job]) -> list[Job]:
    """Same-run duplicates (rare; fetchers already dedup internally) resolved by source priority."""
    by_id: dict[str, Job] = {}
    for job in jobs:
        existing = by_id.get(job.id)
        if existing is None or source_priority(job.source) >= source_priority(existing.source):
            by_id[job.id] = job
    return list(by_id.values())


def fetch_and_prefilter(companies: list[CompanyConfig], since: datetime, applied_history: prefilter.AppliedHistory) -> list[Job]:
    settings = get_settings()
    titles_cfg = settings.search_config["titles"]
    staffing_cfg = settings.search_config["staffing"]
    red_flags = settings.search_config["red_flags"]
    locations_cfg = settings.search_config["locations"]
    max_yoe = settings.search_config["scoring"]["max_yoe_required"]

    jobs: list[Job] = []
    for company in companies:
        fetch = FETCHERS.get(company.ats)
        if fetch is None:
            log.warning("No fetcher for ats=%s (company=%s)", company.ats, company.name)
            continue

        try:
            raw_jobs = fetch(company, since)
        except Exception:
            log.exception("Failed fetching %s (%s)", company.name, company.ats)
            continue

        for raw in raw_jobs:
            job = normalize(raw, locations_cfg, settings.search_config["geo"])
            is_jobspy = raw.source not in ATS_SOURCES
            keep, reason = prefilter.evaluate(
                job,
                since=since,
                is_jobspy=is_jobspy,
                titles_config=titles_cfg,
                staffing_config=staffing_cfg,
                red_flags=red_flags,
                applied_history=applied_history,
                max_yoe=max_yoe,
            )
            if keep:
                job = apply_lca(job)
                job.status = "new"
            else:
                job.status = "excluded"
                job.exclude_reason = reason
            jobs.append(job)

    return jobs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="ats")
    parser.add_argument("--window", default="24h", choices=["24h", "7d", "14d"])
    parser.add_argument("--limit-companies", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--score", action="store_true")
    parser.add_argument("--no-llm", action="store_true", help="with --score, stop after the embedding stage")
    parser.add_argument("--max-score", type=int, default=None, help="with --score, cap how many jobs go to Haiku")
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--email", action="store_true")
    parser.add_argument("--no-mark", action="store_true", help="with --digest, write the file but leave rows as scored")
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if "jobspy" in sources:
        log.warning("--sources jobspy: JobSpy fetcher is not built yet (Step 6); ignoring")

    since = compute_since(args.window)
    companies = load_companies()
    if args.limit_companies:
        companies = companies[: args.limit_companies]

    if args.dry_run:
        jobs = fetch_and_prefilter(companies, since, prefilter.AppliedHistory.empty())
        _print_dry_run_summary(jobs)
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into public.runs (sources, window_arg, status) values (%s, %s, 'running') returning id",
                (sources, args.window),
            )
            run_id = cur.fetchone()[0]
        conn.commit()

        try:
            applied_history = load_applied_history(conn)
            sync_cap_exempt(conn, companies)
            jobs = fetch_and_prefilter(companies, since, applied_history)
            jobs = dedup_batch(jobs)

            counts = {"fetched": len(jobs), "inserted": 0, "updated": 0, "unchanged": 0, "excluded": 0}
            for job in jobs:
                if job.status == "excluded":
                    counts["excluded"] += 1
                outcome = upsert_job(conn, job)
                counts[outcome] += 1
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(
                    "update public.runs set finished_at = now(), counts = %s, status = 'ok' where id = %s",
                    (json.dumps(counts), run_id),
                )
            conn.commit()

            if args.score:
                counts.update(embed.run_embedding_stage(conn))
                if not is_ci():
                    _print_top_shortlisted(conn)
                if not args.no_llm:
                    counts.update({f"score_{k}": v for k, v in score_batch.run_scoring_stage(conn, args.max_score).items()})

            if args.digest or args.email:
                result = digest_stage.run_digest_stage(conn, mark=not args.no_mark)
                counts["digest_roles"] = len(result.jobs)
                if not is_ci():
                    print(f"\nDigest written to {result.path} ({len(result.jobs)} role(s), marked digested: {result.marked})")
                if args.email:
                    counts["emailed"] = int(emailer.send_digest(result))

            with conn.cursor() as cur:
                cur.execute("update public.runs set counts = %s where id = %s", (json.dumps(counts), run_id))
            conn.commit()
            log.info("Run %d complete: %s", run_id, counts)
        except Exception as exc:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(
                    "update public.runs set finished_at = now(), status = 'failed', error = %s where id = %s",
                    (str(exc), run_id),
                )
            conn.commit()
            raise


def _print_top_shortlisted(conn, limit: int = 10) -> None:
    """Local review aid only; never called in CI (titles and companies stay out of public logs)."""
    with conn.cursor() as cur:
        cur.execute(
            "select similarity, is_nyc_metro, company, title from public.jobs "
            "where status = 'shortlisted' order by similarity desc limit %s",
            (limit,),
        )
        rows = cur.fetchall()
    print(f"\nTop {len(rows)} shortlisted by similarity:")
    for sim, nyc, company, title in rows:
        print(f"  {sim:.3f} {'NYC' if nyc else '   '} {company} | {title}")


def _print_dry_run_summary(jobs: list[Job]) -> None:
    stats = {ats: {"jobs": 0, "newest": None} for ats in FETCHERS}
    for job in jobs:
        s = stats.get(job.source)
        if s is None:
            continue
        s["jobs"] += 1
        if job.posted_at and (s["newest"] is None or job.posted_at > s["newest"]):
            s["newest"] = job.posted_at

    print("\nFetch summary (dry run, nothing written):")
    for ats, s in stats.items():
        print(f"  {ats:<12} jobs={s['jobs']:<5} newest_posted_at={s['newest']}")


if __name__ == "__main__":
    main()
