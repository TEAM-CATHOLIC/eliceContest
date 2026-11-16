"""계정 인벤토리(후보 목록) 테스트. 후보는 테스트 안에서 만든 합성 데이터."""

from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.contracts import AccountCandidate, Evidence, EvidenceType
from account_cleaner.ui.candidates.model import (
    CandidateFilter,
    CandidateListModel,
    CandidateSort,
    CandidateStatus,
    evidence_summary,
)
from account_cleaner.ui.candidates.page import InventoryPage

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def candidate(service, domain, score, days, *types):
    evidence = tuple(Evidence(f"<{domain}-{i}>", t, 0.9) for i, t in enumerate(types))
    return AccountCandidate(service, domain, score, evidence, T0, T0 + timedelta(days=days))


SHOP = candidate(
    "샘플쇼핑",
    "shop.example.com",
    0.9,
    10,
    EvidenceType.SIGNUP,
    EvidenceType.SIGNUP,
    EvidenceType.SECURITY,
)
MUSIC = candidate("샘플뮤직", "music.example.net", 0.4, 300, EvidenceType.PROMO)
SNS = candidate("샘플SNS", "sns.example.org", 0.7, 100, EvidenceType.ACTIVITY)


@pytest.fixture
def page(qtbot):
    widget = InventoryPage()
    qtbot.addWidget(widget)
    widget.show()
    widget.set_candidates([MUSIC, SHOP, SNS])
    return widget


# --- 모델 ---


def test_대표_근거는_많은_유형부터_개수와_함께_보인다():
    # given / when / then
    assert evidence_summary(SHOP) == "가입·인증 2 · 보안·복구 1"


def test_목록_한_줄에_서비스_도메인_신뢰도_근거_마지막_메일_상태가_보인다():
    # given
    model = CandidateListModel()
    model.set_candidates([SHOP])

    # when
    text = model.index(0).data()

    # then
    assert "샘플쇼핑" in text and "shop.example.com" in text
    assert "신뢰도 90%" in text and "가입·인증 2" in text
    assert "마지막 메일 2024-01-11" in text and "미확인" in text


def test_저장된_상태가_있으면_그_상태로_보이고_없으면_미확인이다():
    # given
    model = CandidateListModel()

    # when
    model.set_candidates([SHOP, SNS], {"sns.example.org": CandidateStatus.EXCLUDED})

    # then
    assert model.status_of("shop.example.com") is CandidateStatus.UNREVIEWED
    assert model.status_of("sns.example.org") is CandidateStatus.EXCLUDED


def test_필터_탭별_개수는_확정에_정리_중과_완료도_포함한다():
    # given
    model = CandidateListModel()
    model.set_candidates([SHOP, SNS, MUSIC])

    # when
    model.set_status("shop.example.com", CandidateStatus.IN_PROGRESS)
    model.set_status("sns.example.org", CandidateStatus.DEFERRED)

    # then
    assert model.filter_counts() == {
        CandidateFilter.ALL: 3,
        CandidateFilter.UNREVIEWED: 1,
        CandidateFilter.CONFIRMED: 1,
        CandidateFilter.SET_ASIDE: 1,
    }


# --- 화면 ---


def test_기본은_신뢰도_높은_순이고_최근_메일_순으로_바꿀_수_있다(page):
    # given / when
    by_score = [c.domain for c in page.visible_candidates()]
    page.sort_combo.setCurrentIndex(list(CandidateSort).index(CandidateSort.RECENT))
    by_recent = [c.domain for c in page.visible_candidates()]

    # then
    assert by_score == ["shop.example.com", "sns.example.org", "music.example.net"]
    assert by_recent == ["music.example.net", "sns.example.org", "shop.example.com"]


def test_검색어로_서비스명이나_도메인을_찾는다(page):
    # given / when
    page.set_search("뮤직")
    by_name = [c.domain for c in page.visible_candidates()]
    page.set_search("EXAMPLE.ORG")
    by_domain = [c.domain for c in page.visible_candidates()]

    # then
    assert by_name == ["music.example.net"]
    assert by_domain == ["sns.example.org"]


def test_필터_탭을_바꾸면_해당_상태만_보이고_탭에_개수가_보인다(page):
    # given
    page.set_status("sns.example.org", CandidateStatus.EXCLUDED)

    # when
    page.tabs.setCurrentIndex(list(CandidateFilter).index(CandidateFilter.SET_ASIDE))

    # then
    assert [c.domain for c in page.visible_candidates()] == ["sns.example.org"]
    assert page.tabs.tabText(0) == "전체 3"
    assert page.tabs.tabText(1) == "미확인 2"


def test_요약_카드는_상태가_바뀌면_바로_갱신된다(page):
    # given / when
    page.set_status("shop.example.com", CandidateStatus.DONE)

    # then
    assert page.cards["total"].value.text() == "3"
    assert page.cards[CandidateStatus.UNREVIEWED].value.text() == "2"
    assert page.cards[CandidateStatus.DONE].value.text() == "1"


def test_목록에서_고르면_그_후보로_선택_시그널이_온다(qtbot, page):
    # given / when
    with qtbot.waitSignal(page.candidate_selected) as blocker:
        page.select_row(0)

    # then
    assert blocker.args[0] is SHOP


def test_후보가_없으면_안내_문구가_보인다(qtbot):
    # given / when
    empty = InventoryPage()
    qtbot.addWidget(empty)
    empty.show()

    # then
    assert empty.empty_label.isVisible()
    assert not empty.list_view.isVisible()
