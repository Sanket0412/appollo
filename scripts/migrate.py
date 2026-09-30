"""Applies db/migrations/*.sql in filename order, tracked in schema_migrations. Re-running applies nothing new."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.db import get_conn, run_sql_script
from pipeline.log import get_logger

MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

log = get_logger("migrate")

CREATE_TRACKING_TABLE = """
create table if not exists public.schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
);
"""


def main() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TRACKING_TABLE)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("select version from public.schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        pending = sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name not in applied)

        if not pending:
            log.info("Nothing to apply, %d migration(s) already recorded", len(applied))
            return

        for path in pending:
            log.info("Applying %s", path.name)
            sql_text = path.read_text(encoding="utf-8")
            try:
                run_sql_script(conn, sql_text)
                with conn.cursor() as cur:
                    cur.execute(
                        "insert into public.schema_migrations (version) values (%s)",
                        (path.name,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                log.exception("Failed applying %s", path.name)
                raise

        log.info("Applied %d migration(s)", len(pending))


if __name__ == "__main__":
    main()
