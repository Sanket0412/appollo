"""Dating for sources with no usable posted date (Two Sigma, SMBC, Citadel, Bloomberg overflow).

Decided 2026-10-26: the first time a board is seen, every current posting is a baseline and is stored
as stale (so it never reaches the digest). After that, an ID not seen before is dated now. A board
with no stored rows counts as a first sight, so a board that matched no titles on its first run is
baselined again on the next one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pipeline.models import RawJob

BASELINE = datetime(2000, 1, 1, tzinfo=timezone.utc)


def known_ids(conn, source: str, company: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "select ats_job_id from public.jobs where source = %s and company = %s and ats_job_id is not null",
            (source, company),
        )
        return {row[0] for row in cur.fetchall()}


def resolve(raw_jobs: list[RawJob], known: set[str] | None, now: datetime | None = None) -> list[RawJob]:
    """known=None (dry run, no database) or an empty set baselines everything."""
    now = now or datetime.now(timezone.utc)
    out = []
    for raw in raw_jobs:
        if not raw.undated or raw.posted_at is not None:
            out.append(raw)
            continue
        posted = now if known and raw.ats_job_id not in known and raw.ats_job_id is not None else BASELINE
        out.append(raw.model_copy(update={"posted_at": posted}))
    return out
