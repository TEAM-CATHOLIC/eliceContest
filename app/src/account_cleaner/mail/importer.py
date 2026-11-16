"""메일 소스 → `ParsedMail` 목록. 진행률, 취소, 깨진 메일 건너뛰기, 중복 제거."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from account_cleaner.contracts import CancelCheck, ParsedMail, ProgressCallback
from account_cleaner.mail.normalize import MailParseError, parse_mail
from account_cleaner.mail.source import MailSource

log = logging.getLogger(__name__)

PROGRESS_EVERY = 50
"""진행률 콜백을 이 통수마다 부른다 (UI 시그널 폭주 방지)."""


class ImportCancelled(Exception):
    """`should_cancel()`이 True를 돌려줘 가져오기를 멈췄다."""


@dataclass(frozen=True, slots=True)
class SkippedMail:
    origin: str
    reason: str


@dataclass
class ImportStats:
    parsed: int = 0
    duplicates: int = 0
    skipped: list[SkippedMail] = field(default_factory=list)


@dataclass
class ImportResult:
    mails: list[ParsedMail]
    stats: ImportStats


def _skip(stats: ImportStats, origin: str, reason: str) -> None:
    stats.skipped.append(SkippedMail(origin, reason))
    log.warning("메일 건너뜀 (%s): %s", origin, reason)


def iter_parsed_mails(
    source: MailSource,
    stats: ImportStats,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> Iterator[ParsedMail]:
    """한 통씩 `ParsedMail`로 바꿔 내보낸다. 저장소에 바로 쓰면 전체를 메모리에 올리지 않아도 된다."""
    total = source.total()
    seen: set[str] = set()
    last_progress = 0
    for count, raw in enumerate(source, start=1):
        if should_cancel and should_cancel():
            raise ImportCancelled
        last_progress = raw.progress
        if on_progress and total and count % PROGRESS_EVERY == 0:
            on_progress(min(raw.progress, total), total)
        try:
            mail = parse_mail(raw.data)
        except MailParseError as e:
            _skip(stats, raw.origin, str(e))
            continue
        except Exception as e:  # noqa: BLE001 — 깨진 메일 한 통 때문에 전체가 멈추면 안 된다
            _skip(stats, raw.origin, f"예상하지 못한 형식 ({type(e).__name__})")
            continue
        if mail.id in seen:
            stats.duplicates += 1
            continue
        seen.add(mail.id)
        stats.parsed += 1
        yield mail
    for origin, reason in source.failures():
        _skip(stats, origin, reason)
    if on_progress:
        on_progress(total or last_progress, total or last_progress)


def import_mails(
    source: MailSource,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> ImportResult:
    stats = ImportStats()
    mails = list(iter_parsed_mails(source, stats, on_progress, should_cancel))
    log.info(
        "메일 가져오기 완료 (%s): %d통, 중복 %d, 건너뜀 %d",
        source.name,
        stats.parsed,
        stats.duplicates,
        len(stats.skipped),
    )
    return ImportResult(mails, stats)
