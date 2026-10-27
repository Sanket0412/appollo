from datetime import datetime, timezone

from pipeline.fetchers import undated
from pipeline.models import RawJob

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def raw(job_id, **kw):
    return RawJob(source="citadel", ats_job_id=job_id, company="Citadel", title="Data Scientist", url="u", undated=True, **kw)


def test_first_sight_is_baseline():
    out = undated.resolve([raw("a"), raw("b")], set(), NOW)
    assert all(j.posted_at == undated.BASELINE for j in out)


def test_dry_run_without_database_baselines():
    assert undated.resolve([raw("a")], None, NOW)[0].posted_at == undated.BASELINE


def test_new_id_after_first_sight_is_dated_now():
    out = undated.resolve([raw("a"), raw("b")], {"a"}, NOW)
    assert out[0].posted_at == undated.BASELINE
    assert out[1].posted_at == NOW


def test_dated_rows_untouched():
    dated = RawJob(source="x", ats_job_id="1", company="c", title="t", url="u", posted_at=NOW)
    assert undated.resolve([dated], set(), NOW) == [dated]
