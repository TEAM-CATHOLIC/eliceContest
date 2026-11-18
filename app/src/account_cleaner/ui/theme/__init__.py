"""앱 디자인 (#66, A안 청록): 기준값(tokens), 스타일시트, 폰트(Pretendard), 아이콘(Tabler)."""

import logging
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from account_cleaner.ui.theme import tokens
from account_cleaner.ui.theme.icons import Icon, icon, pixmap
from account_cleaner.ui.theme.stylesheet import build_stylesheet

__all__ = [
    "Icon",
    "apply_theme",
    "icon",
    "load_fonts",
    "page_header",
    "pixmap",
    "set_role",
    "tokens",
]

log = logging.getLogger(__name__)

FONT_DIR = Path(__file__).with_name("fonts")


def load_fonts() -> list[str]:
    """앱에 넣은 Pretendard를 등록한다. 등록된 글꼴 이름들을 돌려준다 (실패하면 빈 목록)."""
    families: set[str] = set()
    for path in sorted(FONT_DIR.glob("*.otf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            log.warning("글꼴을 불러오지 못했습니다: %s", path.name)
            continue
        families.update(QFontDatabase.applicationFontFamilies(font_id))
    return sorted(families)


def apply_theme(app: QApplication) -> None:
    """앱 글꼴과 스타일시트를 적용한다. QApplication을 만든 직후 한 번 부른다."""
    loaded = load_fonts()
    font = QFont()
    font.setFamilies([tokens.FONT_FAMILY, *tokens.FONT_FALLBACKS])
    font.setPixelSize(tokens.BODY.size)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    app.setStyle("Fusion")  # OS마다 기본 모양이 달라지지 않게 같은 바탕에서 스타일시트를 입힌다
    app.setStyleSheet(build_stylesheet())
    log.info("디자인 적용 (글꼴: %s)", ", ".join(loaded) or "기본 글꼴")


def set_role(widget: QWidget, name: str, value: str = "true") -> QWidget:
    """스타일시트용 속성(role, variant, card 등)을 붙인다. 이미 그려진 위젯이면 다시 그린다."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    return widget


HEADER_GAP = tokens.SPACE_2
"""페이지 제목과 한 줄 설명 사이"""
HEADER_BOTTOM = tokens.SPACE_2
"""제목 묶음과 아래 내용 사이 (페이지 layout 간격에 더해짐)"""


def page_header(title: QLabel, subtitle: QLabel | None = None) -> QVBoxLayout:
    """페이지 맨 위 제목 + 한 줄 설명. 모든 화면이 같은 여백을 쓴다."""
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, HEADER_BOTTOM)
    layout.setSpacing(HEADER_GAP)
    layout.addWidget(set_role(title, "role", "title"))
    if subtitle is not None:
        set_role(subtitle, "role", "muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
    return layout
