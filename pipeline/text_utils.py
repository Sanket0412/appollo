"""Text normalization shared across LCA matching, dedup and ATS parsing."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_LEGAL_SUFFIXES = [
    "incorporated",
    "inc",
    "l l c",
    "llc",
    "ltd",
    "limited",
    "corporation",
    "corp",
    "company",
    "co",
    "llp",
    "lp",
    "plc",
    "pc",
    "na",
    "usa",
    "us",
    "holdings",
    "group",
]
_SUFFIX_RE = re.compile(r"\b(" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\b$")
_LEADING_THE_RE = re.compile(r"^the\b\s*")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_company(name: str) -> str:
    """Lowercase, strip punctuation and legal suffixes, so 'Google LLC' and 'GOOGLE, L.L.C.' match."""
    text = name.lower()
    text = text.replace("&", " and ")
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _LEADING_THE_RE.sub("", text).strip()

    while text:
        match = _SUFFIX_RE.search(text)
        if not match:
            break
        text = text[: match.start()].strip()

    return _WHITESPACE_RE.sub(" ", text).strip()


_BLOCK_TAGS = ["p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"]


def html_to_text(html: str | None) -> str:
    """Converts a job description's HTML to plain text, preserving paragraph and line breaks."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def title_matches(title: str, titles_config: dict) -> bool:
    """True if title matches at least one include regex and no exclude regex (search.yaml > titles)."""
    if not title:
        return False
    includes = titles_config.get("include", [])
    excludes = titles_config.get("exclude", [])
    if includes and not any(re.search(pat, title, re.IGNORECASE) for pat in includes):
        return False
    return not any(re.search(pat, title, re.IGNORECASE) for pat in excludes)


def parse_location(raw: str | None, locations_config: dict) -> tuple[bool, bool, bool]:
    """Returns (is_us, is_remote, is_nyc_metro) from a free-text location string (search.yaml > locations)."""
    text = (raw or "").strip().lower()

    is_remote = any(kw in text for kw in locations_config["remote_keywords"])
    is_nyc_metro = any(kw in text for kw in locations_config["nyc_metro"])

    if any(kw in text for kw in locations_config["non_us_keywords"]):
        is_us = False
    elif any(kw in text for kw in locations_config["us_keywords"]) or any(
        re.search(rf"\b{re.escape(state)}\b", text.upper()) for state in locations_config["us_states"]
    ):
        is_us = True
    elif not text:
        # No location at all: keep, per search.yaml's unclear_remote_policy, and let Haiku's
        # location_fit judge it later rather than silently dropping the job here.
        is_us = True
    else:
        is_us = False

    return is_us, is_remote, is_nyc_metro
