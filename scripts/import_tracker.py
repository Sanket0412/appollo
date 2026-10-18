"""Loads an existing tracker (.csv or .xlsx with the columns Company Name, Job Title, Date of Application)
into applied_history so those roles are never suggested again. A missing file is not an error.

  import_tracker.py [path]        default data/private/tracker.csv, then tracker.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from pipeline.db import get_conn
from pipeline.text_utils import normalize_company, title_norm

REQUIRED = ["Company Name", "Job Title"]


def find_file(arg: str | None) -> Path | None:
    candidates = [Path(arg)] if arg else [REPO_ROOT / "data" / "private" / n for n in ("tracker.csv", "tracker.xlsx")]
    return next((p for p in candidates if p.exists()), None)


def main() -> int:
    path = find_file(sys.argv[1] if len(sys.argv) > 1 else None)
    if path is None:
        print("No tracker file found (looked for data/private/tracker.csv and tracker.xlsx). Nothing to import.")
        return 0
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_excel(path)
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        print(f"ERROR missing column(s) {missing}; found {list(frame.columns)}")
        return 1
    dates = pd.to_datetime(frame.get("Date of Application"), errors="coerce") if "Date of Application" in frame else None
    added = 0
    with get_conn() as conn, conn.cursor() as cur:
        for i, row in frame.iterrows():
            company, title = row["Company Name"], row["Job Title"]
            if pd.isna(company) or pd.isna(title):
                continue
            applied = None if dates is None or pd.isna(dates.iloc[i]) else dates.iloc[i].date()
            cur.execute(
                "insert into public.applied_history (company_norm, title_norm, applied_at, source) "
                "values (%s, %s, %s, 'tracker') on conflict (company_norm, title_norm) do nothing",
                (normalize_company(str(company)), title_norm(str(title)), applied),
            )
            added += cur.rowcount
        conn.commit()
    print(f"Read {len(frame)} row(s), added {added} new to applied_history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
