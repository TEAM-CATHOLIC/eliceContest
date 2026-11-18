"""계정 인벤토리 화면 (디자인 초안 1번): 요약 카드 + 필터 탭·정렬 + 후보 목록 + 오른쪽 상세 자리.

목록에서 고르면 오른쪽 상세 패널(#12)에 근거와 확인 버튼이 보인다.
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
from account_cleaner.ui.candidates.detail import CandidateDetailPanel
from account_cleaner.ui.candidates.model import (
    CandidateFilter,
    CandidateFilterProxy,
    CandidateListModel,
    CandidateSort,
    CandidateStatus,
    Role,
)
from account_cleaner.ui.theme import set_role

EMPTY_TEXT = "메일을 가져와 분석하면 계정 후보가 여기에 보입니다."


class SummaryCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("summaryCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))
        self.value = QLabel("0")
        set_role(self.value, "role", "number")
        layout.addWidget(self.value)


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
        set_role(title, "role", "title")

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

        self.detail = CandidateDetailPanel()
        self.detail.status_requested.connect(self.set_status)
        self.detail.agent_requested.connect(self.agent_requested)
        self.candidate_selected.connect(self._show_detail)
        detail_box = QFrame()
        detail_box.setObjectName("candidateDetail")
        detail_box.setFrameShape(QFrame.Shape.StyledPanel)
        QVBoxLayout(detail_box).addWidget(self.detail)

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
        service = self.model.service_of(domain)
        if service is not None:
            self.status_changed.emit(domain, service, status)
        if self._selected is not None and self._selected.domain == domain:
            self.detail.set_status(status)

    def set_search(self, text: str) -> None:
        """위쪽 막대 검색창(`TopBar.search_changed`)과 연결한다."""
        self.proxy.set_search(text)

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
        for i, (f, n) in enumerate(self.model.filter_counts().items()):
            self.tabs.setTabText(i, f"{f.label} {n}")
        empty = self.model.rowCount() == 0
        self.empty_label.setVisible(empty)
        self.list_view.setVisible(not empty)
