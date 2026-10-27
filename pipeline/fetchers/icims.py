"""iCIMS HTML fetcher (NYU, Princeton). Public career portal pages, no login. company.host is the portal host.

The shared session keeps the automatic cookie the first redirect sets (a cookie-less client fails).
List rows carry the title, an absolute date "(10/21/2026 5:50 PM)" and the location; matching titles get
the job page for the full description and the ISO datePosted from its JSON-LD."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from pipeline.fetchers.base import get_text
from pipeline.fetchers.html_utils import jsonld_job, parse_iso, soup
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

MAX_PAGES_PER_TERM = 3
DATE_RE = re.compile(r"\((\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2} [AP]M)\)")


def _row_date(row) -> datetime | None:
    match = DATE_RE.search(row.get_text(" ", strip=True))
    if not match:
        return None
    return datetime.strptime(match.group(1), "%m/%d/%Y %I:%M %p").replace(tzinfo=timezone.utc)


def _row_location(row) -> str | None:
    for tag in row.select("div.iCIMS_JobHeaderTag"):
        label = tag.select_one("dt")
        if label and "Location" in label.get_text():
            value = tag.select_one("dd")
            return value.get_text(" ", strip=True) if value else None
    return None


def parse_list(html: str) -> tuple[list[dict], int]:
    """Rows and the page count from one search-results page."""
    page = soup(html)
    rows = []
    for anchor in page.select("a.iCIMS_Anchor[href*='/jobs/']"):
        match = re.search(r"/jobs/(\d+)/", anchor["href"])
        title = anchor.find("h3")
        row = anchor.find_parent("div", class_="row")
        if not (match and title and row):
            continue
        rows.append(
            {
                "id": match.group(1),
                "title": title.get_text(strip=True),
                "url": anchor["href"],
                "posted": _row_date(row),
                "location": _row_location(row),
            }
        )
    pages = re.search(r"Page \d+ of (\d+)", page.get_text(" ", strip=True))
    return rows, int(pages.group(1)) if pages else 1


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config
    host = company.host

    matched: dict[str, dict] = {}
    for term in cfg["workday_search_terms"]:
        for page_no in range(MAX_PAGES_PER_TERM):
            html = get_text(f"https://{host}/jobs/search?ss=1&searchKeyword={quote(term)}&in_iframe=1&pr={page_no}")
            rows, total_pages = parse_list(html)
            for row in rows:
                if row["id"] in matched or not title_matches(row["title"], cfg["titles"]):
                    continue
                if row["posted"] is not None and row["posted"] < since:
                    continue
                matched[row["id"]] = row
            if page_no + 1 >= total_pages:
                break

    jobs: list[RawJob] = []
    for job_id, row in matched.items():
        posting = jsonld_job(get_text(row["url"])) or {}
        posted = parse_iso(posting.get("datePosted")) or row["posted"]
        if posted is not None and posted < since:
            continue
        html = posting.get("description") or ""
        jobs.append(
            RawJob(
                source="icims",
                ats_job_id=job_id,
                company=company.name,
                title=row["title"],
                location=row["location"],
                url=row["url"].split("?")[0],
                posted_at=posted,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
