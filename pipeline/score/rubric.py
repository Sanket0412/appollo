"""Step 8: the Haiku scoring rubric, JSON schema and result validation."""
from __future__ import annotations

import copy
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DESCRIPTION_CHARS = 12000

SYSTEM_PROMPT = """You are a strict technical recruiter screening jobs for one candidate.
Score the job against the candidate's resume and return only JSON that matches the schema.

Rules
- years_required_min is the smallest number of years the posting states as required ("3-5 years" -> 3, "5+ years" -> 5). If no number is stated, null.
- sponsorship_jd is "N/A" when the posting explicitly says it will not sponsor, requires US citizenship or permanent residency, or requires a security clearance.
  It is "Available" when the posting explicitly offers visa sponsorship or immigration support.
  Otherwise it is "Not Mentioned".
- sponsorship_evidence is a verbatim quote from the posting that supports sponsorship_jd, or "" when Not Mentioned. Never paraphrase and never infer.
- one_line_summary describes the role itself in at most 25 words: team, what the person builds, core stack.
- seniority is the level the posting targets.
- Score honestly. A perfect skills match with a 10-year requirement is still a poor experience fit.
- red_flags lists only concerns stated or clearly implied by the posting itself (for example an unrealistic requirement list, an on-site mandate far from the candidate, contract-only work). Never speculate about the candidate's immigration status, nationality or personal circumstances, and never restate sponsorship; that is covered by sponsorship_jd.

<resume>
{resume_text}
</resume>"""

# Same shape as BUILD_PLAN.md Step 8. Verified live against Haiku 4.5 with output_config.format.
SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "years_required_min", "years_required_text", "seniority", "sponsorship_jd",
        "sponsorship_evidence", "skills_match", "experience_fit", "domain_fit", "seniority_fit",
        "location_fit", "total", "one_line_summary", "red_flags",
    ],
    "properties": {
        "years_required_min": {"type": ["integer", "null"]},
        "years_required_text": {"type": "string"},
        "seniority": {"type": "string", "enum": ["intern", "entry", "mid", "senior", "staff_plus", "unclear"]},
        "sponsorship_jd": {"type": "string", "enum": ["Available", "N/A", "Not Mentioned"]},
        "sponsorship_evidence": {"type": "string"},
        "skills_match": {"type": "integer", "minimum": 0, "maximum": 40},
        "experience_fit": {"type": "integer", "minimum": 0, "maximum": 20},
        "domain_fit": {"type": "integer", "minimum": 0, "maximum": 15},
        "seniority_fit": {"type": "integer", "minimum": 0, "maximum": 15},
        "location_fit": {"type": "integer", "minimum": 0, "maximum": 10},
        "total": {"type": "integer", "minimum": 0, "maximum": 100},
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
    skills_match: int = Field(ge=0, le=40)
    experience_fit: int = Field(ge=0, le=20)
    domain_fit: int = Field(ge=0, le=15)
    seniority_fit: int = Field(ge=0, le=15)
    location_fit: int = Field(ge=0, le=10)
    total: int = Field(ge=0, le=100)
    one_line_summary: str
    red_flags: list[str]

    @model_validator(mode="after")
    def _recompute_total(self) -> ScoreResult:
        # The model's own arithmetic is not trusted; the five parts are the source of truth.
        self.total = (
            self.skills_match + self.experience_fit + self.domain_fit + self.seniority_fit + self.location_fit
        )
        return self


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
