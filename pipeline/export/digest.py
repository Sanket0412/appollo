"""Step 9: build the daily digest from scored jobs.

Selection: status 'scored', core fit at or above digest.min_core_fit, posted within the age cap, the top
digest.max_jobs by rank_score (newest first). Grouping: NYC metro, DC / Philadelphia corridor, Remote US, Elsewhere US, each in rank
order. Output is a local markdown file under data/digests/ (gitignored); titles, companies and links are
never logged.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline import geo
from pipeline.log import get_logger
from pipeline.score.rank import display_fit, update_rank_scores
from pipeline.settings import REPO_ROOT, get_settings

DIGEST_DIR = REPO_ROOT / "data" / "digests"
GROUPS = ("NYC metro", "DC / Philadelphia corridor", "Remote US", "Elsewhere US")
NY = ZoneInfo("America/New_York")

log = get_logger("digest")


@dataclass(frozen=True)
class DigestJob:
    id: str
    company: str
    title: str
    location: str | None
    is_nyc_metro: bool
    is_remote: bool
    posted_at: datetime
    yoe_min: int | None
    yoe_text: str | None
    sponsorship_jd: str | None
    sponsorship_evidence: str | None
    lca_filings: int | None
    lca_relevant_soc: int | None
    core_fit: int
    summary: str | None
    url: str


SELECT_SQL = """
select id, company, title, location, is_nyc_metro, is_remote, posted_at, yoe_min, yoe_text,
       sponsorship_jd, sponsorship_evidence, lca_filings, lca_relevant_soc, fit_score, summary, url
from public.jobs
where status = 'scored'
  and rank_score is not null
  and fit_score >= %s
  and posted_at >= now() - make_interval(days => %s)
