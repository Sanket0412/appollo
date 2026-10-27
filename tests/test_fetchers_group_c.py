from datetime import datetime, timezone
from pathlib import Path

from pipeline.fetchers import avature, icims, successfactors, uber
from pipeline.fetchers.html_utils import jsonld_job, ld_location, sitemap_urls
from pipeline.models import CompanyConfig

FIXTURES = Path(__file__).parent / "fixtures"
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="ignore")


def test_sitemap_urls_and_jsonld():
    urls = sitemap_urls(load("uber_sitemap_sample.xml"))
    assert urls[0] == ("https://jobs.uber.com/en/jobs/149574/", "2026-10-20T10:14:24.345Z")
    posting = jsonld_job(load("uber_job_sample.html"))
    assert posting["datePosted"] == "2026-06-19"
    assert ld_location(posting)


def test_uber_skips_pages_with_old_lastmod_and_dates_from_jsonld(monkeypatch):
    fetched = []
    job_page = load("uber_job_sample.html").replace("Sr Staff Engineer, Backend - Core Services", "Senior Machine Learning Engineer")

    def fake(url):
        fetched.append(url)
        return load("uber_sitemap_sample.xml") if url.endswith("sitemap.xml") else job_page

    monkeypatch.setattr(uber, "get_text", fake)
    jobs = uber.fetch(CompanyConfig(name="Uber", ats="uber"), datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert jobs == []  # datePosted 2026-06-19 is older than the window, so it is dropped
    assert all("100001" not in u for u in fetched)  # old lastmod never fetched

    jobs = uber.fetch(CompanyConfig(name="Uber", ats="uber"), LONG_AGO)
    assert [j.ats_job_id for j in jobs] == ["149574", "100001"]
    assert jobs[0].source == "uber"
    assert jobs[0].posted_at == datetime(2026, 6, 19, tzinfo=timezone.utc)


def test_icims_parse_list_reads_rows_dates_and_pages():
    rows, pages = icims.parse_list(load("icims_list_sample.html"))
    assert pages == 8
    first = rows[0]
    assert first["id"] == "16338"
    assert first["title"] == "Career Education Administrator"
    assert first["posted"] == datetime(2026, 10, 21, 17, 50, tzinfo=timezone.utc)
    assert first["location"] == "US-NY-New York"


def test_icims_fetch_uses_session_job_page_for_date(monkeypatch):
    lst = load("icims_list_sample.html").replace("Career Education Administrator", "Data Scientist")
    job = load("icims_job_sample.html").replace("Career Education Administrator", "Data Scientist")
    monkeypatch.setattr(icims, "get_text", lambda url: job if "/job?" in url else lst)
    company = CompanyConfig(name="New York University", ats="icims", host="uscareers-nyu.icims.com")
    jobs = icims.fetch(company, LONG_AGO)
    assert len(jobs) == 1
    assert jobs[0].ats_job_id == "16338"
    assert jobs[0].posted_at == datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)
    assert "?" not in jobs[0].url
    assert jobs[0].description_text


def test_avature_parse_list_dedups_and_skips_buttons():
    rows = avature.parse_list(load("avature_list_sample.html"))
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) and rows
    assert all(r["title"].lower() not in avature.SKIP_LABELS for r in rows)


def test_avature_parse_detail_reads_location_and_full_description():
    location, html = avature.parse_detail(load("avature_job_sample.html"))
    assert location == "London"
    assert "Net-Zero Data Public Utility" in html


def test_avature_fetch_is_undated(monkeypatch):
    lst = load("avature_list_sample.html").replace("Climate Data Utility Tech Team - Senior Data Engineer", "Senior Data Scientist")
    monkeypatch.setattr(avature, "get_text", lambda url: load("avature_job_sample.html") if "JobDetail" in url else lst)
    company = CompanyConfig(name="Bloomberg", ats="avature", host="bloomberg.avature.net", site="careers")
    jobs = avature.fetch(company, LONG_AGO)
    assert jobs and all(j.undated and j.posted_at is None for j in jobs)
    assert jobs[0].source == "avature"


def test_successfactors_parse_list_and_detail_date():
    rows = successfactors.parse_list(load("successfactors_list_sample.html"))
    assert len(rows) == len({r["id"] for r in rows}) and rows[0]["id"] == "1442870100"
    detail = successfactors.parse_detail(load("successfactors_job_sample.html"))
    assert detail["posted"] == datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert detail["location"] == "New York, NY, US"
    assert detail["html"]


def test_successfactors_fetch(monkeypatch):
    lst = load("successfactors_list_sample.html").replace("HR Data Governance and Privacy Lead (12-24 Month Project)", "Data Scientist")
    monkeypatch.setattr(successfactors, "get_text", lambda url: load("successfactors_job_sample.html") if "/job/" in url else lst)
    company = CompanyConfig(name="SMBC", ats="successfactors", host="careers.smbcgroup.com", site="smbc")
    jobs = successfactors.fetch(company, LONG_AGO)
    assert [j.ats_job_id for j in jobs] == ["1442870100"]
    assert jobs[0].url.startswith("https://careers.smbcgroup.com/smbc/job/")
