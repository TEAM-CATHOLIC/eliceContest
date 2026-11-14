"""파싱된 메일 — 데스크톱(mail/) → ML(classifier/)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ParsedMail:
    """메일 한 통에서 분류에 필요한 최소 정보.

    약속:
    - 메일 원문 전체는 담지 않는다. 본문은 앞부분(`body_preview`)만 평문으로 둔다 (PRD NF-01).
    - `sender_domain`은 소문자이고 `sender`의 `@` 뒤와 같다.
    - `date`는 시간대 정보가 있는(aware) datetime이다.
    - 이 객체는 기기 밖으로 보내지 않는다.
    """

    id: str
    """Message-ID. 없으면 내용 해시. 같은 메일함 안에서 유일하다."""
    sender: str
    """발신 주소. 예: "no-reply@shop.example.com" """
    sender_domain: str
    """예: "shop.example.com" """
    subject: str
    date: datetime
    body_preview: str
    """HTML을 걷어낸 평문 앞부분 (최대 `BODY_PREVIEW_LIMIT`자)."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ParsedMail.id가 비어 있음")
        if self.sender_domain != self.sender_domain.lower():
            raise ValueError(f"sender_domain은 소문자여야 함: {self.sender_domain!r}")
        if self.date.tzinfo is None:
            raise ValueError("ParsedMail.date는 시간대 정보가 있어야 함")
        if len(self.body_preview) > BODY_PREVIEW_LIMIT:
            raise ValueError(f"body_preview는 {BODY_PREVIEW_LIMIT}자 이하여야 함")


BODY_PREVIEW_LIMIT = 1000
