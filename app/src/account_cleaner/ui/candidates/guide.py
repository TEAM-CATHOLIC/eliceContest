"""로그인·복구·탈퇴 전 조건 안내 (#14, PRD F-05·F-07, 디자인 초안 3번의 "권리 포기 & 잔여 자산").

플레이북에 적힌 로그인 방식·재설정 주소·탈퇴 전 조건을 보여 주고, 조건을 모두 확인해야
'AI 에이전트로 탈퇴 진행'이 켜진다. 링크는 사용자의 기본 브라우저로 연다 (에이전트 전용 프로필 아님).
"""

from collections.abc import Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.contracts import AccountCandidate, LoginMethod, Playbook

UrlOpener = Callable[[str], None]

LOGIN_METHOD_LABELS = {
    LoginMethod.EMAIL: "이메일·비밀번호",
    LoginMethod.PHONE: "휴대폰 번호",
    LoginMethod.GOOGLE: "구글 로그인",
    LoginMethod.KAKAO: "카카오 로그인",
    LoginMethod.NAVER: "네이버 로그인",
    LoginMethod.APPLE: "애플 로그인",
}
IRREVERSIBLE = "탈퇴하면 계정과 데이터를 되돌릴 수 없다는 것을 확인했습니다"
NO_CONDITIONS = "플레이북에 따로 알려진 탈퇴 전 조건은 없습니다."


def default_open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def login_method_lines(playbook: Playbook, confirmed: LoginMethod | None) -> list[str]:
    """가능한 로그인 방식. 메일로 가입 방식이 확인된 것은 맨 앞에 표시한다."""
    methods = list(playbook.login_methods)
    if confirmed is not None and confirmed not in methods:
        methods.append(confirmed)
    if confirmed is not None:
        methods.remove(confirmed)
        methods.insert(0, confirmed)
    return [
        LOGIN_METHOD_LABELS[m]
        + (" — 메일에서 이 방식으로 가입한 기록을 찾았습니다" if m is confirmed else "")
        for m in methods
    ]


class WithdrawGuideDialog(QDialog):
    agent_requested = Signal(object)
    """조건을 모두 확인하고 'AI 에이전트로 탈퇴 진행'을 누른 `AccountCandidate`"""

    def __init__(
        self,
        candidate: AccountCandidate,
        playbook: Playbook,
        parent: QWidget | None = None,
        open_url: UrlOpener = default_open_url,
    ) -> None:
        super().__init__(parent)
        self.candidate = candidate
        self.playbook = playbook
        self._open_url = open_url
        self.setWindowTitle(f"{playbook.service} 로그인·탈퇴 전 안내")
        self._build()
        self._update_proceed()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        heading = QLabel(f"{self.playbook.service} ({self.candidate.domain})")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(heading)

        layout.addWidget(QLabel("로그인 방법"))
        self.login_lines = login_method_lines(self.playbook, self.candidate.confirmed_login_method)
        for line in self.login_lines:
            label = QLabel(f"• {line}")
            label.setWordWrap(True)
            layout.addWidget(label)
        self.login_button = QPushButton("로그인 페이지 열기")
        self.login_button.clicked.connect(lambda: self._open_url(self.playbook.login_url))
        self.reset_button = QPushButton("공식 비밀번호 재설정 열기")
        self.reset_button.clicked.connect(lambda: self._open_url(self.playbook.password_reset_url))
        links = QHBoxLayout()
        links.addWidget(self.login_button)
        links.addWidget(self.reset_button)
        layout.addLayout(links)
        hint = QLabel(
            "링크는 평소 쓰는 브라우저로 열립니다. 비밀번호가 기억나지 않으면 먼저 재설정하세요."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("탈퇴 전에 확인하세요"))
        if not self.playbook.pre_withdraw_conditions:
            layout.addWidget(QLabel(NO_CONDITIONS))
        self.condition_boxes: list[QCheckBox] = []
        for text in (*self.playbook.pre_withdraw_conditions, IRREVERSIBLE):
            box = QCheckBox(text)
            box.toggled.connect(self._update_proceed)
            self.condition_boxes.append(box)
            layout.addWidget(box)

        self.proceed_button = QPushButton("AI 에이전트로 탈퇴 진행")
        self.proceed_button.clicked.connect(self._proceed)
        self.proceed_hint = QLabel()
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(self.proceed_hint, 1)
        actions.addWidget(close)
        actions.addWidget(self.proceed_button)
        layout.addLayout(actions)

    def all_confirmed(self) -> bool:
        return all(box.isChecked() for box in self.condition_boxes)

    def _update_proceed(self) -> None:
        ok = self.all_confirmed()
        self.proceed_button.setEnabled(ok)
        remaining = sum(not box.isChecked() for box in self.condition_boxes)
        self.proceed_hint.setText("" if ok else f"확인할 항목 {remaining}개가 남았습니다")

    def _proceed(self) -> None:
        if self.all_confirmed():
            self.agent_requested.emit(self.candidate)
            self.accept()
