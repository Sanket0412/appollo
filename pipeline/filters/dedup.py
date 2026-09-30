"""Dedup: computes each job's canonical id and decides which source wins when the same role shows
up from more than one source (ATS beats JobSpy)."""
from __future__ import annotations

import hashlib
import re

from pipeline.text_utils import title_norm

_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")

ATS_SOURCES = frozenset({"greenhouse", "lever", "ashby", "workday"})


def location_norm(location: str | None) -> str:
    text = (location or "").lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def canonical_id(company_norm: str, title: str, location: str | None) -> str:
    key = f"{company_norm}|{title_norm(title)}|{location_norm(location)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def source_priority(source: str) -> int:
    """Higher wins. ATS sources outrank JobSpy sources."""
    return 1 if source in ATS_SOURCES else 0


def should_overwrite(existing_source: str, new_source: str) -> bool:
    """True if a row from new_source should overwrite an existing row from existing_source."""
    return source_priority(new_source) > source_priority(existing_source)
