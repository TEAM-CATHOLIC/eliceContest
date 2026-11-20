"""Local ML + explicit rules implementing the team's AccountAnalyzer contract."""

import math
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

# How strongly one mail of each type suggests an account exists (hand-set, not measured).
STRENGTH = {
    "signup": 0.85,
    "security": 0.85,
    "activity": 0.60,
    "terms": 0.60,
    "deleted": 0.05,
    "promo": 0.0,
}
MODEL_DISCOUNT = 0.7
"""Evidence decided by the model alone counts less than evidence matched by an explicit rule."""
MEMBER_BASE = 0.55
"""Starting score of any service that still mails you after phishing and work mail are removed."""
NOT_FINISHED = ("requested", "account_not_found", "existing_address_signup_blocked")
"""Stages that do not show a finished sign-up. "requested" counts only for sign-up verification;
a password-reset request still implies an existing account."""


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
            # Phishing that imitates account notices is never account or deletion evidence.
            if pred.get("stage_hint") == "phishing_suspected":
                continue
            # Explicit rules win; the optional gate only filters model-decided mail.
            if pred["decision_source"] != "rule":
                if pred.get("gate") in ("suspicious", "unrelated"):
                    continue
                if pred.get("gate") == "promo":
                    pred = {**pred, "type": "promo"}
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
            # Evidence-strength heuristic, not a measured existence probability. The strongest
            # mail of each type counts once, so different kinds of evidence add up while
            # repeats of one kind do not. Raw softmax scores are not used as confidence.
            strength = defaultdict(float)
            for _, p in items:
                weight = STRENGTH[p["type"]] * (
                    1.0 if p["decision_source"] == "rule" else MODEL_DISCOUNT
                )
                strength[p["type"]] = max(strength[p["type"]], weight)
            # A service that keeps mailing you is almost always one you joined (Korean services
            # send ads and privacy notices only to members), so every surviving candidate starts
            # as an account and is lowered only by evidence against it below.
            score = max(MEMBER_BASE, 1.0 - math.prod(1.0 - w for w in strength.values()))
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
            if all(
                p["stage_hint"] in NOT_FINISHED[1:]
                or (p["stage_hint"] == NOT_FINISHED[0] and p["type"] == "signup")
                for _, p in items
            ):
                # Only a verification request or a refused signup: sign-up may never have finished.
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
