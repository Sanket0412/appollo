import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.fetchers import amazon, eightfold, oracle_rc
from pipeline.models import CompanyConfig

FIXTURES = Path(__file__).parent / "fixtures"
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def load(name: str):
    with (FIXTURES / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def test_oracle_rc_maps_list_and_detail(monkeypatch):
    list_payload, detail = load("oracle_list_sample.json"), load("oracle_detail_sample.json")
    detail_id = detail["items"][0]["Id"]
    requested = []

    def fake(url):
        requested.append(url)
        return detail if "RequisitionDetails" in url else list_payload

    monkeypatch.setattr(oracle_rc, "get_json", fake)
    company = CompanyConfig(name="JPMorgan Chase", ats="oracle_rc", host="jpmc.fa.oraclecloud.com", site="CX_1001")
    jobs = oracle_rc.fetch(company, LONG_AGO)

    by_id = {j.ats_job_id: j for j in jobs}
    job = by_id[detail_id]
    assert job.source == "oracle_rc"
    assert job.url == f"https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/{detail_id}"
    assert job.posted_at == datetime.fromisoformat(detail["items"][0]["ExternalPostedStartDate"])
    assert job.description_text and "<" not in job.description_text
    assert any("siteNumber=CX_1001" in u and "%22data%20scientist%22" in u for u in requested)


def test_oracle_rc_skips_old_postings(monkeypatch):
    monkeypatch.setattr(oracle_rc, "get_json", lambda url: load("oracle_list_sample.json"))
    company = CompanyConfig(name="JPMorgan Chase", ats="oracle_rc", host="h", site="CX_1001")
    assert oracle_rc.fetch(company, datetime(2100, 1, 1, tzinfo=timezone.utc)) == []


def test_eightfold_pcsx_epoch_dates_and_detail(monkeypatch):
    listing, detail = load("eightfold_pcsx_list_sample.json"), load("eightfold_detail_sample.json")
    monkeypatch.setattr(eightfold, "get_json", lambda url: detail if "position_details" in url else listing)
    company = CompanyConfig(name="Microsoft", ats="eightfold", host="apply.careers.microsoft.com", site="microsoft.com", board="pcsx")
    jobs = eightfold.fetch(company, LONG_AGO)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "eightfold"
    assert job.url.startswith("https://apply.careers.microsoft.com/careers/job/")
    assert job.posted_at is not None and job.posted_at.tzinfo is not None
    assert job.description_text


def test_eightfold_apply_variant(monkeypatch):
    listing, detail = load("eightfold_apply_list_sample.json"), load("eightfold_detail_sample.json")
    monkeypatch.setattr(eightfold, "get_json", lambda url: detail if "position_details" in url else listing)
    company = CompanyConfig(name="Millennium Management", ats="eightfold", host="mlp.eightfold.ai", site="mlp.com", board="apply")
    jobs = eightfold.fetch(company, LONG_AGO)

    assert len(jobs) == 1
    assert jobs[0].url.startswith("https://mlp.eightfold.ai/careers/job/")
    assert jobs[0].location


def test_amazon_parses_doubled_space_dates():
    assert amazon._parse_date("October  8, 2026") == datetime(2026, 10, 8, tzinfo=timezone.utc)
    assert amazon._parse_date("garbage") is None


def test_amazon_and_audible_split_the_feed(monkeypatch):
    payload = load("amazon_sample.json")
    audible_payload = json.loads(json.dumps(payload))
    audible_payload["jobs"][0]["company_name"] = "Audible, Inc."

    monkeypatch.setattr(amazon, "get_json", lambda url: payload)
    assert len(amazon.fetch(CompanyConfig(name="Amazon", ats="amazon"), LONG_AGO)) == 1
    assert amazon.fetch(CompanyConfig(name="Audible", ats="amazon", site="Audible"), LONG_AGO) == []

    monkeypatch.setattr(amazon, "get_json", lambda url: audible_payload)
    assert amazon.fetch(CompanyConfig(name="Amazon", ats="amazon"), LONG_AGO) == []
    jobs = amazon.fetch(CompanyConfig(name="Audible", ats="amazon", site="Audible"), LONG_AGO)
    assert len(jobs) == 1
    assert jobs[0].source == "amazon"
    assert jobs[0].url.startswith("https://www.amazon.jobs/en/jobs/")
    assert "Basic qualifications" in jobs[0].description_html
