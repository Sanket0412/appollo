"""Lever fetcher."""
from __future__ import annotations

from datetime import datetime, timezone

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import title_matches


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    settings = get_settings()
    titles_cfg = settings.search_config["titles"]

    url = f"https://api.lever.co/v0/postings/{company.slug}?mode=json"
    postings = get_json(url)

    jobs: list[RawJob] = []
    for raw in postings:
        title = raw.get("text", "")
        if not title_matches(title, titles_cfg):
            continue

        created_at_ms = raw.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc) if created_at_ms else None
        )
        if posted_at is not None and posted_at < since:
            continue

        description_html = raw.get("description") or ""
        jobs.append(
            RawJob(
                source="lever",
                ats_job_id=raw["id"],
                company=company.name,
                title=title,
                location=(raw.get("categories") or {}).get("location"),
                is_remote=(raw.get("workplaceType") or "").lower() == "remote",
                url=raw.get("hostedUrl", ""),
                posted_at=posted_at,
                description_html=description_html,
                description_text=raw.get("descriptionPlain") or "",
            )
        )
    return jobs
