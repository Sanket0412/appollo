from pipeline.ats_discovery import AtsRef, looks_like_test_board, parse_ats_url


def test_parses_greenhouse_url():
    ref = parse_ats_url("https://boards.greenhouse.io/ramp/jobs/12345")
    assert ref == AtsRef(ats="greenhouse", slug="ramp")


def test_parses_greenhouse_newer_domain():
    ref = parse_ats_url("https://job-boards.greenhouse.io/anthropic/jobs/999")
    assert ref == AtsRef(ats="greenhouse", slug="anthropic")


def test_parses_lever_url():
    ref = parse_ats_url("https://jobs.lever.co/vercel/abc-123-def")
    assert ref == AtsRef(ats="lever", slug="vercel")


def test_parses_ashby_url():
    ref = parse_ats_url("https://jobs.ashbyhq.com/openai/posting-id")
    assert ref == AtsRef(ats="ashby", slug="openai")


def test_parses_workday_url():
    ref = parse_ats_url("https://intel.wd1.myworkdayjobs.com/External/job/Remote/ML-Engineer_R123")
    assert ref == AtsRef(ats="workday", host="intel.wd1.myworkdayjobs.com", tenant="intel", board="External")


def test_parses_workday_url_with_locale_prefix():
    ref = parse_ats_url("https://intel.wd1.myworkdayjobs.com/en-US/External/job/Remote/ML-Engineer_R123")
    assert ref == AtsRef(ats="workday", host="intel.wd1.myworkdayjobs.com", tenant="intel", board="External")


def test_unrecognized_host_returns_none():
    assert parse_ats_url("https://example.com/careers/123") is None
    assert parse_ats_url("https://www.linkedin.com/jobs/view/12345") is None


def test_malformed_url_returns_none():
    assert parse_ats_url("not a url") is None


def test_looks_like_test_board_flags_digit_titles():
    assert looks_like_test_board(["123123", "456456", "789789"]) is True


def test_looks_like_test_board_flags_bug_bash():
    assert looks_like_test_board(["Bug Bash Job [No Sensitive Questions] - 03/24"]) is True


def test_looks_like_test_board_accepts_real_titles():
    assert looks_like_test_board(["Android Engineer III", "Data Scientist", "Copywriter II"]) is False


def test_looks_like_test_board_empty_list_is_test():
    assert looks_like_test_board([]) is True


def test_looks_like_test_board_tolerates_a_minority_of_noise():
    # One odd title among many real ones shouldn't sink an otherwise-real board.
    titles = ["Data Scientist", "ML Engineer", "Backend Engineer", "test"]
    assert looks_like_test_board(titles) is False
