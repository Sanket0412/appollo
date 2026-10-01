"""Offline location handling: resolve a job's location text to coordinates and measure straight-line
(great-circle) distance to the NYC and Washington D.C. hubs.

City coordinates come from the `geonamescache` package (GeoNames data, US cities with population of
15,000 or more), so there are no web lookups and no cost. Locations that cannot be resolved return None;
callers decide what that means. Settings live in search.yaml under `geo`.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

EARTH_RADIUS_MILES = 3958.8

# Names GeoNames does not list under the form job boards use.
_ALIASES = {
    "new york": ("new york city", "NY"),
    "nyc": ("new york city", "NY"),
    "manhattan": ("new york city", "NY"),
    "brooklyn": ("new york city", "NY"),
    "queens": ("new york city", "NY"),
    "bronx": ("new york city", "NY"),
    "the bronx": ("new york city", "NY"),
    "staten island": ("new york city", "NY"),
    "long island city": ("new york city", "NY"),
    "washington": ("washington", "DC"),
}

_COUNTRY_RE = re.compile(r"\b(united states of america|united states|u\.s\.a\.?|u\.s\.|usa)\b", re.IGNORECASE)
_DC_RE = re.compile(r"\bd\.?\s?c\.?(?=\W|$)|\bdistrict of columbia\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z.'’-]*")


@lru_cache(maxsize=1)
def _gazetteer() -> dict:
    import geonamescache

    gc = geonamescache.GeonamesCache()
    by_name_state: dict[tuple[str, str], tuple[float, float, int]] = {}
    by_name: dict[str, tuple[float, float, int]] = {}
    for c in gc.get_cities().values():
        if c["countrycode"] != "US":
            continue
        name = c["name"].lower()
        entry = (c["latitude"], c["longitude"], c["population"])
        key = (name, c["admin1code"])
        if key not in by_name_state or entry[2] > by_name_state[key][2]:
            by_name_state[key] = entry
        if name not in by_name or entry[2] > by_name[name][2]:
            by_name[name] = entry
    states = {code: s["name"].lower() for code, s in gc.get_us_states().items()}
    states.setdefault("DC", "district of columbia")
    state_by_name = {name: code for code, name in states.items()}
    return {"by_name_state": by_name_state, "by_name": by_name, "states": states, "state_by_name": state_by_name}


def _has_phrase(text: str, phrase: str) -> bool:
    """Whole-word phrase match without regex escapes: pad with spaces and compare."""
    return f" {phrase} " in f" {text} "


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def _ngrams(words: list[str]):
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i : i + n]).lower()


def resolve_segment(segment: str) -> tuple[float, float] | None:
    """Coordinates for one place ("Princeton - NJ - US", "Irving Texas United States", "Atlanta")."""
    g = _gazetteer()
    text = _DC_RE.sub(" DC ", _COUNTRY_RE.sub(" ", segment))
    words = _WORD_RE.findall(text)
    if not words:
        return None

    # State: an uppercase abbreviation as its own word ("AR"), or a full state name anywhere.
    state = next((w.rstrip(".") for w in words if w.rstrip(".") in g["states"] and w.rstrip(".").isupper()), None)
    name_words: list[str] = []
    if state is None:
        lowered = " ".join(w.lower() for w in words)
        for name in sorted(g["state_by_name"], key=len, reverse=True):
            if _has_phrase(lowered, name):
                state = g["state_by_name"][name]
                name_words = name.split()
                break

    # Drop the state tokens so "New York, NY" does not look for a city called "ny", and
    # "Rochester, New York" does not read the state name as the city.
    city_words = [w for w in words if w.rstrip(".").upper() != state] if state else words
    if name_words:
        stripped = [w for w in city_words if w.lower() not in name_words]
        city_words = stripped or city_words  # "New York, New York" keeps its words

    for gram in _ngrams(city_words):
        if gram in _ALIASES:
            name, st = _ALIASES[gram]
            if gram == "washington" and state not in (None, "DC"):
                continue
            entry = g["by_name_state"].get((name, st))
            if entry:
                return entry[0], entry[1]
        if state is not None:
            entry = g["by_name_state"].get((gram, state))
            if entry:
                return entry[0], entry[1]

    if state is None:
        # No state given ("Atlanta, United States of America"): accept only a clearly major city.
        for gram in _ngrams(city_words):
            entry = g["by_name"].get(gram)
            if entry and entry[2] >= 100_000:
                return entry[0], entry[1]
    return None


def resolve_location(location: str | None) -> list[tuple[float, float]]:
    """Coordinates for every resolvable place in a (possibly multi-location, ';'-separated) string."""
    if not location:
        return []
    coords = []
    for segment in location.split(";"):
        point = resolve_segment(segment)
        if point is not None:
            coords.append(point)
    return coords


def _hub(geo_cfg: dict, name: str) -> tuple[float, float]:
    h = geo_cfg["hubs"][name]
    return h["lat"], h["lon"]


def nearest_hub_miles(points: list[tuple[float, float]], geo_cfg: dict) -> float | None:
    """Smallest distance from any place to any of geo.score_hubs, or None when nothing resolved."""
    hubs = [_hub(geo_cfg, n) for n in geo_cfg["score_hubs"]]
    distances = [haversine_miles(p, h) for p in points for h in hubs]
    return min(distances) if distances else None


def distance_points(miles: float, geo_cfg: dict, max_points: int = 10) -> int:
    """max_points up to full_points_miles, falling linearly to 0 at zero_points_miles."""
    full, zero = geo_cfg["full_points_miles"], geo_cfg["zero_points_miles"]
    if miles <= full:
        return max_points
    if miles >= zero:
        return 0
    return round(max_points * (zero - miles) / (zero - full))


def location_points(location: str | None, is_remote: bool, geo_cfg: dict, max_points: int = 10) -> int:
    """The location part of the core fit (0-10), computed in code.

    Remote scores full points. Otherwise the score follows the distance from the nearest place in the
    posting to the nearer of NYC and Washington D.C.; an unresolvable location scores 0.
    """
    if is_remote:
        return max_points
    miles = nearest_hub_miles(resolve_location(location), geo_cfg)
    return 0 if miles is None else distance_points(miles, geo_cfg, max_points)


def metro_group(location: str | None, geo_cfg: dict) -> tuple[str | None, bool]:
    """(group, resolved). group is "nyc", "corridor" (near D.C. or Philadelphia) or None.

    resolved says whether any place in the string could be located, so callers can fall back to
    text rules only when the gazetteer had nothing to say.
    """
    points = resolve_location(location)
    if not points:
        return None, False
    nyc = _hub(geo_cfg, "nyc")
    if any(haversine_miles(p, nyc) <= geo_cfg["nyc_metro_miles"] for p in points):
        return "nyc", True
    corridor_hubs = [_hub(geo_cfg, n) for n in geo_cfg["corridor_hubs"]]
    if any(haversine_miles(p, h) <= geo_cfg["corridor_miles"] for p in points for h in corridor_hubs):
        return "corridor", True
    return None, True
