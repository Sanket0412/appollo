"""Amazon fetcher (amazon.jobs search.json, public, no login). Verified live 2026-10-26.

Searches each term restricted to US postings. posted_date is absolute text with doubled spaces on
single-digit days. Audible shares the feed: company.site == "Audible" keeps only Audible postings, and
the plain Amazon entry skips them. The listing carries the full description, so there is no detail call."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

PAGE_SIZE = 10
MAX_PAGES_PER_TERM = 5
URL = (
    "https://www.amazon.jobs/en/search.json?base_query={q}&offset={offset}&result_limit={size}"
    "&normalized_country_code%5B%5D=USA&sort=recent"
)
SECTIONS = (
    ("description", "Description"),
    ("basic_qualifications", "Basic qualifications"),
    ("preferred_qualifications", "Preferred qualifications"),
)


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(re.sub(r"\s+", " ", text).strip(), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config
    audible = (company.site or "").lower() == "audible"

    seen: dict[str, dict] = {}
    for term in cfg["workday_search_terms"]:
        for page in range(MAX_PAGES_PER_TERM):
            offset = page * PAGE_SIZE
            data = get_json(URL.format(q=quote(term), offset=offset, size=PAGE_SIZE))
            for job in data.get("jobs", []):
                job_id = job["id_icims"]
                if job_id in seen or not title_matches(job.get("title", ""), cfg["titles"]):
                    continue
                if (job.get("company_name") or "").lower().startswith("audible") != audible:
                    continue
                seen[job_id] = job
            if offset + PAGE_SIZE >= data.get("hits", 0):
                break

    jobs: list[RawJob] = []
    for job_id, job in seen.items():
        posted = _parse_date(job.get("posted_date"))
        # posted_date is a day, so it counts until the end of that day.
        if posted is not None and posted.replace(hour=23, minute=59) < since:
            continue
        html = "\n".join(f"<h3>{label}</h3>{job[key]}" for key, label in SECTIONS if job.get(key))
        jobs.append(
            RawJob(
                source="amazon",
                ats_job_id=job_id,
                company=company.name,
                title=job["title"],
                location=job.get("normalized_location") or job.get("location"),
                url=f"https://www.amazon.jobs{job['job_path']}",
                posted_at=posted,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
