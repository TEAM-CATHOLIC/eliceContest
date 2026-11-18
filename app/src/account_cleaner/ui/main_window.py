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

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.theme import Icon, icon, pixmap, set_role, tokens
from account_cleaner.ui.workers import BackgroundTask

APP_TITLE = "계정 정리 AI 에이전트"
SIDEBAR_WIDTH = 236


class PageId(StrEnum):
    """사이드바 순서대로."""

    INVENTORY = "inventory"
    AGENT = "agent"
    SOURCES = "sources"
    HISTORY = "history"


PAGE_ICONS = {
    PageId.INVENTORY: Icon.INVENTORY,
    PageId.AGENT: Icon.AGENT,
    PageId.SOURCES: Icon.SOURCES,
    PageId.HISTORY: Icon.HISTORY,
}

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
        heading = set_role(QLabel(title), "role", "title")
        heading.setObjectName("pageTitle")
        body = set_role(QLabel(text), "role", "muted")
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)


class SidebarFooter(QFrame):
    """사이드바 아래 카드: 상태 줄(엔진 암호화 등)과 "저장된 로그인 모두 지우기" (D-05)."""

    clear_logins_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("sidebarFooter")
        set_role(self, "card", "true")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_4, 14, tokens.SPACE_4, tokens.SPACE_4)
        layout.setSpacing(tokens.SPACE_2)
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE_2)
        lock = QLabel()
        lock.setPixmap(pixmap(Icon.LOCK, tokens.GREEN[1], 16))
        head.addWidget(lock)
        head.addWidget(set_role(QLabel("이 PC 안에서만 처리"), "role", "label"), 1)
        layout.addLayout(head)
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(2)
        self._rows: dict[str, QLabel] = {}
        layout.addLayout(self._rows_box)
        layout.addSpacing(tokens.SPACE_1)
        self.clear_logins_button = QPushButton("저장된 로그인 모두 지우기")
        self.clear_logins_button.setToolTip(
            "AI 안내용 Chrome에 남은 로그인을 지웁니다. 평소 쓰는 Chrome은 그대로입니다."
        )
        self.clear_logins_button.clicked.connect(self.clear_logins_requested)
        layout.addWidget(self.clear_logins_button)
        self.set_status("엔진 암호화", "미정")

    def set_status(self, name: str, value: str) -> None:
        """상태 줄(이름 / 값 두 줄)을 추가하거나 값을 바꾼다. 값은 줄바꿈되므로 길어도 잘리지 않는다."""
        label = self._rows.get(name)
        if label is None:
            self._rows_box.addWidget(set_role(QLabel(name), "role", "caption"))
            label = set_role(QLabel(), "role", "muted")
            label.setWordWrap(True)
            self._rows[name] = label
            self._rows_box.addWidget(label)
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
        layout.setContentsMargins(tokens.SPACE_1, 0, tokens.SPACE_1, 0)
        layout.setSpacing(tokens.SPACE_4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("서비스 이름이나 도메인 검색")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(360)
        self.search.addAction(
            icon(Icon.SEARCH, tokens.GRAY_700, 16), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.textChanged.connect(self.search_changed)
        self.status = set_role(QLabel(DEFAULT_STATUS_TEXT), "role", "caption")
        self.status.setObjectName("statusPill")
        layout.addWidget(self.search, 1)
        layout.addStretch(0)
        layout.addWidget(self.status)


class Brand(QWidget):
    """사이드바 맨 위: 방패 아이콘 + 앱 이름."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, tokens.SPACE_1, 10, 18)
        layout.setSpacing(10)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(32, 32)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(pixmap(Icon.SHIELD, tokens.ON_ACCENT, 18))
        mark.setStyleSheet(f"background: {tokens.ACCENT}; border-radius: 10px;")
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(set_role(QLabel("계정 정리"), "role", "subtitle"))
        names.addWidget(set_role(QLabel("AI 에이전트"), "role", "caption"))
        layout.addWidget(mark)
        layout.addLayout(names, 1)


class NavDelegate(QStyledItemDelegate):
    """사이드바 메뉴 한 줄: 아이콘 + 이름 + (있으면) 숫자 배지. 고른 메뉴는 흰 바탕 + 메인 색."""

    HEIGHT = 40
    GAP = 4
    BADGE_ROLE = Qt.ItemDataRole.UserRole + 1
    TONE_ROLE = Qt.ItemDataRole.UserRole + 2

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(option.rect.width(), self.HEIGHT + self.GAP)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        rect = option.rect.adjusted(0, 0, 0, -self.GAP)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected:
            painter.setBrush(QColor(tokens.WHITE))
            painter.drawRoundedRect(rect, tokens.RADIUS, tokens.RADIUS)
        elif hovered:
            painter.setBrush(QColor(tokens.GRAY_200))
            painter.drawRoundedRect(rect, tokens.RADIUS, tokens.RADIUS)
        color = tokens.ACCENT if selected else tokens.GRAY_800
        x = rect.left() + tokens.SPACE_3
        painter.drawPixmap(
            x, rect.center().y() - 9, pixmap(index.data(Qt.ItemDataRole.DecorationRole), color, 18)
        )
        x += 18 + 10
        right = rect.right() - tokens.SPACE_3
        badge = index.data(self.BADGE_ROLE)
        if badge:
            right = (
                self._paint_badge(painter, rect, str(badge), index.data(self.TONE_ROLE))
                - tokens.SPACE_2
            )
        font = QFont(option.font)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(color))
        text_rect = QRect(x, rect.top(), right - x, rect.height())
        text = QFontMetrics(font).elidedText(
            index.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text
        )
        painter.restore()

    @staticmethod
    def _paint_badge(painter: QPainter, rect: QRect, text: str, tone: str | None) -> int:
        background, foreground = tokens.YELLOW if tone == "warning" else tokens.ACCENT_PAIR
        font = QFont(painter.font())
        font.setPixelSize(tokens.CAPTION.size)
        font.setWeight(QFont.Weight.DemiBold)
        width = max(20, QFontMetrics(font).horizontalAdvance(text) + 12)
        badge = QRect(rect.right() - tokens.SPACE_3 - width + 1, rect.center().y() - 9, width, 20)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(badge, 10, 10)
        painter.setFont(font)
        painter.setPen(QColor(foreground))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(Qt.PenStyle.NoPen)
        return badge.left()


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
        self._nav.setItemDelegate(NavDelegate(self._nav))
        self._nav.setMouseTracking(True)
        self._nav.setStyleSheet("QListWidget#sidebar { background: transparent; }")
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._stack = QStackedWidget()
        self._pages: dict[PageId, QWidget] = {}
        self.top_bar = TopBar()
        self.sidebar_footer = SidebarFooter()

        for page_id in PageId:
            item = QListWidgetItem(PAGE_TITLES[page_id])
            item.setData(Qt.ItemDataRole.UserRole, page_id.value)
            item.setData(Qt.ItemDataRole.DecorationRole, PAGE_ICONS[page_id])
            item.setToolTip(PAGE_TITLES[page_id])
            self._nav.addItem(item)
            self.set_page(
                page_id, PlaceholderPage(PAGE_TITLES[page_id], _PLACEHOLDER_TEXT[page_id])
            )

        self.setCentralWidget(self._build_layout())
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        self._restore_state()

    def _build_layout(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebarPane")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, tokens.SPACE_5, 14, tokens.SPACE_5)
        side.setSpacing(0)
        side.addWidget(Brand())
        side.addWidget(self._nav, 1)
        side.addWidget(self.sidebar_footer)

        content = QWidget()
        right = QVBoxLayout(content)
        right.setContentsMargins(tokens.SPACE_1, tokens.SPACE_5, tokens.SPACE_5, tokens.SPACE_5)
        right.setSpacing(tokens.SPACE_4)
        right.addWidget(self.top_bar)
        right.addWidget(self._stack, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        return central

    def set_nav_badge(self, page_id: PageId, text: str | None, tone: str = "accent") -> None:
        """사이드바 메뉴 오른쪽 숫자 배지. None이나 빈 글이면 없앤다. tone: "accent" | "warning" """
        item = self._nav.item(list(PageId).index(page_id))
        item.setData(NavDelegate.BADGE_ROLE, text or None)
        item.setData(NavDelegate.TONE_ROLE, tone)

    def nav_badge(self, page_id: PageId) -> str | None:
        return self._nav.item(list(PageId).index(page_id)).data(NavDelegate.BADGE_ROLE)

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
