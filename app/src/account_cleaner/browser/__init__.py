"""브라우저 에이전트 (PRD F-06). `providers`가 아래 두 이름을 찾아 실제 구현으로 쓴다.

- `create_withdraw_agent(profile_dir)`: `contracts.WithdrawAgent` 구현
- `PLAYBOOK_DIR`: 계약 형식(`contracts.Playbook`) 플레이북 JSON 폴더

엔진(`browser.agent`)은 브라우저 담당 작성분이고, 이 패키지의 나머지는 데스크톱 인터페이스 연결이다.
"""

from importlib import resources
from pathlib import Path

from account_cleaner.contracts import WithdrawAgent

PLAYBOOK_DIR = Path(str(resources.files(__package__) / "playbooks"))


def create_withdraw_agent(profile_dir: Path) -> WithdrawAgent:
    from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent

    return PlaywrightWithdrawAgent(profile_dir)
