"""역할 사이의 경계. 데스크톱·ML·브라우저 코드는 이 모듈로만 서로를 안다.

- 데스크톱 → ML: `ParsedMail`
- ML → 데스크톱: `AccountAnalyzer`(구현), `AccountCandidate`
- 브라우저 → 데스크톱: `Playbook`(JSON), `WithdrawAgent`(구현)

이 패키지를 바꾸는 PR은 세 역할 담당자 모두의 리뷰를 받는다.
"""

from account_cleaner.contracts.agent import (
    AgentEvent,
    AgentStatus,
    EventCallback,
    HandoffReason,
    WithdrawAgent,
)
from account_cleaner.contracts.analysis import (
    AccountAnalyzer,
    AccountCandidate,
    AnalysisCancelled,
    CancelCheck,
    Evidence,
    EvidenceType,
    ProgressCallback,
)
from account_cleaner.contracts.login import LoginMethod
from account_cleaner.contracts.mail import ParsedMail
from account_cleaner.contracts.playbook import (
    Playbook,
    PlaybookError,
    host_matches,
    load_playbook,
    load_playbooks,
)

__all__ = [
    "AccountAnalyzer",
    "AccountCandidate",
    "AgentEvent",
    "AgentStatus",
    "AnalysisCancelled",
    "CancelCheck",
    "EventCallback",
    "Evidence",
    "EvidenceType",
    "HandoffReason",
    "LoginMethod",
    "ParsedMail",
    "Playbook",
    "PlaybookError",
    "ProgressCallback",
    "WithdrawAgent",
    "host_matches",
    "load_playbook",
    "load_playbooks",
]
