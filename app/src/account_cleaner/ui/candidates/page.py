"""계정 인벤토리 화면 (디자인 초안 1번): 요약 카드 + 필터 탭·정렬 + 후보 목록 + 오른쪽 상세 자리.

목록에서 고르면 오른쪽 상세 패널(#12)에 근거와 확인 버튼이 보인다.
"""

from PySide6.QtCore import QItemSelection, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.contracts import AccountCandidate
from account_cleaner.ui.candidates.delegate import CandidateDelegate
from account_cleaner.ui.candidates.detail import CandidateDetailPanel
from account_cleaner.ui.candidates.model import (
    CandidateFilter,
    CandidateFilterProxy,
    CandidateListModel,
    CandidateSort,
    CandidateStatus,
    Role,
)
from account_cleaner.ui.theme import page_header, set_role, tokens

LIST_STRETCH, DETAIL_STRETCH = 3, 2
DETAIL_MIN_WIDTH = 360
EMPTY_TEXT = "메일을 가져와 분석하면 계정 후보가 여기에 보입니다."


class SummaryCard(QFrame):
    """위쪽 숫자 카드. accent=True면 메인 색 바탕 (지금 할 일)."""

    def __init__(self, title: str, accent: bool = False) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        set_role(self, "card", "accent" if accent else "true")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, tokens.SPACE_4, 18, tokens.SPACE_4)
        layout.setSpacing(6)
        self.title = set_role(QLabel(title), "role", "caption")
        self.value = set_role(QLabel("0"), "role", "number")
        if accent:
            set_role(self.title, "accent")
            set_role(self.value, "accent")
        layout.addWidget(self.title)
        layout.addWidget(self.value)


def headline(total: int, unreviewed: int) -> str:
    """맨 위 한 줄: 지금 할 일을 문장으로."""
    if total == 0:
        return "계정 인벤토리"
    if unreviewed == 0:
        return "찾은 계정을 모두 확인했어요"
    return f"확인할 계정이 {unreviewed}개 있어요"


