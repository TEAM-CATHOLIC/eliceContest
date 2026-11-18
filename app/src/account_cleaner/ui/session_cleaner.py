"""전용 Chrome 프로필의 로그인 세션 정리 (#16, 논의사항 D-05).

- 탈퇴를 끝낸 서비스와 보관 기한(14일)이 지난 서비스의 세션을 지운다 (`StatusStore.sessions_to_clear`).
- '저장된 로그인 모두 지우기'는 전용 프로필 폴더를 통째로 지운다.
- 지우는 일은 작업 스레드에서 한다 (서비스별 정리는 Chrome을 화면 없이 잠깐 띄운다).
- 에이전트 안내가 진행 중이면 프로필이 사용 중이므로 지우지 않고, 안내가 끝난 뒤 다시 시도한다.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from account_cleaner.contracts import Playbook, WithdrawAgent
from account_cleaner.storage import StatusStore
from account_cleaner.ui.workers import BackgroundTask

log = logging.getLogger(__name__)

AgentFactory = Callable[[Path], WithdrawAgent]
PlaybookLookup = Callable[[str], Playbook | None]
BusyCheck = Callable[[], bool]


def cookie_domains(domain: str, playbook: Playbook | None) -> tuple[str, ...]:
    """후보 도메인과 그 서비스 플레이북에 적힌 도메인(로그인 도메인 포함)."""
    domains = [domain]
    if playbook is not None:
        domains += [*playbook.domains, *playbook.auth_domains]
    return tuple(dict.fromkeys(d.lower() for d in domains))


class SessionCleaner(QObject):
    cleared = Signal(list)
    """지운 서비스 도메인 목록. 모두 지웠으면 `["*"]`"""
    failed = Signal(str)
    """사용자에게 보여 줄 실패 설명"""

    ALL = "*"

    def __init__(
        self,
        store: StatusStore,
        profile_dir: Path,
        agent_factory: AgentFactory,
        playbook_lookup: PlaybookLookup,
        agent_busy: BusyCheck,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._profile_dir = profile_dir
        self._agent_factory = agent_factory
        self._playbook_lookup = playbook_lookup
        self._agent_busy = agent_busy
        self._task: BackgroundTask | None = None
        self._pending = False
        """정리할 것이 생겼지만 그때는 할 수 없었다 (안내 중·정리 중)"""

    def is_running(self) -> bool:
        return self._task is not None and self._task.is_running()

    def clear_due(self) -> bool:
        """지울 세션이 있으면 지우기 시작한다. 지금 할 수 없으면 나중으로 미루고 False."""
        if self._agent_busy() or self.is_running():
            self._pending = True
            return False
        self._pending = False
        due = self._store.sessions_to_clear()
        if not due:
            return False
        domains = tuple(
            d for domain in due for d in cookie_domains(domain, self._playbook_lookup(domain))
        )
        log.info("로그인 세션 정리: 서비스 %d곳", len(due))
        return self._start(domains, due)

    def clear_all(self) -> bool:
        """전용 프로필 통째로 삭제. 안내가 진행 중이면 하지 않고 False."""
        if self._agent_busy() or self.is_running():
            self.failed.emit(
                "안내가 진행 중이라 지금은 지울 수 없습니다. 안내를 마친 뒤 다시 눌러 주세요."
            )
            return False
        log.info("저장된 로그인 모두 지우기")
        return self._start(None, [self.ALL])

    def retry_pending(self) -> None:
        """에이전트 안내가 끝났을 때 부른다."""
        if self._pending:
            self.clear_due()

    def _start(self, domains: tuple[str, ...] | None, records: list[str]) -> bool:
        agent = self._agent_factory(self._profile_dir)

        def job(_ctx) -> list[str]:
            agent.clear_session(domains)
            return records

        self._task = BackgroundTask(job, name="session-cleanup", parent=self)
        self._task.succeeded.connect(self._on_succeeded)
        self._task.failed.connect(self._on_failed)
        self._task.finished.connect(self._on_finished)
        self._task.start()
        return True

    def _on_succeeded(self, records: list[str]) -> None:
        if records == [self.ALL]:
            self._store.clear_all_sessions()
        else:
            for domain in records:
                self._store.session_cleared(domain)
        self.cleared.emit(records)

    def _on_failed(self, error: BaseException) -> None:
        log.warning("로그인 세션 정리 실패: %r", error)
        self.failed.emit(
            f"저장된 로그인을 지우지 못했습니다 ({type(error).__name__}). 다음 실행 때 다시 시도합니다."
        )

    def _on_finished(self) -> None:
        self._task = None
        if self._pending:
            self.clear_due()
