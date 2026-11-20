"""후보 상세 패널 (#12, 디자인 초안 1번 오른쪽): 근거 메일, 신뢰도 설명, 사용자 확인, 다음 행동.

근거 메일 내용은 `mail_lookup`(메일 ID → `ParsedMail`)으로 찾는다. 가져온 메일이 없으면 ID만 보인다.
"""

from collections import Counter
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.classifier.reasons import key_sentence
from account_cleaner.contracts import (
    AccountCandidate,
    EvidenceType,
    LoginMethod,
    ParsedMail,
    Playbook,
)
from account_cleaner.ui.candidates.delegate import STATUS_TONES, avatar_tint, display_name
from account_cleaner.ui.candidates.guide import UrlOpener, WithdrawGuideDialog, default_open_url
from account_cleaner.ui.candidates.model import CandidateStatus, evidence_label, verdict_label
from account_cleaner.ui.theme import Icon, pixmap, set_role, tokens

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
    """판정을 만든 근거를 문장으로 (NF-03)."""
    counts = Counter(e.type for e in candidate.evidence)
    labels = Counter(evidence_label(e) for e in candidate.evidence)
    parts = [f"{label} 메일 {n}통" for label, n in labels.most_common()]
    text = f"{verdict_label(candidate)} — " + ", ".join(parts) + "을 근거로 판단했습니다."
    text += " 메일 근거로 본 판단이며 현재 계정 상태를 확인한 것은 아닙니다."
    deleted = [e for e in candidate.evidence if e.type is EvidenceType.DELETED]
    if any(e.probability == 1.0 for e in deleted):
        text += " 과거 탈퇴 완료 근거가 있습니다. 이후 재가입과 현재 상태는 확인이 필요합니다."
    elif deleted:
        text += " 삭제 유형은 모델의 추정입니다. 탈퇴 완료로 확인되지 않았으니 본문을 검토하세요."
    if set(counts) <= {EvidenceType.PROMO, EvidenceType.TERMS}:
        text += (
            " 광고·안내 메일은 보통 회원에게만 보내므로 계정이 있을 가능성이 높습니다."
            " 다만 가입 완료나 로그인 메일은 찾지 못했습니다."
        )
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
        self.completion_results: dict[str, tuple[ParsedMail, str]] = {}
        self._status = CandidateStatus.UNREVIEWED
        self._build()
        self.show_candidate(None)

    def set_mail_lookup(self, lookup: MailLookup) -> None:
        self._mail_lookup = lookup

    def set_completion_results(self, results: dict[str, tuple[ParsedMail, str]]) -> None:
        self.completion_results = results
        self._refresh_completion()

    def clear_completion_result(self, domain: str) -> None:
        self.completion_results.pop(domain, None)
        self._refresh_completion()

    def _refresh_completion(self) -> None:
        domain = self._candidate.domain if self._candidate else ""
        result = self.completion_results.get(domain)
        manual = (
            "사용자 완료 확인" if self._status is CandidateStatus.DONE else "사용자 완료 미확인"
        )
        mail_text = "완료 표현 메일 발견" if result else "완료 메일 미확인"
        text = f"{manual} · {mail_text}"
        if result:
            mail, statement = result
            text += f"\n{mail.date:%Y.%m.%d} · {statement}"
            text += "\n메일 표현을 확인한 결과이며 실제 계정 삭제를 보증하지 않습니다."
        else:
            text += "\n메일이 없다고 탈퇴 실패를 뜻하지 않습니다. 안내 후 메일을 다시 가져와 확인하세요."
        self.completion_label.setText(text)
        self.completion_button.setVisible(result is not None)

    def _show_completion_mail(self) -> None:
        result = self.completion_results.get(self._candidate.domain) if self._candidate else None
        if result is not None:
            mail, _statement = result
            self.preview.setPlainText(
                f"보낸 사람: {mail.sender}\n제목: {mail.subject}\n\n{mail.body_text[:PREVIEW_CHARS]}"
            )
            self.preview.show()

    def set_playbook_lookup(self, lookup: PlaybookLookup) -> None:
        self._playbook_lookup = lookup

    def _build(self) -> None:
        self.empty_label = set_role(
            QLabel("목록에서 후보를 고르면 근거와 상세가 여기에 보입니다."), "role", "muted"
        )
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 머리: [첫 글자] 서비스 이름 / 도메인            [상태]
        self.avatar = QLabel()
        self.avatar.setFixedSize(44, 44)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = set_role(QLabel(), "role", "titleSmall")
        self.domain_label = set_role(QLabel(), "role", "caption")
        self.domain_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label = QLabel()
        self.status_label.setObjectName("statusBadge")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedHeight(24)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(self.title_label)
        names.addWidget(self.domain_label)
        header = QHBoxLayout()
        header.setSpacing(tokens.SPACE_3)
        header.addWidget(self.avatar)
        header.addLayout(names, 1)
        header.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignTop)

        self.dates_label = set_role(QLabel(), "role", "caption")
        self.dates_label.setWordWrap(True)
        self.login_label = set_role(QLabel(), "role", "caption")
        self.login_label.setWordWrap(True)

        # 왜 계정이라고 봤나요? (NF-03)
        self.score_label = set_role(QLabel(), "role", "body")
        self.score_label.setWordWrap(True)
        why = set_role(QFrame(), "card", "subtle")
        why_layout = QVBoxLayout(why)
        why_layout.setContentsMargins(14, 14, 14, 14)
        why_layout.setSpacing(tokens.SPACE_2)
        why_layout.addWidget(set_role(QLabel("왜 계정이라고 봤나요?"), "role", "label"))
        why_layout.addWidget(self.score_label)
        self.completion_label = QLabel()
        self.completion_label.setTextFormat(Qt.TextFormat.PlainText)
        self.completion_label.setWordWrap(True)
        why_layout.addWidget(self.completion_label)
        self.completion_button = QPushButton("완료 근거 메일 보기")
        self.completion_button.clicked.connect(self._show_completion_mail)
        why_layout.addWidget(self.completion_button)

        self.evidence_title = set_role(QLabel("근거 메일"), "role", "label")
        self.evidence_list = QListWidget()
        self.evidence_list.setObjectName("evidenceList")
        self.evidence_list.setWordWrap(True)
        self.evidence_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.evidence_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.evidence_list.setStyleSheet(
            f"QListWidget#evidenceList {{ border: 1px solid {tokens.GRAY_300}; padding: 4px; }}"
        )
        self.evidence_list.currentItemChanged.connect(self._on_evidence_changed)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("근거 메일을 고르면 본문 앞부분이 보입니다.")
        self.preview.setFixedHeight(140)
        self.preview.hide()

        self.content = QWidget()
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, tokens.SPACE_1, 0)
        body.setSpacing(14)
        body.addLayout(header)
        details = QVBoxLayout()
        details.setSpacing(2)
        details.addWidget(self.dates_label)
        details.addWidget(self.login_label)
        body.addLayout(details)
        body.addWidget(why)
        evidence = QVBoxLayout()
        evidence.setSpacing(tokens.SPACE_2)
        evidence.addWidget(self.evidence_title)
        evidence.addWidget(self.evidence_list, 1)
        evidence.addWidget(self.preview)
        body.addLayout(evidence)
        body.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("detailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea#detailScroll, QScrollArea#detailScroll > QWidget > QWidget { background: transparent; }"
        )
        scroll.setWidget(self.content)

        # 아래 고정: 내 계정 판단 → 탈퇴 준비 (강조 버튼은 하나만)
        self.review_buttons: dict[CandidateStatus, QPushButton] = {}
        review = QGridLayout()
        review.setSpacing(6)
        for column, (status, text) in enumerate(REVIEW_BUTTONS):
            button = set_role(QPushButton(text), "variant", "choice")
            button.clicked.connect(lambda _=False, s=status: self._request_status(s))
            self.review_buttons[status] = button
            review.addWidget(button, 0, column)

        # 버튼 하나로 안내 창을 연다: 로그인·복구 링크 확인 → 탈퇴 전 조건 체크 → 에이전트 진행 (F-05·F-07)
        self.guide_button = set_role(QPushButton("탈퇴 준비하기"), "variant", "primary")
        self.guide_button.setMinimumHeight(44)
        self.guide_button.setToolTip(
            "로그인 방법과 비밀번호 재설정 링크를 보고, 탈퇴 전 조건을 확인한 뒤 AI 안내를 시작합니다."
        )
        self.guide_button.clicked.connect(self.open_guide)
        self.agent_hint = set_role(QLabel(), "role", "caption")
        self.agent_hint.setWordWrap(True)
        # 최종 탈퇴 버튼은 사용자가 누르므로 끝냈는지도 사용자가 알려 준다 → 로그인 세션 바로 삭제 (D-05)
        self.done_button = set_role(QPushButton("탈퇴를 끝냈어요"), "variant", "soft")
        self.done_button.setToolTip(
            "서비스에서 최종 탈퇴를 마쳤으면 눌러 주세요. 저장된 로그인도 지웁니다."
        )
        self.done_button.clicked.connect(lambda: self._request_status(CandidateStatus.DONE))
        lock = QLabel()
        lock.setPixmap(pixmap(Icon.LOCK, tokens.GRAY_800, 13))
        safety = QHBoxLayout()
        safety.setSpacing(6)
        safety.addStretch(1)
        safety.addWidget(lock)
        safety.addWidget(set_role(QLabel("최종 탈퇴 버튼은 직접 누르게 돼요"), "role", "caption"))
        safety.addStretch(1)

        self.actions = QWidget()
        actions = QVBoxLayout(self.actions)
        actions.setContentsMargins(0, tokens.SPACE_3, 0, 0)
        actions.setSpacing(tokens.SPACE_2)
        actions.addLayout(review)
        actions.addWidget(self.guide_button)
        actions.addWidget(self.done_button)
        actions.addWidget(self.agent_hint)
        actions.addLayout(safety)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.empty_label, 1)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.actions)
        self._scroll = scroll

    # --- 표시 ---

    def show_candidate(
        self, candidate: AccountCandidate | None, status: CandidateStatus | None = None
    ) -> None:
        self._candidate = candidate
        self.empty_label.setVisible(candidate is None)
        self._scroll.setVisible(candidate is not None)
        self.actions.setVisible(candidate is not None)
        if candidate is None:
            return
        name = display_name(candidate.service)
        background, foreground = avatar_tint(candidate.domain)
        self.avatar.setText(name[:1])
        self.avatar.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 12px;"
            " font-size: 18px; font-weight: 700;"
        )
        self.title_label.setText(name)
        self.title_label.setToolTip(name)
        self.domain_label.setText(candidate.domain)
        self.set_status(status or CandidateStatus.UNREVIEWED)
        self.dates_label.setText(
            f"처음 메일 {candidate.first_seen:%Y.%m.%d} · 마지막 메일 {candidate.last_seen:%Y.%m.%d}"
        )
        method = candidate.confirmed_login_method
        self.login_label.setVisible(method is not None)
        if method is not None:
            self.login_label.setText(f"메일에 적힌 가입 방식: {LOGIN_METHOD_LABELS[method]}")
        self.score_label.setText(explain_score(candidate))
        self._fill_evidence(candidate)
        self.evidence_title.setText(f"근거 메일 {len(candidate.evidence)}통")
        self._playbook = self._playbook_lookup(candidate.domain)
        self.guide_button.setEnabled(self._playbook is not None)
        self.agent_hint.setVisible(self._playbook is None)
        self.agent_hint.setText(
            ""
            if self._playbook
            else "이 서비스는 아직 안내 정보(플레이북)가 없어 로그인·탈퇴 안내와 "
            "에이전트 진행을 할 수 없습니다. 서비스 사이트의 고객센터에서 탈퇴 방법을 확인하세요."
        )

    def set_status(self, status: CandidateStatus) -> None:
        status = CandidateStatus(status)
        self._status = status
        self._refresh_completion()
        background, foreground = STATUS_TONES[status]
        self.status_label.setText(status.label)
        self.status_label.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 12px;"
            " padding: 0 10px; font-size: 12px; font-weight: 600;"
        )
        self.done_button.setVisible(status is CandidateStatus.IN_PROGRESS)
        for s, button in self.review_buttons.items():
            button.setDown(False)
            button.setEnabled(s is not status)

    def _fill_evidence(self, candidate: AccountCandidate) -> None:
        self.evidence_list.clear()
        self.preview.clear()
        self.preview.hide()
        for evidence in sorted(candidate.evidence, key=lambda e: -e.probability):
            mail = self._mail_lookup(evidence.mail_id)
            label = evidence_label(evidence)
            head = f"[{label}]"
            if mail is None:
                text = f"{head} · 메일 {evidence.mail_id}"
            else:
                quote = key_sentence(mail.body_text, evidence.type)
                text = f"{mail.date:%Y.%m.%d}  {mail.subject}\n{head}" + (
                    f" “{quote}”" if quote else ""
                )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, mail)
            self.evidence_list.addItem(item)
        self._fit_evidence_height()

    def _fit_evidence_height(self) -> None:
        """근거 메일 목록은 안에서 스크롤하지 않고 내용만큼 키운다 (패널 전체가 스크롤된다)."""
        rows = sum(self.evidence_list.sizeHintForRow(i) for i in range(self.evidence_list.count()))
        frame = self.evidence_list.frameWidth() * 2 + 10  # 테두리 + 안쪽 여백(4px 위아래) + 여유
        self.evidence_list.setFixedHeight(max(rows, 40) + frame)

    def resizeEvent(self, event) -> None:  # 줄바꿈 높이는 폭에 따라 바뀐다
        super().resizeEvent(event)
        if self._candidate is not None:
            self._fit_evidence_height()

    def _on_evidence_changed(self, current: QListWidgetItem | None, _previous) -> None:
        mail = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.preview.setVisible(current is not None)
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
