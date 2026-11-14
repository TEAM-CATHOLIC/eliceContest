"""로그 설정. 파일(앱 데이터 폴더/logs) + 콘솔.

로그에는 메일 본문·비밀번호를 쓰지 않는 것이 원칙이다. 실수로 이메일 주소가 섞여도
`RedactEmailFilter`가 아이디 부분을 가린다 (예: hong@gmail.com → h***@gmail.com).
"""

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = "app.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def redact_emails(text: str) -> str:
    return _EMAIL.sub(r"\1***@\2", text)


class RedactEmailFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_emails(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_emails(record.exc_text)
        return True


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    """루트 로거에 파일·콘솔 핸들러를 붙인다. 여러 번 불려도 핸들러가 중복되지 않는다."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_account_cleaner", False):
            root.removeHandler(h)
            h.close()

    formatter = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    console = logging.StreamHandler()
    for h in (file_handler, console):
        h.setFormatter(formatter)
        h.addFilter(RedactEmailFilter())
        h._account_cleaner = True  # type: ignore[attr-defined]
        root.addHandler(h)
