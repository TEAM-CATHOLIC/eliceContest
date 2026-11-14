"""오류 대화상자와 처리되지 않은 예외 처리."""

import logging
import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from account_cleaner.core.log_setup import redact_emails

log = logging.getLogger(__name__)


def show_error(
    parent: QWidget | None, title: str, message: str, details: str | None = None
) -> None:
    """사용자용 오류 안내. `details`는 접힌 "자세히" 영역에 보인다 (이메일 주소는 가림)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    if details:
        box.setDetailedText(redact_emails(details))
    box.exec()


def show_exception(parent: QWidget | None, error: BaseException, message: str) -> None:
    details = "".join(traceback.format_exception(error))
    show_error(parent, "오류", message, details)


def install_excepthook() -> None:
    """UI 스레드에서 처리되지 않은 예외를 로그에 남기고 대화상자로 알린다. 앱은 계속 실행된다."""

    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("처리되지 않은 예외", exc_info=(exc_type, exc, tb))
        if QApplication.instance() is not None:
            show_exception(None, exc.with_traceback(tb), "예상하지 못한 오류가 발생했습니다.")

    sys.excepthook = hook
