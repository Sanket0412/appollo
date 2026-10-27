"""Oracle Recruiting Cloud fetcher (JPMorgan Chase, Mount Sinai). Public candidate-experience REST API,
no login. company.host is the Oracle host, company.site the siteNumber. Verified live 2026-10-26.

The list gives only a day-level PostedDate and a short description, so matching titles get the detail
call (full description and an exact ExternalPostedStartDate)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from pipeline.fetchers.base import get_json
from pipeline.models import CompanyConfig, RawJob
from pipeline.settings import get_settings
from pipeline.text_utils import html_to_text, title_matches

PAGE_LIMIT = 25
MAX_PAGES_PER_TERM = 3
BASE = "https://{host}/hcmRestApi/resources/latest"


def _quoted(value: str) -> str:
    return quote(f'"{value}"')


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _description_html(detail: dict) -> str:
    parts = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
    return "\n".join(detail[k] for k in parts if detail.get(k))


def fetch(company: CompanyConfig, since: datetime) -> list[RawJob]:
    cfg = get_settings().search_config
    base = BASE.format(host=company.host)

    matched: dict[str, dict] = {}
    for term in cfg["workday_search_terms"]:
        for page in range(MAX_PAGES_PER_TERM):
            offset = page * PAGE_LIMIT
            finder = (
                f"findReqs;siteNumber={company.site},limit={PAGE_LIMIT},offset={offset},"
                f"keyword={_quoted(term)},sortBy=POSTING_DATES_DESC"
            )
            data = get_json(
                f"{base}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder={finder}"
            )
            item = (data.get("items") or [{}])[0]
            for req in item.get("requisitionList", []):
                if req["Id"] in matched or not title_matches(req.get("Title", ""), cfg["titles"]):
                    continue
                day = _parse_iso(req.get("PostedDate"))
                # PostedDate is a date only, so a posting counts until the end of that day.
                if day is not None and day + timedelta(days=1) < since:
                    continue
                matched[req["Id"]] = req
            if offset + PAGE_LIMIT >= item.get("TotalJobsCount", 0):
                break

    jobs: list[RawJob] = []
    for req_id, req in matched.items():
        detail_payload = get_json(
            f"{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
            f"&finder=ById;Id={_quoted(req_id)},siteNumber={company.site}"
        )
        detail = (detail_payload.get("items") or [{}])[0]
        posted = _parse_iso(detail.get("ExternalPostedStartDate")) or _parse_iso(req.get("PostedDate"))
        if posted is not None and posted < since:
            continue
        html = _description_html(detail) or req.get("ShortDescriptionStr") or ""
        jobs.append(
            RawJob(
                source="oracle_rc",
                ats_job_id=req_id,
                company=company.name,
                title=req["Title"],
                location=req.get("PrimaryLocation"),
                is_remote="remote" in (req.get("WorkplaceType") or "").lower(),
                url=f"https://{company.host}/hcmUI/CandidateExperience/en/sites/{company.site}/job/{req_id}",
                posted_at=posted,
                description_html=html,
                description_text=html_to_text(html),
            )
        )
    return jobs
