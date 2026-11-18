"""진행 기록 화면 (#16, PRD F-08, 디자인 초안 사이드바 '진행 기록').

- 위: 지금 다시 알려야 할 서비스(재알림). 다시 안내 / 14일 뒤 다시 알림 / 탈퇴를 끝냈어요.
- 가운데: 서비스별 진행 상태 (에이전트 안내를 시작한 서비스).
- 아래: 언제 무엇을 했는지 (최근 일부터).

메일 내용은 보여 주지 않는다. 저장소(`StatusStore`)에 있는 서비스 이름·상태·시각만 쓴다.
"""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from account_cleaner.contracts import AgentStatus
from account_cleaner.storage import EventKind, HistoryEvent, Progress, StatusStore
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.theme import page_header, page_layout, section_card, set_role, tokens

RESULT_LABELS = {
    "started": "안내 중",
    AgentStatus.REACHED.value: "탈퇴 화면 도착 (최종 버튼은 직접)",
    AgentStatus.STOPPED.value: "중단",
    AgentStatus.FAILED.value: "진행 불가",
}
COLUMNS = ("서비스", "도메인", "상태", "시작", "최근", "재알림")
EMPTY_TEXT = "아직 진행한 탈퇴가 없습니다. 계정 인벤토리에서 후보를 골라 안내를 시작하세요."


