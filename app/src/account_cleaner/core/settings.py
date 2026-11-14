"""사용자 설정. 앱 데이터 폴더의 settings.ini 한 파일에 저장한다.

비밀번호·토큰 같은 인증정보는 여기에 저장하지 않는다 (PRD NF-01).
"""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QSettings

_FORBIDDEN_WORDS = ("password", "token", "secret_value")


class AppSettings:
    def __init__(self, path: Path) -> None:
        self._qs = QSettings(str(path), QSettings.Format.IniFormat)

    def get(self, key: str, default: Any = None, type_: type | None = None) -> Any:
        if type_ is None:
            return self._qs.value(key, default)
        return self._qs.value(key, default, type=type_)

    def set(self, key: str, value: Any) -> None:
        if any(w in key.lower() for w in _FORBIDDEN_WORDS):
            raise ValueError(f"인증정보로 보이는 키는 설정에 저장하지 않음: {key}")
        self._qs.setValue(key, value)

    def remove(self, key: str) -> None:
        self._qs.remove(key)

    def sync(self) -> None:
        self._qs.sync()

    # 창 위치·크기
    def window_geometry(self) -> QByteArray | None:
        value = self._qs.value("window/geometry")
        return value if isinstance(value, QByteArray) else None

    def set_window_geometry(self, geometry: QByteArray) -> None:
        self._qs.setValue("window/geometry", geometry)
