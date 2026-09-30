"""Greenhouse fetcher. Uses first_published for freshness; updated_at gets bulk-restamped across
whole boards, so it is never used here."""
from __future__ import annotations

import html
from datetime import datetime

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    settings = get_settings()
    titles_cfg = settings.search_config["titles"]

    url = f"https://boards-api.greenhouse.io/v1/boards/{company.slug}/jobs?content=true"
    payload = get_json(url)

    jobs: list[RawJob] = []
    for raw in payload.get("jobs", []):
        title = raw.get("title", "")
        if not title_matches(title, titles_cfg):
            continue

        posted_at = _parse_iso(raw.get("first_published"))
        if posted_at is None:
            # Not in the list payload for this board; fetch the per-job detail only since we
            # already know the title matched.
            detail = get_json(f"https://boards-api.greenhouse.io/v1/boards/{company.slug}/jobs/{raw['id']}")
            posted_at = _parse_iso(detail.get("first_published"))

        if posted_at is not None and posted_at < since:
            continue

        content_html = html.unescape(raw.get("content") or "")
        jobs.append(
            RawJob(
                source="greenhouse",
                ats_job_id=str(raw["id"]),
                company=company.name,
                title=title,
                location=(raw.get("location") or {}).get("name"),
                url=raw.get("absolute_url", ""),
                posted_at=posted_at,
                description_html=content_html,
                description_text=html_to_text(content_html),
            )
        )
    return jobs
