"""Writes the application tracker from public.v_tracker to data/tracker.md and data/tracker.csv (both gitignored).
Columns are fixed by CLAUDE.md; this module never renames or reorders them."""
from __future__ import annotations

import csv

from pipeline.settings import REPO_ROOT

TRACKER_MD = REPO_ROOT / "data" / "tracker.md"
TRACKER_CSV = REPO_ROOT / "data" / "tracker.csv"


def _cell(value) -> str:
    return "" if value is None else str(value)


def write_tracker(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("select * from public.v_tracker")
        headers = [d.name for d in cur.description]
        rows = cur.fetchall()
    TRACKER_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(v).replace("|", "/") for v in row) + " |" for row in rows]
    TRACKER_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with TRACKER_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows([[_cell(v) for v in row] for row in rows])
    return len(rows)
