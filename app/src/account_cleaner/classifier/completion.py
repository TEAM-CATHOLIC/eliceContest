"""Conservative completion evidence; this does not verify a live account or sender identity."""

import re
from dataclasses import dataclass
from datetime import datetime

from account_cleaner.contracts import ParsedMail

from .model import DELETED_COMPLETED as _COMPLETED
from .phishing import looks_like_phishing
from .services import resolve_service


@dataclass(frozen=True)
class CompletionEvidence:
    mail_id: str
    domain: str
    received_at: datetime
    statement: str


def find_completion(
    mails: list[ParsedMail], domain: str, started_at: datetime, known_mail_ids: set[str]
) -> CompletionEvidence | None:
    """Only new, later, same-service mail with explicit completed wording qualifies.

    Date headers and sender domains alone are not authentication. The caller presents
    mail evidence, not a guarantee of real-world deletion. No candidate status is mutated.
    """
    if started_at.tzinfo is None:
        raise ValueError("started_at must include a timezone")
    for mail in sorted(mails, key=lambda m: m.date, reverse=True):
        if mail.id in known_mail_ids or mail.date <= started_at:
            continue
        service = resolve_service(mail)
        if service is None or service[1] != domain:
            continue
        # Do not use forwarded/quoted old confirmations as a new completion statement.
        subject = mail.subject.strip()
        if re.match(r"(?i)^(?:re|fw|fwd)\s*:|^전달\s*:", subject):
            continue
        body = re.split(r"(?im)^\s*(?:>|-+\s*Original|보낸\s*사람\s*:|From\s*:)", mail.body_text)[0]
        if looks_like_phishing(subject, body):
            continue
        match = _COMPLETED.search(body[:1600])
        if match:
            return CompletionEvidence(mail.id, domain, mail.date, match.group())
    return None
