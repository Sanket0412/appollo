import math
from datetime import datetime, timezone

import pytest

from pipeline.fetchers import jobspy_fetcher


def test_fetch_refuses_in_ci(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(RuntimeError):
        jobspy_fetcher.fetch(datetime.now(timezone.utc))


def test_row_prefers_direct_url_and_tags_source():
    raw = jobspy_fetcher.row_to_raw_job(
        {"id": "in-1", "site": "indeed", "title": "Data Scientist", "company": "Acme", "location": "New York, NY, US",
         "job_url": "https://indeed.com/x", "job_url_direct": "https://boards.greenhouse.io/acme/jobs/1",
         "date_posted": "2026-10-16", "is_remote": False, "description": "d"}
    )
    assert raw.source == "jobspy_indeed"
    assert raw.url == "https://boards.greenhouse.io/acme/jobs/1"
    assert raw.posted_at is not None and raw.posted_at.date().isoformat() == "2026-10-16"


def test_row_handles_nan_and_missing_fields():
    nan = math.nan
    assert jobspy_fetcher.row_to_raw_job({"site": "linkedin", "title": nan, "company": "A", "job_url": "u"}) is None
    raw = jobspy_fetcher.row_to_raw_job(
        {"id": nan, "site": "linkedin", "title": "ML Engineer", "company": "A", "job_url": "https://l/1",
         "job_url_direct": nan, "date_posted": nan, "is_remote": nan, "location": nan, "description": nan}
    )
    assert raw.url == "https://l/1" and raw.posted_at is None and raw.is_remote is False and raw.ats_job_id == "https://l/1"
