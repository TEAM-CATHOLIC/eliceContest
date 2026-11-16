"""계정 인벤토리 화면 (디자인 초안 1번): 요약 카드 + 필터 탭·정렬 + 후보 목록 + 오른쪽 상세 자리.

상세 패널은 #12에서 채운다. 지금은 `set_detail_widget()`으로 바꿔 끼울 수 있는 자리표시만 둔다.
"""

from PySide6.QtCore import QItemSelection, Signal
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
from account_cleaner.ui.candidates.model import (
    CandidateFilter,
    CandidateFilterProxy,
    CandidateListModel,
    CandidateSort,
    CandidateStatus,
    Role,
)

EMPTY_TEXT = "메일을 가져와 분석하면 계정 후보가 여기에 보입니다."


class SummaryCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))
        self.value = QLabel("0")
        self.value.setStyleSheet("font-size: 24px; font-weight: 700;")
        layout.addWidget(self.value)


class InventoryPage(QWidget):
    candidate_selected = Signal(object)
    """고른 `AccountCandidate` (선택이 없어지면 None)"""

    def __init__(self) -> None:
        super().__init__()
        self.model = CandidateListModel(self)
        self.proxy = CandidateFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self._build()
        self.model.modelReset.connect(self._refresh_counts)
        self.model.dataChanged.connect(self._refresh_counts)
        self._refresh_counts()

    def _build(self) -> None:
        title = QLabel("계정 인벤토리")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")

        self.cards = {
            "total": SummaryCard("발견된 계정"),
            CandidateStatus.UNREVIEWED: SummaryCard("확인 필요"),
            CandidateStatus.IN_PROGRESS: SummaryCard("정리 중"),
            CandidateStatus.DONE: SummaryCard("완료"),
        }
        cards = QHBoxLayout()
        for card in self.cards.values():
            cards.addWidget(card)

        self.tabs = QTabBar()
        for f in CandidateFilter:
            self.tabs.addTab(f.label)
        self.tabs.currentChanged.connect(lambda i: self.proxy.set_filter(list(CandidateFilter)[i]))
        self.sort_combo = QComboBox()
        for s in CandidateSort:
            self.sort_combo.addItem(s.label, s)
        self.sort_combo.currentIndexChanged.connect(
            lambda _: self.proxy.set_sort(self.sort_combo.currentData())
        )
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.tabs, 1)
        toolbar.addWidget(self.sort_combo)

        self.list_view = QListView()
        self.list_view.setObjectName("candidateList")
        self.list_view.setModel(self.proxy)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setAlternatingRowColors(True)
        self.list_view.selectionModel().selectionChanged.connect(self._on_selection)
        self.empty_label = QLabel(EMPTY_TEXT)
        self.empty_label.setWordWrap(True)

        center = QVBoxLayout()
        center.addLayout(toolbar)
        center.addWidget(self.empty_label)
        center.addWidget(self.list_view, 1)

        self.detail_area = QVBoxLayout()
        self._detail: QWidget = QLabel("목록에서 후보를 고르면 근거와 상세가 여기에 보입니다.")
        self._detail.setWordWrap(True)
        self.detail_area.addWidget(self._detail)
        detail_box = QFrame()
        detail_box.setObjectName("candidateDetail")
        detail_box.setFrameShape(QFrame.Shape.StyledPanel)
        detail_box.setLayout(self.detail_area)

        body = QHBoxLayout()
        body.addLayout(center, 3)
        body.addWidget(detail_box, 2)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
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

    def set_search(self, text: str) -> None:
        """위쪽 막대 검색창(`TopBar.search_changed`)과 연결한다."""
        self.proxy.set_search(text)

    def set_detail_widget(self, widget: QWidget) -> None:
        """오른쪽 상세 패널을 바꿔 끼운다 (#12)."""
        self.detail_area.removeWidget(self._detail)
        self._detail.deleteLater()
        self._detail = widget
        self.detail_area.addWidget(widget)

    def visible_candidates(self) -> list[AccountCandidate]:
        return [self.proxy.index(i, 0).data(Role.CANDIDATE) for i in range(self.proxy.rowCount())]

    def select_row(self, row: int) -> None:
        self.list_view.setCurrentIndex(self.proxy.index(row, 0))

    # --- 내부 ---

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
        for i, (f, n) in enumerate(self.model.filter_counts().items()):
            self.tabs.setTabText(i, f"{f.label} {n}")
        empty = self.model.rowCount() == 0
        self.empty_label.setVisible(empty)
        self.list_view.setVisible(not empty)
