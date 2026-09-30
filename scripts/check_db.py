"""Prints the Postgres server version, whether pgvector is installed, and row counts for every Appollo table."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from psycopg import sql

from pipeline.db import get_conn

TABLES = ["jobs", "lca_employers", "applied_history", "runs", "score_batches"]


def main() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("select version()")
        print(cur.fetchone()[0])

        cur.execute("select extname from pg_extension where extname = 'vector'")
        installed = cur.fetchone() is not None
        print(f"vector extension installed: {installed}")

        for table in TABLES:
            cur.execute(sql.SQL("select count(*) from public.{}").format(sql.Identifier(table)))
            count = cur.fetchone()[0]
            print(f"{table}: {count} row(s)")


if __name__ == "__main__":
    main()
