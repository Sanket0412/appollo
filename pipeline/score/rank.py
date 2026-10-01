"""Step 9: ranking. The digest is ordered by how recently a job was posted (newest first); within the
same posting day, higher core fit comes first. See search.yaml > ranking for the decision record.

fit_score in the jobs table is the core fit: skills_match + experience_fit + domain_fit + location_fit
(max 85), all judged by Haiku. Recency is computed live from posted_at and never stored.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from pipeline.log import get_logger
from pipeline.score.rubric import recency_points
from pipeline.settings import get_settings

EPOCH = date(2026, 1, 1)

log = get_logger("rank")


def rank_score(posted_at: datetime, core_fit: int, tiebreak_divisor: int) -> float:
    """Whole days since 2026-01-01 (UTC date of posted_at) plus core_fit / divisor.

    The fit term stays below one day as long as core_fit / divisor < 1, so it only orders jobs
    posted on the same day.
    """
    days = (posted_at.astimezone(timezone.utc).date() - EPOCH).days
    return days + core_fit / tiebreak_divisor


def display_fit(core_fit: int, posted_at: datetime | None, now: datetime) -> tuple[int, int]:
    """(recency points, total out of 100) for the digest, using today's age."""
    cfg = get_settings().search_config
    rec = recency_points(posted_at, now, cfg["scoring"]["recency_max_points"], cfg["max_posting_age_days"])
    return rec, core_fit + rec


def update_rank_scores(conn) -> int:
    """Sets rank_score on every scored, not yet digested row."""
    divisor = get_settings().search_config["ranking"]["tiebreak_divisor"]
    with conn.cursor() as cur:
        cur.execute(
            "select id, posted_at, fit_score from public.jobs "
            "where status = 'scored' and posted_at is not null and fit_score is not null"
        )
        rows = cur.fetchall()
        for job_id, posted_at, fit in rows:
            cur.execute(
                "update public.jobs set rank_score = %s where id = %s",
                (rank_score(posted_at, fit, divisor), job_id),
            )
    conn.commit()
    log.info("Updated rank_score on %d row(s)", len(rows))
    return len(rows)
