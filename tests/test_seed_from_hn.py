import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.ats_discovery import AtsRef
from scripts.seed_from_hn import (
    existing_ref_keys,
    extract_urls,
    guess_company_name,
    ref_key,
    to_entry,
)

SAMPLE_COMMENT = (
    'Modash.io | Senior Product Engineer | Remote (Europe) | Full-time | €75k–110k | '
    '<a href="https:&#x2F;&#x2F;modash.io" rel="nofollow">https:&#x2F;&#x2F;modash.io</a>'
    "<p>Modash helps brands find, manage, and pay creators.<p>"
    'Apply: <a href="https:&#x2F;&#x2F;jobs.lever.co&#x2F;modash" rel="nofollow">https:&#x2F;&#x2F;jobs.lever.co&#x2F;modash</a>'
)


def test_extract_urls_unescapes_and_finds_hrefs():
    urls = extract_urls(SAMPLE_COMMENT)
    assert "https://modash.io" in urls
    assert "https://jobs.lever.co/modash" in urls


def test_extract_urls_empty_text():
    assert extract_urls("") == []
    assert extract_urls(None) == []


def test_guess_company_name_parses_pipe_format():
    assert guess_company_name(SAMPLE_COMMENT, fallback="modash") == "Modash.io"


def test_guess_company_name_falls_back_when_no_pipe_format():
    text = "<p>We are hiring like crazy this month, check out our jobs page!"
    assert guess_company_name(text, fallback="somecompany") == "somecompany"


def test_guess_company_name_falls_back_on_empty_text():
    assert guess_company_name("", fallback="fallback-name") == "fallback-name"


def test_guess_company_name_strips_trailing_url():
    text = 'Smarkets ( <a href="https:&#x2F;&#x2F;www.smarkets.com">https:&#x2F;&#x2F;www.smarkets.com</a> ) | Engineer'
    assert guess_company_name(text, fallback="smarkets") == "Smarkets"


def test_guess_company_name_rejects_location_as_first_field():
    # Some posters write "NYC | Norm AI | ..." instead of "Company | Title | Location"; a location
    # token in the company-name slot should fall back rather than be trusted.
    assert guess_company_name("NYC | Backend Engineer | ...", fallback="norm-ai") == "norm-ai"
    assert guess_company_name("Remote (US) Close | Engineer | ...", fallback="close") == "close"


def test_ref_key_workday_uses_full_tuple():
    ref = AtsRef(ats="workday", host="intel.wd1.myworkdayjobs.com", tenant="intel", board="External")
    assert ref_key(ref) == ("workday", "intel.wd1.myworkdayjobs.com", "intel", "External")


def test_ref_key_non_workday_uses_slug():
    ref = AtsRef(ats="greenhouse", slug="ramp")
    assert ref_key(ref) == ("greenhouse", "ramp")


def test_existing_ref_keys_handles_mixed_entries():
    companies = [
        {"name": "Ramp", "ats": "greenhouse", "slug": "ramp", "source": "manual"},
        {"name": "Intel", "ats": "workday", "host": "intel.wd1.myworkdayjobs.com", "tenant": "intel", "board": "External", "source": "manual"},
    ]
    keys = existing_ref_keys(companies)
    assert ("greenhouse", "ramp") in keys
    assert ("workday", "intel.wd1.myworkdayjobs.com", "intel", "External") in keys


def test_to_entry_greenhouse():
    ref = AtsRef(ats="greenhouse", slug="ramp")
    assert to_entry("Ramp", ref, "hn") == {"name": "Ramp", "ats": "greenhouse", "slug": "ramp", "source": "hn"}


def test_to_entry_workday():
    ref = AtsRef(ats="workday", host="intel.wd1.myworkdayjobs.com", tenant="intel", board="External")
    entry = to_entry("Intel", ref, "manual")
    assert entry == {
        "name": "Intel",
        "ats": "workday",
        "host": "intel.wd1.myworkdayjobs.com",
        "tenant": "intel",
        "board": "External",
        "source": "manual",
    }
