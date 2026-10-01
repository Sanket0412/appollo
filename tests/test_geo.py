import pytest

from pipeline import geo
from pipeline.text_utils import parse_location

GEO = {
    "hubs": {
        "nyc": {"lat": 40.7128, "lon": -74.0060},
        "dc": {"lat": 38.9072, "lon": -77.0369},
        "philadelphia": {"lat": 39.9526, "lon": -75.1652},
    },
    "score_hubs": ["nyc", "dc"],
    "full_points_miles": 25,
    "zero_points_miles": 250,
    "nyc_metro_miles": 50,
    "corridor_hubs": ["dc", "philadelphia"],
    "corridor_miles": 50,
}

LOCATIONS = {
    "us_states": ["NY", "NJ", "DC", "PA", "MD", "TX", "AR", "CA", "WA"],
    "us_keywords": ["united states"],
    "non_us_keywords": ["london"],
    "remote_keywords": ["remote"],
    "nyc_metro": ["new york", "newark"],
}


def miles(a, b):
    return geo.haversine_miles(a, b)


def test_haversine_known_distances():
    nyc, dc, philly = (40.7128, -74.0060), (38.9072, -77.0369), (39.9526, -75.1652)
    assert 200 <= miles(nyc, dc) <= 208
    assert 76 <= miles(nyc, philly) <= 85


@pytest.mark.parametrize("text", [
    "New York, NY",
    "Princeton - NJ - US",
    "Irving Texas United States, United States of America",
    "(USA) Change Building AR Bentonville Home Office",
    "Atlanta, United States of America",
    "Washington, DC",
    "Washington D.C.",
])
def test_messy_job_board_formats_resolve(text):
    assert geo.resolve_location(text), text


def test_unknown_and_empty_do_not_resolve():
    assert geo.resolve_location(None) == []
    assert geo.resolve_location("Remote") == []
    assert geo.resolve_location("Hobokenville") == []


def test_state_name_is_not_read_as_the_city():
    # "Rochester, New York" is upstate, not NYC; "Seattle, Washington" is not D.C.
    assert geo.metro_group("Rochester, New York", GEO) == (None, True)
    assert geo.metro_group("Seattle, Washington", GEO) == (None, True)
    assert geo.metro_group("New York, New York", GEO) == ("nyc", True)


def test_multi_location_uses_the_closest_place():
    loc = "Sunnyvale, CA; San Francisco, CA; Seattle, WA; New York, NY"
    assert geo.metro_group(loc, GEO) == ("nyc", True)
    assert geo.location_points(loc, False, GEO) == 10


def test_points_by_distance():
    assert geo.location_points("Jersey City, NJ", False, GEO) == 10
    assert geo.location_points("Bethesda, MD", False, GEO) == 10
    philly = geo.location_points("Philadelphia, PA", False, GEO)
    assert 7 <= philly <= 8
    assert geo.location_points("Boston, MA", False, GEO) == 3
    assert geo.location_points("Austin, TX", False, GEO) == 0


def test_nearest_hub_not_balanced():
    # Close to only one hub still scores full points; being near both is not required.
    assert geo.location_points("New York, NY", False, GEO) == geo.location_points("Washington, DC", False, GEO) == 10


def test_corridor_hubs_and_groups():
    assert geo.metro_group("Philadelphia, PA", GEO) == ("corridor", True)
    assert geo.metro_group("Baltimore, MD", GEO) == ("corridor", True)
    assert geo.metro_group("Princeton - NJ - US", GEO) == ("nyc", True)
    assert geo.metro_group("Austin, TX", GEO) == (None, True)
    assert geo.metro_group("Somewhere Unknown", GEO) == (None, False)


def test_remote_scores_full_and_unresolvable_scores_zero():
    assert geo.location_points("Remote", True, GEO) == 10
    assert geo.location_points("Somewhere Unknown", False, GEO) == 0
    assert geo.location_points(None, False, GEO) == 0


def test_distance_points_edges():
    assert geo.distance_points(25, GEO) == 10
    assert geo.distance_points(250, GEO) == 0
    assert geo.distance_points(137.5, GEO) == 5


def test_parse_location_prefers_distance_over_the_substring_list():
    # "new york" is in the text list, but Rochester is upstate.
    assert parse_location("Rochester, New York", LOCATIONS, geo_config=GEO)[2] is False
    assert parse_location("Rochester, New York", LOCATIONS)[2] is True  # list-only fallback
    assert parse_location("Newark, DE", LOCATIONS, geo_config=GEO)[2] is False
    assert parse_location("Newark, NJ", LOCATIONS, geo_config=GEO)[2] is True
