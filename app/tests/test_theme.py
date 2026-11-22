"""디자인 테마(#66): 글꼴·아이콘·스타일시트가 제대로 실리고, 메뉴 글자가 잘리지 않는다."""

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QLabel

from account_cleaner.ui.main_window import (
    PAGE_TITLES,
    SIDEBAR_WIDTH,
    MainWindow,
    NavDelegate,
    PageId,
)
from account_cleaner.ui.theme import (
    Icon,
    apply_theme,
    load_fonts,
    page_header,
    pixmap,
    section_card,
    set_role,
    tokens,
)
from account_cleaner.ui.theme.icons import ICON_DIR
from account_cleaner.ui.theme.stylesheet import build_stylesheet

APP_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def themed(qapp: QApplication):
    font, sheet = qapp.font(), qapp.styleSheet()
    apply_theme(qapp)
    yield qapp
    qapp.setFont(font)
    qapp.setStyleSheet(sheet)


def test_앱에_넣은_Pretendard_글꼴을_등록한다(qapp):
    # when
    families = load_fonts()

    # then
    assert tokens.FONT_FAMILY in families


def test_테마를_적용하면_앱_글꼴이_Pretendard_14px이고_메인_색이_스타일시트에_들어간다(themed):
    # then
    assert themed.font().families()[0] == tokens.FONT_FAMILY
    assert themed.font().pixelSize() == tokens.BODY.size
    assert tokens.ACCENT in themed.styleSheet()


def test_스타일시트에_채워지지_않은_자리가_없다():
    # when
    sheet = build_stylesheet()

    # then
    assert "{t." not in sheet
    assert "None" not in sheet
    assert sheet.count("{") == sheet.count("}")


@pytest.mark.parametrize("name", [v for k, v in vars(Icon).items() if not k.startswith("_")])
def test_모든_아이콘을_원하는_색으로_그린다(qapp, name):
    # when
    image = pixmap(name, tokens.ACCENT, 18).toImage()

    # then
    colors = {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() == 255
    }
    assert QColor(tokens.ACCENT).name() in colors


def test_set_role은_스타일시트용_속성을_붙인다(qapp):
    # given
    label = QLabel("제목")

    # when
    set_role(label, "role", "title")

    # then
    assert label.property("role") == "title"


def test_사이드바_메뉴_이름은_배지가_있어도_잘리지_않는다(themed):
    # given: 메뉴 한 줄 = 여백 12 + 아이콘 18 + 간격 10 + 글자 + 간격 8 + 배지(두 자리) + 여백 12
    font = QFont(themed.font())
    font.setWeight(QFont.Weight.DemiBold)
    badge = max(20, QFontMetrics(font).horizontalAdvance("99") + 12)
    available = SIDEBAR_WIDTH - 2 * 14 - 12 - 18 - 10 - 8 - badge - 12

    # then
    for title in PAGE_TITLES.values():
        assert QFontMetrics(font).horizontalAdvance(title) <= available, title


def test_사이드바_메뉴에_숫자_배지를_달고_뗄_수_있다(qtbot):
    # given
    window = MainWindow()
    qtbot.addWidget(window)

    # when
    window.set_nav_badge(PageId.INVENTORY, "7")
    window.set_nav_badge(PageId.HISTORY, "1", tone="warning")
    window.set_nav_badge(PageId.HISTORY, None)

    # then
    assert window.nav_badge(PageId.INVENTORY) == "7"
    assert window.nav_badge(PageId.HISTORY) is None
    assert isinstance(window._nav.itemDelegate(), NavDelegate)


def test_가져다_쓴_글꼴_아이콘_디자인_값의_라이선스를_함께_배포한다():
    # then
    assert (ICON_DIR / "LICENSE").is_file()
    assert (ICON_DIR.parent / "fonts" / "OFL.txt").is_file()
    notices = (APP_DIR / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for name in ("Pretendard", "Tabler Icons", "SEED Design", "Apache License"):
        assert name in notices


def test_페이지_머리는_제목과_한_줄_설명_사이에_여백을_둔다(qapp):
    # given
    title, subtitle = QLabel("진행 기록"), QLabel("설명")

    # when
    layout = page_header(title, subtitle)

    # then
    assert layout.spacing() >= tokens.SPACE_2
    assert title.property("role") == "title"
    assert subtitle.property("role") == "muted"
    assert subtitle.wordWrap()


def test_구역_카드는_소제목과_넉넉한_안쪽_여백을_가진다(qapp):
    # when
    card, layout = section_card("서비스별 진행", kind="warning")

    # then
    assert card.property("card") == "warning"
    assert layout.itemAt(0).widget().text() == "서비스별 진행"
    margins = layout.contentsMargins()
    assert min(margins.left(), margins.top(), margins.right()) >= tokens.SPACE_4


def test_앱_아이콘_파일이_있고_창_아이콘으로_불러올_수_있다(qapp):
    # given / when
    from account_cleaner.ui.theme.icons import APP_ICON, app_icon

    # then
    assert APP_ICON.is_file()
    assert not app_icon().isNull()
