"""Compares the scorer with your own decisions. Reads jobs you marked applied or skipped (mark_applied.py)
and reports core-fit statistics per outcome and per skip reason, plus how many applied roles each
digest.min_core_fit cutoff would have kept. Needs roughly 15 to 20 decisions before it means much.

Prints counts and scores only, no titles or companies."""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.db import get_conn
from pipeline.settings import get_settings


def describe(scores: list[int]) -> str:
    if not scores:
        return "n=0"
    return f"n={len(scores)} min={min(scores)} median={statistics.median(scores):g} max={max(scores)}"


def main() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "select status, coalesce(exclude_reason, ''), fit_score from public.jobs "
            "where status in ('applied', 'skipped') and fit_score is not null"
        )
        rows = cur.fetchall()
    applied = [r[2] for r in rows if r[0] == "applied"]
    skipped = [r[2] for r in rows if r[0] == "skipped"]
    print(f"applied  {describe(applied)}\nskipped  {describe(skipped)}")
    reasons = sorted({r[1] for r in rows if r[0] == "skipped" and r[1]})
    for reason in reasons:
        print(f"  {reason:<28}{describe([r[2] for r in rows if r[0] == 'skipped' and r[1] == reason])}")
    if len(rows) < 15:
        print(f"\nOnly {len(rows)} decision(s) so far; keep marking roles (aim for 15 to 20) before changing the cutoff.")
    current = get_settings().search_config["digest"]["min_core_fit"]
    print(f"\ncurrent digest.min_core_fit = {current}")
    for cutoff in range(40, 81, 5):
        kept_applied = sum(1 for s in applied if s >= cutoff)
        kept_skipped = sum(1 for s in skipped if s >= cutoff)
        print(f"  cutoff {cutoff}: keeps {kept_applied}/{len(applied)} applied, {kept_skipped}/{len(skipped)} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
