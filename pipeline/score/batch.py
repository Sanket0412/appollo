"""Step 8: score shortlisted jobs with Haiku, through the Message Batches API.

Order of work per run: collect batches left over from earlier runs, submit one new batch, poll it,
write the scores, and if the wait expires fall back to synchronous calls for whatever is left.
Titles, companies and descriptions are never logged here (CI logs are public); counts and cost only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from psycopg.types.json import Jsonb

from pipeline.log import get_logger
from pipeline.score import rubric
from pipeline.settings import get_settings, resume_text

MAX_TOKENS = 800
POLL_SECONDS = 30
CANCEL_WAIT_SECONDS = 90

# USD per million tokens, Haiku 4.5 (verified in BUILD_PLAN.md section 2): batch is 50% off.
PRICE_SYNC = (1.00, 5.00)
PRICE_BATCH = (0.50, 2.50)

log = get_logger("batch")


@dataclass
class Job:
    id: str
    company: str
    title: str
    location: str | None
    description: str | None


@dataclass
class Tally:
    scored: int = 0
    excluded_no_sponsorship: int = 0
    excluded_yoe: int = 0
    left_shortlisted: int = 0
    evidence_violations: int = 0
    batch_in: int = 0
    batch_out: int = 0
    sync_in: int = 0
    sync_out: int = 0
    notes: list[str] = field(default_factory=list)

    def cost(self) -> float:
        return (
            self.batch_in * PRICE_BATCH[0] + self.batch_out * PRICE_BATCH[1]
            + self.sync_in * PRICE_SYNC[0] + self.sync_out * PRICE_SYNC[1]
        ) / 1_000_000

    def counts(self) -> dict:
        return {
            "scored": self.scored,
            "excluded_no_sponsorship": self.excluded_no_sponsorship,
            "excluded_yoe": self.excluded_yoe,
            "left_shortlisted": self.left_shortlisted,
            "evidence_violations": self.evidence_violations,
            "cost_usd": round(self.cost(), 4),
        }


def _request_params(model: str, system: str, job: Job) -> dict:
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "output_config": {"format": {"type": "json_schema", "schema": rubric.api_schema()}},
        "messages": [
            {"role": "user", "content": rubric.build_user(job.company, job.title, job.location, job.description)}
        ],
    }


def _parse_message(message) -> rubric.ScoreResult | None:
    """None when the response is unusable (refusal, truncation, invalid JSON, schema violation)."""
    if message.stop_reason != "end_turn":
        return None
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return rubric.parse_result(text)
    except ValueError:
        return None


def load_jobs(conn, ids: list[str]) -> dict[str, Job]:
    if not ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "select id, company, title, location, description from public.jobs where id = any(%s)", (ids,)
        )
        return {r[0]: Job(*r) for r in cur.fetchall()}


def load_shortlisted(conn, exclude_ids: set[str], limit: int) -> list[Job]:
    with conn.cursor() as cur:
        cur.execute(
            "select id, company, title, location, description from public.jobs "
            "where status = 'shortlisted' and not (id = any(%s)) "
            "order by is_nyc_metro desc, similarity desc nulls last limit %s",
            (list(exclude_ids), limit),
        )
        return [Job(*r) for r in cur.fetchall()]


def apply_score(conn, job: Job, result: rubric.ScoreResult, tally: Tally) -> None:
    max_yoe = get_settings().search_config["scoring"]["max_yoe_required"]

    if not rubric.evidence_is_verbatim(result.sponsorship_evidence, job.description):
        tally.evidence_violations += 1
        log.warning("Sponsorship evidence is not a verbatim quote for a scored job (job id %s)", job.id)

    status, reason = "scored", None
    if result.sponsorship_jd == "N/A":
        status, reason = "excluded", "jd_no_sponsorship"
        tally.excluded_no_sponsorship += 1
    elif result.years_required_min is not None and result.years_required_min > max_yoe:
        status, reason = "excluded", "yoe_too_high"
        tally.excluded_yoe += 1
    else:
        tally.scored += 1

    with conn.cursor() as cur:
        cur.execute(
            """
            update public.jobs set
                yoe_min = %s, yoe_text = %s, seniority = %s, sponsorship_jd = %s,
                sponsorship_evidence = %s, fit_score = %s, summary = %s, red_flags = %s,
                status = %s, exclude_reason = %s,
                description = case when %s = 'excluded' then null else description end
            where id = %s
            """,
            (
                result.years_required_min, result.years_required_text, result.seniority,
                result.sponsorship_jd, result.sponsorship_evidence or None, result.total,
                result.one_line_summary, Jsonb(result.red_flags), status, reason, status, job.id,
            ),
        )


def score_sync(client, model: str, system: str, job: Job, tally: Tally) -> rubric.ScoreResult | None:
    """One regular call, one retry on an unusable response."""
    for _ in range(2):
        message = client.messages.create(**_request_params(model, system, job))
        tally.sync_in += message.usage.input_tokens
        tally.sync_out += message.usage.output_tokens
        result = _parse_message(message)
        if result is not None:
            return result
    return None


def process_batch_results(conn, client, batch_id: str, jobs: dict[str, Job], model: str, system: str, tally: Tally) -> set[str]:
    """Writes every usable result; returns the ids that were scored or excluded."""
    done: set[str] = set()
    for entry in client.messages.batches.results(batch_id):
        job = jobs.get(entry.custom_id)
        if job is None or entry.result.type != "succeeded":
            continue
        message = entry.result.message
        tally.batch_in += message.usage.input_tokens
        tally.batch_out += message.usage.output_tokens
        result = _parse_message(message) or score_sync(client, model, system, job, tally)
        if result is None:
            continue
        apply_score(conn, job, result, tally)
        done.add(job.id)
    conn.commit()
    return done


def _wait_for_end(client, batch_id: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def _set_batch_status(conn, batch_id: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute("update public.score_batches set status = %s where batch_id = %s", (status, batch_id))
    conn.commit()


def collect_earlier_batches(conn, client, model: str, system: str, tally: Tally) -> set[str]:
    """Collects ended batches from earlier runs; returns ids still in flight (to avoid resubmitting)."""
    with conn.cursor() as cur:
        cur.execute("select batch_id, job_ids from public.score_batches where status = 'in_progress'")
        pending = cur.fetchall()

    in_flight: set[str] = set()
    for batch_id, job_ids in pending:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            in_flight.update(job_ids)
            continue
        jobs = {j: v for j, v in load_jobs(conn, job_ids).items()}
        process_batch_results(conn, client, batch_id, jobs, model, system, tally)
        _set_batch_status(conn, batch_id, "ended")
        log.info("Collected earlier batch %s", batch_id)
    return in_flight


def run_scoring_stage(conn, max_score: int | None = None) -> dict:
    cfg = get_settings().search_config["scoring"]
    model = cfg["model"]
    client = anthropic.Anthropic()
    system = rubric.build_system(resume_text())
    tally = Tally()

    in_flight = collect_earlier_batches(conn, client, model, system, tally)

    jobs = load_shortlisted(conn, in_flight, max_score or cfg["max_per_run"])
    if jobs:
        by_id = {j.id: j for j in jobs}
        batch = client.messages.batches.create(
            requests=[
                Request(custom_id=j.id, params=MessageCreateParamsNonStreaming(**_request_params(model, system, j)))
                for j in jobs
            ]
        )
        with conn.cursor() as cur:
            cur.execute(
                "insert into public.score_batches (batch_id, job_ids) values (%s, %s)",
                (batch.id, list(by_id)),
            )
        conn.commit()
        log.info("Submitted batch %s with %d request(s)", batch.id, len(jobs))

        ended = _wait_for_end(client, batch.id, cfg["batch_wait_minutes"] * 60)
        if ended:
            done = process_batch_results(conn, client, batch.id, by_id, model, system, tally)
            _set_batch_status(conn, batch.id, "ended")
        elif cfg["fallback_sync"]:
            log.warning("Batch %s not finished in %d min; cancelling and scoring the rest synchronously", batch.id, cfg["batch_wait_minutes"])
            client.messages.batches.cancel(batch.id)
            _wait_for_end(client, batch.id, CANCEL_WAIT_SECONDS)
            done = process_batch_results(conn, client, batch.id, by_id, model, system, tally)
            _set_batch_status(conn, batch.id, "canceled")
            for job in jobs:
                if job.id in done:
                    continue
                result = score_sync(client, model, system, job, tally)
                if result is not None:
                    apply_score(conn, job, result, tally)
                    done.add(job.id)
            conn.commit()
        else:
            done = set()
            log.warning("Batch %s still running; it will be collected on the next run", batch.id)

        tally.left_shortlisted = len(jobs) - len(done)

    counts = tally.counts()
    log.info("Scoring stage: %s", counts)
    print(f"Estimated scoring cost this run: ${tally.cost():.4f}")
    return counts
