import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.fetchers import ashby, greenhouse, lever, workday
from pipeline.models import CompanyConfig

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    with (FIXTURES / name).open("r", encoding="utf-8") as f:
        return json.load(f)


LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_greenhouse_filters_titles_and_maps_fields(monkeypatch):
    fixture = load_fixture("greenhouse_sample.json")
    monkeypatch.setattr(greenhouse, "get_json", lambda url: fixture)

    company = CompanyConfig(name="DoorDash", ats="greenhouse", slug="doordashusa")
    jobs = greenhouse.fetch(company, since=LONG_AGO)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Data Scientist, Machine Learning"
    assert job.source == "greenhouse"
    assert job.company == "DoorDash"
    assert job.posted_at is not None
    assert job.description_text  # html_to_text produced something non-empty
    assert "<" not in job.description_text  # actually converted, not raw HTML


def test_greenhouse_respects_since_window(monkeypatch):
    fixture = load_fixture("greenhouse_sample.json")
    monkeypatch.setattr(greenhouse, "get_json", lambda url: fixture)

    company = CompanyConfig(name="DoorDash", ats="greenhouse", slug="doordashusa")
    future = datetime.now(timezone.utc) + timedelta(days=365)
    jobs = greenhouse.fetch(company, since=future)

    assert jobs == []


def test_lever_filters_titles_and_maps_fields(monkeypatch):
    fixture = load_fixture("lever_sample.json")
    monkeypatch.setattr(lever, "get_json", lambda url: fixture)

    company = CompanyConfig(name="Palantir Technologies", ats="lever", slug="palantir")
    jobs = lever.fetch(company, since=LONG_AGO)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Data Scientist, Machine Learning"
    assert job.source == "lever"
    assert job.is_remote is False  # fixture workplaceType is "hybrid"
    assert job.url.startswith("https://jobs.lever.co/")


def test_ashby_skips_unlisted_and_filters_titles(monkeypatch):
    fixture = load_fixture("ashby_sample.json")
    monkeypatch.setattr(ashby, "get_json", lambda url: fixture)

    company = CompanyConfig(name="Smarkets", ats="ashby", slug="smarkets")
    jobs = ashby.fetch(company, since=LONG_AGO)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Data Scientist, Machine Learning"
    assert job.source == "ashby"
    assert job.is_remote is True


def test_workday_paginates_dedupes_and_fetches_detail_only_for_matches(monkeypatch):
    list_fixture = load_fixture("workday_list_sample.json")
    detail_fixture = load_fixture("workday_detail_sample.json")

    detail_calls = []

    def fake_post_json(url, body):
        return list_fixture

    def fake_get_json(url):
        detail_calls.append(url)
        return detail_fixture

    monkeypatch.setattr(workday, "post_json", fake_post_json)
    monkeypatch.setattr(workday, "get_json", fake_get_json)

    company = CompanyConfig(
        name="Barclays",
        ats="workday",
        host="barclays.wd3.myworkdayjobs.com",
        tenant="barclays",
        board="External_Career_Site_Barclays",
    )
    jobs = workday.fetch(company, since=LONG_AGO)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Senior Data Scientist, Machine Learning"
    assert job.source == "workday"
    assert job.description_text  # converted from jobDescription HTML
    # Detail is fetched exactly once, even though the same posting appears under every search term.
    assert len(detail_calls) == 1


def test_workday_respects_since_window(monkeypatch):
    list_fixture = load_fixture("workday_list_sample.json")
    detail_fixture = load_fixture("workday_detail_sample.json")

    monkeypatch.setattr(workday, "post_json", lambda url, body: list_fixture)
    monkeypatch.setattr(workday, "get_json", lambda url: detail_fixture)

    company = CompanyConfig(
        name="Barclays",
        ats="workday",
        host="barclays.wd3.myworkdayjobs.com",
        tenant="barclays",
        board="External_Career_Site_Barclays",
    )
    # "Posted Today" in the fixture is younger than 2 days ago, so a since of 2 days back keeps it;
    # pushing since a year into the future should drop it.
    future = datetime.now(timezone.utc) + timedelta(days=365)
    jobs = workday.fetch(company, since=future)

    assert jobs == []


def test_workday_location_falls_back_to_detail_and_appends_country():
    detail = {"location": "Pune, PDC2C", "country": {"descriptor": "India"}}
    assert workday._resolve_location(None, detail) == "Pune, PDC2C, India"
    assert workday._resolve_location("2 Locations", detail) == "Pune, PDC2C, India"


def test_workday_location_keeps_list_text_when_country_already_in_it():
    detail = {"location": "x", "country": {"descriptor": "United States of America"}}
    assert workday._resolve_location("New York, United States of America", detail) == "New York, United States of America"


def test_workday_location_none_when_nothing_known():
    assert workday._resolve_location(None, {}) is None
