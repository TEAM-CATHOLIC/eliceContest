"""후보 상세 패널 (#12, 디자인 초안 1번 오른쪽): 근거 메일, 신뢰도 설명, 사용자 확인, 다음 행동.

근거 메일 내용은 `mail_lookup`(메일 ID → `ParsedMail`)으로 찾는다. 가져온 메일이 없으면 ID만 보인다.
"""

from collections import Counter
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.contracts import (
    AccountCandidate,
    EvidenceType,
    LoginMethod,
    ParsedMail,
    Playbook,
)
from account_cleaner.ui.candidates.guide import UrlOpener, WithdrawGuideDialog, default_open_url
from account_cleaner.ui.candidates.model import CandidateStatus, evidence_label

MailLookup = Callable[[str], ParsedMail | None]
PlaybookLookup = Callable[[str], Playbook | None]

PREVIEW_CHARS = 600
LOGIN_METHOD_LABELS = {
    LoginMethod.EMAIL: "이메일",
    LoginMethod.PHONE: "휴대폰",
    LoginMethod.GOOGLE: "구글",
    LoginMethod.KAKAO: "카카오",
    LoginMethod.NAVER: "네이버",
    LoginMethod.APPLE: "애플",
}
REVIEW_BUTTONS = (
    (CandidateStatus.CONFIRMED, "내 계정 맞아요"),
    (CandidateStatus.EXCLUDED, "아니에요"),
    (CandidateStatus.DEFERRED, "나중에"),
)


def explain_score(candidate: AccountCandidate) -> str:
    """신뢰도를 만든 근거를 문장으로 (NF-03: 숫자만 보여 주지 않는다)."""
    counts = Counter(e.type for e in candidate.evidence)
    labels = Counter(evidence_label(e) for e in candidate.evidence)
    strongest: dict[str, float] = {}
    for e in candidate.evidence:
        label = evidence_label(e)
        strongest[label] = max(strongest.get(label, 0.0), e.probability)
    parts = [
        f"{label} 메일 {n}통(최고 {round(strongest[label] * 100)}%)"
        for label, n in labels.most_common()
    ]
    text = (
        f"신뢰도 {round(candidate.score * 100)}% — " + ", ".join(parts) + "을 근거로 판단했습니다."
    )
    text += " 이 점수는 후보 정렬용이며 검증된 계정 존재 확률이 아닙니다."
    deleted = [e for e in candidate.evidence if e.type is EvidenceType.DELETED]
    if any(e.probability == 1.0 for e in deleted):
        text += " 과거 탈퇴 완료 근거가 있습니다. 이후 재가입과 현재 상태는 확인이 필요합니다."
    elif deleted:
        text += " 삭제 유형은 모델의 추정입니다. 탈퇴 완료로 확인되지 않았으니 본문을 검토하세요."
    if set(counts) == {EvidenceType.PROMO}:
        text += " 광고·초대만 발견한 약한 흔적이며 가입 여부는 확인되지 않았습니다."
    if candidate.domain.endswith(".invalid"):
        text += " 서비스 이름만 발견했으며 실제 사이트 주소는 확인되지 않았습니다."
    return text


