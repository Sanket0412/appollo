from pipeline.filters.dedup import canonical_id, location_norm, should_overwrite


def test_canonical_id_is_stable_for_identical_inputs():
    a = canonical_id("acme", "Data Scientist", "New York, NY")
    b = canonical_id("acme", "Data Scientist", "New York, NY")
    assert a == b


def test_canonical_id_ignores_title_formatting_differences():
    a = canonical_id("acme", "Data Scientist", "New York, NY")
    b = canonical_id("acme", "Data Scientist - Remote (Req-104822)", "New York, NY")
    assert a == b


def test_canonical_id_differs_for_different_company_title_or_location():
    base = canonical_id("acme", "Data Scientist", "New York, NY")
    assert canonical_id("other-co", "Data Scientist", "New York, NY") != base
    assert canonical_id("acme", "Machine Learning Engineer", "New York, NY") != base
    assert canonical_id("acme", "Data Scientist", "Jersey City, NJ") != base


def test_location_norm_collapses_punctuation_and_case():
    assert location_norm("New York, NY") == location_norm("NEW YORK NY") == "new york ny"


def test_location_norm_handles_none():
    assert location_norm(None) == ""


def test_ats_overwrites_jobspy():
    assert should_overwrite(existing_source="jobspy_indeed", new_source="greenhouse") is True


def test_jobspy_never_overwrites_ats():
    assert should_overwrite(existing_source="greenhouse", new_source="jobspy_indeed") is False


def test_same_priority_does_not_overwrite():
    assert should_overwrite(existing_source="greenhouse", new_source="lever") is False
    assert should_overwrite(existing_source="jobspy_indeed", new_source="jobspy_linkedin") is False
