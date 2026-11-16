"""탈퇴 화면 안내 에이전트 — 브라우저 담당(browser/)이 구현하고 데스크톱이 호출한다."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from account_cleaner.contracts.playbook import Playbook


class AgentStatus(StrEnum):
    NAVIGATING = "navigating"
    """에이전트가 이동 중"""
    USER_TURN = "user_turn"
    """사용자가 직접 처리해야 함 — `resume()`까지 대기"""
    REACHED = "reached"
    """탈퇴 화면 도달. 최종 버튼 앞에서 멈춘 상태 (종료 상태).
    최종 버튼은 사용자가 누르므로, 이 이벤트를 보낸 뒤에도 브라우저는 사용자가 닫거나 `stop()`할 때까지
    열려 있고 `run()`은 그때 이 이벤트를 돌려준다."""
    STOPPED = "stopped"
    """`stop()`으로 중단됨 (종료 상태)"""
    FAILED = "failed"
    """더 진행할 수 없음 (종료 상태)"""

    @property
    def is_final(self) -> bool:
        return self in (AgentStatus.REACHED, AgentStatus.STOPPED, AgentStatus.FAILED)


class HandoffReason(StrEnum):
    """사용자에게 넘기는 이유 (PRD 5장 넘겨주기 조건)."""

    LOGIN = "login"
    """비밀번호 입력 칸"""
    IDENTITY = "identity"
    """본인인증"""
    CAPTCHA = "captcha"
    TWO_FACTOR = "two_factor"
    PAYMENT = "payment"
    EXTERNAL_AUTH = "external_auth"
    """`auth_domains`(소셜 로그인 등)로 넘어감"""
    UNKNOWN = "unknown"
    """에이전트가 다음 동작을 찾지 못해 사용자 판단이 필요함"""


@dataclass(frozen=True, slots=True)
class AgentStep:
    """에이전트가 지금 몇 번째 단계에 있는지. UI의 단계 표시(Step n of m)에 쓴다.

    단계 수와 제목은 플레이북마다 브라우저 쪽이 정한다 (예: "탈퇴 메뉴 진입", "탈퇴 전 조건 확인",
    "본인 확인"). 최종 탈퇴 버튼은 사용자가 누르므로 단계에 넣지 않는다. UI가 마지막에
    "최종 탈퇴 (직접)"를 잠긴 단계로 따로 붙인다.
    """

    index: int
    """1부터 시작"""
    total: int
    title: str

    def __post_init__(self) -> None:
        if not 1 <= self.index <= self.total:
            raise ValueError(f"단계 번호가 범위를 벗어남: {self.index}/{self.total}")
        if not self.title.strip():
            raise ValueError("단계 제목이 비어 있음")


@dataclass(frozen=True, slots=True)
class AgentEvent:
    status: AgentStatus
    message: str = ""
    """사용자에게 그대로 보여 줄 한국어 안내"""
    reason: HandoffReason | None = None
    """`USER_TURN`일 때만 채운다."""
    url: str | None = None
    """현재 페이지 주소 (기록용)"""
    step: AgentStep | None = None
    """지금 단계. 종료 이벤트(`STOPPED`·`FAILED`)는 비워도 된다. UI는 마지막으로 받은 단계를 유지한다."""

    def __post_init__(self) -> None:
        if (self.status is AgentStatus.USER_TURN) != (self.reason is not None):
            raise ValueError("reason은 USER_TURN일 때만, 그리고 반드시 채운다")


type EventCallback = Callable[[AgentEvent], None]


class WithdrawAgent(ABC):
    """플레이북을 따라 탈퇴 화면까지 이동한다 (PRD F-06, 5장).

    안전 규칙 (구현이 반드시 지킨다):
    - 최종 탈퇴 버튼은 절대 누르지 않는다. 탈퇴 화면에 도달하면 `REACHED`로 끝낸다.
    - `playbook.allows(url)`이 False인 주소로 이동하지 않는다.
    - 비밀번호·본인인증·캡차·2단계 인증·결제·외부 인증 화면에서는 `USER_TURN`을 보내고 멈춘다.
    - 사용자 입력값(비밀번호 등)을 읽거나 저장하거나 외부로 보내지 않는다.

    스레드 규칙:
    - `run()`, `clear_session()`은 데스크톱이 만든 **작업 스레드 하나**에서만 호출된다.
      Playwright 객체는 그 스레드에서 만들고 그 스레드에서만 쓴다.
    - `resume()`, `stop()`은 **UI 스레드**에서 호출된다. Playwright를 직접 건드리지 말고
      `threading.Event` 등으로 작업 스레드에 신호만 보낸다.
    - `on_event`는 작업 스레드에서 불린다. 데스크톱이 Qt 시그널로 UI에 넘긴다.
    """

    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        """앱 전용 Chrome 프로필 폴더. 데스크톱이 정한다."""

    @abstractmethod
    def run(self, playbook: Playbook, on_event: EventCallback) -> AgentEvent:
        """탈퇴 화면까지 진행하고 마지막(종료 상태) 이벤트를 돌려준다.

        종료될 때까지 블로킹한다. `USER_TURN` 동안에는 `resume()` 또는 `stop()`을 기다린다.
        마지막 이벤트도 `on_event`로 한 번 보낸다. `REACHED`는 이벤트를 먼저 보내고, 사용자가 브라우저를
        닫거나 `stop()`이 올 때까지 기다렸다가 돌려준다 (사용자가 최종 버튼을 누를 시간).
        """

    @abstractmethod
    def resume(self) -> None:
        """사용자가 직접 처리를 마쳤다. `USER_TURN`이 아니면 무시한다."""

    @abstractmethod
    def stop(self) -> None:
        """진행을 멈추고 `STOPPED`로 끝내게 한다. 이미 끝났으면 무시한다."""

    @abstractmethod
    def clear_session(self, domains: tuple[str, ...] | None = None) -> None:
        """전용 프로필에서 로그인 세션(쿠키·저장소)을 지운다 (논의사항 D-05).

        `domains`가 None이면 전부 지운다. `run()`이 실행 중일 때는 호출되지 않는다.
        """
