from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipeline.export import emailer
from pipeline.export.digest import (
    DigestJob,
    DigestResult,
    group_jobs,
    lca_label,
    posted_age,
    render_html,
    render_markdown,
    sponsorship_label,
    yoe_label,
)
from pipeline.score.rank import EPOCH, rank_score

NOW = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)


def make(**kw) -> DigestJob:
    base = {
        "id": "abc", "company": "Acme", "title": "Data Scientist", "location": "New York, NY", "is_nyc_metro": True,
        "is_remote": False, "posted_at": NOW - timedelta(hours=5), "yoe_min": 3, "yoe_text": "3+ years",
        "sponsorship_jd": "Not Mentioned", "sponsorship_evidence": None, "lca_filings": None, "lca_relevant_soc": None,
        "core_fit": 60, "summary": "Builds models.", "url": "https://example.com/apply",
    }
    base.update(kw)
    return DigestJob(**base)


# --- ranking ---

def test_newer_posting_day_beats_higher_fit():
    newer = rank_score(NOW, 50, 1000)
    older = rank_score(NOW - timedelta(days=1), 85, 1000)
    assert newer > older


def test_fit_breaks_ties_within_the_same_day():
    assert rank_score(NOW, 70, 1000) > rank_score(NOW, 60, 1000)


def test_rank_score_counts_days_since_epoch():
    assert int(rank_score(datetime(2026, 1, 11, 3, tzinfo=timezone.utc), 0, 1000)) == 10
    assert EPOCH.year == 2026


# --- grouping ---

def test_groups_split_nyc_remote_elsewhere_and_keep_order():
    jobs = [
        make(id="1", is_nyc_metro=False, is_remote=True),
        make(id="2", is_nyc_metro=True),
        make(id="3", is_nyc_metro=False, is_remote=False),
        make(id="4", is_nyc_metro=True),
    ]
    grouped = group_jobs(jobs)
    assert [j.id for j in grouped["NYC metro"]] == ["2", "4"]
    assert [j.id for j in grouped["Remote US"]] == ["1"]
    assert [j.id for j in grouped["Elsewhere US"]] == ["3"]


# --- labels ---

def test_lca_none_renders_no_filing_history_but_zero_is_a_real_number():
    assert lca_label(make(lca_filings=None)) == "No filing history"
    assert lca_label(make(lca_filings=0, lca_relevant_soc=0)).startswith("0 LCA filings")


def test_sponsorship_label_includes_evidence_quote():
    assert sponsorship_label(make(sponsorship_jd="Available", sponsorship_evidence="We sponsor visas")) == (
        'Available ("We sponsor visas")'
    )
    assert sponsorship_label(make(sponsorship_jd=None)) == "Not Mentioned"


def test_yoe_label_falls_back():
    assert yoe_label(make(yoe_min=4)) == "4+ years"
    assert yoe_label(make(yoe_min=None, yoe_text="Several years")) == "Several years"
    assert yoe_label(make(yoe_min=None, yoe_text=None)) == "Not stated"


def test_posted_age_labels():
    assert posted_age(NOW - timedelta(hours=3), NOW) == "posted today"
    assert posted_age(NOW - timedelta(hours=30), NOW) == "posted 1 day ago"
    assert posted_age(NOW - timedelta(days=5, hours=2), NOW) == "posted 5 days ago"


# --- rendering ---

def test_markdown_lists_groups_in_order_with_apply_link():
    grouped = group_jobs([make(id="r", is_nyc_metro=False, is_remote=True), make(id="n")])
    md = render_markdown(grouped, NOW)
    assert md.index("## NYC metro") < md.index("## Remote US")
    assert "https://example.com/apply" in md
    assert "Elsewhere US" not in md


def test_empty_digest_says_so():
    assert "No roles met the bar today." in render_markdown(group_jobs([]), NOW)


def test_html_escapes_untrusted_text():
    grouped = group_jobs([make(company="A<b>&Co", summary="<script>x</script>")])
    out = render_html(grouped, NOW)
    assert "<script>" not in out and "A&lt;b&gt;&amp;Co" in out


# --- emailer ---

def _result():
    grouped = group_jobs([make()])
    return DigestResult([make()], render_markdown(grouped, NOW), render_html(grouped, NOW), Path("x.md"), False, NOW)


def test_email_subject_and_both_parts():
    msg = emailer.build_message(_result(), "me@example.com", "you@example.com")
    assert msg["Subject"] == "Appollo, 1 new roles, Thu Oct 01"
    kinds = {part.get_content_type() for part in msg.walk()}
    assert {"text/plain", "text/html"} <= kinds


def test_email_skipped_without_credentials(monkeypatch):
    class S:
        gmail_address = None
        gmail_app_password = "x"
        digest_to = "you@example.com"

    monkeypatch.setattr(emailer, "get_settings", lambda: S())
    assert emailer.send_digest(_result()) is False
