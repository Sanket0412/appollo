"""JobSpy fetcher (Step 6). Local machine only: Indeed, LinkedIn, Google and friends via python-jobspy.

Never runs in CI (hard rule 7). Nothing here logs in to any account; JobSpy reads public search pages.
Also does source G auto-discovery: a result whose direct apply URL is a Greenhouse, Lever, Ashby or
Workday board is validated and appended to config/companies.yaml as source: discovered.
"""
from __future__ import annotations

import math
import random
import time
from datetime import date, datetime, timezone
from datetime import time as dtime

import yaml

from pipeline.ats_discovery import (
    existing_ref_keys,
    parse_ats_url,
    ref_key,
    to_entry,
    validate_board,
)
from pipeline.exclusions import is_excluded, load_excluded
from pipeline.log import get_logger
from pipeline.models import RawJob
from pipeline.settings import REPO_ROOT, get_settings, is_ci
from pipeline.text_utils import normalize_company, title_matches

log = get_logger("jobspy")

COMPANIES_PATH = REPO_ROOT / "config" / "companies.yaml"
HOME_LOCATION = "Jersey City, NJ"
PAUSE_SECONDS = (10, 20)


def _refuse_in_ci() -> None:
    if is_ci():
        raise RuntimeError("JobSpy must not run in CI (GITHUB_ACTIONS=true); it is local-only.")


def _clean(value) -> str | None:
    """pandas gives NaN/None/'' for missing cells; return None for all of them."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _posted_at(value) -> datetime | None:
    """JobSpy dates are day-level. Use the end of that day (capped at now) so a job posted late
    yesterday is not called stale by a 24h window; hours_old already limits what each site returns."""
    text = _clean(value)
    if text is None:
        return None
    try:
        if isinstance(value, datetime):
            day = value.date()
        elif isinstance(value, date):
            day = value
        else:
            day = date.fromisoformat(text[:10])
    except ValueError:
        return None
    end_of_day = datetime.combine(day, dtime(23, 59), tzinfo=timezone.utc)
    return min(end_of_day, datetime.now(timezone.utc))


def row_to_raw_job(row: dict) -> RawJob | None:
    title = _clean(row.get("title"))
    company = _clean(row.get("company"))
    url = _clean(row.get("job_url_direct")) or _clean(row.get("job_url"))
    site = _clean(row.get("site"))
    if not (title and company and url and site):
        return None
    ats_job_id = _clean(row.get("id")) or url
    is_remote = row.get("is_remote")
    return RawJob(
        source=f"jobspy_{site}",
        ats_job_id=ats_job_id,
        company=company,
        title=title,
        location=_clean(row.get("location")),
        is_remote=bool(is_remote) if is_remote is not None and not (isinstance(is_remote, float) and math.isnan(is_remote)) else False,
        url=url,
        posted_at=_posted_at(row.get("date_posted")),
        description_text=_clean(row.get("description")),
    )


def _google_term(term: str, remote: bool) -> str:
    where = "remote in the United States" if remote else f"near {HOME_LOCATION}"
    return f"{term} jobs {where} since yesterday"


def fetch(since: datetime, discover: bool = True) -> list[RawJob]:
    _refuse_in_ci()
    from jobspy import (
        scrape_jobs,  # imported late: only installed from requirements-local.txt
    )

    search_config = get_settings().search_config
    cfg = search_config["jobspy"]
    hours_old = max(1, math.ceil((datetime.now(timezone.utc) - since).total_seconds() / 3600))

    searches = []
    for term in cfg["search_terms"]:
        searches.append((term, False))
        searches.append((term, True))

    out: list[RawJob] = []
    discovered_candidates: list[tuple[str, str]] = []
    for i, (term, remote) in enumerate(searches):
        if i:
            time.sleep(random.uniform(*PAUSE_SECONDS))
        kwargs = {
            "site_name": cfg["sites"],
            "search_term": term,
            "google_search_term": _google_term(term, remote),
            "location": "USA" if remote else HOME_LOCATION,
            "distance": cfg["distance_miles"],
            "is_remote": remote,
            "results_wanted": cfg["results_wanted"],
            "hours_old": hours_old,
            "country_indeed": "USA",
            "linkedin_fetch_description": True,
            "description_format": "markdown",
        }
        try:
            df = scrape_jobs(**kwargs)
        except Exception:
            log.exception("JobSpy call failed (remote=%s)", remote)
            continue

        rows = df.to_dict("records") if df is not None else []
        by_site: dict[str, int] = {}
        for row in rows:
            site = _clean(row.get("site")) or "unknown"
            by_site[site] = by_site.get(site, 0) + 1
            raw = row_to_raw_job(row)
            if raw is None:
                continue
            out.append(raw)
            direct = _clean(row.get("job_url_direct"))
            if direct and title_matches(raw.title, search_config["titles"]):
                discovered_candidates.append((raw.company, direct))
        log.info("JobSpy call remote=%s returned %d rows by site %s", remote, len(rows), by_site)
        if "linkedin" in cfg["sites"] and by_site.get("linkedin", 0) == 0:
            log.warning("LinkedIn returned zero rows (it fails quietly when throttled)")

    added = discover_boards(discovered_candidates) if discover else 0
    log.info("JobSpy: %d rows total, %d new boards discovered", len(out), added)
    return out


def discover_boards(candidates: list[tuple[str, str]]) -> int:
    """Source G. Validates direct apply URLs (from DS/ML-titled rows only) that point at a supported ATS and appends new boards to
    companies.yaml with source: discovered. Never edits an existing entry. Returns how many were added."""
    if not candidates:
        return 0
    blocklist = {normalize_company(n) for n in get_settings().search_config["staffing"]["company_blocklist"]}
    with COMPANIES_PATH.open("r", encoding="utf-8") as f:
        existing = yaml.safe_load(f) or []
    seen = existing_ref_keys(existing)
    excluded = load_excluded()

    new_entries = []
    for company, url in candidates:
        ref = parse_ats_url(url)
        if ref is None or normalize_company(company) in blocklist:
            continue
        if is_excluded(company, excluded) or is_excluded(ref.slug or ref.tenant or "", excluded):
            continue
        key = ref_key(ref)
        if key in seen:
            continue
        seen.add(key)  # one validation attempt per board per run, pass or fail
        if validate_board(ref):
            new_entries.append(to_entry(company, ref, source="discovered"))
    if not new_entries:
        return 0

    with COMPANIES_PATH.open("a", encoding="utf-8") as f:
        for e in new_entries:
            f.write("- " + yaml.safe_dump(e, default_flow_style=True, sort_keys=False).strip() + "\n")
    return len(new_entries)
