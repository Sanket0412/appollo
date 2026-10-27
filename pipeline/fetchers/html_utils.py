"""Small helpers shared by the HTML and sitemap fetchers (Uber, iCIMS, Avature, SuccessFactors)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def sitemap_urls(xml: str) -> list[tuple[str, str | None]]:
    """(loc, lastmod) pairs from a sitemap."""
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, flags=re.DOTALL):
        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block)
        mod = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block)
        if loc:
            out.append((loc.group(1), mod.group(1) if mod else None))
    return out


def jsonld_job(html: str) -> dict | None:
    """The schema.org JobPosting object from a page's JSON-LD, if any."""
    for tag in soup(html).find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def ld_location(posting: dict) -> str | None:
    places = posting.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    parts = []
    for place in places:
        addr = place.get("address") or {}
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        text = ", ".join(p for p in (addr.get("addressLocality"), addr.get("addressRegion"), country) if p)
        if text:
            parts.append(text)
    return "; ".join(parts) or None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def slug_title(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip()
