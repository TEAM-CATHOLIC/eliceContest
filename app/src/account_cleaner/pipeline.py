"""메일 가져오기 → 계정 후보 분석 (PRD F-01 → F-02). 화면 없이 작업 스레드에서 실행한다.

단계마다 `on_stage(단계, 처리한 수, 전체 수)`로 진행률을 알리고, `should_cancel()`이 True면
`ImportCancelled`(가져오기 중) 또는 `AnalysisCancelled`(분석 중)로 멈춘다. 결과는 메모리에만 둔다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from account_cleaner.contracts import (
    AccountAnalyzer,
    AccountCandidate,
    CancelCheck,
    ParsedMail,
)
from account_cleaner.mail import ImportStats, MailSource, iter_parsed_mails


class Stage(StrEnum):
    CONNECT = "connect"
    IMPORT = "import"
    ANALYZE = "analyze"

    @property
    def label(self) -> str:
        return {
            Stage.CONNECT: "계정 연결",
            Stage.IMPORT: "메일 가져오기",
            Stage.ANALYZE: "계정 후보 분석",
        }[self]


StageCallback = Callable[[Stage, int, int], None]
Cleanup = Callable[[], None]
SourceOpener = Callable[[CancelCheck], tuple[MailSource, Cleanup | None]]
"""소스를 연다 (계정 연결이면 로그인까지). 끝나면 부를 정리 함수(토큰 폐기 등)를 함께 돌려준다."""


@dataclass(frozen=True)
class ImportOutcome:
    source_name: str
    mails: list[ParsedMail]
    candidates: list[AccountCandidate]
    stats: ImportStats
    private_values: tuple[str, ...] = ()
    """범용 LLM 호출 전 가릴 연결 계정 식별자. 메일 본문은 포함하지 않는다."""

    def mail_lookup(self) -> Callable[[str], ParsedMail | None]:
        by_id = {m.id: m for m in self.mails}
        return by_id.get


def run_pipeline(
    open_source: SourceOpener,
    analyzer: AccountAnalyzer,
    on_stage: StageCallback,
    should_cancel: CancelCheck,
) -> ImportOutcome:
    on_stage(Stage.CONNECT, 0, 1)
    source, cleanup = open_source(should_cancel)
    try:
        on_stage(Stage.IMPORT, 0, 0)
        stats = ImportStats()
        mails = list(
            iter_parsed_mails(
                source,
                stats,
                on_progress=lambda done, total: on_stage(Stage.IMPORT, done, total),
                should_cancel=should_cancel,
            )
        )
    finally:
        if cleanup is not None:
            cleanup()
    on_stage(Stage.ANALYZE, 0, len(mails))
    candidates = analyzer.analyze(
        mails,
        on_progress=lambda done, total: on_stage(Stage.ANALYZE, done, total),
        should_cancel=should_cancel,
    )
    on_stage(Stage.ANALYZE, len(mails), len(mails))
    return ImportOutcome(source.name, mails, candidates, stats, source.private_values)
