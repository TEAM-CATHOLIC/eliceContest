"""메일 소스 연결 화면 (#10, 디자인 초안 4번): Gmail 계정 연결 / MBOX·EML 파일 / 네이버(준비 중).

가져오기 → 분석은 `pipeline.run_pipeline`을 작업 스레드에서 돌린다. 끝나면 `import_finished`로
결과(`ImportOutcome`)를 알리고, 메인 창이 계정 인벤토리로 넘긴다. 결과는 메모리에만 둔다.

화면 문구는 기획과 논의 전 임시 문구다 (개인정보 안내, 카드 구성).
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from account_cleaner import providers
from account_cleaner.contracts import AccountAnalyzer, AnalysisCancelled, CancelCheck
from account_cleaner.mail import (
    SUPPORTED_EXTENSIONS,
    FileMailSource,
    GmailError,
    GmailMailSource,
    GoogleGmailApi,
    ImportCancelled,
    UnsupportedFileError,
    authorize,
    find_client_secret,
    load_client_config,
    revoke,
)
from account_cleaner.pipeline import ImportOutcome, SourceOpener, Stage, run_pipeline
from account_cleaner.ui.theme import (
    Icon,
    page_header,
    page_layout,
    pixmap,
    section_card,
    set_role,
    tokens,
)
from account_cleaner.ui.workers import BackgroundTask, TaskCancelled

PRIVACY_NOTE = (
    "메일 본문은 이 기기 안에서만 분석하며 외부로 보내지 않습니다. "
    "계정 연결 정보(토큰)는 저장하지 않고, 가져오기가 끝나면 폐기합니다."
)
GMAIL_LIMITS = ((1000, "최근 1,000통"), (5000, "최근 5,000통"), (0, "전체 (오래 걸릴 수 있음)"))
FILE_FILTER = "메일함 파일 (*.mbox *.mbx *.eml *.zip);;모든 파일 (*)"


def file_opener(paths: list[Path]) -> SourceOpener:
    def open_source(_should_cancel: CancelCheck):
        return FileMailSource(paths), None

    return open_source


def gmail_opener(app_root: Path | None, max_messages: int | None) -> SourceOpener:
    def open_source(should_cancel: CancelCheck):
        config = load_client_config(find_client_secret(app_root))
        credentials = authorize(config, should_cancel=should_cancel)
        source = GmailMailSource(
            GoogleGmailApi(credentials), max_messages=max_messages, should_cancel=should_cancel
        )
        return source, lambda: revoke(credentials)

    return open_source


class _StageRelay(QObject):
    """작업 스레드 → UI 스레드 진행률."""

    stage = Signal(str, int, int)


class SourceCard(QFrame):
    """메일 소스 카드: [아이콘] 제목 (배지) / 설명 / … / 아래 버튼. 버튼은 카드 바닥에 맞춘다."""

    def __init__(
        self, title: str, description: str, icon_name: str = Icon.SOURCES, badge: str = ""
    ) -> None:
        super().__init__()
        self.setObjectName("sourceCard")
        set_role(self, "card", "true")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(tokens.SPACE_5, tokens.SPACE_5, tokens.SPACE_5, tokens.SPACE_5)
        self.body.setSpacing(tokens.SPACE_3)
        mark = QLabel()
        mark.setFixedSize(40, 40)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setPixmap(pixmap(icon_name, tokens.ACCENT, 20))
        mark.setStyleSheet(f"background: {tokens.ACCENT_SOFT}; border-radius: 12px;")
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE_3)
        head.addWidget(mark)
        heading = set_role(QLabel(title), "role", "subtitle")
        heading.setWordWrap(True)
        head.addWidget(heading, 1)
        if badge:
            pill = QLabel(badge)
            pill.setFixedHeight(24)
            pill.setStyleSheet(
                f"background: {tokens.GRAY_200}; color: {tokens.GRAY_800}; border-radius: 12px;"
                " padding: 0 10px; font-size: 12px; font-weight: 600;"
            )
            head.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        text = set_role(QLabel(description), "role", "muted")
        text.setWordWrap(True)
        self.body.addLayout(head)
        self.body.addWidget(text)

    def add_bottom(self, *widgets: QWidget) -> None:
        """남는 공간 아래에 붙인다 (세 카드의 버튼 높이를 맞춘다)."""
        self.body.addStretch(1)
        for widget in widgets:
            self.body.addWidget(widget)


class FileCard(SourceCard):
    """파일 선택 + 끌어다 놓기."""

    files_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__(
            "메일함 파일 (MBOX / EML)",
            "Gmail 테이크아웃(.mbox, .zip)이나 메일 프로그램에서 내보낸 .eml 파일·폴더를 "
            "고르거나 이곳에 끌어다 놓으세요.",
            Icon.INVENTORY,
        )
        self.setAcceptDrops(True)
        self.paths: list[Path] = []
        self.files_label = set_role(QLabel("선택한 파일 없음"), "role", "caption")
        self.files_label.setWordWrap(True)
        self.files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.files_label.setMinimumHeight(44)
        self.files_label.setStyleSheet(
            f"border: 1.5px dashed {tokens.GRAY_400}; border-radius: 10px; padding: 8px;"
        )
        pick_files = QPushButton("파일 선택")
        pick_files.clicked.connect(self._pick_files)
        pick_folder = QPushButton("폴더 선택")
        pick_folder.clicked.connect(self._pick_folder)
        self.import_button = set_role(QPushButton("파일에서 가져오기"), "variant", "primary")
        self.import_button.setEnabled(False)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        row.addWidget(pick_files)
        row.addWidget(pick_folder)
        self.add_bottom(self.files_label, buttons, self.import_button)

    def set_paths(self, paths: list[Path]) -> None:
        self.paths = paths
        names = ", ".join(p.name for p in paths[:3]) + (
            f" 외 {len(paths) - 3}개" if len(paths) > 3 else ""
        )
        self.files_label.setText(names or "선택한 파일 없음")
        self.import_button.setEnabled(bool(paths))
        self.files_changed.emit(paths)

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "메일함 파일 선택", "", FILE_FILTER)
        if files:
            self.set_paths([Path(f) for f in files])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "메일 폴더 선택")
        if folder:
            self.set_paths([Path(folder)])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        usable = [p for p in paths if p.is_dir() or p.suffix.lower() in SUPPORTED_EXTENSIONS]
        if usable:
            self.set_paths(usable)


class SourcesPage(QWidget):
    import_finished = Signal(object)
    """`ImportOutcome`"""

    def __init__(
        self,
        app_root: Path | None = None,
        analyzer_factory: Callable[[], AccountAnalyzer] = providers.get_analyzer,
    ) -> None:
        super().__init__()
        self._app_root = app_root
        self._analyzer_factory = analyzer_factory
        self._task: BackgroundTask | None = None
        self._relay = _StageRelay(self)
        self._relay.stage.connect(self._on_stage)
        self._build()
        self._set_running(False)

    def _build(self) -> None:
        title = QLabel("메일 소스 연결")
        title.setObjectName("pageTitle")
        privacy = QLabel(PRIVACY_NOTE)
        privacy.setObjectName("privacyNote")

        self.gmail_card = SourceCard(
            "Gmail 계정 연결",
            "Google 로그인 창에서 'Gmail 메일 보기'만 허락하면 메일을 불러옵니다. "
            "테스트 중인 앱이라 '확인되지 않은 앱' 경고가 뜨면 '고급 → 이동'을 누르세요.",
        )
        self.gmail_limit = QComboBox()
        for value, text in GMAIL_LIMITS:
            self.gmail_limit.addItem(text, value)
        self.gmail_button = set_role(
            QPushButton("Google로 로그인해 가져오기"), "variant", "primary"
        )
        self.gmail_button.clicked.connect(self.start_gmail)
        self.gmail_card.add_bottom(self.gmail_limit, self.gmail_button)

        self.file_card = FileCard()
        self.file_card.import_button.clicked.connect(lambda: self.start_files(self.file_card.paths))

        self.naver_card = SourceCard(
            "네이버 메일",
            "네이버는 메일용 로그인 연동이 없어 IMAP과 애플리케이션 비밀번호로 연결할 예정입니다.",
            badge="준비 중",
        )
        self.naver_card.add_bottom()
        self.naver_card.setEnabled(False)

        cards = QHBoxLayout()
        cards.setSpacing(tokens.SPACE_3)
        for card in (self.gmail_card, self.file_card, self.naver_card):
            cards.addWidget(card, 1)

        self.stage_label = set_role(QLabel(""), "role", "label")
        self.progress = QProgressBar()
        self.cancel_button = QPushButton("가져오기 취소")
        self.cancel_button.clicked.connect(self.cancel)
        self.status_card, status = section_card()
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_4)
        row.addWidget(self.stage_label)
        row.addWidget(self.progress, 1)
        row.addWidget(self.cancel_button)
        status.addLayout(row)
        self.message_label = set_role(QLabel(""), "role", "body")
        self.message_label.setObjectName("importMessage")
        self.message_label.setWordWrap(True)

        layout = page_layout(self)
        layout.addLayout(page_header(title, privacy))
        layout.addLayout(cards)
        layout.addWidget(self.status_card)
        layout.addWidget(self.message_label)
        layout.addStretch(1)

    # --- 시작·취소 ---

    def is_running(self) -> bool:
        return self._task is not None and self._task.is_running()

    def start_files(self, paths: list[Path]) -> None:
        try:
            FileMailSource(paths)  # 지원하는 파일이 있는지 먼저 확인
        except (UnsupportedFileError, OSError) as e:
            self.message_label.setText(str(e))
            return
        self._start(file_opener(paths))

    def start_gmail(self) -> None:
        limit = self.gmail_limit.currentData() or None
        self._start(gmail_opener(self._app_root, limit))

    def cancel(self) -> None:
        if self._task is not None and self.is_running():
            self.message_label.setText("취소하는 중입니다…")
            self._task.cancel()

    def _start(self, opener: SourceOpener) -> None:
        if self.is_running():
            return
        relay = self._relay

        def job(ctx):
            try:
                ctx.raise_if_cancelled()
                analyzer = self._analyzer_factory()
                ctx.raise_if_cancelled()
                return run_pipeline(
                    opener,
                    analyzer,
                    on_stage=lambda s, d, t: relay.stage.emit(s.value, d, t),
                    should_cancel=lambda: ctx.cancelled,
                )
            except (ImportCancelled, AnalysisCancelled) as e:
                raise TaskCancelled from e

        self._task = BackgroundTask(job, name="mail-import", parent=self)
        self._task.succeeded.connect(self._on_succeeded)
        self._task.failed.connect(self._on_failed)
        self._task.cancelled.connect(self._on_cancelled)
        self._task.finished.connect(lambda: self._set_running(False))
        self.message_label.clear()
        self._set_running(True)
        self._task.start()

    # --- 결과 (UI 스레드) ---

    def _on_stage(self, stage: str, done: int, total: int) -> None:
        self.stage_label.setText(Stage(stage).label)
        self.progress.setRange(0, total or 0)  # 전체를 모르면 움직이는 막대
        if total:
            self.progress.setValue(done)

    def _on_succeeded(self, outcome: ImportOutcome) -> None:
        skipped = len(outcome.stats.skipped)
        self.message_label.setText(
            f"{outcome.source_name}: 메일 {len(outcome.mails)}통에서 계정 후보 "
            f"{len(outcome.candidates)}개를 찾았습니다."
            + (f" (읽지 못한 메일 {skipped}통)" if skipped else "")
        )
        self.import_finished.emit(outcome)

    def _on_failed(self, error: BaseException) -> None:
        if isinstance(error, GmailError):
            self.message_label.setText(str(error))
        else:
            self.message_label.setText(
                f"가져오지 못했습니다 ({type(error).__name__}). 다시 시도해 주세요."
            )

    def _on_cancelled(self) -> None:
        self.message_label.setText("가져오기를 취소했습니다. 가져온 메일은 남기지 않았습니다.")

    def _set_running(self, running: bool) -> None:
        for widget in (self.gmail_button, self.gmail_limit, self.file_card):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.status_card.setVisible(running)
        if not running:
            self._task = None
