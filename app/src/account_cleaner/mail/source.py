"""메일 소스 공통 형태. 파일(#6), Gmail(#20), 네이버(#21)가 모두 이 형태로 메일을 내보낸다.

소스는 메일 원문(RFC 822 바이트)만 내보내고, `ParsedMail`로 바꾸는 일은 `normalize`가 한 곳에서 한다.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawMail:
    data: bytes
    """메일 원문 (헤더 + 본문, RFC 822)"""
    origin: str
    """어디서 왔는지 (오류 기록용). 예: "takeout.zip:All mail.mbox#120" """
    progress: int
    """이 메일까지 처리한 양. 단위는 소스마다 다르다 (파일은 바이트, 계정 연결은 통 수)."""


class MailSource(ABC):
    """메일을 한 통씩 내보낸다. 전체를 메모리에 올리지 않는다 (대용량 MBOX 대비)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """화면에 보여 줄 이름. 예: "takeout.zip" """

    @abstractmethod
    def total(self) -> int | None:
        """`RawMail.progress`의 끝 값. 모르면 None."""

    @abstractmethod
    def __iter__(self) -> Iterator[RawMail]: ...

    def failures(self) -> list[tuple[str, str]]:
        """원문을 받지 못해 건너뛴 메일 (위치, 이유). 계정 연결 소스가 네트워크 오류 등을 담는다."""
        return []
