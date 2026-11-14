"""계정 분석 — ML(classifier/)이 구현하고 데스크톱이 호출한다."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from account_cleaner.contracts.login import LoginMethod
from account_cleaner.contracts.mail import ParsedMail

type ProgressCallback = Callable[[int, int], None]
"""(처리한 수, 전체 수)."""

type CancelCheck = Callable[[], bool]
"""True를 돌려주면 분석을 멈춰야 한다."""


class EvidenceType(StrEnum):
    """메일 한 통이 계정 존재를 얼마나 증명하는지 (PRD F-02)."""

    SIGNUP = "signup"
    """가입·인증 — 강한 증거"""
    SECURITY = "security"
    """보안·복구 — 강한 증거"""
    ACTIVITY = "activity"
    """거래·활동 — 다른 증거와 결합"""
    TERMS = "terms"
    """약관·휴면 — 다른 증거와 결합"""
    DELETED = "deleted"
    """탈퇴 완료 — 과거 계정으로 처리"""
    PROMO = "promo"
    """광고·초대 — 단독 근거로 쓰지 않음"""

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    EvidenceType.SIGNUP: "가입·인증",
    EvidenceType.SECURITY: "보안·복구",
    EvidenceType.ACTIVITY: "거래·활동",
    EvidenceType.TERMS: "약관·휴면",
    EvidenceType.DELETED: "탈퇴 완료",
    EvidenceType.PROMO: "광고·초대",
}


def _check_unit(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}는 0~1 사이여야 함: {value}")


@dataclass(frozen=True, slots=True)
class Evidence:
    """후보를 뒷받침하는 메일 한 통."""

    mail_id: str
    """`ParsedMail.id`"""
    type: EvidenceType
    probability: float
    """분류기가 이 유형이라고 본 확률 (0~1). 규칙 엔진이 확정한 경우 1.0."""

    def __post_init__(self) -> None:
        _check_unit("Evidence.probability", self.probability)


@dataclass(frozen=True, slots=True)
class AccountCandidate:
    """서비스 하나에 대한 계정 후보 (PRD F-03).

    약속:
    - `evidence`는 비어 있지 않다 (NF-03: 모든 후보에 근거가 있어야 함).
    - `score`는 계정이 존재할 가능성 0~1. 탈퇴 완료 메일이 있으면 낮게 준다.
    - `confirmed_login_method`는 메일에 가입 방식이 명시된 경우에만 채운다.
    """

    service: str
    """정규화된 서비스명. 예: "샘플쇼핑" """
    domain: str
    """대표 도메인(소문자). 예: "shop.example.com". 플레이북 매칭에 쓴다."""
    score: float
    evidence: tuple[Evidence, ...]
    first_seen: datetime
    last_seen: datetime
    confirmed_login_method: LoginMethod | None = None

    def __post_init__(self) -> None:
        _check_unit("AccountCandidate.score", self.score)
        if not self.evidence:
            raise ValueError(f"{self.service}: evidence가 비어 있음")
        if self.domain != self.domain.lower():
            raise ValueError(f"domain은 소문자여야 함: {self.domain!r}")
        if self.first_seen > self.last_seen:
            raise ValueError(f"{self.service}: first_seen이 last_seen보다 늦음")

    @property
    def has_deleted_evidence(self) -> bool:
        """탈퇴 완료 메일이 있는지 — 있으면 과거 계정으로 표시한다."""
        return any(e.type is EvidenceType.DELETED for e in self.evidence)


class AccountAnalyzer(ABC):
    """메일 목록을 받아 계정 후보를 만든다.

    스레드: 데스크톱 앱이 **작업 스레드**에서 호출한다. UI 객체에 접근하지 않는다.
    개인정보: 메일 내용을 기기 밖(클라우드 LLM 등)으로 보내지 않는다 (NF-01).
    """

    @abstractmethod
    def analyze(
        self,
        mails: Sequence[ParsedMail],
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelCheck | None = None,
    ) -> list[AccountCandidate]:
        """후보를 `score` 내림차순으로 돌려준다.

        - `on_progress`는 적당한 간격으로 (처리한 수, 전체 수)를 알린다. 호출 스레드에서 불린다.
        - `should_cancel()`이 True면 가능한 빨리 `AnalysisCancelled`를 던진다.
        """


class AnalysisCancelled(Exception):
    """사용자가 분석을 취소했다."""
