"""메일 가져오기 (PRD F-01). 소스(파일·Gmail·네이버) → 공통 정규화 → `ParsedMail`."""

from account_cleaner.mail.files import (
    SUPPORTED_EXTENSIONS,
    FileMailSource,
    UnsupportedFileError,
    iter_mbox,
)
from account_cleaner.mail.importer import (
    ImportCancelled,
    ImportResult,
    ImportStats,
    SkippedMail,
    import_mails,
    iter_parsed_mails,
)
from account_cleaner.mail.normalize import MailParseError, decode_bytes, parse_mail
from account_cleaner.mail.source import MailSource, RawMail

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "FileMailSource",
    "ImportCancelled",
    "ImportResult",
    "ImportStats",
    "MailParseError",
    "MailSource",
    "RawMail",
    "SkippedMail",
    "UnsupportedFileError",
    "decode_bytes",
    "import_mails",
    "iter_mbox",
    "iter_parsed_mails",
    "parse_mail",
]
