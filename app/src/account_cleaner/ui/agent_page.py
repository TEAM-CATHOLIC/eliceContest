"""AI 에이전트 정리 화면 (#15, 디자인 초안 3번).

왼쪽: 서비스 선택, 단계 표시, 사용자 차례 안내(계속·중단), 진행 로그
오른쪽: 브라우저 상태. 브라우저는 앱 안에 넣지 않고 별도 Chrome 창으로 띄운다.

에이전트(`WithdrawAgent.run`)는 `BackgroundTask` 작업 스레드에서 돈다. 에이전트가 작업 스레드에서
보내는 이벤트는 `_EventRelay` 시그널로 UI 스레드에 넘긴다.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from account_cleaner import providers
from account_cleaner.contracts import AgentEvent, AgentStatus, Playbook, WithdrawAgent
from account_cleaner.ui.workers import BackgroundTask

FINAL_STEP_TITLE = "최종 탈퇴 (직접)"
DEMO_KEY = "__local_demo__"
SAFETY_RULE = "비밀번호 입력과 최종 탈퇴 클릭은 사용자가 직접 합니다"

STATUS_TEXT = {
    AgentStatus.NAVIGATING: "Chrome 창에서 진행 중",
    AgentStatus.USER_TURN: "사용자 차례 — Chrome 창에서 직접 처리하세요",
    AgentStatus.REACHED: "탈퇴 화면 도착 — 최종 버튼은 직접 누르세요",
    AgentStatus.STOPPED: "중단했습니다",
    AgentStatus.FAILED: "진행하지 못했습니다",
}

# 단계 행 앞 표시
DONE, CURRENT, WAITING, PENDING, LOCKED = "✓", "▶", "⏸", "○", "🔒"

AgentFactory = Callable[[Path], WithdrawAgent]
PlaybookLoader = Callable[[], dict[str, Playbook]]


class _EventRelay(QObject):
    """작업 스레드 → UI 스레드. UI 스레드에서 만들었으므로 emit은 큐 연결로 UI 스레드에서 처리된다."""

    event = Signal(object)


class StepList(QListWidget):
    """에이전트 단계 표시. 단계 제목은 이벤트(`AgentEvent.step`)로 알게 된 것만 채운다."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("agentSteps")
        self._titles: dict[int, str] = {}
        self._total = 0
        self.restart()

    def restart(self) -> None:
        self._titles.clear()
        self._total = 0
        self._render(current=0, marker=CURRENT)

    def update_from(self, event: AgentEvent) -> None:
        if event.step is None:
            return
        self._total = event.step.total
        self._titles[event.step.index] = event.step.title
        if event.status is AgentStatus.REACHED:
            self._render(current=self._total + 1, marker=CURRENT)
        elif event.status is AgentStatus.USER_TURN:
            self._render(current=event.step.index, marker=WAITING)
        else:
            self._render(current=event.step.index, marker=CURRENT)

    def _render(self, current: int, marker: str) -> None:
        self.clear()
        for index in range(1, self._total + 1):
            title = self._titles.get(index, f"단계 {index}")
            if index < current:
                prefix = DONE
            elif index == current:
                prefix = marker
            else:
                prefix = PENDING
            self.addItem(QListWidgetItem(f"{prefix}  {index}. {title}"))
        reached = current > self._total and self._total > 0
        final = QListWidgetItem(f"{CURRENT if reached else LOCKED}  {FINAL_STEP_TITLE}")
        self.addItem(final)

    def rows(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())]