class CandidateDetailPanel(QWidget):
    status_requested = Signal(str, object)
    """(도메인, `CandidateStatus`) — 사용자가 확정·제외·보류를 눌렀다"""
    agent_requested = Signal(object)
    """`AccountCandidate` — 안내 창에서 탈퇴 전 조건을 모두 확인하고 AI 에이전트로 진행"""

    def __init__(
        self,
        mail_lookup: MailLookup | None = None,
        playbook_lookup: PlaybookLookup | None = None,
        open_url: UrlOpener = default_open_url,
    ) -> None:
        super().__init__()
        self._open_url = open_url
        self._playbook: Playbook | None = None
        self.guide_dialog: WithdrawGuideDialog | None = None
        self._mail_lookup = mail_lookup or (lambda _id: None)
        self._playbook_lookup = playbook_lookup or (lambda _domain: None)
        self._candidate: AccountCandidate | None = None
        self._build()
        self.show_candidate(None)

    def set_mail_lookup(self, lookup: MailLookup) -> None:
        self._mail_lookup = lookup

    def set_playbook_lookup(self, lookup: PlaybookLookup) -> None:
        self._playbook_lookup = lookup

    def _build(self) -> None:
        self.empty_label = QLabel("목록에서 후보를 고르면 근거와 상세가 여기에 보입니다.")
        self.empty_label.setWordWrap(True)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.status_label = QLabel()
        self.status_label.setObjectName("statusBadge")
        self.dates_label = QLabel()
        self.login_label = QLabel()
        self.score_label = QLabel()
        self.score_label.setWordWrap(True)

        self.evidence_list = QListWidget()
        self.evidence_list.setObjectName("evidenceList")
        self.evidence_list.currentItemChanged.connect(self._on_evidence_changed)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("근거 메일을 고르면 본문 앞부분이 보입니다.")
        self.preview.setMaximumHeight(140)

        self.review_buttons: dict[CandidateStatus, QPushButton] = {}
        review = QHBoxLayout()
        for status, text in REVIEW_BUTTONS:
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, s=status: self._request_status(s))
            self.review_buttons[status] = button
            review.addWidget(button)

        self.guide_button = QPushButton("로그인·복구 안내")
        self.guide_button.clicked.connect(self.open_guide)
        # 에이전트 진행도 안내 창을 거쳐 탈퇴 전 조건을 확인한 뒤에만 시작한다 (F-07)
        self.agent_button = QPushButton("AI 에이전트로 탈퇴 진행")
        self.agent_button.clicked.connect(self.open_guide)
        self.agent_hint = QLabel()
        self.agent_hint.setWordWrap(True)
        actions = QHBoxLayout()
        actions.addWidget(self.guide_button)
        actions.addWidget(self.agent_button)

        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        for widget in (self.title_label, self.status_label, self.dates_label, self.login_label):
            body.addWidget(widget)
        body.addWidget(QLabel("신뢰도 설명"))
        body.addWidget(self.score_label)
        body.addWidget(QLabel("데이터 근거 (메일)"))
        body.addWidget(self.evidence_list, 1)
        body.addWidget(self.preview)
        body.addWidget(QLabel("내 계정이 맞나요?"))
        body.addLayout(review)
        body.addLayout(actions)
        body.addWidget(self.agent_hint)

        layout = QVBoxLayout(self)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.content, 1)

    # --- 표시 ---

    def show_candidate(
        self, candidate: AccountCandidate | None, status: CandidateStatus | None = None
    ) -> None:
        self._candidate = candidate
        self.empty_label.setVisible(candidate is None)
        self.content.setVisible(candidate is not None)
        if candidate is None:
            return
        self.title_label.setText(f"{candidate.service}   {candidate.domain}")
        self.set_status(status or CandidateStatus.UNREVIEWED)
        self.dates_label.setText(
            f"처음 메일 {candidate.first_seen:%Y-%m-%d} · 마지막 메일 {candidate.last_seen:%Y-%m-%d}"
        )
        method = candidate.confirmed_login_method
        self.login_label.setVisible(method is not None)
        if method is not None:
            self.login_label.setText(f"메일에 적힌 가입 방식: {LOGIN_METHOD_LABELS[method]}")
        self.score_label.setText(explain_score(candidate))
        self._fill_evidence(candidate)
        self._playbook = self._playbook_lookup(candidate.domain)
        self.guide_button.setEnabled(self._playbook is not None)
        self.agent_button.setEnabled(self._playbook is not None)
        self.agent_hint.setText(
            ""
            if self._playbook
            else "이 서비스는 아직 안내 정보(플레이북)가 없어 로그인·탈퇴 안내와 "
            "에이전트 진행을 할 수 없습니다. 서비스 사이트의 고객센터에서 탈퇴 방법을 확인하세요."
        )

    def set_status(self, status: CandidateStatus) -> None:
        self.status_label.setText(f"상태: {status.label}")
        for s, button in self.review_buttons.items():
            button.setDown(False)
            button.setEnabled(s is not status)

    def _fill_evidence(self, candidate: AccountCandidate) -> None:
        self.evidence_list.clear()
        self.preview.clear()
        for evidence in sorted(candidate.evidence, key=lambda e: -e.probability):
            mail = self._mail_lookup(evidence.mail_id)
            label = evidence_label(evidence)
            head = f"[{label}] {round(evidence.probability * 100)}%"
            if mail is None:
                text = f"{head} · 메일 {evidence.mail_id}"
            else:
                text = f"{head} · {mail.date:%Y-%m-%d} · {mail.subject}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, mail)
            self.evidence_list.addItem(item)

    def _on_evidence_changed(self, current: QListWidgetItem | None, _previous) -> None:
        mail = current.data(Qt.ItemDataRole.UserRole) if current else None
        if mail is None:
            self.preview.setPlainText(
                "가져온 메일에서 이 근거를 찾지 못했습니다." if current else ""
            )
            return
        body = mail.body_text[:PREVIEW_CHARS]
        more = "…" if len(mail.body_text) > PREVIEW_CHARS else ""
        self.preview.setPlainText(f"보낸 사람: {mail.sender}\n제목: {mail.subject}\n\n{body}{more}")

    # --- 요청 ---

    def _request_status(self, status: CandidateStatus) -> None:
        if self._candidate is not None:
            self.status_requested.emit(self._candidate.domain, status)

    def open_guide(self) -> None:
        """로그인·복구·탈퇴 전 조건 안내 창. 조건을 모두 확인해야 에이전트 진행이 켜진다."""
        if self._candidate is None or self._playbook is None:
            return
        if self.guide_dialog is not None:
            self.guide_dialog.close()
        dialog = WithdrawGuideDialog(self._candidate, self._playbook, self, open_url=self._open_url)
        dialog.agent_requested.connect(self.agent_requested)
        self.guide_dialog = dialog
        dialog.open()
