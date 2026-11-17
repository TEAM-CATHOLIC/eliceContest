"""Local ML + explicit rules implementing the team's AccountAnalyzer contract."""

from collections import defaultdict

from account_cleaner.contracts import (
    AccountAnalyzer,
    AccountCandidate,
    AnalysisCancelled,
    Evidence,
    EvidenceType,
)

from .model import Predictor
from .services import resolve_service


class LocalAccountAnalyzer(AccountAnalyzer):
    def __init__(self, artifacts):
        self.predictor = Predictor(artifacts)

    def analyze(self, mails, on_progress=None, should_cancel=None):
        if should_cancel and should_cancel():
            raise AnalysisCancelled()
        unique = {m.id: m for m in mails}
        ordered = list(unique.values())
        rows = [{"id": m.id, "subject": m.subject, "body_text": m.body_text} for m in ordered]
        try:
            predictions = self.predictor.predict(rows, on_progress, should_cancel)
        except InterruptedError as error:
            raise AnalysisCancelled() from error
        groups = defaultdict(list)
        for mail, pred in zip(ordered, predictions):
            if should_cancel and should_cancel():
                raise AnalysisCancelled()
            service = resolve_service(mail)
            if service:
                groups[service].append((mail, pred))
        candidates = []
        for (service, domain), items in groups.items():
            items.sort(key=lambda pair: pair[0].date)
            evidence = tuple(
                Evidence(
                    m.id,
                    EvidenceType(p["type"]),
                    1.0
                    if p["type"] == "deleted"
                    and p["stage_hint"] == "account_deleted_completed"
                    or p["decision_source"] == "rule"
                    and p["type"] != "deleted"
                    else min(p["classification_score"], 0.99),
                )
                for m, p in items
            )
            # Uncalibrated ranking heuristic, not a validated existence probability.
            score = max(
                {
                    "signup": 0.65,
                    "security": 0.60,
                    "activity": 0.30,
                    "terms": 0.25,
                    "deleted": 0.05,
                    "promo": 0,
                }[p["type"]]
                * (1.0 if p["decision_source"] == "rule" else p["classification_score"])
                for _, p in items
            )
            decisive = [
                (m, p)
                for m, p in items
                if p["type"] in ("signup", "security")
                or (p["type"] == "deleted" and p["stage_hint"] == "account_deleted_completed")
            ]
            if decisive:
                latest = decisive[-1][1]
                if latest["type"] == "deleted":
                    score = min(score, 0.10)
                elif latest["stage_hint"] in (
                    "requested",
                    "account_not_found",
                    "existing_address_signup_blocked",
                ):
                    score = min(score, 0.25)
            candidates.append(
                AccountCandidate(
                    service=service,
                    domain=domain,
                    score=score,
                    evidence=evidence,
                    first_seen=items[0][0].date,
                    last_seen=items[-1][0].date,
                    confirmed_login_method=None,
                )
            )
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates
