"""Eightfold fetcher (Microsoft, Millennium). Public careers APIs, no login. Verified live 2026-10-26.

company.host is the careers host, company.site the Eightfold domain, company.board picks the search
API ("pcsx" for /api/pcsx/search, "apply" for /api/apply/v2/jobs). Both use /api/pcsx/position_details
for the description, fetched only for title matches."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

PAGE_SIZE = 10
MAX_PAGES_PER_TERM = 3


def _search(company: CompanyConfig, term: str, start: int) -> tuple[list[dict], int]:
    host, domain = company.host, company.site
    if company.board == "apply":
        data = get_json(
            f"https://{host}/api/apply/v2/jobs?domain={domain}&query={quote(term)}&start={start}&num={PAGE_SIZE}"
        )
        return data.get("positions", []), data.get("count", 0)
    payload = get_json(
        f"https://{host}/api/pcsx/search?domain={domain}&query={quote(term)}&location=&start={start}&sort_by=timestamp"
    )
    data = payload.get("data", payload)
    return data.get("positions", []), data.get("count", 0)


def _epoch(value) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config
    host, domain = company.host, company.site

    matched: dict[str, tuple[dict, datetime | None]] = {}
    for term in cfg["workday_search_terms"]:
        for page in range(MAX_PAGES_PER_TERM):
            start = page * PAGE_SIZE
            positions, count = _search(company, term, start)
            for pos in positions:
                pid = str(pos["id"])
                if pid in matched or not title_matches(pos.get("name", ""), cfg["titles"]):
                    continue
                posted = _epoch(pos.get("postedTs") or pos.get("t_create"))
                if posted is not None and posted < since:
                    continue
                matched[pid] = (pos, posted)
            if not positions or start + PAGE_SIZE >= count:
                break

    jobs: list[RawJob] = []
    for pid, (pos, posted) in matched.items():
        detail = get_json(f"https://{host}/api/pcsx/position_details?position_id={pid}&domain={domain}&hl=en")
        detail = detail.get("data", detail)
        html = detail.get("jobDescription") or pos.get("job_description") or ""
        locations = pos.get("locations") or []
        location = pos.get("location") or (locations[0] if locations else None)
        url = pos.get("canonicalPositionUrl") or f"https://{host}{pos.get('positionUrl') or '/careers/job/' + pid}"
        remote_option = pos.get("workLocationOption") or pos.get("work_location_option") or ""
        jobs.append(
            RawJob(
                source="eightfold",
                ats_job_id=pid,
                company=company.name,
                title=pos["name"],
                location=location,
                is_remote=remote_option == "remote",
                url=url,
                posted_at=posted,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
