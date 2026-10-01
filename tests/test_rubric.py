from datetime import datetime, timedelta, timezone

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
    "required_skills": ["python", "sql", "pytorch", "airflow"], "matched_skills": ["python", "sql", "pytorch"],
    "experience_fit": 15, "domain_fit": 10,
    "total": 99, "skills_match": 99, "one_line_summary": "Builds ranking models in Python.", "red_flags": [],
}


def test_skills_score_is_computed_from_the_lists_not_the_models_number():
    r = ScoreResult(**GOOD)
    assert r.skills_match == 30  # round(40 * 3 / 4); the model's "99" is ignored
    assert r.total == 55  # 30 + 15 + 10


def test_no_required_skills_scores_zero_skills():
    r = ScoreResult(**{**GOOD, "required_skills": [], "matched_skills": []})
    assert r.skills_match == 0


def test_all_matched_gives_full_skills_points():
    r = ScoreResult(**{**GOOD, "matched_skills": ["python", "sql", "pytorch", "airflow"]})
    assert r.skills_match == 40


def test_matched_must_be_a_subset_of_required():
    with pytest.raises(ValidationError):
        ScoreResult(**{**GOOD, "matched_skills": ["python", "rust"]})


def test_subset_check_ignores_case_and_spacing_and_duplicates():
    r = ScoreResult(**{**GOOD, "required_skills": ["Python", "SQL"], "matched_skills": [" python ", "PYTHON", "sql"]})
    assert r.skills_match == 40


def test_more_than_twelve_required_skills_rejected():
    many = [f"skill{i}" for i in range(13)]
    with pytest.raises(ValidationError):
        ScoreResult(**{**GOOD, "required_skills": many, "matched_skills": []})


def test_experience_fit_capped_at_ten_when_five_years_required():
    assert ScoreResult(**{**GOOD, "years_required_min": 5, "experience_fit": 20}).experience_fit == 10
    assert ScoreResult(**{**GOOD, "years_required_min": 4, "experience_fit": 20}).experience_fit == 20
    assert ScoreResult(**{**GOOD, "years_required_min": 5, "experience_fit": 6}).experience_fit == 6
    assert ScoreResult(**{**GOOD, "years_required_min": None, "experience_fit": 20}).experience_fit == 20


def test_null_years_allowed():
    assert ScoreResult(**{**GOOD, "years_required_min": None}).years_required_min is None


@pytest.mark.parametrize("field,value", [
    ("experience_fit", 21), ("domain_fit", 16), ("experience_fit", -1),
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
    assert schema["properties"]["experience_fit"]["description"] == "Integer from 0 to 20."
    # the spec schema itself is untouched
    assert rubric.SCHEMA["properties"]["experience_fit"]["maximum"] == 20


def test_skills_match_is_not_asked_of_the_model():
    assert "skills_match" not in rubric.SCHEMA["properties"]
    assert {"required_skills", "matched_skills"} <= set(rubric.SCHEMA["required"])


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


def test_seniority_fit_and_location_fit_are_gone_from_the_schema():
    assert "seniority_fit" not in rubric.SCHEMA["properties"]
    assert "location_fit" not in rubric.SCHEMA["properties"]
    assert "total" not in rubric.SCHEMA["required"]


NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def test_recency_full_points_when_just_posted():
    assert rubric.recency_points(NOW, NOW, 15, 14) == 15


def test_recency_decays_linearly_to_zero_at_the_cap():
    assert rubric.recency_points(NOW - timedelta(days=7), NOW, 15, 14) == 8
    assert rubric.recency_points(NOW - timedelta(days=14), NOW, 15, 14) == 0
    assert rubric.recency_points(NOW - timedelta(days=30), NOW, 15, 14) == 0


def test_recency_zero_when_date_unknown_and_never_negative_age():
    assert rubric.recency_points(None, NOW, 15, 14) == 0
    assert rubric.recency_points(NOW + timedelta(hours=3), NOW, 15, 14) == 15
