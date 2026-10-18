"""Record what you did with a digest role.

  mark_applied.py <id|id-prefix|url> [...]                      mark applied today
  mark_applied.py <ref> --date 2026-10-17                       mark applied on a given day
  mark_applied.py <ref> --skip [--reason location|seniority|pay|company|not_relevant|other]
  mark_applied.py --list                                        digested roles still undecided
  mark_applied.py --skip-rest [--reason ...]                    skip everything still undecided

Roles you never act on simply stay 'digested': they are not shown again and cost nothing. Skip with a
reason when you want the reason remembered for tuning the scoring.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import tracking
from pipeline.db import get_conn
from pipeline.export.tracker_md import write_tracker


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("refs", nargs="*", help="job id, id prefix (8+ characters) or apply URL")
    ap.add_argument("--skip", action="store_true", help="mark skipped instead of applied")
    ap.add_argument("--reason", choices=tracking.SKIP_REASONS, help="why it was skipped (with --skip or --skip-rest)")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="application date, default today")
    ap.add_argument("--list", action="store_true", help="list digested roles awaiting a decision")
    ap.add_argument("--skip-rest", action="store_true", help="skip every digested role still undecided")
    args = ap.parse_args()

    with get_conn() as conn:
        if args.list:
            rows = tracking.undecided(conn)
            for job_id, company, title, location, posted_at, url in rows:
                print(f"{job_id[:10]}  {company} | {title} | {location or 'n/a'} | {posted_at:%Y-%m-%d}\n            {url}")
            print(f"{len(rows)} undecided")
            return 0
        if args.skip_rest:
            print(f"Skipped {tracking.skip_remaining_digested(conn, args.reason)} role(s)")
            return 0
        if not args.refs:
            ap.error("give at least one job id or URL, or use --list / --skip-rest")
        status = 0
        for ref in args.refs:
            try:
                job = tracking.resolve(conn, ref)
            except tracking.AmbiguousRef as exc:
                print(f"ERROR {exc}")
                status = 1
                continue
            if job is None:
                print(f"ERROR no job found for {ref!r}")
                status = 1
                continue
            job_id, company, title, _ = job
            if args.skip:
                tracking.mark_skipped(conn, job_id, args.reason)
                print(f"skipped  {company} | {title}" + (f" ({args.reason})" if args.reason else ""))
            else:
                tracking.mark_applied(conn, job_id, args.date or datetime.now().astimezone().date())
                print(f"applied  {company} | {title}")
        if not args.skip:
            print(f"Tracker updated ({write_tracker(conn)} applied role(s)) in data/tracker.md and data/tracker.csv")
        return status


if __name__ == "__main__":
    raise SystemExit(main())
