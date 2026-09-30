"""Detects which ATS a job-board URL belongs to, and validates the board is real, not a sandbox.

Shared by scripts/seed_from_hn.py (Step 3) and the JobSpy auto-discovery path (Step 6), since both
need to turn an arbitrary URL into an ATS reference and then decide whether it's worth keeping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

REQUEST_TIMEOUT = 10
MIN_JOBS_FOR_VALID_BOARD = 3

# Known-bad boards found by hand: internal sandboxes that otherwise look like a real, listed board.
# Keyed by (ats, slug-or-tenant).
BLOCKLISTED_BOARDS = {
    ("greenhouse", "linkedin"),  # LinkedIn's own Greenhouse board is a sandbox: titles like "123123", "Bug Bash Job"
}

_TEST_TITLE_RE = re.compile(r"^\d+$|test|sandbox|bug\s*bash|do\s*not\s*apply|ignore\s*this", re.IGNORECASE)
_LOCALE_RE = re.compile(r"^[a-z]{2}(-[a-zA-Z]{2})?$")


@dataclass(frozen=True)
class AtsRef:
    ats: str  # greenhouse | lever | ashby | workday
    slug: str | None = None  # greenhouse | lever | ashby
    host: str | None = None  # workday
    tenant: str | None = None  # workday
    board: str | None = None  # workday

    def blocklist_key(self) -> tuple[str, str | None]:
        return (self.ats, self.slug or self.tenant)


def parse_ats_url(url: str) -> AtsRef | None:
    """Recognizes Greenhouse, Lever, Ashby and Workday job-board URLs. None if the host doesn't match."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = parsed.netloc.lower()
    segments = [s for s in parsed.path.split("/") if s]

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and segments:
        return AtsRef(ats="greenhouse", slug=segments[0])

    if host == "jobs.lever.co" and segments:
        return AtsRef(ats="lever", slug=segments[0])

    if host == "jobs.ashbyhq.com" and segments:
        return AtsRef(ats="ashby", slug=segments[0])

    if host.endswith(".myworkdayjobs.com") and segments:
        tenant = host.split(".")[0]
        # Skip a leading locale segment, e.g. /en-US/External/job/... -> board is "External".
        board_segments = [s for s in segments if not _LOCALE_RE.match(s)]
        if not board_segments:
            return None
        return AtsRef(ats="workday", host=host, tenant=tenant, board=board_segments[0])

    return None


def looks_like_test_board(job_titles: list[str]) -> bool:
    """True if a board's titles look like sandbox/test data (digits only, "test", "bug bash", ...)."""
    if not job_titles:
        return True
    matches = sum(1 for t in job_titles if _TEST_TITLE_RE.search(t or ""))
    return (matches / len(job_titles)) > 0.3


def _fetch_job_titles(ref: AtsRef) -> list[str] | None:
    try:
        if ref.ats == "greenhouse":
            resp = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{ref.slug}/jobs", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            return [j.get("title", "") for j in resp.json().get("jobs", [])]

        if ref.ats == "lever":
            resp = requests.get(f"https://api.lever.co/v0/postings/{ref.slug}?mode=json", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            return [j.get("text", "") for j in payload] if isinstance(payload, list) else None

        if ref.ats == "ashby":
            resp = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{ref.slug}", timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            return [j.get("title", "") for j in resp.json().get("jobs", [])]

        if ref.ats == "workday":
            resp = requests.post(
                f"https://{ref.host}/wday/cxs/{ref.tenant}/{ref.board}/jobs",
                json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            return [j.get("title", "") for j in resp.json().get("jobPostings", [])]
    except requests.RequestException:
        return None
    return None


def validate_board(ref: AtsRef) -> bool:
    """One live fetch: real if it clears the blocklist, has enough jobs, and doesn't look like test data."""
    if ref.blocklist_key() in BLOCKLISTED_BOARDS:
        return False

    titles = _fetch_job_titles(ref)
    if titles is None or len(titles) < MIN_JOBS_FOR_VALID_BOARD:
        return False
    return not looks_like_test_board(titles)
