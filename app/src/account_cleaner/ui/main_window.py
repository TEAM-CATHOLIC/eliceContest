"""메인 창: 왼쪽 사이드바 + 오른쪽 페이지 영역."""

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.workers import BackgroundTask

APP_TITLE = "계정 정리 AI 에이전트"


class PageId(StrEnum):
    IMPORT = "import"
    CANDIDATES = "candidates"
    PROGRESS = "progress"


PAGE_TITLES = {
    PageId.IMPORT: "메일 가져오기",
    PageId.CANDIDATES: "계정 후보",
    PageId.PROGRESS: "진행 현황",
}

_PLACEHOLDER_TEXT = {
    PageId.IMPORT: "메일 계정을 연결하거나 메일함 파일을 넣어 분석을 시작합니다.",
    PageId.CANDIDATES: "메일에서 찾은 계정 후보와 근거를 확인합니다.",
    PageId.PROGRESS: "서비스별 탈퇴 진행 상황과 재알림을 확인합니다.",
}


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


class MainWindow(QMainWindow):
    page_changed = Signal(str)
    """바뀐 페이지의 `PageId` 값"""

    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self._settings = settings
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 720)

        self._nav = QListWidget()
        self._nav.setFixedWidth(180)
        self._nav.setObjectName("sidebar")
        self._stack = QStackedWidget()
        self._pages: dict[PageId, QWidget] = {}

        for page_id in PageId:
            item = QListWidgetItem(PAGE_TITLES[page_id])
            item.setData(Qt.ItemDataRole.UserRole, page_id.value)
            self._nav.addItem(item)
            self.set_page(
                page_id, PlaceholderPage(PAGE_TITLES[page_id], _PLACEHOLDER_TEXT[page_id])
            )

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._nav)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._restore_state()

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
        start = PageId.IMPORT
        if self._settings:
            geometry = self._settings.window_geometry()
            if geometry is not None:
                self.restoreGeometry(geometry)
            saved = self._settings.get("window/last_page", PageId.IMPORT.value)
            if saved in PageId._value2member_map_:
                start = PageId(saved)
        self.show_page(start)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._settings:
            self._settings.set_window_geometry(self.saveGeometry())
            self._settings.sync()
        BackgroundTask.shutdown_all()
        super().closeEvent(event)
