"""Step 9: email the digest through Gmail SMTP (SSL, port 465).

Only sends when GMAIL_ADDRESS, GMAIL_APP_PASSWORD and DIGEST_TO are all set; otherwise skips quietly.
The digest content is never logged (the repo and its CI logs are public).
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from pipeline.export.digest import NY, DigestResult
from pipeline.log import get_logger
from pipeline.settings import get_settings

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

log = get_logger("emailer")


def build_subject(result: DigestResult) -> str:
    return f"Appollo, {len(result.jobs)} new roles, {result.now.astimezone(NY):%a %b %d}"


def build_message(result: DigestResult, sender: str, recipient: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = build_subject(result)
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(result.markdown)
    msg.add_alternative(result.html, subtype="html")
    return msg


def send_digest(result: DigestResult) -> bool:
    s = get_settings()
    if not (s.gmail_address and s.gmail_app_password and s.digest_to):
        log.info("Email skipped: GMAIL_ADDRESS, GMAIL_APP_PASSWORD or DIGEST_TO is not set")
        return False
    msg = build_message(result, s.gmail_address, s.digest_to)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(s.gmail_address, s.gmail_app_password)
        smtp.send_message(msg)
    log.info("Digest email sent (%d role(s))", len(result.jobs))
    return True
