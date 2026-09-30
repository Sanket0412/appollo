"""Matches a job's employer against DOL LCA filing history.

Match order: config/employer_aliases.yaml override (summing filings across every listed entity),
then an exact employer_norm match, then a fuzzy match via rapidfuzz.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import yaml
from rapidfuzz import fuzz, process

from pipeline.db import get_conn
from pipeline.log import get_logger
from pipeline.settings import REPO_ROOT, get_settings
from pipeline.text_utils import normalize_company

ALIASES_PATH = REPO_ROOT / "config" / "employer_aliases.yaml"

log = get_logger("employer_match")


@dataclass(frozen=True)
class LcaMatch:
    matched_name: str
    match_score: float
    filings_total: int
    filings_relevant_soc: int
    ny_nj_filings: int
    source: str  # "alias" | "exact" | "fuzzy"
    entities: tuple[str, ...]  # underlying employer_raw name(s) the counts were summed from


def _load_aliases() -> dict[str, list[str]]:
    if not ALIASES_PATH.exists():
        return {}
    with ALIASES_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    aliases: dict[str, list[str]] = {}
    for alias_key, targets in raw.items():
        target_list = targets if isinstance(targets, list) else [targets]
        aliases[normalize_company(alias_key)] = [normalize_company(t) for t in target_list]
    return aliases


def _load_employers() -> dict[str, dict]:
    employers: dict[str, dict] = {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select employer_norm, employer_raw, filings_total, filings_relevant_soc, ny_nj_filings "
            "from public.lca_employers"
        )
        for employer_norm, employer_raw, filings_total, filings_relevant_soc, ny_nj_filings in cur.fetchall():
            employers[employer_norm] = {
                "employer_raw": employer_raw,
                "filings_total": filings_total,
                "filings_relevant_soc": filings_relevant_soc,
                "ny_nj_filings": ny_nj_filings,
            }
    return employers


class EmployerMatcher:
    """Holds lca_employers and employer_aliases.yaml in memory so many companies can be matched cheaply."""

    def __init__(self, employers: dict[str, dict], aliases: dict[str, list[str]], fuzzy_score_cutoff: int = 90):
        self._employers = employers
        self._aliases = aliases
        self._all_norms = list(employers.keys())
        self._fuzzy_score_cutoff = fuzzy_score_cutoff
        self._cache: dict[str, LcaMatch | None] = {}

    @classmethod
    def load(cls) -> EmployerMatcher:
        settings = get_settings()
        fuzzy_score_cutoff = settings.search_config["lca"]["fuzzy_threshold"]
        employers = _load_employers()
        aliases = _load_aliases()
        log.info("Loaded %d LCA employer(s), %d alias entrie(s)", len(employers), len(aliases))
        return cls(employers, aliases, fuzzy_score_cutoff)

    def match(self, company: str) -> LcaMatch | None:
        company_norm = normalize_company(company)
        if company_norm in self._cache:
            return self._cache[company_norm]

        result = (
            self._match_alias(company_norm)
            or self._match_exact(company_norm)
            or self._match_fuzzy(company_norm)
        )
        self._cache[company_norm] = result
        return result

    def _match_alias(self, company_norm: str) -> LcaMatch | None:
        targets = self._aliases.get(company_norm)
        if not targets:
            return None

        found = [(t, self._employers[t]) for t in targets if t in self._employers]
        missing = [t for t in targets if t not in self._employers]
        if missing:
            log.warning("Alias %r: no lca_employers row for %s", company_norm, missing)
        if not found:
            return None

        return LcaMatch(
            matched_name=company_norm,
            match_score=100.0,
            filings_total=sum(row["filings_total"] for _, row in found),
            filings_relevant_soc=sum(row["filings_relevant_soc"] for _, row in found),
            ny_nj_filings=sum(row["ny_nj_filings"] for _, row in found),
            source="alias",
            entities=tuple(row["employer_raw"] for _, row in found),
        )

    def _match_exact(self, company_norm: str) -> LcaMatch | None:
        row = self._employers.get(company_norm)
        if row is None:
            return None
        return LcaMatch(
            matched_name=row["employer_raw"],
            match_score=100.0,
            filings_total=row["filings_total"],
            filings_relevant_soc=row["filings_relevant_soc"],
            ny_nj_filings=row["ny_nj_filings"],
            source="exact",
            entities=(row["employer_raw"],),
        )

    def _match_fuzzy(self, company_norm: str) -> LcaMatch | None:
        if not self._all_norms:
            return None
        result = process.extractOne(
            company_norm,
            self._all_norms,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=self._fuzzy_score_cutoff,
        )
        if result is None:
            return None
        matched_norm, score, _ = result
        row = self._employers[matched_norm]
        return LcaMatch(
            matched_name=row["employer_raw"],
            match_score=float(score),
            filings_total=row["filings_total"],
            filings_relevant_soc=row["filings_relevant_soc"],
            ny_nj_filings=row["ny_nj_filings"],
            source="fuzzy",
            entities=(row["employer_raw"],),
        )


@lru_cache(maxsize=1)
def _default_matcher() -> EmployerMatcher:
    return EmployerMatcher.load()


def match_employer(company: str) -> LcaMatch | None:
    return _default_matcher().match(company)
