"""Seeds config/companies.yaml from HN "Ask HN: Who is hiring?" threads.

Usage: python scripts/seed_from_hn.py [--months N] [--dry-run]
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.ats_discovery import AtsRef, parse_ats_url, validate_board
from pipeline.log import get_logger
from pipeline.settings import get_settings
from pipeline.text_utils import normalize_company

COMPANIES_PATH = REPO_ROOT / "config" / "companies.yaml"

# Verified live 2026-09-29: search_by_date finds threads by author, items/{id} returns the full
# comment tree (with HTML text) in one call.
ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ALGOLIA_ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"

MIN_REQUEST_INTERVAL = 1.0
REQUEST_TIMEOUT = 15

HREF_RE = re.compile(r'href="([^"]+)"')
_TRAILING_URL_RE = re.compile(r"\s*\(\s*https?://\S+?\s*\)\s*$")

# Posters don't all use "Company | Title | Location" order; reject a first field that is clearly a
# location/work-mode token rather than a company name, so guess_company_name falls back to the slug.
_NOT_A_COMPANY_NAME_RE = re.compile(
    r"^(remote|hybrid|onsite|on-site|nyc|ny|nj|sf|bay area|usa?|us only|us-remote)\b", re.IGNORECASE
)

log = get_logger("seed_from_hn")

_last_request_time = 0.0


def _pace() -> None:
    """Shared 1-request/second clock for every outbound call this script makes, Algolia included."""
    global _last_request_time
    wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_time)
    if wait > 0:
        time.sleep(wait)
    _last_request_time = time.monotonic()


def _rate_limited_get(url: str, **kwargs) -> requests.Response | None:
    _pace()
    try:
        return requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        log.debug("Request failed for %s: %s", url, exc)
        return None


def _rate_limited_validate(ref: AtsRef) -> bool:
    _pace()
    return validate_board(ref)


def find_recent_threads(months: int) -> list[dict]:
    resp = _rate_limited_get(
        ALGOLIA_SEARCH_URL,
        params={"tags": "story,author_whoishiring", "query": "Who is hiring", "hitsPerPage": 50},
    )
    if resp is None or resp.status_code != 200:
        raise RuntimeError("HN Algolia search_by_date request failed")

    hits = [h for h in resp.json().get("hits", []) if h["title"].startswith("Ask HN: Who is hiring?")]
    hits.sort(key=lambda h: h["created_at"], reverse=True)
    return hits[:months]


def fetch_top_level_comments(story_id: str) -> list[dict]:
    resp = _rate_limited_get(ALGOLIA_ITEM_URL.format(id=story_id))
    if resp is None or resp.status_code != 200:
        log.warning("Could not fetch thread %s", story_id)
        return []
    return resp.json().get("children") or []


def extract_urls(comment_text: str) -> list[str]:
    if not comment_text:
        return []
    return HREF_RE.findall(html.unescape(comment_text))


def guess_company_name(comment_text: str, fallback: str) -> str:
    """"Who is hiring" convention is 'Company | Title | Location | ...'; fall back to the board slug."""
    if comment_text:
        plain = html.unescape(re.sub(r"<[^>]+>", " ", comment_text))
        first_line = plain.strip().splitlines()[0] if plain.strip() else ""
        name = first_line.split("|")[0].strip(" -–—")
        name = _TRAILING_URL_RE.sub("", name).strip()
        if 0 < len(name) <= 60 and not _NOT_A_COMPANY_NAME_RE.match(name):
            return name
    return fallback


def load_existing_companies() -> list[dict]:
    if not COMPANIES_PATH.exists() or COMPANIES_PATH.stat().st_size == 0:
        return []
    with COMPANIES_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def ref_key(ref: AtsRef) -> tuple:
    if ref.ats == "workday":
        return (ref.ats, ref.host, ref.tenant, ref.board)
    return (ref.ats, ref.slug)


def existing_ref_keys(companies: list[dict]) -> set[tuple]:
    keys = set()
    for c in companies:
        if c.get("ats") == "workday":
            keys.add((c["ats"], c.get("host"), c.get("tenant"), c.get("board")))
        else:
            keys.add((c.get("ats"), c.get("slug")))
    return keys


def to_entry(name: str, ref: AtsRef, source: str) -> dict:
    if ref.ats == "workday":
        return {
            "name": name,
            "ats": "workday",
            "host": ref.host,
            "tenant": ref.tenant,
            "board": ref.board,
            "source": source,
        }
    return {"name": name, "ats": ref.ats, "slug": ref.slug, "source": source}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=1, help="how many recent 'who is hiring' threads to scan")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    blocklist = {normalize_company(n) for n in settings.search_config["staffing"]["company_blocklist"]}

    existing = load_existing_companies()
    seen_keys = existing_ref_keys(existing)
    seen_names = {normalize_company(c["name"]) for c in existing}

    threads = find_recent_threads(args.months)
    log.info("Found %d thread(s): %s", len(threads), [t["title"] for t in threads])

    added: list[dict] = []
    no_ats_link = 0
    already_present = 0

    for thread in threads:
        comments = fetch_top_level_comments(thread["objectID"])
        log.info("%s: %d top-level comment(s)", thread["title"], len(comments))

        for comment in comments:
            text = comment.get("text") or ""

            ref = None
            for url in extract_urls(text):
                candidate = parse_ats_url(url)
                if candidate is not None:
                    ref = candidate
                    break

            if ref is None:
                no_ats_link += 1
                continue

            key = ref_key(ref)
            if key in seen_keys:
                already_present += 1
                continue

            name = guess_company_name(text, fallback=ref.slug or ref.board or "unknown")
            name_norm = normalize_company(name)
            if name_norm in blocklist or name_norm in seen_names:
                if name_norm in seen_names:
                    already_present += 1
                continue

            if not _rate_limited_validate(ref):
                continue

            seen_keys.add(key)
            seen_names.add(name_norm)
            added.append(to_entry(name, ref, source="hn"))
            log.info("HN hit: %s -> %s (%s)", name, ref.slug or ref.board, ref.ats)

    print(f"\nAdded: {len(added)}")
    print(f"No ATS link: {no_ats_link}")
    print(f"Already present: {already_present}")

    if args.dry_run:
        log.info("Dry run, not writing companies.yaml")
        return

    merged = existing + added
    with COMPANIES_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, sort_keys=False)
    log.info("Wrote %d compan(ies) to %s (%d new from hn)", len(merged), COMPANIES_PATH, len(added))


if __name__ == "__main__":
    main()