class AgentPage(QWidget):
    run_finished = Signal(object)
    """마지막 `AgentEvent` (종료 상태)"""

    def __init__(
        self,
        profile_dir: Path,
        agent_factory: AgentFactory = providers.get_withdraw_agent,
        playbook_loader: PlaybookLoader = providers.get_playbooks,
        include_demo: bool = True,
    ) -> None:
        super().__init__()
        self._profile_dir = profile_dir
        self._agent_factory = agent_factory
        self._playbooks = playbook_loader()
        self._include_demo = include_demo
        self._agent: WithdrawAgent | None = None
        self._task: BackgroundTask | None = None
        self._demo_server = None
        self._relay = _EventRelay(self)
        self._relay.event.connect(self._on_event)
        self._build()
        self._set_running(False)

    # --- 화면 구성 ---

    def _build(self) -> None:
        title = QLabel("AI 에이전트 정리")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        rule = QLabel(f"AI 통제 규칙: {SAFETY_RULE}")
        rule.setObjectName("safetyRule")
        rule.setWordWrap(True)

        self.service_combo = QComboBox()
        for key, playbook in sorted(self._playbooks.items(), key=lambda kv: kv[1].service):
            self.service_combo.addItem(playbook.service, key)
        if self._include_demo:
            self.service_combo.addItem("안전 데모 (로컬)", DEMO_KEY)
        self.start_button = QPushButton("안내 시작")
        self.start_button.clicked.connect(self.start)
        chooser = QHBoxLayout()
        chooser.addWidget(self.service_combo, 1)
        chooser.addWidget(self.start_button)

        self.steps = StepList()

        self.turn_box = QFrame()
        self.turn_box.setObjectName("userTurn")
        self.turn_box.setFrameShape(QFrame.Shape.StyledPanel)
        self.turn_label = QLabel()
        self.turn_label.setWordWrap(True)
        self.resume_button = QPushButton("직접 처리했어요, 계속")
        self.resume_button.clicked.connect(self.resume)
        turn = QVBoxLayout(self.turn_box)
        turn.addWidget(self.turn_label)
        turn.addWidget(self.resume_button)
        self.turn_box.hide()

        self.stop_button = QPushButton("안내 중단")
        self.stop_button.clicked.connect(self.stop)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("agentLog")
        self.log_view.setReadOnly(True)

        left = QVBoxLayout()
        left.addLayout(chooser)
        left.addWidget(QLabel("진행 단계"))
        left.addWidget(self.steps, 2)
        left.addWidget(self.turn_box)
        left.addWidget(self.stop_button)
        left.addWidget(QLabel("진행 로그"))
        left.addWidget(self.log_view, 2)

        self.status_label = QLabel("서비스를 고르고 안내를 시작하세요")
        self.status_label.setObjectName("browserStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.url_label = QLabel("")
        self.url_label.setObjectName("browserUrl")
        self.url_label.setWordWrap(True)
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.front_button = QPushButton("Chrome 창 앞으로 가져오기")
        self.front_button.clicked.connect(self.bring_to_front)
        note = QLabel(
            "브라우저는 앱 안이 아니라 별도 Chrome 창(앱 전용 프로필)으로 열립니다. "
            "로그인과 인증은 그 창에서 직접 하세요."
        )
        note.setWordWrap(True)

        right_box = QFrame()
        right_box.setObjectName("browserPanel")
        right_box.setFrameShape(QFrame.Shape.StyledPanel)
        right = QVBoxLayout(right_box)
        right.addWidget(self.status_label)
        right.addWidget(self.url_label)
        right.addWidget(self.front_button)
        right.addWidget(note)
        right.addStretch(1)

        columns = QHBoxLayout()
        columns.addLayout(left, 2)
        columns.addWidget(right_box, 3)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(rule)
        layout.addLayout(columns, 1)

    # --- 실행 ---

    def is_running(self) -> bool:
        return self._task is not None and self._task.is_running()

    def start(self) -> None:
        if self.is_running():
            return
        playbook = self._selected_playbook()
        self.steps.restart()
        self.log_view.clear()
        self.turn_box.hide()
        self.url_label.clear()
        self._log(f"{playbook.service} 안내를 시작합니다")
        agent = self._agent_factory(self._profile_dir)
        self._agent = agent

        def job(ctx) -> AgentEvent:
            return agent.run(playbook, self._relay.event.emit)

        self._task = BackgroundTask(
            job, name=f"agent:{playbook.id}", parent=self, on_cancel=agent.stop
        )
        self._task.failed.connect(self._on_task_failed)
        self._task.finished.connect(self._on_task_finished)
        self._set_running(True)
        self._task.start()

    def _selected_playbook(self) -> Playbook:
        key = self.service_combo.currentData()
        if key == DEMO_KEY:
            from account_cleaner.browser.demo import demo_playbook, start_demo_server

            self._stop_demo_server()
            self._demo_server = start_demo_server()
            return demo_playbook(self._demo_server.server_address[1])
        return self._playbooks[key]

    def playbook_for_domain(self, domain: str) -> Playbook | None:
        """계정 후보 도메인에 맞는 플레이북 (상세 패널의 'AI 에이전트로 탈퇴 진행' 활성화에 씀)."""
        return next((p for p in self._playbooks.values() if p.matches_domain(domain)), None)

    def start_for(self, playbook_id: str) -> bool:
        """그 서비스를 골라 바로 안내를 시작한다. 이미 진행 중이면 False."""
        if self.is_running():
            return False
        index = self.service_combo.findData(playbook_id)
        if index < 0:
            return False
        self.service_combo.setCurrentIndex(index)
        self.start()
        return True

    def resume(self) -> None:
        if self._agent is not None:
            self.turn_box.hide()
            self._log("사용자가 처리를 마쳤습니다. 이어서 진행합니다")
            self._agent.resume()

    def stop(self) -> None:
        if self._task is not None and self.is_running():
            self._log("중단을 요청했습니다")
            self._task.cancel()

    def bring_to_front(self) -> None:
        if self._agent is not None and self.is_running():
            self._agent.bring_to_front()

    # --- 이벤트 (UI 스레드) ---

    def _on_event(self, event: AgentEvent) -> None:
        self.steps.update_from(event)
        self.status_label.setText(STATUS_TEXT[event.status])
        if event.url:
            self.url_label.setText(event.url)
        if event.message:
            self._log(event.message)
        if event.status is AgentStatus.USER_TURN:
            self.turn_label.setText(event.message)
            self.turn_box.show()
        else:
            self.turn_box.hide()
        if event.status is AgentStatus.REACHED:
            self._log("Chrome 창을 닫으면 안내가 끝납니다")
        if event.status.is_final:
            self.run_finished.emit(event)

    def _on_task_failed(self, error: BaseException) -> None:
        self._log(f"오류로 멈췄습니다: {type(error).__name__}")
        self.status_label.setText(STATUS_TEXT[AgentStatus.FAILED])

    def _on_task_finished(self) -> None:
        self._task = None
        self._agent = None
        self.turn_box.hide()
        self._stop_demo_server()
        self._set_running(False)

    # --- 기타 ---

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.service_combo.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.front_button.setEnabled(running)

    def _stop_demo_server(self) -> None:
        if self._demo_server is not None:
            self._demo_server.shutdown()
            self._demo_server = None

    def _log(self, message: str) -> None:
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {message}")

    def log_lines(self) -> list[str]:
        return self.log_view.toPlainText().splitlines()
