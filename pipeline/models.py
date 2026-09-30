"""Shared data shapes: company config (from companies.yaml), a fetcher's raw output, and the
normalized row that matches the jobs table (db/migrations/001_init.sql)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class CompanyConfig(BaseModel):
    name: str
    ats: str  # greenhouse | lever | ashby | workday
    source: str = "manual"  # manual | hn | discovered
    cap_exempt: bool = False
    slug: str | None = None  # greenhouse | lever | ashby
    host: str | None = None  # workday
    tenant: str | None = None  # workday
    board: str | None = None  # workday


class RawJob(BaseModel):
    source: str  # greenhouse | lever | ashby | workday | jobspy_indeed | jobspy_linkedin | jobspy_google
    ats_job_id: str
    company: str
    title: str
    location: str | None = None
    is_remote: bool = False
    url: str
    posted_at: datetime | None = None
    description_html: str | None = None
    description_text: str | None = None


class Job(BaseModel):
    """Normalized row matching public.jobs. Optional fields are filled in by later pipeline stages."""

    id: str
    source: str
    ats_job_id: str | None = None
    company: str
    company_norm: str
    title: str
    location: str | None = None
    is_remote: bool = False
    is_us: bool = True
    is_nyc_metro: bool = False
    url: str
    posted_at: datetime | None = None
    description: str | None = None

    similarity: float | None = None
    yoe_min: int | None = None
    yoe_text: str | None = None
    seniority: str | None = None
    sponsorship_jd: str | None = None  # Available | N/A | Not Mentioned
    sponsorship_evidence: str | None = None
    lca_filings: int | None = None
    lca_relevant_soc: int | None = None
    lca_match_name: str | None = None
    lca_match_score: float | None = None
    fit_score: int | None = None
    rank_score: float | None = None
    summary: str | None = None
    red_flags: list[str] = []

    status: str = "new"
    exclude_reason: str | None = None
    digested_at: datetime | None = None
    applied_at: date | None = None
