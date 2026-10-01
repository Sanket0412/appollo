"""Workday fetcher. Paginates one search term at a time, fetches the description detail only for
title-matched postings, and de-dupes across search terms since the same posting can match several."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from pipeline.fetchers.base import get_json, post_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

PAGE_LIMIT = 20

_POSTED_TODAY_RE = re.compile(r"posted\s+today", re.IGNORECASE)
_POSTED_YESTERDAY_RE = re.compile(r"posted\s+yesterday", re.IGNORECASE)
_POSTED_N_DAYS_RE = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def _parse_posted_on(text: str | None, now: datetime) -> datetime | None:
    if not text:
        return None
    if _POSTED_TODAY_RE.search(text):
        return now
    if _POSTED_YESTERDAY_RE.search(text):
        return now - timedelta(days=1)
    match = _POSTED_N_DAYS_RE.search(text)
    if match:
        return now - timedelta(days=int(match.group(1)))
    return None


_N_LOCATIONS_RE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)


def _resolve_location(list_text: str | None, detail: dict) -> str | None:
    """List payloads sometimes omit locationsText or say "2 Locations"; the detail payload has the
    real location and a country, which is what decides is_us downstream."""
    text = list_text if list_text and not _N_LOCATIONS_RE.match(list_text.strip()) else detail.get("location")
    country = (detail.get("country") or {}).get("descriptor")
    if country and (not text or country.lower() not in text.lower()):
        text = f"{text}, {country}" if text else country
    return text or None


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    settings = get_settings()
    titles_cfg = settings.search_config["titles"]
    search_terms = settings.search_config["workday_search_terms"]

    base_url = f"https://{company.host}/wday/cxs/{company.tenant}/{company.board}/jobs"
    now = datetime.now(since.tzinfo)

    seen_paths: set[str] = set()
    jobs: list[RawJob] = []

    for term in search_terms:
        offset = 0
        while True:
            payload = post_json(base_url, {"appliedFacets": {}, "limit": PAGE_LIMIT, "offset": offset, "searchText": term})
            postings = payload.get("jobPostings", [])
            total = payload.get("total", 0)

            for posting in postings:
                external_path = posting.get("externalPath")
                if not external_path or external_path in seen_paths:
                    continue
                seen_paths.add(external_path)

                title = posting.get("title", "")
                if not title_matches(title, titles_cfg):
                    continue

                posted_at = _parse_posted_on(posting.get("postedOn"), now)
                if posted_at is not None and posted_at < since:
                    continue

                detail_url = f"https://{company.host}/wday/cxs/{company.tenant}/{company.board}{external_path}"
                detail = get_json(detail_url).get("jobPostingInfo", {})
                description_html = detail.get("jobDescription") or ""

                jobs.append(
                    RawJob(
                        source="workday",
                        ats_job_id=detail.get("id") or external_path,
                        company=company.name,
                        title=title,
                        location=_resolve_location(posting.get("locationsText"), detail),
                        url=detail.get("externalUrl") or f"https://{company.host}/{company.board}{external_path}",
                        posted_at=posted_at,
                        description_html=description_html,
                        description_text=html_to_text(description_html),
                    )
                )

            offset += PAGE_LIMIT
            if not postings or offset >= total:
                break

    return jobs
