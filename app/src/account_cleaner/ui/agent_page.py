"""AI 에이전트 정리 화면 (#15, 디자인 초안 3번).

왼쪽: 서비스 선택, 단계 표시, 사용자 차례 안내(계속·중단), 진행 로그
오른쪽: 브라우저 상태. 브라우저는 앱 안에 넣지 않고 별도 Chrome 창으로 띄운다.

에이전트(`WithdrawAgent.run`)는 `BackgroundTask` 작업 스레드에서 돈다. 에이전트가 작업 스레드에서
보내는 이벤트는 `_EventRelay` 시그널로 UI 스레드에 넘긴다.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from account_cleaner import providers
from account_cleaner.browser.agent.llm import llm_available
from account_cleaner.contracts import (
    AccountCandidate,
    AgentEvent,
    AgentStatus,
    Playbook,
    WithdrawAgent,
)
from account_cleaner.contracts.login import LoginMethod
from account_cleaner.ui.theme import page_header, page_layout, section_card, set_role, tokens
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
GenericAvailability = Callable[[], bool]


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


CandidateLookup = Callable[[str], AccountCandidate | None]
"""도메인 → 인벤토리 후보 (없으면 None)"""


class AgentPage(QWidget):
    run_finished = Signal(object)
    """마지막 `AgentEvent` (종료 상태)"""

    def __init__(
        self,
        profile_dir: Path,
        agent_factory: AgentFactory = providers.get_withdraw_agent,
        playbook_loader: PlaybookLoader = providers.get_playbooks,
        include_demo: bool = True,
        generic_available: GenericAvailability = llm_available,
    ) -> None:
        super().__init__()
        self._profile_dir = profile_dir
        self._agent_factory = agent_factory
        self._playbooks = playbook_loader()
        self._include_demo = include_demo
        self._generic_available = generic_available
        self._agent: WithdrawAgent | None = None
        self._task: BackgroundTask | None = None
        self._demo_server = None
        self.guide_dialog = None
        self._candidate_lookup: CandidateLookup = lambda _domain: None
        self._private_values: tuple[str, ...] = ()
        self.current_domain: str | None = None
        """후보 상세에서 시작한 안내일 때 그 후보의 도메인 (결과 기록용)"""
        self._relay = _EventRelay(self)
        self._relay.event.connect(self._on_event)
        self._build()
        self._set_running(False)

    # --- 화면 구성 ---

    def _build(self) -> None:
        title = QLabel("AI 에이전트 정리")
        title.setObjectName("pageTitle")
        rule = QLabel(f"AI 통제 규칙: {SAFETY_RULE}")
        rule.setObjectName("safetyRule")

        # 위: 서비스 고르기 + 시작·중단
        self.service_combo = QComboBox()
        for key, playbook in sorted(self._playbooks.items(), key=lambda kv: kv[1].service):
            self.service_combo.addItem(playbook.service, key)
        if self._include_demo:
            self.service_combo.addItem("안전 데모 (로컬)", DEMO_KEY)
        self.start_button = set_role(QPushButton("안내 시작"), "variant", "primary")
        self.start_button.setMinimumWidth(120)
        self.start_button.clicked.connect(self.request_start)
        self.stop_button = QPushButton("안내 중단")
        self.stop_button.clicked.connect(self.stop)
        control_card, control = section_card()
        chooser = QHBoxLayout()
        chooser.setSpacing(tokens.SPACE_2)
        chooser.addWidget(self.service_combo, 1)
        chooser.addWidget(self.start_button)
        chooser.addWidget(self.stop_button)
        control.addLayout(chooser)

        # 왼쪽: 진행 단계 (+ 사용자 차례 알림)
        self.steps = StepList()
        self.steps.setMinimumHeight(160)
        self.turn_box, turn = section_card(kind="warning")
        self.turn_box.setObjectName("userTurn")
        self.turn_label = set_role(QLabel(), "role", "label")
        self.turn_label.setWordWrap(True)
        self.resume_button = set_role(QPushButton("직접 처리했어요, 계속"), "variant", "primary")
        self.resume_button.clicked.connect(self.resume)
        turn.addWidget(self.turn_label)
        turn.addWidget(self.resume_button)
        self.turn_box.hide()
        steps_card, steps = section_card("진행 단계")
        steps.addWidget(self.turn_box)
        steps.addWidget(self.steps, 1)

        # 오른쪽: Chrome 창 상태 + 진행 로그
        self.status_label = QLabel("서비스를 고르고 안내를 시작하세요")
        self.status_label.setObjectName("browserStatus")
        self.status_label.setWordWrap(True)
        set_role(self.status_label, "role", "subtitle")
        self.url_label = set_role(QLabel(""), "role", "caption")
        self.url_label.setObjectName("browserUrl")
        self.url_label.setWordWrap(True)
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.front_button = QPushButton("Chrome 창 앞으로 가져오기")
        self.front_button.clicked.connect(self.bring_to_front)
        note = set_role(
            QLabel(
                "브라우저는 앱 안이 아니라 별도 Chrome 창(앱 전용 프로필)으로 열립니다. "
                "로그인과 인증은 그 창에서 직접 하세요."
            ),
            "role",
            "muted",
        )
        note.setWordWrap(True)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("agentLog")
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("안내를 시작하면 진행 상황이 여기에 쌓입니다.")
        right_box, right = section_card()
        right_box.setObjectName("browserPanel")
        right.addWidget(self.status_label)
        right.addWidget(self.url_label)
        right.addWidget(note)
        right.addWidget(self.front_button, 0, Qt.AlignmentFlag.AlignLeft)
        right.addSpacing(tokens.SPACE_1)
        right.addWidget(set_role(QLabel("진행 로그"), "role", "label"))
        right.addWidget(self.log_view, 1)

        columns = QHBoxLayout()
        columns.setSpacing(tokens.SPACE_3)
        columns.addWidget(steps_card, 2)
        columns.addWidget(right_box, 3)

        layout = page_layout(self)
        layout.addLayout(page_header(title, rule))
        layout.addWidget(control_card)
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
        known = next((p for p in self._playbooks.values() if p.matches_domain(domain)), None)
        if known is not None:
            if known.id.startswith("generic:") and known.private_values != self._private_values:
                known = replace(known, private_values=self._private_values)
                self._playbooks[known.id] = known
            return known
        domain = domain.strip().lower().rstrip(".")
        if not self._generic_available() or not domain or any(c in domain for c in "/:@"):
            return None
        playbook_id = f"generic:{domain}"
        generic = self._playbooks.get(playbook_id)
        if generic is None:
            url = f"https://{domain}"
            generic = Playbook(
                id=playbook_id,
                service=domain,
                domains=(domain,),
                login_methods=(LoginMethod.EMAIL,),
                login_url=url,
                password_reset_url=url,
                withdraw_url=url,
                steps=(),
                private_values=self._private_values,
            )
            self._playbooks[playbook_id] = generic
            self.service_combo.addItem(f"{domain} · AI 실험", playbook_id)
        return generic

    def set_private_values(self, values: tuple[str, ...]) -> None:
        """메일 연결에서 확인한 사용자 식별자를 LLM 마스킹에만 전달한다."""
        cleaned = tuple(dict.fromkeys(value.strip() for value in values if len(value.strip()) >= 2))
        self._private_values = cleaned
        for key, playbook in tuple(self._playbooks.items()):
            if key.startswith("generic:"):
                self._playbooks[key] = replace(playbook, private_values=cleaned)

    def set_candidate_lookup(self, lookup: CandidateLookup) -> None:
        """안내 창에 메일에서 찾은 가입 방식을 보여 주려고 인벤토리 후보를 찾는다."""
        self._candidate_lookup = lookup

    def request_start(self) -> None:
        """`안내 시작` 버튼. 인벤토리와 같은 안내 창(로그인 방법 + 탈퇴 전 확인)을 거친다 (#70).

        연습용 `안전 데모`는 바로 시작한다. 인벤토리·진행 기록에서 온 안내는 이미 확인했으므로
        `start_for`로 바로 시작한다.
        """
        if self.is_running():
            return
        key = self.service_combo.currentData()
        if key == DEMO_KEY:
            self.start()
            return
        from account_cleaner.ui.candidates.guide import WithdrawGuideDialog

        playbook = self._playbooks[key]
        candidate = next(
            (c for d in playbook.domains if (c := self._candidate_lookup(d)) is not None), None
        )
        if self.guide_dialog is not None:
            self.guide_dialog.close()
        dialog = WithdrawGuideDialog(candidate, playbook, self)
        dialog.agent_requested.connect(lambda _candidate: self.start())
        self.guide_dialog = dialog
        dialog.open()

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
