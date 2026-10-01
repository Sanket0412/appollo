"""Prefilter: decides whether a normalized job should be kept. Checks run in order; the first
failure wins, so exclude_reason always names the single most relevant reason."""
from __future__ import annotations

import re
from datetime import datetime

from rapidfuzz import fuzz

from pipeline.models import Job
from pipeline.text_utils import normalize_company, title_norm

FUZZY_TITLE_THRESHOLD = 90


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

    if applied_history.matches(job.company_norm, job.title):
        return False, "already_applied"

    return True, None
