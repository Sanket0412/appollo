"""Pipeline CLI.

Fetch-only for now: prefilter, dedup, upsert, scoring and digest land in later steps
(see docs/BUILD_PLAN.md). This lets Step 4's fetchers be smoke-tested end to end.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import yaml

from pipeline.fetchers import ashby, greenhouse, lever, workday
from pipeline.log import get_logger
from pipeline.models import CompanyConfig
from pipeline.settings import REPO_ROOT, get_settings

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
    hours = settings.search_config["windows"][window] + settings.search_config["grace_hours"]
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="ats")
    parser.add_argument("--window", default="24h", choices=["24h", "7d"])
    parser.add_argument("--limit-companies", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    since = compute_since(args.window)
    companies = load_companies()
    if args.limit_companies:
        companies = companies[: args.limit_companies]

    stats = {ats: {"companies": 0, "jobs": 0, "title_matches": 0, "newest": None} for ats in FETCHERS}

    for company in companies:
        fetch = FETCHERS.get(company.ats)
        if fetch is None:
            continue

        try:
            jobs = fetch(company, since)
        except Exception:
            log.exception("Failed fetching %s (%s)", company.name, company.ats)
            continue

        s = stats[company.ats]
        s["companies"] += 1
        s["jobs"] += len(jobs)
        s["title_matches"] += len(jobs)  # fetchers already filter by title before returning
        for job in jobs:
            if job.posted_at and (s["newest"] is None or job.posted_at > s["newest"]):
                s["newest"] = job.posted_at

    label = "Fetch summary (dry run, nothing written)" if args.dry_run else "Fetch summary"
    print(f"\n{label}:")
    for ats, s in stats.items():
        print(
            f"  {ats:<12} companies={s['companies']:<4} jobs={s['jobs']:<5} "
            f"title_matches={s['title_matches']:<5} newest_posted_at={s['newest']}"
        )


if __name__ == "__main__":
    main()
