"""실제 구현과 가짜 구현 중 무엇을 쓸지 고른다. 앱 코드는 구현 클래스를 직접 import하지 않고 여기서 받는다.

실제 구현 쪽 약속 (각 담당자가 패키지 `__init__.py`에 둔다):
- `account_cleaner.classifier.create_analyzer() -> AccountAnalyzer`
- `account_cleaner.browser.create_withdraw_agent(profile_dir: Path) -> WithdrawAgent`
- `account_cleaner.browser.PLAYBOOK_DIR: Path` (플레이북 JSON 폴더)

환경변수 `ACCOUNT_CLEANER_FAKE`:
- 없음 또는 `auto`: 실제 구현이 있으면 그것, 없으면 가짜 (경고 로그)
- `all`: 전부 가짜
- `none`: 전부 실제. 없으면 에러
- `analyzer,agent,playbooks` 중 일부를 쉼표로: 적은 것만 가짜, 나머지는 실제 (없으면 에러)
"""

import importlib
import logging
import os
from pathlib import Path
from typing import Any

from account_cleaner.contracts import AccountAnalyzer, Playbook, WithdrawAgent, load_playbooks
from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR, FakeAnalyzer, FakeWithdrawAgent

log = logging.getLogger(__name__)

COMPONENTS = ("analyzer", "agent", "playbooks")
_REAL = {
    "analyzer": ("account_cleaner.classifier", "create_analyzer"),
    "agent": ("account_cleaner.browser", "create_withdraw_agent"),
    "playbooks": ("account_cleaner.browser", "PLAYBOOK_DIR"),
}


class ProviderError(RuntimeError):
    pass


def _mode(component: str) -> str:
    """ "fake" | "real" | "auto"."""
    raw = os.environ.get("ACCOUNT_CLEANER_FAKE", "auto").strip().lower()
    if raw in ("", "auto"):
        return "auto"
    if raw == "all":
        return "fake"
    if raw == "none":
        return "real"
    names = {n.strip() for n in raw.split(",")}
    unknown = names - set(COMPONENTS)
    if unknown:
        raise ProviderError(f"ACCOUNT_CLEANER_FAKE에 알 수 없는 값: {', '.join(sorted(unknown))}")
    return "fake" if component in names else "real"


def _real(component: str) -> Any | None:
    module_name, attr = _REAL[component]
    module = importlib.import_module(module_name)
    if component == "analyzer" and hasattr(module, "is_configured") and not module.is_configured():
        return None
    return getattr(module, attr, None)


def _resolve(component: str) -> Any | None:
    """실제 구현을 돌려주거나, 가짜를 써야 하면 None."""
    mode = _mode(component)
    if mode == "fake":
        return None
    real = _real(component)
    if real is None:
        if mode == "real":
            module_name, attr = _REAL[component]
            raise ProviderError(f"실제 구현 없음: {module_name}.{attr}")
        log.warning("%s: 실제 구현이 없어 가짜를 사용합니다", component)
    return real


def get_analyzer() -> AccountAnalyzer:
    factory = _resolve("analyzer")
    return factory() if factory else FakeAnalyzer()


def get_withdraw_agent(profile_dir: Path) -> WithdrawAgent:
    factory = _resolve("agent")
    return factory(profile_dir) if factory else FakeWithdrawAgent(profile_dir)


def get_playbooks() -> dict[str, Playbook]:
    directory = _resolve("playbooks")
    return load_playbooks(Path(directory) if directory else SAMPLE_PLAYBOOK_DIR)
