from pipeline.tracking import url_key


def test_linkedin_url_collapses_to_job_id():
    assert url_key("https://www.linkedin.com/jobs/view/4472069604?trk=abc&refId=x") == "4472069604"
    assert url_key("https://www.linkedin.com/jobs/view/ai-engineer-at-acme-4472069604") == "4472069604"


def test_other_urls_are_kept_whole():
    assert url_key(" https://boards.greenhouse.io/acme/jobs/1 ") == "https://boards.greenhouse.io/acme/jobs/1"
