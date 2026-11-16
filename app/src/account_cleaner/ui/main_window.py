"""메인 창 (디자인 초안 기준 틀).

┌────────────┬──────────────────────────────────────────┐
│ 앱 이름     │ [검색창                ]  [상태 표시]     │  ← 위쪽 막대
├────────────┼──────────────────────────────────────────┤
│ 사이드바    │                                          │
│  메뉴 4개   │  페이지 영역 (QStackedWidget)              │
│            │                                          │
│ 엔진 암호화 │                                          │
│ [로그인 지우기]                                        │
└────────────┴──────────────────────────────────────────┘
"""

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.workers import BackgroundTask

APP_TITLE = "계정 정리 AI 에이전트"
SIDEBAR_WIDTH = 220


class PageId(StrEnum):
    """사이드바 순서대로."""

    INVENTORY = "inventory"
    AGENT = "agent"
    SOURCES = "sources"
    HISTORY = "history"


PAGE_TITLES = {
    PageId.INVENTORY: "계정 인벤토리",
    PageId.AGENT: "AI 에이전트 정리",
    PageId.SOURCES: "메일 소스 연결",
    PageId.HISTORY: "진행 기록",
}

_PLACEHOLDER_TEXT = {
    PageId.INVENTORY: "메일에서 찾은 계정 후보와 근거를 확인합니다.",
    PageId.AGENT: "에이전트가 탈퇴 화면까지 안내합니다. 최종 탈퇴 버튼은 직접 누릅니다.",
    PageId.SOURCES: "메일 계정을 연결하거나 메일함 파일을 넣어 분석을 시작합니다.",
    PageId.HISTORY: "서비스별 진행 이력과 재알림을 확인합니다.",
}

FIRST_RUN_PAGE = PageId.SOURCES
"""저장된 마지막 페이지가 없을 때 (처음 실행)"""

DEFAULT_STATUS_TEXT = "메일 외부 전송 0건 · 로컬 분류기"


class PlaceholderPage(QWidget):
    """아직 구현되지 않은 페이지 자리."""

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        body = QLabel(text)
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)


class SidebarFooter(QFrame):
    """사이드바 아래: 상태 줄(엔진 암호화 등)과 "저장된 로그인 모두 지우기" (D-05)."""

    clear_logins_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebarFooter")
        layout = QVBoxLayout(self)
        self._form = QFormLayout()
        self._rows: dict[str, QLabel] = {}
        layout.addLayout(self._form)
        self.clear_logins_button = QPushButton("저장된 로그인 모두 지우기")
        self.clear_logins_button.clicked.connect(self.clear_logins_requested)
        layout.addWidget(self.clear_logins_button)
        self.set_status("엔진 암호화", "미정")

    def set_status(self, name: str, value: str) -> None:
        """상태 줄을 추가하거나 값을 바꾼다."""
        label = self._rows.get(name)
        if label is None:
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._rows[name] = label
            self._form.addRow(name, label)
        label.setText(value)

    def status(self, name: str) -> str:
        return self._rows[name].text()


class TopBar(QFrame):
    """위쪽 막대: 검색창과 상태 표시."""

    search_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("topBar")
        layout = QHBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("서비스명, 도메인 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed)
        self.status = QLabel(DEFAULT_STATUS_TEXT)
        self.status.setObjectName("statusPill")
        layout.addWidget(self.search, 1)
        layout.addWidget(self.status)


class MainWindow(QMainWindow):
    page_changed = Signal(str)
    """바뀐 페이지의 `PageId` 값"""

    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self._settings = settings
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)

        self._nav = QListWidget()
        self._nav.setObjectName("sidebar")
        self._stack = QStackedWidget()
        self._pages: dict[PageId, QWidget] = {}
        self.top_bar = TopBar()
        self.sidebar_footer = SidebarFooter()

        for page_id in PageId:
            item = QListWidgetItem(PAGE_TITLES[page_id])
            item.setData(Qt.ItemDataRole.UserRole, page_id.value)
            self._nav.addItem(item)
            self.set_page(
                page_id, PlaceholderPage(PAGE_TITLES[page_id], _PLACEHOLDER_TEXT[page_id])
            )

        self.setCentralWidget(self._build_layout())
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._restore_state()

    def _build_layout(self) -> QWidget:
        app_name = QLabel(APP_TITLE)
        app_name.setObjectName("appName")
        app_name.setStyleSheet("font-size: 16px; font-weight: 600; padding: 12px;")

        sidebar = QWidget()
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(app_name)
        side.addWidget(self._nav, 1)
        side.addWidget(self.sidebar_footer)

        content = QWidget()
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.top_bar)
        right.addWidget(self._stack, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        return central

    # 페이지
    def set_page(self, page_id: PageId, widget: QWidget) -> None:
        """페이지 위젯을 등록하거나 자리표시 페이지를 실제 페이지로 바꾼다."""
        old = self._pages.get(page_id)
        index = list(PageId).index(page_id)
        if old is not None:
            self._stack.removeWidget(old)
            old.deleteLater()
        self._stack.insertWidget(index, widget)
        self._pages[page_id] = widget
        if self._nav.currentRow() == index:
            self._stack.setCurrentIndex(index)

    def page(self, page_id: PageId) -> QWidget:
        return self._pages[page_id]

    def show_page(self, page_id: PageId) -> None:
        self._nav.setCurrentRow(list(PageId).index(page_id))

    def current_page(self) -> PageId:
        return list(PageId)[max(self._stack.currentIndex(), 0)]

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self._stack.setCurrentIndex(row)
        page_id = list(PageId)[row]
        if self._settings:
            self._settings.set("window/last_page", page_id.value)
        self.page_changed.emit(page_id.value)

    # 창 상태
    def _restore_state(self) -> None:
        start = FIRST_RUN_PAGE
        if self._settings:
            geometry = self._settings.window_geometry()
            if geometry is not None:
                self.restoreGeometry(geometry)
            saved = self._settings.get("window/last_page", FIRST_RUN_PAGE.value)
            if saved in PageId._value2member_map_:
                start = PageId(saved)
        self.show_page(start)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._settings:
            self._settings.set_window_geometry(self.saveGeometry())
            self._settings.sync()
        BackgroundTask.shutdown_all()
        super().closeEvent(event)
