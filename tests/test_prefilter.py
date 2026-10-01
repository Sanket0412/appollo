from datetime import datetime, timedelta, timezone

from pipeline.filters.prefilter import AppliedHistory, evaluate
from pipeline.models import Job

TITLES_CONFIG = {
    "include": [r"\bdata scien(ce|tist)", r"\bmachine learning\b"],
    "exclude": [r"\bmanager\b", r"\bintern(ship)?\b"],
}

STAFFING_CONFIG = {
    "company_blocklist": ["robert half", "teksystems", "insight global"],
    "description_patterns": [
        r"on behalf of (our|a) client",
        r"our client (is|has)",
        r"\bw-?2 (only|contract)\b",
        r"\bc2c\b|corp[- ]to[- ]corp",
        r"\bstaffing (agency|firm|partner)\b",
    ],
}

# Mirrors config/search.yaml's red_flags list. Kept as a literal fixture (not loaded from the real
# config) so this test stays fully offline per the project's test convention.
RED_FLAGS = [
    r"must be (a )?u\.?s\.? citizen",
    r"u\.?s\.? citizen(ship)? (is )?required",
    r"citizenship is required",
    r"(active|current|ability to obtain)\s+(a\s+)?(secret|top secret|ts/sci|public trust)",
    r"security clearance (is )?required",
    r"(will|can|do) not (provide |offer )?sponsor",
    r"unable to (provide |offer )?sponsor",
    r"not (able|eligible) to sponsor",
    r"no (visa |h-?1b )?sponsorship",
    r"sponsorship (is )?not (available|provided|offered)",
    r"without (the need for )?(current or future )?(visa )?sponsorship",
    r"(green card|gc) holders? only",
    r"\busc(/gc)? only\b",
]

RED_FLAG_TRUE_POSITIVES = [
    "Applicants must be a US citizen to apply.",
    "US citizenship required for this role.",
    "Note: citizenship is required due to government contracts.",
    "Must have an active Top Secret clearance.",
    "A security clearance is required.",
    "We will not sponsor employment visas for this position.",
    "We are unable to sponsor work visas at this time.",
    "Candidates are not eligible to sponsor visa applications.",
    "No visa sponsorship is available for this role.",
    "Sponsorship is not available for this position.",
    "This role is offered without the need for current or future visa sponsorship.",
    "Green card holders only need apply.",
    "USC/GC only for this position.",
]

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=7)


def make_job(**overrides) -> Job:
    defaults = {
        "id": "job-1",
        "source": "greenhouse",
        "company": "Acme Inc",
        "company_norm": "acme",
        "title": "Senior Data Scientist",
        "location": "New York, NY",
        "is_us": True,
        "url": "https://example.com/job/1",
        "posted_at": NOW - timedelta(days=1),
        "description": "We are happy to sponsor visas for qualified candidates.",
    }
    defaults.update(overrides)
    return Job(**defaults)


def evaluate_job(job: Job, *, is_jobspy: bool = False, applied_history: AppliedHistory | None = None):
    return evaluate(
        job,
        since=SINCE,
        is_jobspy=is_jobspy,
        titles_config=TITLES_CONFIG,
        staffing_config=STAFFING_CONFIG,
        red_flags=RED_FLAGS,
        applied_history=applied_history or AppliedHistory.empty(),
    )


def test_keeps_a_clean_matching_job():
    keep, reason = evaluate_job(make_job())
    assert (keep, reason) == (True, None)


def test_excludes_title_with_no_include_match():
    keep, reason = evaluate_job(make_job(title="Backend Engineer"))
    assert (keep, reason) == (False, "title_no_match")


def test_excludes_title_matching_exclude_pattern():
    keep, reason = evaluate_job(make_job(title="Data Scientist Manager"))
    assert (keep, reason) == (False, "title_excluded")


def test_excludes_non_us_location():
    keep, reason = evaluate_job(make_job(is_us=False))
    assert (keep, reason) == (False, "not_us")


def test_excludes_stale_posting():
    keep, reason = evaluate_job(make_job(posted_at=SINCE - timedelta(days=1)))
    assert (keep, reason) == (False, "stale")


def test_ats_job_with_missing_posted_at_is_excluded():
    keep, reason = evaluate_job(make_job(posted_at=None), is_jobspy=False)
    assert (keep, reason) == (False, "no_posted_at")


def test_jobspy_job_with_missing_posted_at_is_excluded():
    keep, reason = evaluate_job(make_job(posted_at=None), is_jobspy=True)
    assert (keep, reason) == (False, "no_posted_at")


def test_excludes_staffing_company_blocklist():
    keep, reason = evaluate_job(make_job(company_norm="robert half"))
    assert (keep, reason) == (False, "staffing_company")


def test_excludes_staffing_description_pattern():
    keep, reason = evaluate_job(make_job(description="This role is on behalf of a client in finance."))
    assert (keep, reason) == (False, "staffing_description")


def test_the_classic_false_positive_is_not_excluded():
    # "happy to sponsor" must never trip the red-flag or staffing checks.
    keep, reason = evaluate_job(make_job(description="We are happy to sponsor visas for this role."))
    assert (keep, reason) == (True, None)


def test_every_red_flag_pattern_has_a_true_positive():
    assert len(RED_FLAG_TRUE_POSITIVES) == len(RED_FLAGS)
    for text in RED_FLAG_TRUE_POSITIVES:
        keep, reason = evaluate_job(make_job(description=text))
        assert (keep, reason) == (False, "red_flag_description"), f"expected exclusion for: {text!r}"


def test_already_applied_exact_match_excluded():
    history = AppliedHistory([("acme", "senior data scientist")])
    keep, reason = evaluate_job(make_job(), applied_history=history)
    assert (keep, reason) == (False, "already_applied")


def test_already_applied_fuzzy_match_excluded():
    # Missing the trailing "II" should still fuzzy-match at the >=90 threshold.
    history = AppliedHistory([("acme", "senior data scientist ii")])
    keep, reason = evaluate_job(make_job(title="Senior Data Scientist"), applied_history=history)
    assert (keep, reason) == (False, "already_applied")


def test_applied_history_at_a_different_company_does_not_exclude():
    history = AppliedHistory([("other-co", "senior data scientist")])
    keep, reason = evaluate_job(make_job(), applied_history=history)
    assert (keep, reason) == (True, None)


def test_check_order_title_wins_before_staffing_or_red_flags():
    # A job with a bad title AND a blocklisted company should report the title failure, since
    # title checks run first.
    keep, reason = evaluate_job(make_job(title="Backend Engineer", company_norm="robert half"))
    assert (keep, reason) == (False, "title_no_match")
