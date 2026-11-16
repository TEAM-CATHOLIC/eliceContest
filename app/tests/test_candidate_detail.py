"""후보 상세 패널 테스트. 후보와 메일은 테스트 안에서 만든 합성 데이터."""

from datetime import UTC, datetime

import pytest

from account_cleaner.contracts import (
    AccountCandidate,
    Evidence,
    EvidenceType,
    LoginMethod,
    ParsedMail,
    load_playbooks,
)
from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR, FakeWithdrawAgent
from account_cleaner.ui.agent_page import AgentPage
from account_cleaner.ui.candidates.detail import CandidateDetailPanel, explain_score
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.candidates.page import InventoryPage
from account_cleaner.ui.workers import BackgroundTask

T = datetime(2024, 3, 11, tzinfo=UTC)
MAIL = ParsedMail(
    "<m1@shop>", "no-reply@shop.example.com", "shop.example.com", "가입을 환영합니다", T,
    "샘플쇼핑 회원가입이 완료되었습니다. " * 50,
)  # fmt: skip
SHOP = AccountCandidate(
    "샘플쇼핑",
    "shop.example.com",
    0.92,
    (
        Evidence("<m1@shop>", EvidenceType.SIGNUP, 0.95),
        Evidence("<m2@shop>", EvidenceType.PROMO, 0.6),
    ),
    T,
    T,
    confirmed_login_method=LoginMethod.KAKAO,
)
UNKNOWN = AccountCandidate(
    "모르는서비스", "unknown.example.io", 0.5, (Evidence("<x>", EvidenceType.DELETED, 0.9),), T, T
)


@pytest.fixture
def panel(qtbot):
    widget = CandidateDetailPanel(
        mail_lookup={"<m1@shop>": MAIL}.get,
        playbook_lookup=lambda domain: object() if domain == "shop.example.com" else None,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_신뢰도는_어떤_근거_메일이_만들었는지_문장으로_설명한다():
    # given / when
    text = explain_score(SHOP)

    # then
    assert text.startswith("신뢰도 92%")
    assert "가입·인증 메일 1통(최고 95%)" in text
    assert "광고·초대 메일 1통(최고 60%)" in text


def test_탈퇴_완료_메일이_있으면_이미_탈퇴했을_가능성을_알린다():
    # given / when / then
    assert "이미 탈퇴했을 가능성" in explain_score(UNKNOWN)


def test_후보를_고르기_전에는_안내만_보인다(panel):
    # given / when / then
    assert panel.empty_label.isVisible()
    assert not panel.content.isVisible()


def test_후보를_고르면_서비스_날짜_가입_방식_근거_메일이_보인다(panel):
    # given / when
    panel.show_candidate(SHOP, CandidateStatus.UNREVIEWED)

    # then
    assert "샘플쇼핑" in panel.title_label.text()
    assert "처음 메일 2024-03-11" in panel.dates_label.text()
    assert panel.login_label.text() == "메일에 적힌 가입 방식: 카카오"
    rows = [panel.evidence_list.item(i).text() for i in range(panel.evidence_list.count())]
    assert rows[0] == "[가입·인증] 95% · 2024-03-11 · 가입을 환영합니다"
    assert rows[1] == "[광고·초대] 60% · 메일 <m2@shop>"  # 가져온 메일에 없으면 ID만


def test_근거_메일을_고르면_본문_앞부분만_미리_보인다(panel):
    # given
    panel.show_candidate(SHOP)

    # when
    panel.evidence_list.setCurrentRow(0)

    # then
    text = panel.preview.toPlainText()
    assert text.startswith("보낸 사람: no-reply@shop.example.com")
    assert text.endswith("…")


def test_확인_버튼을_누르면_도메인과_상태로_요청_시그널이_온다(qtbot, panel):
    # given
    panel.show_candidate(SHOP)

    # when
    with qtbot.waitSignal(panel.status_requested) as blocker:
        panel.review_buttons[CandidateStatus.EXCLUDED].click()

    # then
    assert blocker.args == ["shop.example.com", CandidateStatus.EXCLUDED]


def test_플레이북이_없는_서비스는_에이전트_버튼이_꺼지고_이유가_보인다(panel):
    # given / when
    panel.show_candidate(UNKNOWN)

    # then
    assert not panel.agent_button.isEnabled()
    assert "플레이북이 없어" in panel.agent_hint.text()


def test_인벤토리에서_확정을_누르면_목록과_상세의_상태가_함께_바뀐다(qtbot):
    # given: 후보 하나를 고른 인벤토리
    page = InventoryPage()
    qtbot.addWidget(page)
    page.show()
    page.set_candidates([SHOP])
    page.select_row(0)

    # when
    page.detail.review_buttons[CandidateStatus.CONFIRMED].click()

    # then
    assert page.model.status_of("shop.example.com") is CandidateStatus.CONFIRMED
    assert page.detail.status_label.text() == "상태: 확정"
    assert not page.detail.review_buttons[CandidateStatus.CONFIRMED].isEnabled()


def test_에이전트_화면은_후보_도메인에_맞는_플레이북을_찾아_바로_안내를_시작한다(qtbot, tmp_path):
    # given
    agent_page = AgentPage(
        tmp_path / "profile",
        agent_factory=lambda d: FakeWithdrawAgent(d, step_delay=0.01),
        playbook_loader=lambda: load_playbooks(SAMPLE_PLAYBOOK_DIR),
        include_demo=False,
    )
    qtbot.addWidget(agent_page)
    playbook = agent_page.playbook_for_domain("mail.shop.example.com")

    # when
    started = agent_page.start_for(playbook.id)

    # then
    assert playbook.id == "sample_shop"
    assert started
    assert agent_page.service_combo.currentData() == "sample_shop"
    assert agent_page.playbook_for_domain("unknown.example.io") is None
    agent_page.stop()
    BackgroundTask.shutdown_all()
