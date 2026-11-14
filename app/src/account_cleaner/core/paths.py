"""앱 데이터 폴더. DB, 전용 브라우저 프로필, 로그, 설정을 모두 한 폴더 아래에 둔다.

한 폴더에 모아 두면 "앱 데이터 모두 지우기"가 폴더 삭제 하나로 끝난다 (논의사항 D-05).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QStandardPaths

HOME_ENV = "ACCOUNT_CLEANER_HOME"
"""이 환경변수가 있으면 OS 기본 위치 대신 그 폴더를 쓴다 (개발·테스트용)."""


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / "account_cleaner.sqlite3"

    @property
    def browser_profile(self) -> Path:
        """에이전트 전용 Chrome 프로필 (PRD 5장). 사용자의 Chrome 프로필과 분리된다."""
        return self.root / "browser_profile"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.ini"

    def ensure(self) -> "AppPaths":
        for d in (self.root, self.browser_profile, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        return self


def default_root() -> Path:
    """OS별 기본 위치.

    - macOS: ~/Library/Application Support/<조직>/<앱>
    - Windows: %APPDATA%/<조직>/<앱>
    - Linux: ~/.local/share/<조직>/<앱>

    `QCoreApplication.setOrganizationName/setApplicationName`이 먼저 불려 있어야 한다.
    """
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not location:
        raise RuntimeError("앱 데이터 폴더 위치를 알 수 없음")
    return Path(location)


def resolve_app_paths() -> AppPaths:
    override = os.environ.get(HOME_ENV)
    root = Path(override).expanduser() if override else default_root()
    return AppPaths(root).ensure()
