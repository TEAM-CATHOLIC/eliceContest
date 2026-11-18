"""앱 디자인 (#66, A안 청록): 기준값(tokens), 스타일시트, 폰트(Pretendard), 아이콘(Tabler)."""

import logging
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from account_cleaner.ui.theme import tokens
from account_cleaner.ui.theme.icons import Icon, icon, pixmap
from account_cleaner.ui.theme.stylesheet import build_stylesheet

__all__ = ["Icon", "apply_theme", "icon", "load_fonts", "pixmap", "set_role", "tokens"]

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
