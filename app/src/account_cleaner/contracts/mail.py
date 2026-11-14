"""파싱된 메일 — 데스크톱(mail/) → ML(classifier/)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ParsedMail:
    """메일 한 통에서 분류에 필요한 최소 정보.

    약속:
    - 본문은 HTML을 걷어낸 **평문 전체**(`body_text`)다. 첨부파일은 담지 않는다 (PRD F-01).
      분류기에 얼마나 넣을지(임베딩 길이 제한 등)는 ML 쪽에서 정한다.
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
    body_text: str
    """HTML을 걷어낸 본문 평문 전체. 본문이 없으면 빈 문자열."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ParsedMail.id가 비어 있음")
        if self.sender_domain != self.sender_domain.lower():
            raise ValueError(f"sender_domain은 소문자여야 함: {self.sender_domain!r}")
        if self.date.tzinfo is None:
            raise ValueError("ParsedMail.date는 시간대 정보가 있어야 함")
