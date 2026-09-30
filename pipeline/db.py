"""Postgres connection helper. Connects directly (Session pooler), bypassing Supabase's REST API entirely."""
from __future__ import annotations

from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from pipeline.settings import get_settings


@contextmanager
def get_conn():
    conn = psycopg.connect(get_settings().database_url)
    try:
        try:
            register_vector(conn)
        except psycopg.ProgrammingError:
            # "create extension vector" has not run yet, e.g. the first migrate.py pass.
            conn.rollback()
        yield conn
    finally:
        conn.close()


def run_sql_script(conn, sql_text: str) -> None:
    """Run a (possibly multi-statement) SQL script, e.g. a migration file with dollar-quoted function bodies.

    psycopg3 sends a bare string with no parameters over the simple query protocol, which Postgres
    parses as a script rather than a single prepared statement.
    """
    with conn.cursor() as cur:
        cur.execute(sql_text)