order by rank_score desc
limit %s
"""


def select_digest_jobs(conn) -> list[DigestJob]:
    cfg = get_settings().search_config
    with conn.cursor() as cur:
        cur.execute(SELECT_SQL, (cfg["digest"]["min_core_fit"], cfg["max_posting_age_days"], cfg["digest"]["max_jobs"]))
        return [DigestJob(*row) for row in cur.fetchall()]


def group_of(job: DigestJob, geo_cfg: dict | None = None) -> str:
    """NYC metro, then the D.C. / Philadelphia corridor, then Remote US, then Elsewhere US.

    Distance decides when the location can be resolved; the stored is_nyc_metro flag is the fallback.
    """
    if geo_cfg is not None:
        metro, resolved = geo.metro_group(job.location, geo_cfg)
        if metro == "nyc":
            return GROUPS[0]
        if metro == "corridor":
            return GROUPS[1]
        nyc = job.is_nyc_metro and not resolved
    else:
        nyc = job.is_nyc_metro
    if nyc:
        return GROUPS[0]
    if job.is_remote:
        return GROUPS[2]
    return GROUPS[3]


def group_jobs(jobs: list[DigestJob], geo_cfg: dict | None = None) -> dict[str, list[DigestJob]]:
    """Groups keep the input order, which is already rank order."""
    grouped: dict[str, list[DigestJob]] = {g: [] for g in GROUPS}
    for job in jobs:
        grouped[group_of(job, geo_cfg)].append(job)
    return grouped


def posted_age(posted_at: datetime, now: datetime) -> str:
    hours = (now - posted_at).total_seconds() / 3600
    if hours < 24:
        return "posted today"
    days = int(hours // 24)
    return "posted 1 day ago" if days == 1 else f"posted {days} days ago"


def yoe_label(job: DigestJob) -> str:
    if job.yoe_min is not None:
        return f"{job.yoe_min}+ years"
    return job.yoe_text or "Not stated"


def sponsorship_label(job: DigestJob) -> str:
    status = job.sponsorship_jd or "Not Mentioned"
    return f'{status} ("{job.sponsorship_evidence}")' if job.sponsorship_evidence else status


def lca_label(job: DigestJob) -> str:
    # NULL means the employer was never matched in the LCA data; 0 is a real "matched, none relevant".
    if job.lca_filings is None:
        return "No filing history"
    return f"{job.lca_filings} LCA filings, {job.lca_relevant_soc or 0} in relevant SOC codes"


def fit_label(job: DigestJob, now: datetime) -> str:
    rec, total = display_fit(job.core_fit, job.posted_at, now)
    return f"{total}/100 (core {job.core_fit}/85 + recency {rec}/15)"


def render_markdown(grouped: dict[str, list[DigestJob]], now: datetime) -> str:
    total = sum(len(v) for v in grouped.values())
    lines = [f"# Appollo digest, {now.astimezone(NY):%a %b %d, %Y}", "", f"{total} role(s), newest first within each group.", ""]
    for group in GROUPS:
        jobs = grouped[group]
        if not jobs:
            continue
        lines += [f"## {group} ({len(jobs)})", ""]
        for i, j in enumerate(jobs, 1):
            lines += [
                f"### {i}. {j.company} - {j.title}",
                f"- Location: {j.location or 'Not stated'} ({posted_age(j.posted_at, now)})",
                f"- Fit: {fit_label(j, now)}",
                f"- Years required: {yoe_label(j)}",
                f"- Sponsorship: {sponsorship_label(j)}",
                f"- H-1B history: {lca_label(j)}",
                f"- Summary: {j.summary or ''}",
                f"- Apply: {j.url}",
                f"- Job id: `{j.id}`",
                "",
            ]
    if total == 0:
        lines.append("No roles met the bar today.")
    return "\n".join(lines) + "\n"


def render_html(grouped: dict[str, list[DigestJob]], now: datetime) -> str:
    e = html.escape
    parts = [f"<h2>Appollo digest, {now.astimezone(NY):%a %b %d, %Y}</h2>"]
    for group in GROUPS:
        jobs = grouped[group]
        if not jobs:
            continue
        parts.append(f"<h3>{e(group)} ({len(jobs)})</h3>")
        parts.append('<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px">')
        parts.append(
            "<tr><th>#</th><th>Company</th><th>Role</th><th>Location</th><th>Posted</th><th>Fit</th>"
            "<th>YOE</th><th>Sponsorship</th><th>H-1B history</th><th>Summary</th><th>Apply</th></tr>"
        )
        for i, j in enumerate(jobs, 1):
            parts.append(
                f"<tr><td>{i}</td><td>{e(j.company)}</td><td>{e(j.title)}</td><td>{e(j.location or '')}</td>"
                f"<td>{e(posted_age(j.posted_at, now))}</td><td>{e(fit_label(j, now))}</td><td>{e(yoe_label(j))}</td>"
                f"<td>{e(sponsorship_label(j))}</td><td>{e(lca_label(j))}</td><td>{e(j.summary or '')}</td>"
                f'<td><a href="{e(j.url, quote=True)}">Apply</a></td></tr>'
            )
        parts.append("</table>")
    if all(not v for v in grouped.values()):
        parts.append("<p>No roles met the bar today.</p>")
    return "\n".join(parts)


def write_digest(markdown: str, now: datetime) -> Path:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGEST_DIR / f"{now.astimezone(NY):%Y-%m-%d}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def mark_digested(conn, ids: list[str]) -> None:
    if not ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "update public.jobs set status = 'digested', digested_at = now() where id = any(%s) and status = 'scored'",
            (ids,),
        )
    conn.commit()


@dataclass(frozen=True)
class DigestResult:
    jobs: list[DigestJob]
    markdown: str
    html: str
    path: Path
    marked: bool
    now: datetime


def run_digest_stage(conn, mark: bool = True) -> DigestResult:
    """Ranks, selects, writes the markdown file, and (unless mark is False) flips the rows to digested."""
    now = datetime.now(timezone.utc)
    update_rank_scores(conn)
    jobs = select_digest_jobs(conn)
    grouped = group_jobs(jobs, get_settings().search_config["geo"])
    markdown = render_markdown(grouped, now)
    path = write_digest(markdown, now)
    if mark:
        mark_digested(conn, [j.id for j in jobs])
    log.info("Digest: %d role(s) selected (marked digested: %s)", len(jobs), mark)
    return DigestResult(jobs, markdown, render_html(grouped, now), path, mark, now)
