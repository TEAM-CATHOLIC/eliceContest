"""AI 안내용 Anthropic API 키 입력 창 (#81).

사용자가 Console에서 직접 발급한 키를 넣으면 OS 키체인에만 저장한다. 파일·로그에는 남기지 않는다.

┌ AI 안내 키 설정 ─────────────────────────────┐
│ 처음 보는 사이트를 AI가 안내하려면 …           │
│ [sk-ant-••••••••••••]  [ ] 키 보기             │
│ 지금: 켜짐 (키체인에 저장됨)                   │
│ 키체인에서 지우기          닫기   [저장]        │
└──────────────────────────────────────────────┘
"""

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from account_cleaner.browser.agent.llm import (
    ApiKeyStoreError,
    api_key_source,
    delete_api_key,
    save_api_key,
)
from account_cleaner.ui.theme import section_card, set_role, tokens

STATUS_TEXT = {
    "env": "켜짐 (환경변수 ANTHROPIC_API_KEY 사용 중 — 저장한 키보다 먼저 쓰입니다)",
    "keychain": "켜짐 (키체인에 저장됨)",
    None: "꺼짐 (API 키 없음)",
}
GUIDE_LINES = (
    "플레이북이 없는 처음 보는 사이트는 AI가 화면의 링크·버튼 목록만 보고 다음에 누를 곳을 고릅니다.",
    "이때 Anthropic API를 쓰므로 본인 키가 필요합니다.",
)
ISSUE_STEPS = "발급: Anthropic Console → Connect to the Claude API → Somewhere else"
PRIVACY_NOTE = "키는 이 PC의 키체인에만 저장되고, 파일이나 로그에는 남기지 않습니다."
DIALOG_WIDTH = 520


def ai_status_text(source: str | None) -> str:
    """사이드바 상태 줄 문구."""
    return {"env": "켜짐 (환경변수)", "keychain": "켜짐", None: "꺼짐 (API 키 없음)"}[source]


class ApiKeyDialog(QDialog):
    key_changed = Signal()
    """키를 저장하거나 지웠다 (화면의 'AI 안내' 버튼 상태를 다시 계산)"""

    def __init__(
        self,
        parent: QWidget | None = None,
        save: Callable[[str], None] = save_api_key,
        delete: Callable[[], None] = delete_api_key,
        source: Callable[[], str | None] = api_key_source,
    ) -> None:
        super().__init__(parent)
        self._save, self._delete, self._source = save, delete, source
        self.setWindowTitle("AI 안내 키 설정")
        self._build()
        self._refresh()
        self._fit_height()

    def _build(self) -> None:
        # 줄바꿈 글(QLabel wordWrap)은 폭이 정해져야 높이를 제대로 계산한다 → 폭 고정, 높이는 내용만큼
        self.setFixedWidth(DIALOG_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_6, tokens.SPACE_6, tokens.SPACE_6, tokens.SPACE_5)
        layout.setSpacing(tokens.SPACE_4)
        layout.addWidget(set_role(QLabel("AI 안내 키 설정"), "role", "titleSmall"))

        guide_card, guide = section_card()  # 창 바탕(회색) 위 흰 카드
        guide.setSpacing(tokens.SPACE_2)
        guide.setContentsMargins(tokens.SPACE_4, 14, tokens.SPACE_4, 14)
        for text, role in (
            *((line, "body") for line in GUIDE_LINES),
            (ISSUE_STEPS, "caption"),
            (PRIVACY_NOTE, "caption"),
        ):
            label = set_role(QLabel(text), "role", role)
            label.setWordWrap(True)
            guide.addWidget(label)
        layout.addWidget(guide_card)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("sk-ant-로 시작하는 키 붙여넣기")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.textChanged.connect(lambda _text: self._update_buttons())
        self.show_key = QCheckBox("키 보기")
        self.show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_3)
        row.addWidget(self.key_edit, 1)
        row.addWidget(self.show_key)
        field = QVBoxLayout()
        field.setSpacing(6)
        field.addLayout(row)
        self.status_label = set_role(QLabel(), "role", "caption")
        self.status_label.setWordWrap(True)
        field.addWidget(self.status_label)
        layout.addLayout(field)

        self.message_label = set_role(QLabel(), "role", "body")
        self.message_label.setWordWrap(True)
        self.message_label.hide()
        layout.addWidget(self.message_label)

        self.delete_button = set_role(QPushButton("키체인에서 지우기"), "variant", "ghost")
        self.delete_button.clicked.connect(self.delete_key)
        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        self.save_button = set_role(QPushButton("저장"), "variant", "primary")
        self.save_button.setMinimumWidth(96)
        self.save_button.clicked.connect(self.save_key)
        actions = QHBoxLayout()
        actions.setSpacing(tokens.SPACE_2)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(close)
        actions.addWidget(self.save_button)
        layout.addSpacing(tokens.SPACE_1)
        layout.addLayout(actions)

    def _fit_height(self) -> None:
        """고정 폭에서 줄바꿈된 글 높이만큼 창 높이를 맞춘다 (글이 겹치거나 잘리지 않게)."""
        layout = self.layout()
        layout.activate()
        self.setMinimumHeight(layout.totalHeightForWidth(DIALOG_WIDTH))
        self.resize(DIALOG_WIDTH, self.minimumHeight())

    def _message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))
        self._fit_height()

    def _refresh(self) -> None:
        self.status_label.setText(f"지금: {STATUS_TEXT[self._source()]}")
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.save_button.setEnabled(bool(self.key_edit.text().strip()))
        self.delete_button.setEnabled(self._source() == "keychain")

    def save_key(self) -> None:
        try:
            self._save(self.key_edit.text())
        except ValueError as e:
            self._message(str(e))
            return
        except ApiKeyStoreError as e:
            self._message(f"{e}. 대신 ANTHROPIC_API_KEY 환경변수를 설정한 뒤 앱을 실행해 주세요.")
            return
        self.key_edit.clear()
        self._message("저장했습니다. 이제 플레이북이 없는 서비스에서 AI 안내를 쓸 수 있어요.")
        self._refresh()
        self.key_changed.emit()

    def delete_key(self) -> None:
        try:
            self._delete()
        except ApiKeyStoreError as e:
            self._message(str(e))
            return
        self._message("키체인에서 지웠습니다.")
        self._refresh()
        self.key_changed.emit()
