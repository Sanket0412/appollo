"""Companies Sanket never wants in the board list. One name per line in data/exclude_companies.txt
(gitignored, local only). Used by scripts/seed_from_hn.py and the JobSpy auto-discovery step so a
removed company is never added back."""
from __future__ import annotations

import re
from pathlib import Path

from pipeline.settings import REPO_ROOT
from pipeline.text_utils import normalize_company

EXCLUDE_PATH = REPO_ROOT / "data" / "exclude_companies.txt"

_TRAILING_WORD_RE = re.compile(r"\s+(technologies|technology|tech)$")


def normalize_excluded(name: str) -> str:
    """normalize_company (lowercase, punctuation, inc/llc/corp/ltd...) plus a trailing 'technologies'."""
    text = normalize_company(name)
    while True:
        stripped = _TRAILING_WORD_RE.sub("", text).strip()
        if stripped == text:
            return text
        text = stripped


def load_excluded(path: Path = EXCLUDE_PATH) -> set[str]:
    """Normalized names from the file; blank lines and lines starting with # are ignored. Missing file is empty."""
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(normalize_excluded(line))
    names.discard("")
    return names


def is_excluded(name: str, excluded: set[str]) -> bool:
    return normalize_excluded(name) in excluded
