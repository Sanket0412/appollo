"""Applied / skipped bookkeeping for the review loop. Applying records the role in applied_history so the
prefilter never brings it back; skipping keeps the row (never re-evaluated) and stores why, which doubles
as labelled data for tuning the scoring rubric."""
from __future__ import annotations

import re
from datetime import date

from pipeline.text_utils import normalize_company, title_norm

SKIP_REASONS = ("location", "seniority", "pay", "company", "not_relevant", "already_applied_elsewhere", "other")
_LINKEDIN_ID_RE = re.compile(r"/jobs/view/(?:[^/?]*-)?(\d{6,})")


class AmbiguousRef(Exception):
    pass


def url_key(ref: str) -> str:
    """LinkedIn links carry tracking parameters; compare on the numeric job id when there is one."""
    m = _LINKEDIN_ID_RE.search(ref)
    return m.group(1) if m else ref.strip()


def resolve(conn, ref: str) -> tuple[str, str, str, str] | None:
    """Finds one job by id, id prefix (8+ chars) or apply URL. Returns (id, company, title, status) or None."""
    ref = ref.strip()
    key = url_key(ref)
    with conn.cursor() as cur:
        cur.execute(
            "select id, company, title, status from public.jobs "
            "where id = %s or (length(%s) >= 8 and id like %s) or url = %s or (%s ~ '^[0-9]{6,}$' and url like %s) "
            "order by (status = 'digested') desc, first_seen_at desc",
            (ref, ref, ref + "%", ref, key, f"%/{key}%"),
        )
        rows = cur.fetchall()
    if len(rows) > 1:
        raise AmbiguousRef(f"{ref!r} matches {len(rows)} jobs; use more of the id")
    return rows[0] if rows else None


def mark_applied(conn, job_id: str, applied_on: date) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update public.jobs set status = 'applied', applied_at = %s, exclude_reason = null where id = %s "
            "returning company, title",
            (applied_on, job_id),
        )
        company, title = cur.fetchone()
        cur.execute(
            "insert into public.applied_history (company_norm, title_norm, applied_at) values (%s, %s, %s) "
            "on conflict (company_norm, title_norm) do nothing",
            (normalize_company(company), title_norm(title), applied_on),
        )
    conn.commit()


def mark_skipped(conn, job_id: str, reason: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update public.jobs set status = 'skipped', exclude_reason = %s where id = %s",
            (f"skip:{reason}" if reason else "skip", job_id),
        )
    conn.commit()


def skip_remaining_digested(conn, reason: str | None) -> int:
    """Everything emailed but never acted on becomes skipped (no per-role reason)."""
    with conn.cursor() as cur:
        cur.execute(
            "update public.jobs set status = 'skipped', exclude_reason = %s where status = 'digested'",
            (f"skip:{reason}" if reason else "skip",),
        )
        n = cur.rowcount
    conn.commit()
    return n


def undecided(conn) -> list[tuple]:
    """Digested roles still waiting for an applied / skipped decision, newest first."""
    with conn.cursor() as cur:
        cur.execute(
            "select id, company, title, location, posted_at, url from public.jobs "
            "where status = 'digested' order by posted_at desc nulls last"
        )
        return cur.fetchall()
