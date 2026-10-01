"""Step 8: the Haiku scoring rubric, JSON schema and result validation."""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DESCRIPTION_CHARS = 12000
MAX_REQUIRED_SKILLS = 12
SKILLS_MAX_POINTS = 40
# A posting that requires this many years (or more) caps experience_fit, enforced in code. Postings
# requiring more than scoring.max_yoe_required are excluded before scoring ever happens.
EXPERIENCE_CAP_YEARS = 5
EXPERIENCE_CAP_POINTS = 10


def _skill_key(skill: str) -> str:
    return " ".join(skill.casefold().split())

SYSTEM_PROMPT = """You are a strict technical recruiter screening jobs for one candidate.
Score the job against the candidate's resume and return only JSON that matches the schema.

Candidate profile: about 4 years of professional data science and machine learning experience. Based in the New York / New Jersey area.

Scoring calibration (be stingy)
- You score experience_fit and domain_fit and list skills; the skills score itself, the location score and the recency score are computed in code from your lists and the posting data, so never score them. Be stingy: most reasonable postings deserve a combined experience_fit plus domain_fit of 15 to 25 out of 35.
- experience_fit: the posting requires 3 to 4 years -> up to 20. Requires 5 years -> at most 10. Requires 6 or more years -> at most 4.
- domain_fit: a domain the resume has no experience in is at most 6.

Rules
- years_required_min is the smallest number of years the posting states as required ("3-5 years" -> 3, "5+ years" -> 5). If no number is stated, null.
- sponsorship_jd is "N/A" when the posting explicitly says it will not sponsor, requires US citizenship or permanent residency, or requires a security clearance.
  It is "Available" when the posting explicitly offers visa sponsorship or immigration support.
  Otherwise it is "Not Mentioned".
- sponsorship_evidence is a verbatim quote from the posting that supports sponsorship_jd, or "" when Not Mentioned. Never paraphrase and never infer.
- one_line_summary describes the role itself in at most 25 words: team, what the person builds, core stack.
- required_skills lists the distinct technical skills, tools, methods and domains the posting states as REQUIRED, not preferred or nice to have. Use short normalized names (for example "python", "sql", "pytorch", "causal inference"). At most 12, most important first. Empty when the posting states none.
- matched_skills is the subset of required_skills that the resume clearly shows. Copy each string exactly as written in required_skills. Never list a skill the resume does not show.
- seniority is the level the posting targets.
- Score honestly. A perfect skills match with a 10-year requirement is still a poor experience fit.
- red_flags lists only concerns stated or clearly implied by the posting itself (for example an unrealistic requirement list, an on-site mandate far from the candidate, contract-only work). Never speculate about the candidate's immigration status, nationality or personal circumstances, and never restate sponsorship; that is covered by sponsorship_jd.

<resume>
{resume_text}
</resume>"""

# BUILD_PLAN.md Step 8 shape, with skills_match replaced by required_skills / matched_skills (skills score computed
# in code, 2026-10-01), minus seniority_fit (dropped 2026-10-01; recency replaces it, computed in code),
# location_fit (computed in code from distance, 2026-10-01) and the model's own total (always recomputed). Verified live against Haiku 4.5.
SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "years_required_min", "years_required_text", "seniority", "sponsorship_jd",
        "sponsorship_evidence", "required_skills", "matched_skills", "experience_fit", "domain_fit",
        "one_line_summary", "red_flags",
    ],
    "properties": {
        "years_required_min": {"type": ["integer", "null"]},
        "years_required_text": {"type": "string"},
        "seniority": {"type": "string", "enum": ["intern", "entry", "mid", "senior", "staff_plus", "unclear"]},
        "sponsorship_jd": {"type": "string", "enum": ["Available", "N/A", "Not Mentioned"]},
        "sponsorship_evidence": {"type": "string"},
        "required_skills": {"type": "array", "items": {"type": "string"}, "description": "At most 12 required skills."},
        "matched_skills": {"type": "array", "items": {"type": "string"}, "description": "Subset of required_skills the resume clearly shows."},
        "experience_fit": {"type": "integer", "minimum": 0, "maximum": 20},
        "domain_fit": {"type": "integer", "minimum": 0, "maximum": 15},
        "one_line_summary": {"type": "string"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
}


def api_schema() -> dict:
    """SCHEMA minus integer minimum/maximum, which the API rejects (verified live, 400).

    The ranges move into each field's description so the model still sees them; ScoreResult
    enforces them on our side.
    """
    schema = copy.deepcopy(SCHEMA)
    for prop in schema["properties"].values():
        lo, hi = prop.pop("minimum", None), prop.pop("maximum", None)
        if lo is not None and hi is not None:
            prop["description"] = f"Integer from {lo} to {hi}."
    return schema


class ScoreResult(BaseModel):
    years_required_min: int | None
    years_required_text: str
    seniority: Literal["intern", "entry", "mid", "senior", "staff_plus", "unclear"]
    sponsorship_jd: Literal["Available", "N/A", "Not Mentioned"]
    sponsorship_evidence: str
    required_skills: list[str] = Field(max_length=MAX_REQUIRED_SKILLS)
    matched_skills: list[str]
    skills_match: int = 0  # computed below, never taken from the model
    experience_fit: int = Field(ge=0, le=20)
    domain_fit: int = Field(ge=0, le=15)
    total: int = 0  # recomputed below: the three Haiku-judged parts, max 75; location is added in code
    one_line_summary: str
    red_flags: list[str]

    @model_validator(mode="after")
    def _recompute_total(self) -> ScoreResult:
        required = {_skill_key(s) for s in self.required_skills if s.strip()}
        matched = {_skill_key(s) for s in self.matched_skills if s.strip()}
        if not matched <= required:
            raise ValueError("matched_skills must be a subset of required_skills")
        self.skills_match = round(SKILLS_MAX_POINTS * len(matched) / max(len(required), 1))
        if self.years_required_min is not None and self.years_required_min >= EXPERIENCE_CAP_YEARS:
            self.experience_fit = min(self.experience_fit, EXPERIENCE_CAP_POINTS)
        self.total = self.skills_match + self.experience_fit + self.domain_fit
        return self


def recency_points(posted_at: datetime | None, now: datetime, max_points: int, cap_days: int) -> int:
    """max_points for a job posted just now, falling linearly to 0 at cap_days; 0 when the date is unknown."""
    if posted_at is None:
        return 0
    age_days = max((now - posted_at).total_seconds() / 86400, 0.0)
    return round(max_points * max(1 - age_days / cap_days, 0.0))


def build_system(resume_text: str) -> str:
    # str.replace rather than .format: the resume may contain braces.
    return SYSTEM_PROMPT.replace("{resume_text}", resume_text)


def build_user(company: str, title: str, location: str | None, description: str | None) -> str:
    return (
        f"Company: {company}\nTitle: {title}\nLocation: {location or 'unspecified'}\n\n"
        f"Job description:\n{(description or '')[:DESCRIPTION_CHARS]}"
    )


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def evidence_is_verbatim(evidence: str, description: str | None) -> bool:
    """True when empty or when the quote appears in the description (whitespace/case-insensitive)."""
    if not evidence.strip():
        return True
    return _squash(evidence) in _squash(description or "")


def parse_result(text: str) -> ScoreResult:
    return ScoreResult.model_validate_json(text)
