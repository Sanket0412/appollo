"""Ashby fetcher. Skips unlisted jobs (isListed=False)."""
from __future__ import annotations

from datetime import datetime

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import title_matches


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    settings = get_settings()
    titles_cfg = settings.search_config["titles"]

    url = f"https://api.ashbyhq.com/posting-api/job-board/{company.slug}?includeCompensation=true"
    payload = get_json(url)

    jobs: list[RawJob] = []
    for raw in payload.get("jobs", []):
        if not raw.get("isListed", True):
            continue

        title = raw.get("title", "")
        if not title_matches(title, titles_cfg):
            continue

        posted_at = None
        published_at = raw.get("publishedAt")
        if published_at:
            try:
                posted_at = datetime.fromisoformat(published_at)
            except ValueError:
                posted_at = None
        if posted_at is not None and posted_at < since:
            continue

        description_html = raw.get("descriptionHtml") or ""
        jobs.append(
            RawJob(
                source="ashby",
                ats_job_id=raw["id"],
                company=company.name,
                title=title,
                location=raw.get("location"),
                is_remote=bool(raw.get("isRemote")),
                url=raw.get("jobUrl", ""),
                posted_at=posted_at,
                description_html=description_html,
                description_text=raw.get("descriptionPlain") or "",
            )
        )
    return jobs
