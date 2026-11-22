"""Tabler 아이콘(MIT)을 원하는 색으로 그려 쓴다.

SVG의 `currentColor`를 색으로 바꿔 그린다. 고해상도 화면에서도 선명하도록 2배로 그린다.
"""

import tempfile
from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from account_cleaner.ui.theme import tokens

ICON_DIR = Path(__file__).with_name("icons")
APP_ICON = Path(__file__).with_name("app_icon.png")
"""앱 아이콘 (창·작업 표시줄·트레이). 실행 파일 아이콘은 packaging/icons/의 .ico·.icns"""
SCALE = 2


class Icon:
    INVENTORY = "list-details"
    AGENT = "arrow-right"
    SOURCES = "mail"
    HISTORY = "clock"
    SEARCH = "search"
    LOCK = "lock"
    SHIELD = "shield-check"
    CHEVRON_DOWN = "chevron-down"
    CHECK = "check"
    CLOSE = "x"


@cache
def svg_text(name: str, color: str) -> str:
    path = ICON_DIR / f"{name}.svg"
    if not path.is_file():
        raise FileNotFoundError(f"아이콘이 없습니다: {name}")
    return path.read_text(encoding="utf-8").replace("currentColor", color)


def pixmap(name: str, color: str = tokens.GRAY_800, size: int = 18) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_text(name, color).encode()))
    image = QPixmap(QSize(size * SCALE, size * SCALE))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * SCALE, size * SCALE))
    painter.end()
    image.setDevicePixelRatio(SCALE)
    return image


def icon(
    name: str,
    color: str = tokens.GRAY_800,
    size: int = 18,
    selected_color: str | None = None,
    disabled_color: str = tokens.GRAY_600,
) -> QIcon:
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, disabled_color, size), QIcon.Mode.Disabled)
    if selected_color:
        result.addPixmap(pixmap(name, selected_color, size), QIcon.Mode.Selected)
    return result


@cache
def icon_file(name: str, color: str) -> str:
    """스타일시트(`image: url(...)`)에 쓸 색 입힌 SVG 파일 경로. 임시 폴더에 한 번만 만든다."""
    folder = Path(tempfile.gettempdir()) / "account-cleaner-icons"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}.svg"
    path.write_text(svg_text(name, color), encoding="utf-8")
    return path.as_posix()


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON))
