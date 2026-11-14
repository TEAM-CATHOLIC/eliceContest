"""ML 분류기가 오기 전까지 쓰는 가짜 분석기. 제목 키워드로만 판단한다."""

from collections import defaultdict
from collections.abc import Sequence

from account_cleaner.contracts import (
    AccountAnalyzer,
    AccountCandidate,
    AnalysisCancelled,
    CancelCheck,
    Evidence,
    EvidenceType,
    LoginMethod,
    ParsedMail,
    ProgressCallback,
)

_KEYWORDS: list[tuple[EvidenceType, tuple[str, ...]]] = [
    (EvidenceType.DELETED, ("탈퇴 완료", "탈퇴가 완료", "계정 삭제")),
    (EvidenceType.SIGNUP, ("가입", "이메일 인증", "welcome", "환영")),
    (EvidenceType.SECURITY, ("비밀번호", "로그인 알림", "새로운 기기", "password")),
    (EvidenceType.ACTIVITY, ("주문", "결제", "배송", "영수증")),
    (EvidenceType.TERMS, ("약관", "휴면", "개인정보 처리방침")),
]

_WEIGHT = {
    EvidenceType.SIGNUP: 0.6,
    EvidenceType.SECURITY: 0.5,
    EvidenceType.ACTIVITY: 0.25,
    EvidenceType.TERMS: 0.2,
    EvidenceType.PROMO: 0.05,
    EvidenceType.DELETED: 0.0,
}

_SOCIAL = {"카카오": LoginMethod.KAKAO, "네이버": LoginMethod.NAVER, "구글": LoginMethod.GOOGLE}


def classify(mail: ParsedMail) -> Evidence:
    text = f"{mail.subject} {mail.body_preview}".lower()
    for etype, words in _KEYWORDS:
        if any(w.lower() in text for w in words):
            return Evidence(mail.id, etype, 0.9)
    return Evidence(mail.id, EvidenceType.PROMO, 0.6)


def _service_name(domain: str) -> str:
    parts = domain.split(".")
    return parts[-2] if len(parts) >= 2 else domain


def _registrable(domain: str) -> str:
    """ "mail.shop.example.com" → "shop.example.com" (마지막 세 칸까지만 단순 처리)."""
    return ".".join(domain.split(".")[-3:])


class FakeAnalyzer(AccountAnalyzer):
    def analyze(
        self,
        mails: Sequence[ParsedMail],
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> list[AccountCandidate]:
        groups: dict[str, list[tuple[ParsedMail, Evidence]]] = defaultdict(list)
        total = len(mails)
        for n, mail in enumerate(mails, 1):
            if should_cancel and should_cancel():
                raise AnalysisCancelled
            groups[_registrable(mail.sender_domain)].append((mail, classify(mail)))
            if on_progress and (n % 50 == 0 or n == total):
                on_progress(n, total)

        candidates = []
        for domain, items in groups.items():
            evidence = tuple(e for _, e in items)
            types = {e.type for e in evidence}
            score = min(1.0, sum(_WEIGHT[t] for t in types))
            if EvidenceType.DELETED in types:
                score *= 0.2
            dates = [m.date for m, _ in items]
            method = next(
                (
                    lm
                    for m, e in items
                    if e.type is EvidenceType.SIGNUP
                    for word, lm in _SOCIAL.items()
                    if word in m.subject
                ),
                None,
            )
            candidates.append(
                AccountCandidate(
                    service=_service_name(domain),
                    domain=domain,
                    score=round(score, 3),
                    evidence=evidence,
                    first_seen=min(dates),
                    last_seen=max(dates),
                    confirmed_login_method=method,
                )
            )
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates
