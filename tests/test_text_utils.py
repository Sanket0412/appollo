from pipeline.text_utils import (
    html_to_text,
    normalize_company,
    parse_location,
    title_matches,
)

TITLES_CONFIG = {
    "include": [r"\bdata scien(ce|tist)", r"\bmachine learning\b"],
    "exclude": [r"\bmanager\b", r"\bintern(ship)?\b"],
}

LOCATIONS_CONFIG = {
    "us_states": ["NY", "NJ", "CA"],
    "us_keywords": ["united states", "usa", "us-remote", "remote - us"],
    "non_us_keywords": ["london", "toronto", "india"],
    "remote_keywords": ["remote"],
    "nyc_metro": ["new york", "nyc", "jersey city"],
}


def test_matches_llc_variants():
    assert normalize_company("Google LLC") == normalize_company("GOOGLE, L.L.C.") == "google"


def test_strips_leading_the_and_ampersand():
    assert normalize_company("The Johnson & Johnson Company") == "johnson and johnson"


def test_strips_multiple_trailing_suffixes():
    assert normalize_company("Example Holdings Inc") == "example"
    assert normalize_company("Acme Corp") == "acme"
    assert normalize_company("Acme Corporation") == "acme"


def test_collapses_whitespace_and_punctuation():
    assert normalize_company("  Two   Sigma, Investments,  LP ") == "two sigma investments"


def test_idempotent_for_already_bare_names():
    assert normalize_company("openai") == "openai"


def test_html_to_text_preserves_paragraph_breaks():
    html = "<div><p>First paragraph.</p><p>Second paragraph.</p></div>"
    text = html_to_text(html)
    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert text.index("First paragraph.") < text.index("Second paragraph.")


def test_html_to_text_converts_br_to_newline():
    assert html_to_text("Line one<br>Line two") == "Line one\nLine two"


def test_html_to_text_empty_input():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_title_matches_requires_include_and_no_exclude():
    assert title_matches("Senior Data Scientist", TITLES_CONFIG) is True
    assert title_matches("Data Scientist Manager", TITLES_CONFIG) is False  # excluded
    assert title_matches("Backend Engineer", TITLES_CONFIG) is False  # no include match
    assert title_matches("", TITLES_CONFIG) is False


def test_parse_location_nyc_metro():
    is_us, is_remote, is_nyc = parse_location("New York, NY", LOCATIONS_CONFIG)
    assert (is_us, is_remote, is_nyc) == (True, False, True)


def test_parse_location_remote_us():
    is_us, is_remote, is_nyc = parse_location("Remote - US", LOCATIONS_CONFIG)
    assert (is_us, is_remote, is_nyc) == (True, True, False)


def test_parse_location_non_us():
    is_us, is_remote, is_nyc = parse_location("London, UK", LOCATIONS_CONFIG)
    assert (is_us, is_remote, is_nyc) == (False, False, False)


def test_parse_location_empty_defaults_to_us():
    is_us, is_remote, is_nyc = parse_location(None, LOCATIONS_CONFIG)
    assert (is_us, is_remote, is_nyc) == (True, False, False)


def test_parse_location_state_abbreviation():
    is_us, _, _ = parse_location("Jersey City, NJ", LOCATIONS_CONFIG)
    assert is_us is True
