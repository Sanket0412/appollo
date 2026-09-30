from pipeline.text_utils import normalize_company


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
