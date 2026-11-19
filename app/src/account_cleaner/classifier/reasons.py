"""Pick the sentence of a mail that best shows why it counts as evidence. No ML, no I/O."""

import re

from account_cleaner.contracts import EvidenceType

MAX_CHARS = 90
_CUES = {
    EvidenceType.SIGNUP: r"가입.{0,12}(?:완료|환영|축하|감사|처리)|환영합니다|인증|"
    r"welcome|account.{0,20}(?:created|ready|active)|signed up|sign(?:ing)? up",
    EvidenceType.SECURITY: r"로그인|비밀번호|새 ?기기|2단계|액세스 권한|"
    r"sign(?:ed)?[ -]?in|log(?:ged)?[ -]?in|password|new device",
    EvidenceType.ACTIVITY: r"결제|주문|영수증|배송|구독|예약|환불|적립|"
    r"receipt|order|payment|charged|invoice|shipped",
    EvidenceType.TERMS: r"약관|처리방침|개인정보|휴면|terms|privacy policy",
    EvidenceType.DELETED: r"탈퇴|삭제|해지|파기|deleted|closed|removed",
    EvidenceType.PROMO: r"\(?광고\)?|할인|이벤트|쿠폰|혜택|수신 ?거부|unsubscribe|sale|% off",
}
_PATTERNS = {t: re.compile(p, re.IGNORECASE) for t, p in _CUES.items()}


def key_sentence(body_text: str, evidence_type: EvidenceType) -> str:
    """First sentence containing a cue for this evidence type; "" when none is found."""
    pattern = _PATTERNS[evidence_type]
    for sentence in re.split(r"(?<=[.!?。])\s+|\n+", body_text[:3000]):
        sentence = " ".join(sentence.split())
        if len(sentence) >= 8 and pattern.search(sentence):
            return sentence if len(sentence) <= MAX_CHARS else sentence[: MAX_CHARS - 1] + "…"
    return ""
