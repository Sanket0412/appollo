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


def test_parse_location_empty_is_not_us():
    is_us, is_remote, is_nyc = parse_location(None, LOCATIONS_CONFIG)
    assert (is_us, is_remote, is_nyc) == (False, False, False)


def test_parse_location_remote_without_country_is_not_us():
    is_us, is_remote, _ = parse_location("Remote", LOCATIONS_CONFIG)
    assert (is_us, is_remote) == (False, True)


def test_parse_location_state_abbreviation():
    is_us, _, _ = parse_location("Jersey City, NJ", LOCATIONS_CONFIG)
    assert is_us is True


# --- Remote with no country: kept only on a clear US signal in the description ---

def _remote(description):
    return parse_location("Remote", LOCATIONS_CONFIG, description)


def test_remote_kept_when_description_says_united_states():
    assert _remote("This role is open to candidates in the United States.") == (True, True, False)


def test_remote_kept_with_us_based_phrase():
    assert _remote("Must be US-based. You will build forecasting models.")[0] is True


def test_remote_kept_with_city_state_in_description():
    assert _remote("Our team sits in Brooklyn, NY and works remotely.")[0] is True


def test_remote_kept_with_state_name_in_description():
    assert _remote("Candidates must reside in California or Colorado.")[0] is True


def test_remote_kept_with_usd_salary_range():
    assert _remote("Pay range: $120,000 - $155,000 per year.")[0] is True
    assert _remote("Compensation $120k-$155k plus equity.")[0] is True


def test_remote_skipped_when_description_has_no_us_signal():
    assert _remote("Join a fast-growing team and build ML models.")[0] is False


def test_remote_skipped_when_us_signal_but_non_us_keyword_present():
    assert _remote("US-based preferred, but we also hire in London.")[0] is False


def test_remote_skipped_without_a_description():
    assert parse_location("Remote", LOCATIONS_CONFIG)[0] is False


def test_stray_uppercase_word_is_not_read_as_a_state():
    assert _remote("Experience with SQL, OR Python is required.")[0] is False


def test_non_us_keyword_needs_a_whole_word():
    assert parse_location("Indianapolis, NY", LOCATIONS_CONFIG)[0] is True


def test_word_in_is_not_read_as_state_indiana():
    assert parse_location("Remote - anywhere in the world", LOCATIONS_CONFIG)[0] is False
