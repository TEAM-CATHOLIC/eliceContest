"""계정 인벤토리 디자인 (#66): 맨 위 문장, 목록 줄, 상세 패널 표시."""

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame

from account_cleaner.contracts import AccountCandidate, Evidence, EvidenceType
from account_cleaner.ui.candidates.delegate import (
    ROW_HEIGHT,
    avatar_tint,
    display_name,
    meta_text,
)
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage, headline

WHEN = datetime(2026, 10, 19, tzinfo=UTC)


def candidate(service: str, domain: str, score: float = 0.9) -> AccountCandidate:
    return AccountCandidate(
        service=service,
        domain=domain,
        score=score,
        evidence=(Evidence("m1", EvidenceType.SIGNUP, 0.9),),
        first_seen=WHEN,
        last_seen=WHEN,
    )


def test_맨_위_문장은_지금_할_일을_알려_준다():
    # then
    assert headline(0, 0) == "계정 인벤토리"
    assert headline(12, 7) == "확인할 계정이 7개 있어요"
    assert headline(12, 0) == "찾은 계정을 모두 확인했어요"


def test_소문자_영문_서비스_이름만_첫_글자를_대문자로_보여_준다():
    # then
    assert display_name("github") == "Github"
    assert display_name("GitHub") == "GitHub"
    assert display_name("쿠팡") == "쿠팡"


def test_아바타_색은_도메인마다_항상_같다():
    # then
    assert avatar_tint("github.com") == avatar_tint("github.com")


def test_목록_줄_요약은_근거와_마지막_메일_날짜를_담는다():
    # then
    assert meta_text(candidate("github", "github.com")) == "가입·인증 1 · 마지막 메일 2026.10.19"


def test_목록_줄은_넉넉한_높이로_그리고_잘린_글은_툴팁으로_전체를_보여_준다(qtbot):
    # given
    page = InventoryPage()
    qtbot.addWidget(page)
    page.set_candidates([candidate("github", "github.com")])
    index = page.proxy.index(0, 0)

    # then
    assert page.list_view.sizeHintForRow(0) >= ROW_HEIGHT
    assert "github.com" in index.data(Qt.ItemDataRole.ToolTipRole)


def test_후보를_불러오면_맨_위_문장과_확인_필요_숫자가_바뀐다(qtbot):
    # given
    page = InventoryPage()
    qtbot.addWidget(page)

    # when
    page.set_candidates(
        [candidate("github", "github.com"), candidate("notion", "notion.so")],
        {"notion.so": CandidateStatus.CONFIRMED},
    )

    # then
    assert page.title_label.text() == "확인할 계정이 1개 있어요"
    assert page.cards[CandidateStatus.UNREVIEWED].value.text() == "1"


def test_상세_패널은_고른_상태_버튼을_꺼서_메인_색으로_보여_준다(qtbot):
    # given
    page = InventoryPage()
    qtbot.addWidget(page)
    page.set_candidates([candidate("github", "github.com")], {"github.com": "confirmed"})

    # when
    page.select_row(0)

    # then
    button = page.detail.review_buttons[CandidateStatus.CONFIRMED]
    assert button.property("variant") == "choice"
    assert not button.isEnabled()
    assert page.detail.status_label.text() == "확정"
    assert page.detail.title_label.text() == "Github"


def test_창을_키우면_목록과_상세_패널이_함께_늘어난다(qtbot):
    # given (#71)
    page = InventoryPage()
    qtbot.addWidget(page)
    page.set_candidates([candidate("github", "github.com")])
    page.resize(1000, 700)
    page.show()
    qtbot.waitExposed(page)
    detail = page.findChild(QFrame, "candidateDetail")
    small = detail.width()

    # when
    page.resize(1800, 900)
    qtbot.waitUntil(lambda: detail.width() > small)

    # then: 목록:상세 ≈ 3:2
    list_card = page.findChild(QFrame, "candidateListCard")
    assert detail.width() > small + 200
    assert 1.2 < list_card.width() / detail.width() < 1.8
