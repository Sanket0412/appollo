"""Prefilter: decides whether a normalized job should be kept. Checks run in order; the first
failure wins, so exclude_reason always names the single most relevant reason."""
from __future__ import annotations

import re
from datetime import datetime

from rapidfuzz import fuzz

from pipeline.models import Job
from pipeline.text_utils import normalize_company, title_norm

FUZZY_TITLE_THRESHOLD = 90

# "5+ years of experience", "3-5 years' relevant experience", "minimum of 6 years", "at least 7 years".
_YEARS_EXPERIENCE_RE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|\u2013|to)\s*\d{1,2}\s*\+?\s*)?years?\b[^.\n]{0,60}?\bexperience",
    re.IGNORECASE,
)
_YEARS_MINIMUM_RE = re.compile(r"(?:minimum|at least|min\.?)\s+(?:of\s+)?(\d{1,2})\s*\+?\s*years?\b", re.IGNORECASE)
_OPTIONAL_RE = re.compile(r"\bprefer(?:red|ably)?\b|nice to have|\bbonus\b|\ba plus\b", re.IGNORECASE)


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start))
    rights = [i for i in (text.find("\n", end), text.find(". ", end)) if i != -1]
    return text[left + 1 : min(rights) if rights else len(text)]


def min_years_required(description: str | None) -> int | None:
    """Smallest years-of-experience figure the posting states as required, or None when it states none.

    Taking the smallest figure across all statements is deliberate: a posting that lists "3+ years
    Python" next to "7+ years in the industry" only truly requires 3. Statements marked preferred /
    bonus / nice to have are ignored.
    """
    if not description:
        return None
    found: list[int] = []
    for regex in (_YEARS_EXPERIENCE_RE, _YEARS_MINIMUM_RE):
        for m in regex.finditer(description):
            if _OPTIONAL_RE.search(_sentence_around(description, m.start(), m.end())):
                continue
            years = int(m.group(1))
            if 0 < years <= 30:
                found.append(years)
    return min(found) if found else None



class AppliedHistory:
    """Precomputed lookup for public.applied_history, grouped by company so the fuzzy title
    comparison only ever runs against titles at the same employer."""

    def __init__(self, rows: list[tuple[str, str]]):
        self._titles_by_company: dict[str, list[str]] = {}
        for company_norm, title in rows:
            self._titles_by_company.setdefault(company_norm, []).append(title)

    def matches(self, company_norm: str, title: str) -> bool:
        titles = self._titles_by_company.get(company_norm)
        if not titles:
            return False
        norm = title_norm(title)
        return any(norm == t or fuzz.token_sort_ratio(norm, t) >= FUZZY_TITLE_THRESHOLD for t in titles)

    @classmethod
    def empty(cls) -> AppliedHistory:
        return cls([])


def evaluate(
    job: Job,
    *,
    since: datetime,
    is_jobspy: bool,
    titles_config: dict,
    staffing_config: dict,
    red_flags: list[str],
    applied_history: AppliedHistory,
    max_yoe: int | None = None,
) -> tuple[bool, str | None]:
    includes = titles_config.get("include", [])
    excludes = titles_config.get("exclude", [])

    if includes and not any(re.search(pat, job.title, re.IGNORECASE) for pat in includes):
        return False, "title_no_match"
    if any(re.search(pat, job.title, re.IGNORECASE) for pat in excludes):
        return False, "title_excluded"

    if not job.is_us:
        return False, "not_us"

    # A known posted date is required from every source (decided 2026-10-01): only jobs
    # guaranteed to be recent are kept.
    if job.posted_at is None:
        return False, "no_posted_at"
    if job.posted_at < since:
        return False, "stale"

    blocklist_norm = {normalize_company(n) for n in staffing_config["company_blocklist"]}
    if job.company_norm in blocklist_norm:
        return False, "staffing_company"

    description = job.description or ""
    if any(re.search(pat, description, re.IGNORECASE) for pat in staffing_config["description_patterns"]):
        return False, "staffing_description"

    if any(re.search(pat, description, re.IGNORECASE) for pat in red_flags):
        return False, "red_flag_description"

    if max_yoe is not None:
        years = min_years_required(description)
        if years is not None and years > max_yoe:
            return False, "yoe_too_high"

    if applied_history.matches(job.company_norm, job.title):
        return False, "already_applied"

    return True, None
