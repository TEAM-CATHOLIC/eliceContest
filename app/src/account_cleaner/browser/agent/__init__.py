"""브라우저 에이전트 엔진 (브라우저 담당 작성).

플레이북 단계를 실행하고, 인증·결제 화면에서 사용자에게 넘기고, 허용 도메인 밖 이동과
최종 탈퇴 버튼 클릭을 막는다. 데스크톱과의 연결(`contracts.WithdrawAgent`)은 상위 패키지
`account_cleaner.browser`의 어댑터가 맡는다.
"""

from .engine import BrowserAgent
from .llm import ElementCandidate, NextClick, NextClickSelector
from .models import AgentResult, AgentStatus, Playbook

__all__ = [
    "AgentResult",
    "AgentStatus",
    "BrowserAgent",
    "ElementCandidate",
    "NextClick",
    "NextClickSelector",
    "Playbook",
]
