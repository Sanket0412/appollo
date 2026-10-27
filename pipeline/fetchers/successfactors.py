"""SAP SuccessFactors fetcher (SMBC). Public career-site HTML search, no login; the /services/ RSS feed
is disallowed by robots.txt and is not used. company.host is the site host, company.site the path
prefix ("smbc"). The job page microdata carries datePosted (e.g. "Thu Oct 22 00:00:00 UTC 2026"),
which the research notes had missed, so postings are dated."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from pipeline.fetchers.base import get_text
from pipeline.fetchers.html_utils import soup
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

PAGE_SIZE = 25
MAX_PAGES_PER_TERM = 3


def parse_list(html: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for anchor in soup(html).select("a.jobTitle-link"):
        match = re.search(r"/(\d+)/?$", anchor["href"])
        if match:
            rows.setdefault(match.group(1), {"id": match.group(1), "title": anchor.get_text(strip=True), "href": anchor["href"]})
    return list(rows.values())


def _meta(page, prop: str) -> str | None:
    tag = page.find(attrs={"itemprop": prop})
    if tag is None:
        return None
    return (tag.get("content") or tag.get_text(" ", strip=True)) or None


def parse_detail(html: str) -> dict:
    page = soup(html)
    posted = None
    raw = _meta(page, "datePosted")
    if raw:
        try:
            posted = datetime.strptime(raw, "%a %b %d %H:%M:%S UTC %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            posted = None
    place = ", ".join(p for p in (_meta(page, "addressLocality"), _meta(page, "addressRegion"), _meta(page, "addressCountry")) if p)
    body = page.select_one("span.jobdescription") or page.find(attrs={"itemprop": "description"})
    return {"posted": posted, "location": place or None, "html": str(body) if body else ""}


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config
    base = f"https://{company.host}"

    matched: dict[str, dict] = {}
    for term in cfg["workday_search_terms"]:
        for page_no in range(MAX_PAGES_PER_TERM):
            rows = parse_list(get_text(f"{base}/{company.site}/search/?q={quote(term)}&startrow={page_no * PAGE_SIZE}"))
            for row in rows:
                if row["id"] not in matched and title_matches(row["title"], cfg["titles"]):
                    matched[row["id"]] = row
            if len(rows) < PAGE_SIZE:
                break

    jobs: list[RawJob] = []
    for job_id, row in matched.items():
        url = base + row["href"]
        detail = parse_detail(get_text(url))
        if detail["posted"] is not None and detail["posted"] < since:
            continue
        jobs.append(
            RawJob(
                source="successfactors",
                ats_job_id=job_id,
                company=company.name,
                title=row["title"],
                location=detail["location"],
                url=url,
                posted_at=detail["posted"],
                description_html=detail["html"],
                description_text=html_to_text(detail["html"]),
            )
        )
    return jobs
