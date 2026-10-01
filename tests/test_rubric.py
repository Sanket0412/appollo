import pytest
from pydantic import ValidationError

from pipeline.score import rubric
from pipeline.score.rubric import (
    ScoreResult,
    api_schema,
    evidence_is_verbatim,
    parse_result,
)

GOOD = {
    "years_required_min": 3, "years_required_text": "3+ years", "seniority": "mid",
    "sponsorship_jd": "Not Mentioned", "sponsorship_evidence": "",
    "skills_match": 30, "experience_fit": 15, "domain_fit": 10, "seniority_fit": 10, "location_fit": 5,
    "total": 99, "one_line_summary": "Builds ranking models in Python.", "red_flags": [],
}


def test_total_is_recomputed_from_parts():
    assert ScoreResult(**GOOD).total == 70


def test_null_years_allowed():
    assert ScoreResult(**{**GOOD, "years_required_min": None}).years_required_min is None


@pytest.mark.parametrize("field,value", [
    ("skills_match", 41), ("experience_fit", 21), ("domain_fit", 16), ("seniority_fit", 16),
    ("location_fit", 11), ("skills_match", -1),
])
def test_part_ranges_enforced(field, value):
    with pytest.raises(ValidationError):
        ScoreResult(**{**GOOD, field: value})


def test_bad_enum_rejected():
    with pytest.raises(ValidationError):
        ScoreResult(**{**GOOD, "sponsorship_jd": "Maybe"})


def test_parse_result_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_result("not json")


def test_api_schema_has_no_integer_bounds_but_keeps_ranges_in_descriptions():
    schema = api_schema()
    assert all("minimum" not in p and "maximum" not in p for p in schema["properties"].values())
    assert schema["properties"]["skills_match"]["description"] == "Integer from 0 to 40."
    # the spec schema itself is untouched
    assert rubric.SCHEMA["properties"]["skills_match"]["maximum"] == 40


def test_evidence_verbatim_ignores_whitespace_and_case():
    desc = "We offer  visa\nsponsorship for qualified candidates."
    assert evidence_is_verbatim("visa sponsorship for qualified candidates", desc)
    assert evidence_is_verbatim("", desc)


def test_evidence_not_in_description_is_flagged():
    assert not evidence_is_verbatim("we will sponsor H-1B", "Competitive salary and benefits.")


def test_build_system_survives_braces_in_resume():
    assert "{x}" in rubric.build_system("skills: {x}")


def test_build_user_truncates_description():
    text = rubric.build_user("Acme", "DS", None, "x" * 20000)
    assert text.count("x") == 12000
