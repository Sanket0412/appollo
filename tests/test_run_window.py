from datetime import datetime, timezone

from pipeline.run import compute_since


def test_14d_window_is_capped_at_the_age_limit():
    hours = (datetime.now(timezone.utc) - compute_since("14d")).total_seconds() / 3600
    assert 335.9 < hours <= 336.1


def test_24h_window_adds_grace():
    hours = (datetime.now(timezone.utc) - compute_since("24h")).total_seconds() / 3600
    assert abs(hours - 26) < 0.1
