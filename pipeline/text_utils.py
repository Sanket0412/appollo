"""Text normalization shared across LCA matching, dedup and ATS parsing."""
from __future__ import annotations

import re
from functools import lru_cache

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


_WORKMODE_RE = re.compile(r"\b(remote|hybrid|onsite|on site)\b", re.IGNORECASE)
_TRAILING_CODE_RE = re.compile(r"\b(req|job|jr|r)?\s*\d{3,}\w*\s*$", re.IGNORECASE)


def title_norm(title: str) -> str:
    """Lowercase, strip work-mode words and trailing requisition codes, so the same role posted as
    'Data Scientist' and 'Data Scientist - Remote (Req-104822)' dedup to the same canonical id."""
    text = title.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _WORKMODE_RE.sub(" ", text)
    text = _TRAILING_CODE_RE.sub(" ", text)
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


_US_STATE_NAMES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
]
_US_STATE_NAME_RE = re.compile(r"\b(" + "|".join(_US_STATE_NAMES) + r")\b", re.IGNORECASE)
_US_TEXT_SIGNAL_RE = re.compile(r"\bunited states\b|\bus[- ]based\b|\bu\.s\.|\bUSA\b|\bUS only\b", re.IGNORECASE)
# "$120,000 - $150,000", "$120k-$150k", "$95,000 to $130,000"
_USD_RANGE_RE = re.compile(
    r"\$\s?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s?[kK]?\s*(?:-|\u2013|\u2014|to)\s*\$?\s?\d{2,3}(?:,\d{3})?(?:\.\d+)?\s?[kK]?"
)


def _has_word(text: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text) is not None


def _is_state_abbreviation_in_location_context(raw: str, states: list[str]) -> bool:
    """Uppercase state code right after a comma ("Austin, TX") or as the whole token in a short
    location string ("NY"), checked on the original case so the word "in" is never read as IN."""
    return any(re.search(rf"(?:,\s*|^|[-/(]\s*){state}\b", raw) for state in states)


@lru_cache(maxsize=4)
def _city_state_re(states: tuple[str, ...]) -> re.Pattern:
    return re.compile(r"\b[A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+)*,\s*(?:" + "|".join(states) + r")\b")


def has_us_signal_in_description(description: str, locations_config: dict) -> bool:
    """Clear US evidence in free text: "United States", "US-based", "U.S.", a US state name or a
    ", NY" style abbreviation, or a USD salary range."""
    if not description:
        return False
    return bool(
        _US_TEXT_SIGNAL_RE.search(description)
        or _US_STATE_NAME_RE.search(description)
        or _city_state_re(tuple(locations_config["us_states"])).search(description)
        or _USD_RANGE_RE.search(description)
    )


def has_non_us_keyword(text: str, locations_config: dict) -> bool:
    lowered = text.lower()
    return any(_has_word(lowered, kw) for kw in locations_config["non_us_keywords"])


def parse_location(
    raw: str | None, locations_config: dict, description: str | None = None, geo_config: dict | None = None
) -> tuple[bool, bool, bool]:
    """Returns (is_us, is_remote, is_nyc_metro) from a free-text location string (search.yaml > locations).

    A remote location with no country ("Remote") is not skipped outright when a description is
    given: it is kept only if the description shows a clear US signal and no non-US keyword.
    """
    text = (raw or "").strip().lower()
    raw_text = (raw or "").strip()

    is_remote = any(kw in text for kw in locations_config["remote_keywords"])
    is_nyc_metro = any(kw in text for kw in locations_config["nyc_metro"])
    if geo_config is not None:
        # Distance beats the substring list when the place can be located ("Rochester, New York" is
        # not NYC); the list is only the fallback for text the gazetteer cannot resolve.
        from pipeline import geo

        group, resolved = geo.metro_group(raw_text, geo_config)
        if resolved:
            is_nyc_metro = group == "nyc"

    if has_non_us_keyword(text, locations_config):
        is_us = False
    elif any(kw in text for kw in locations_config["us_keywords"]) or _is_state_abbreviation_in_location_context(
        raw_text, locations_config["us_states"]
    ):
        is_us = True
    elif is_remote and description:
        # Ambiguous remote: needs a US signal in the description and no non-US country anywhere.
        is_us = has_us_signal_in_description(description, locations_config) and not has_non_us_keyword(
            description, locations_config
        )
    else:
        # No location, or no clear US signal: skip, per search.yaml's unclear_remote_policy.
        is_us = False

    return is_us, is_remote, is_nyc_metro
