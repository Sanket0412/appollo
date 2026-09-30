"""Text normalization shared across LCA matching, dedup and ATS parsing."""
from __future__ import annotations

import re

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