def short_time(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else "-"


def progress_label(progress: Progress) -> str:
    if progress.completed_at is not None:
        return "완료"
    return RESULT_LABELS.get(progress.last_result, progress.last_result)


def event_text(event: HistoryEvent) -> str:
    """진행 기록 한 줄. 예: "2026-11-18 09:30  GitHub — 안내 시작" """
    if event.kind is EventKind.LABEL:
        known = event.detail in CandidateStatus._value2member_map_
        what = f"'{CandidateStatus(event.detail).label if known else event.detail}'(으)로 표시"
    elif event.kind is EventKind.FINISHED:
        what = f"안내 끝: {RESULT_LABELS.get(event.detail, event.detail)}"
    elif event.kind is EventKind.SNOOZED:
        what = f"재알림을 {event.detail}일 뒤로 미룸"
    else:
        what = {
            EventKind.STARTED: "안내 시작",
            EventKind.COMPLETED: "탈퇴를 끝냈다고 확인",
            EventKind.SESSION_CLEARED: "저장된 로그인 삭제",
            EventKind.ALL_SESSIONS_CLEARED: "저장된 로그인 모두 삭제",
        }[event.kind]
    return f"{short_time(event.at)}  {event.service} — {what}"


class HistoryPage(QWidget):
    restart_requested = Signal(str)
    """재알림에서 '다시 안내'를 누른 서비스 도메인"""
    done_requested = Signal(str)
    """재알림에서 '탈퇴를 끝냈어요'를 누른 서비스 도메인"""

    def __init__(self, store: StatusStore) -> None:
        super().__init__()
        self._store = store
        self._build()
        self.refresh()

    def _build(self) -> None:
        title = QLabel("진행 기록")
        title.setObjectName("pageTitle")
        subtitle = QLabel("탈퇴 안내를 어디까지 했는지, 언제 무엇을 했는지 모아 봅니다.")

        # 다시 알려 줄 서비스 (노란 알림 카드)
        self.reminder_box, box = section_card(kind="warning")
        self.reminder_box.setObjectName("reminderBox")
        self.reminder_title = set_role(QLabel(), "role", "label")
        self.reminder_title.setWordWrap(True)
        self.reminder_list = QListWidget()
        self.reminder_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.reminder_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.restart_button = set_role(QPushButton("다시 안내 시작"), "variant", "primary")
        self.restart_button.clicked.connect(lambda: self._emit_selected(self.restart_requested))
        self.snooze_button = QPushButton("14일 뒤 다시 알림")
        self.snooze_button.clicked.connect(self.snooze_selected)
        self.done_button = QPushButton("탈퇴를 끝냈어요")
        self.done_button.clicked.connect(lambda: self._emit_selected(self.done_requested))
        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.SPACE_2)
        for button in (self.restart_button, self.snooze_button, self.done_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        box.addWidget(self.reminder_title)
        box.addWidget(self.reminder_list)
        box.addLayout(buttons)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("progressTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        self.empty_label = set_role(QLabel(EMPTY_TEXT), "role", "muted")
        self.empty_label.setWordWrap(True)
        table_card, table = section_card("서비스별 진행")
        table.addWidget(self.empty_label)
        table.addWidget(self.table, 1)

        self.event_list = QListWidget()
        self.event_list.setObjectName("eventList")
        self.event_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.event_list.setWordWrap(True)
        events_card, events = section_card("언제 무엇을 했는지")
        events.addWidget(self.event_list, 1)

        layout = page_layout(self)
        layout.addLayout(page_header(title, subtitle))
        layout.addWidget(self.reminder_box)
        layout.addWidget(table_card, 3)
        layout.addWidget(events_card, 2)
        events_card.setMinimumHeight(160)

    # --- 표시 ---

    def refresh(self) -> None:
        """저장소에서 다시 읽는다 (화면이 보일 때, 진행이 바뀔 때)."""
        reminders = self._store.reminders()
        self._fill_reminders()
        self._fill_table(self._store.all_progress(), reminders)
        self.event_list.clear()
        for event in self._store.history():
            self.event_list.addItem(event_text(event))

    def due_domains(self) -> list[str]:
        return [
            self.reminder_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.reminder_list.count())
        ]

    def _fill_reminders(self) -> None:
        due = self._store.due_reminders()
        services = {p.domain: p.service for p in self._store.all_progress()}
        self.reminder_list.clear()
        for domain in due:
            item = QListWidgetItem(f"{services.get(domain, domain)} ({domain})")
            item.setData(Qt.ItemDataRole.UserRole, domain)
            self.reminder_list.addItem(item)
        self.reminder_box.setVisible(bool(due))
        self.reminder_title.setText(
            f"탈퇴 화면까지 갔지만 아직 끝내지 않은 서비스가 {len(due)}곳 있어요. "
            "최종 탈퇴 버튼을 누르셨나요?"
        )
        rows = sum(self.reminder_list.sizeHintForRow(i) for i in range(len(due)))
        self.reminder_list.setFixedHeight(min(rows, 160) + 2 * self.reminder_list.frameWidth() + 2)
        if due:
            self.reminder_list.setCurrentRow(0)
        self._update_buttons()

    def _fill_table(self, progress: list[Progress], reminders: dict[str, datetime]) -> None:
        self.table.setRowCount(len(progress))
        for row, p in enumerate(progress):
            values = (
                p.service,
                p.domain,
                progress_label(p),
                short_time(p.started_at),
                short_time(p.updated_at),
                short_time(reminders.get(p.domain)) if p.completed_at is None else "-",
            )
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.empty_label.setVisible(not progress)
        self.table.setVisible(bool(progress))
        # 5줄까지는 표 안에서 스크롤하지 않도록 높이를 확보한다 (그 이상은 스크롤)
        shown = min(len(progress), 5)
        self.table.setMinimumHeight(
            self.table.horizontalHeader().sizeHint().height()
            + shown * self.table.verticalHeader().defaultSectionSize()
            + 2 * self.table.frameWidth()
            + 2
        )

    def _selected_domain(self) -> str | None:
        item = self.reminder_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        selected = self._selected_domain() is not None
        for button in (self.restart_button, self.snooze_button, self.done_button):
            button.setEnabled(selected)

    # --- 동작 ---

    def _emit_selected(self, signal) -> None:
        domain = self._selected_domain()
        if domain is not None:
            signal.emit(domain)

    def snooze_selected(self) -> None:
        domain = self._selected_domain()
        if domain is not None:
            self._store.snooze_reminder(domain)
            self.refresh()

    def showEvent(self, event: QShowEvent) -> None:
        self.refresh()
        super().showEvent(event)