class InventoryPage(QWidget):
    candidate_selected = Signal(object)
    """고른 `AccountCandidate` (선택이 없어지면 None)"""
    status_changed = Signal(str, str, object)
    """(도메인, 서비스명, `CandidateStatus`) — 저장소에 기록할 때 쓴다"""
    agent_requested = Signal(object)
    """상세 패널에서 'AI 에이전트로 탈퇴 진행'을 누른 `AccountCandidate`"""

    def __init__(self) -> None:
        super().__init__()
        self._selected: AccountCandidate | None = None
        self.known_mail_ids: set[str] = set()
        self.model = CandidateListModel(self)
        self.proxy = CandidateFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self._build()
        self.model.modelReset.connect(self._refresh_counts)
        self.model.dataChanged.connect(self._refresh_counts)
        self._refresh_counts()

    def _build(self) -> None:
        title = set_role(QLabel("계정 인벤토리"), "role", "title")
        title.setObjectName("pageTitle")
        self.title_label = title
        self.subtitle_label = set_role(QLabel(), "role", "muted")
        heading = page_header(title, self.subtitle_label)

        self.cards = {
            "total": SummaryCard("찾은 계정"),
            CandidateStatus.UNREVIEWED: SummaryCard("확인 필요", accent=True),
            CandidateStatus.IN_PROGRESS: SummaryCard("정리 중"),
            CandidateStatus.DONE: SummaryCard("완료"),
        }
        cards = QHBoxLayout()
        cards.setSpacing(tokens.SPACE_3)
        for card in self.cards.values():
            cards.addWidget(card, 1)

        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(False)
        for f in CandidateFilter:
            self.tabs.addTab(f.label)
        self.tabs.currentChanged.connect(lambda i: self.proxy.set_filter(list(CandidateFilter)[i]))
        tabs_box = QFrame()
        tabs_box.setObjectName("filterTabs")
        tabs_box.setStyleSheet(
            f"QFrame#filterTabs {{ background: {tokens.GRAY_200}; border-radius: {tokens.RADIUS}px; }}"
        )
        tabs_layout = QHBoxLayout(tabs_box)
        tabs_layout.setContentsMargins(2, 0, 2, 0)
        tabs_layout.addWidget(self.tabs)
        self.sort_combo = QComboBox()
        self.sort_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for s in CandidateSort:
            self.sort_combo.addItem(s.label, s)
        self.sort_combo.currentIndexChanged.connect(
            lambda _: self.proxy.set_sort(self.sort_combo.currentData())
        )
        toolbar = QHBoxLayout()
        toolbar.setSpacing(tokens.SPACE_2)
        toolbar.addWidget(tabs_box)
        toolbar.addStretch(1)
        toolbar.addWidget(self.sort_combo)

        self.list_view = QListView()
        self.list_view.setObjectName("candidateList")
        self.list_view.setModel(self.proxy)
        self.list_view.setItemDelegate(CandidateDelegate(self.list_view))
        self.list_view.setMouseTracking(True)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list_view.selectionModel().selectionChanged.connect(self._on_selection)
        self.empty_label = set_role(QLabel(EMPTY_TEXT), "role", "muted")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        list_card = set_role(QFrame(), "card", "true")
        list_card.setObjectName("candidateListCard")
        center = QVBoxLayout(list_card)
        center.setContentsMargins(tokens.SPACE_2, 14, tokens.SPACE_2, tokens.SPACE_2)
        center.setSpacing(10)
        toolbar.setContentsMargins(tokens.SPACE_2, 0, tokens.SPACE_2, 0)
        center.addLayout(toolbar)
        center.addWidget(self.empty_label, 1)
        center.addWidget(self.list_view, 1)

        self.detail = CandidateDetailPanel()
        self.detail.status_requested.connect(self.set_status)
        self.detail.agent_requested.connect(self.agent_requested)
        self.candidate_selected.connect(self._show_detail)
        detail_box = set_role(QFrame(), "card", "true")
        detail_box.setObjectName("candidateDetail")
        detail_box.setMinimumWidth(DETAIL_MIN_WIDTH)
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(22, 22, 22, 22)
        detail_layout.addWidget(self.detail)

        body = QHBoxLayout()
        body.setSpacing(tokens.SPACE_3)
        # 창을 키우면 목록과 상세가 3:2로 함께 늘어난다 (#71)
        body.addWidget(list_card, LIST_STRETCH)
        body.addWidget(detail_box, DETAIL_STRETCH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_1, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_4)
        layout.addLayout(heading)
        layout.addLayout(cards)
        layout.addLayout(body, 1)

    # --- 외부에서 쓰는 것 ---

    def set_candidates(
        self,
        candidates: list[AccountCandidate],
        statuses: dict[str, CandidateStatus] | None = None,
    ) -> None:
        self.model.set_candidates(candidates, statuses)

    def set_status(self, domain: str, status: CandidateStatus) -> None:
        self.model.set_status(domain, status)
        service = self.model.service_of(domain)
        if service is not None:
            self.status_changed.emit(domain, service, status)
        if self._selected is not None and self._selected.domain == domain:
            self.detail.set_status(status)

    def set_search(self, text: str) -> None:
        """위쪽 막대 검색창(`TopBar.search_changed`)과 연결한다."""
        self.proxy.set_search(text)

    def refresh_detail(self) -> None:
        """고른 후보의 상세를 다시 그린다 (예: AI 키를 바꿔 'AI 안내' 버튼 상태가 바뀔 때)."""
        self._show_detail(self._selected)

    def visible_candidates(self) -> list[AccountCandidate]:
        return [self.proxy.index(i, 0).data(Role.CANDIDATE) for i in range(self.proxy.rowCount())]

    def select_row(self, row: int) -> None:
        self.list_view.setCurrentIndex(self.proxy.index(row, 0))

    # --- 내부 ---

    def _show_detail(self, candidate: AccountCandidate | None) -> None:
        self._selected = candidate
        status = self.model.status_of(candidate.domain) if candidate else None
        self.detail.show_candidate(candidate, status)

    def _on_selection(self, selected: QItemSelection, _deselected: QItemSelection) -> None:
        indexes = selected.indexes()
        self.candidate_selected.emit(indexes[0].data(Role.CANDIDATE) if indexes else None)

    def _refresh_counts(self, *_args) -> None:
        counts = self.model.status_counts()
        self.cards["total"].value.setText(str(self.model.rowCount()))
        for status in (
            CandidateStatus.UNREVIEWED,
            CandidateStatus.IN_PROGRESS,
            CandidateStatus.DONE,
        ):
            self.cards[status].value.setText(str(counts[status]))
        total = self.model.rowCount()
        self.title_label.setText(headline(total, counts[CandidateStatus.UNREVIEWED]))
        self.subtitle_label.setText(
            f"메일에서 계정 {total}개를 찾았어요 · 메일은 이 PC 밖으로 나가지 않아요"
            if total
            else "메일을 불러오면 가입한 서비스를 찾아 드려요"
        )
        for i, (f, n) in enumerate(self.model.filter_counts().items()):
            self.tabs.setTabText(i, f"{f.label} {n}")
        empty = self.model.rowCount() == 0
        self.empty_label.setVisible(empty)
        self.list_view.setVisible(not empty)
