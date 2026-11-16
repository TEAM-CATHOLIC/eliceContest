"""브라우저 에이전트가 오기 전까지 쓰는 가짜 에이전트. 브라우저를 띄우지 않고 상태만 순서대로 보낸다."""

import threading
from pathlib import Path

from account_cleaner.contracts import (
    AgentEvent,
    AgentStatus,
    AgentStep,
    EventCallback,
    HandoffReason,
    Playbook,
    WithdrawAgent,
)

STEP_TITLES = ("로그인", "탈퇴 메뉴 진입", "탈퇴 전 조건 확인")


class FakeWithdrawAgent(WithdrawAgent):
    """이동 → 로그인 넘겨주기 → (resume) → 이동 → 탈퇴 화면 도달.

    `fail_at_step`을 주면 그 단계에서 FAILED로 끝난다 (실패 화면 확인용).
    """

    def __init__(self, profile_dir: Path, step_delay: float = 0.5, fail_at_step: int | None = None):
        super().__init__(profile_dir)
        self.step_delay = step_delay
        self.fail_at_step = fail_at_step
        self.cleared: list[tuple[str, ...] | None] = []
        self._resume = threading.Event()
        self._stop = threading.Event()
        self._awaiting_user = False

    def run(self, playbook: Playbook, on_event: EventCallback) -> AgentEvent:
        try:
            return self._run_once(playbook, on_event)
        finally:
            # 시작할 때가 아니라 끝날 때 비운다 (시작 직전에 온 stop()을 잃지 않도록)
            self._resume.clear()
            self._stop.clear()
            self._awaiting_user = False

    def _run_once(self, playbook: Playbook, on_event: EventCallback) -> AgentEvent:
        login, menu, conditions = (
            AgentStep(i, len(STEP_TITLES), t) for i, t in enumerate(STEP_TITLES, start=1)
        )
        script = [
            AgentEvent(
                AgentStatus.NAVIGATING,
                f"{playbook.service} 로그인 페이지 여는 중",
                url=playbook.login_url,
                step=login,
            ),
            AgentEvent(
                AgentStatus.USER_TURN,
                "로그인해 주세요. 끝나면 '계속'을 누르세요.",
                reason=HandoffReason.LOGIN,
                url=playbook.login_url,
                step=login,
            ),
            AgentEvent(
                AgentStatus.NAVIGATING,
                "계정 설정 → 탈퇴 메뉴로 이동 중",
                url=playbook.withdraw_url,
                step=menu,
            ),
            AgentEvent(
                AgentStatus.REACHED,
                "탈퇴 화면에 도착했습니다. 조건을 확인하고 최종 버튼은 직접 누르세요.",
                url=playbook.withdraw_url,
                step=conditions,
            ),
        ]
        for step, event in enumerate(script):
            if step == self.fail_at_step:
                return self._finish(on_event, AgentEvent(AgentStatus.FAILED, "가짜 실패"))
            if self._stop.wait(self.step_delay):
                return self._finish(on_event, AgentEvent(AgentStatus.STOPPED, "중단했습니다."))
            if event.status.is_final:
                return self._finish(on_event, event)
            # resume()이 USER_TURN 이벤트 직후 바로 와도 놓치지 않도록 먼저 대기 상태로 둔다.
            self._awaiting_user = event.status is AgentStatus.USER_TURN
            on_event(event)
            if self._awaiting_user:
                while not self._resume.wait(0.05):
                    if self._stop.is_set():
                        return self._finish(
                            on_event, AgentEvent(AgentStatus.STOPPED, "중단했습니다.")
                        )
                self._awaiting_user = False
                self._resume.clear()
        raise AssertionError("unreachable")

    def _finish(self, on_event: EventCallback, event: AgentEvent) -> AgentEvent:
        on_event(event)
        return event

    def resume(self) -> None:
        if self._awaiting_user:
            self._resume.set()

    def stop(self) -> None:
        self._stop.set()

    def clear_session(self, domains: tuple[str, ...] | None = None) -> None:
        self.cleared.append(domains)
