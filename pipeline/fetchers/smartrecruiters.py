"""SmartRecruiters fetcher (public Posting API, no key). Searches each term in workday_search_terms
restricted to US postings, filters on title and release date from the list, then fetches the detail
(description and apply URL) only for matches. Verified live 2026-10-18."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

API = "https://api.smartrecruiters.com/v1/companies"
PAGE_LIMIT = 100
MAX_PAGES_PER_TERM = 3


def _parse_released(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _location(loc: dict) -> str | None:
    text = loc.get("fullLocation") or ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
    return text or None


def _description_html(detail: dict) -> str:
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    order = ("jobDescription", "qualifications", "additionalInformation")
    return "\n".join(f"<h3>{sections[k].get('title', '')}</h3>{sections[k].get('text', '')}" for k in order if k in sections)


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config
    base = f"{API}/{company.slug}/postings"

    matched: dict[str, tuple[dict, datetime | None]] = {}
    for term in cfg["workday_search_terms"]:
        for page in range(MAX_PAGES_PER_TERM):
            offset = page * PAGE_LIMIT
            data = get_json(f"{base}?limit={PAGE_LIMIT}&offset={offset}&country=us&q={quote(term)}")
            for item in data.get("content", []):
                posted = _parse_released(item.get("releasedDate"))
                if item["id"] in matched or not title_matches(item.get("name", ""), cfg["titles"]):
                    continue
                if posted is not None and posted < since:
                    continue
                matched[item["id"]] = (item, posted)
            if offset + PAGE_LIMIT >= data.get("totalFound", 0):
                break

    jobs: list[RawJob] = []
    for job_id, (item, posted) in matched.items():
        detail = get_json(f"{base}/{job_id}")
        html = _description_html(detail)
        loc = item.get("location") or {}
        jobs.append(
            RawJob(
                source="smartrecruiters",
                ats_job_id=job_id,
                company=company.name,
                title=item["name"],
                location=_location(loc),
                is_remote=bool(loc.get("remote")),
                url=detail.get("postingUrl") or detail.get("applyUrl") or "",
                posted_at=posted,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
