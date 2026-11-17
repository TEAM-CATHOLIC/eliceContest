"""계정 후보 목록 모델. 후보(`AccountCandidate`) + 사용자가 정한 상태.

상태 저장(#8)이 생기기 전까지는 메모리에만 둔다. 상태는 도메인을 키로 관리한다.
"""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from account_cleaner.contracts import AccountCandidate, Evidence, EvidenceType


class CandidateStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    EXCLUDED = "excluded"
    DEFERRED = "deferred"
    IN_PROGRESS = "in_progress"
    DONE = "done"

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


_STATUS_LABELS = {
    CandidateStatus.UNREVIEWED: "미확인",
    CandidateStatus.CONFIRMED: "확정",
    CandidateStatus.EXCLUDED: "제외",
    CandidateStatus.DEFERRED: "보류",
    CandidateStatus.IN_PROGRESS: "정리 중",
    CandidateStatus.DONE: "완료",
}


class CandidateFilter(StrEnum):
    """목록 위 필터 탭."""

    ALL = "all"
    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    SET_ASIDE = "set_aside"

    @property
    def label(self) -> str:
        return _FILTER_LABELS[self]

    def accepts(self, status: CandidateStatus) -> bool:
        return status in _FILTER_STATUSES[self]


_FILTER_LABELS = {
    CandidateFilter.ALL: "전체",
    CandidateFilter.UNREVIEWED: "미확인",
    CandidateFilter.CONFIRMED: "확정",
    CandidateFilter.SET_ASIDE: "제외·보류",
}
_FILTER_STATUSES = {
    CandidateFilter.ALL: set(CandidateStatus),
    CandidateFilter.UNREVIEWED: {CandidateStatus.UNREVIEWED},
    CandidateFilter.CONFIRMED: {
        CandidateStatus.CONFIRMED,
        CandidateStatus.IN_PROGRESS,
        CandidateStatus.DONE,
    },
    CandidateFilter.SET_ASIDE: {CandidateStatus.EXCLUDED, CandidateStatus.DEFERRED},
}


class CandidateSort(StrEnum):
    SCORE = "score"
    RECENT = "recent"

    @property
    def label(self) -> str:
        return {CandidateSort.SCORE: "신뢰도 높은 순", CandidateSort.RECENT: "최근 메일 순"}[self]


def evidence_label(evidence: Evidence) -> str:
    if evidence.type is EvidenceType.DELETED and evidence.probability < 1.0:
        return "삭제 추정 · 검토 필요"
    return evidence.type.label


def evidence_summary(candidate: AccountCandidate, limit: int = 3) -> str:
    """대표 근거 유형과 개수. 예: "가입·인증 2 · 보안·복구 1" """
    counts = Counter(evidence_label(e) for e in candidate.evidence)
    top = counts.most_common(limit)
    return " · ".join(f"{label} {n}" for label, n in top)


@dataclass
class CandidateRow:
    candidate: AccountCandidate
    status: CandidateStatus = CandidateStatus.UNREVIEWED

    def display_text(self) -> str:
        c = self.candidate
        first = f"{c.service}   {c.domain}"
        second = " · ".join(
            [
                f"신뢰도 {round(c.score * 100)}%",
                evidence_summary(c),
                f"마지막 메일 {c.last_seen:%Y-%m-%d}",
                self.status.label,
            ]
        )
        return f"{first}\n{second}"


class Role:
    CANDIDATE = Qt.ItemDataRole.UserRole + 1
    STATUS = Qt.ItemDataRole.UserRole + 2
    SCORE = Qt.ItemDataRole.UserRole + 3
    LAST_SEEN = Qt.ItemDataRole.UserRole + 4
    SEARCH = Qt.ItemDataRole.UserRole + 5


class CandidateListModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[CandidateRow] = []

    def set_candidates(
        self,
        candidates: list[AccountCandidate],
        statuses: dict[str, CandidateStatus] | None = None,
    ) -> None:
        statuses = statuses or {}
        self.beginResetModel()
        self._rows = [
            CandidateRow(c, statuses.get(c.domain, CandidateStatus.UNREVIEWED)) for c in candidates
        ]
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008 — Qt 기본 인자 관례
        return 0 if parent.isValid() else len(self._rows)

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row.display_text()
        if role == Role.CANDIDATE:
            return row.candidate
        if role == Role.STATUS:
            return row.status
        if role == Role.SCORE:
            return row.candidate.score
        if role == Role.LAST_SEEN:
            return row.candidate.last_seen.timestamp()
        if role == Role.SEARCH:
            return f"{row.candidate.service} {row.candidate.domain}".casefold()
        return None

    def status_of(self, domain: str) -> CandidateStatus | None:
        return next((r.status for r in self._rows if r.candidate.domain == domain), None)

    def service_of(self, domain: str) -> str | None:
        return next((r.candidate.service for r in self._rows if r.candidate.domain == domain), None)

    def set_status(self, domain: str, status: CandidateStatus) -> None:
        for i, row in enumerate(self._rows):
            if row.candidate.domain == domain and row.status is not status:
                row.status = status
                index = self.index(i)
                self.dataChanged.emit(index, index)

    def status_counts(self) -> Counter[CandidateStatus]:
        return Counter(r.status for r in self._rows)

    def filter_counts(self) -> dict[CandidateFilter, int]:
        counts = self.status_counts()
        return {f: sum(n for s, n in counts.items() if f.accepts(s)) for f in CandidateFilter}


class CandidateFilterProxy(QSortFilterProxyModel):
    """필터 탭 + 검색어 + 정렬."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._filter = CandidateFilter.ALL
        self._search = ""
        self.setDynamicSortFilter(True)
        self.set_sort(CandidateSort.SCORE)

    def set_filter(self, value: CandidateFilter) -> None:
        self.beginFilterChange()
        self._filter = value
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_search(self, text: str) -> None:
        self.beginFilterChange()
        self._search = text.strip().casefold()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_sort(self, value: CandidateSort) -> None:
        self.setSortRole(Role.SCORE if value is CandidateSort.SCORE else Role.LAST_SEEN)
        self.sort(0, Qt.SortOrder.DescendingOrder)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        if not self._filter.accepts(index.data(Role.STATUS)):
            return False
        return not self._search or self._search in index.data(Role.SEARCH)
