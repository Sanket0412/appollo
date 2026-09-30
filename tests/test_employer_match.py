from pipeline.sponsorship.employer_match import EmployerMatcher

EMPLOYERS = {
    "google": {"employer_raw": "Google LLC", "filings_total": 100, "filings_relevant_soc": 80, "ny_nj_filings": 20},
    "amazon com services": {
        "employer_raw": "Amazon.com Services LLC",
        "filings_total": 50,
        "filings_relevant_soc": 30,
        "ny_nj_filings": 5,
    },
    "amazon web services": {
        "employer_raw": "Amazon Web Services, Inc.",
        "filings_total": 20,
        "filings_relevant_soc": 15,
        "ny_nj_filings": 3,
    },
    "two sigma investments": {
        "employer_raw": "Two Sigma Investments, LP",
        "filings_total": 10,
        "filings_relevant_soc": 8,
        "ny_nj_filings": 10,
    },
}

ALIASES = {
    "amazon": ["amazon com services", "amazon web services"],
    "meta": ["meta platforms"],  # deliberately missing from EMPLOYERS, to test the "no row" case
}


def make_matcher() -> EmployerMatcher:
    return EmployerMatcher(EMPLOYERS, ALIASES, fuzzy_score_cutoff=90)


def test_exact_match():
    result = make_matcher().match("Google LLC")
    assert result is not None
    assert result.source == "exact"
    assert result.filings_relevant_soc == 80


def test_alias_sums_multiple_entities():
    result = make_matcher().match("Amazon")
    assert result is not None
    assert result.source == "alias"
    assert result.filings_total == 70
    assert result.filings_relevant_soc == 45
    assert result.ny_nj_filings == 8
    assert set(result.entities) == {"Amazon.com Services LLC", "Amazon Web Services, Inc."}


def test_alias_with_no_matching_employer_falls_through():
    # "meta" aliases to "meta platforms", which has no lca_employers row and is not a fuzzy hit either.
    assert make_matcher().match("Meta") is None


def test_fuzzy_hit():
    result = make_matcher().match("Two Sigma Investment LP")  # missing the trailing "s" on "Investments"
    assert result is not None
    assert result.source == "fuzzy"
    assert result.matched_name == "Two Sigma Investments, LP"
    assert result.match_score >= 90


def test_fuzzy_miss_returns_none():
    assert make_matcher().match("Some Totally Unrelated Startup Inc") is None


def test_results_are_cached_per_run():
    matcher = make_matcher()
    first = matcher.match("Google LLC")
    second = matcher.match("Google LLC")
    assert first is second
