"""실제 구현(ML·브라우저)이 오기 전까지 쓰는 가짜 구현. 시연·개발용으로 src에 둔다."""

from importlib.resources import files
from pathlib import Path

from account_cleaner.fakes.agent import FakeWithdrawAgent
from account_cleaner.fakes.analyzer import FakeAnalyzer

SAMPLE_PLAYBOOK_DIR = Path(str(files(__package__) / "playbooks"))
"""예시 플레이북 3개 (example.com 계열 가상 서비스)."""

__all__ = ["SAMPLE_PLAYBOOK_DIR", "FakeAnalyzer", "FakeWithdrawAgent"]
