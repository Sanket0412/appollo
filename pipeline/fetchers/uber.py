"""Uber fetcher (public sitemap plus schema.org JobPosting JSON-LD, robots.txt allows everything).

The sitemap has no titles but its lastmod is never earlier than the posting date, so only pages with
lastmod inside the window are fetched; datePosted on the page is absolute and decides freshness."""
from __future__ import annotations

from datetime import datetime

from pipeline.fetchers.base import get_text
from pipeline.fetchers.html_utils import (
    jsonld_job,
    ld_location,
    parse_iso,
    sitemap_urls,
)
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

SITEMAP = "https://jobs.uber.com/en/jobs/sitemap.xml"


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    titles_cfg = get_settings().search_config["titles"]
    jobs: list[RawJob] = []
    for url, lastmod in sitemap_urls(get_text(SITEMAP)):
        modified = parse_iso(lastmod)
        if modified is not None and modified < since:
            continue
        posting = jsonld_job(get_text(url))
        if posting is None or not title_matches(posting.get("title", ""), titles_cfg):
            continue
        posted = parse_iso(posting.get("datePosted"))
        if posted is not None and posted < since:
            continue
        html = posting.get("description") or ""
        jobs.append(
            RawJob(
                source="uber",
                ats_job_id=url.rstrip("/").rsplit("/", 1)[-1],
                company=company.name,
                title=posting["title"],
                location=ld_location(posting),
                url=url,
                posted_at=posted,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
