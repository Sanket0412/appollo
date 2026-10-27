"""Avature fetcher (Bloomberg, Two Sigma). Public career-site HTML, no login. company.host is the site
host and company.site its path prefix ("careers"). Neither site shows a posted date, so jobs are
undated and fetchers/undated.py dates them by first sight.

Bloomberg is searched per term (/SearchJobs/{term}); Two Sigma lists all open roles
(/OpenRoles, paged by jobOffset), so only its titles are filtered here."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

from pipeline.fetchers.base import get_text
from pipeline.fetchers.html_utils import soup
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

PAGE_SIZE = 10
MAX_PAGES = 12
SKIP_LABELS = {"apply", "view role", "view job", "view"}


def parse_list(html: str) -> list[dict]:
    """Unique (id, title, url, location) rows from a results page."""
    rows: dict[str, dict] = {}
    for anchor in soup(html).find_all("a", href=re.compile(r"/JobDetail/")):
        text = anchor.get_text(" ", strip=True)
        job_id = anchor["href"].rstrip("/").rsplit("/", 1)[-1]
        if not text or text.lower() in SKIP_LABELS:
            continue
        container = anchor.find_parent(class_=re.compile(r"article__header__text"))
        location_tag = container.select_one(".article__header__content__text .paragraph_inner-span") if container else None
        rows.setdefault(
            job_id,
            {
                "id": job_id,
                "title": text,
                "url": anchor["href"],
                "location": location_tag.get_text(" ", strip=True) if location_tag else None,
            },
        )
    return list(rows.values())


def parse_detail(html: str) -> tuple[str | None, str]:
    """(location, description html) from a job page."""
    page = soup(html)
    location = None
    for label in page.select(".article__content__view__field__label"):
        if label.get_text(strip=True).lower() == "location":
            value = label.find_next(class_="article__content__view__field__value")
            location = value.get_text(" ", strip=True) if value else None
            break
    sections = page.select(".article__content") or ([page.body] if page.body else [])
    return location, "\n".join(str(section) for section in sections)


def _list_urls(company: CompanyConfig, terms: list[str]) -> list[str]:
    base = f"https://{company.host}/{company.site}"
    urls = []
    if company.name == "Bloomberg":
        for term in terms:
            urls += [f"{base}/SearchJobs/{quote(term)}?jobOffset={n * PAGE_SIZE}" for n in range(3)]
    else:
        urls += [f"{base}/OpenRoles?jobRecordsPerPage={PAGE_SIZE}&jobOffset={n * PAGE_SIZE}" for n in range(MAX_PAGES)]
    return urls


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config

    matched: dict[str, dict] = {}
    empty_pages = 0
    for url in _list_urls(company, cfg["workday_search_terms"]):
        rows = parse_list(get_text(url))
        new = [r for r in rows if r["id"] not in matched]
        empty_pages = 0 if new else empty_pages + 1
        for row in new:
            if title_matches(row["title"], cfg["titles"]):
                matched[row["id"]] = row
        if empty_pages >= 2 and company.name != "Bloomberg":
            break

    jobs: list[RawJob] = []
    for job_id, row in matched.items():
        location, html = parse_detail(get_text(row["url"]))
        jobs.append(
            RawJob(
                source="avature",
                ats_job_id=job_id,
                company=company.name,
                title=row["title"],
                location=location or row["location"],
                url=row["url"],
                undated=True,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
