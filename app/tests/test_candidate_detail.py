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
SAMPLE_PLAYBOOKS = load_playbooks(SAMPLE_PLAYBOOK_DIR)
OPENED: list[str] = []
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
        playbook_lookup=lambda domain: (
            SAMPLE_PLAYBOOKS["sample_shop"] if domain == "shop.example.com" else None
        ),
        open_url=OPENED.append,
    )
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_신뢰도는_어떤_근거_메일이_만들었는지_문장으로_설명한다():
    # given / when
    text = explain_score(SHOP)

    # then
    assert text.startswith("계정 있음")
    assert "가입·인증 메일 1통" in text
    assert "광고·초대 메일 1통" in text
    assert "%" not in text


def test_근거_메일에는_판단에_쓰인_문장이_함께_보인다(panel):
    # given / when
    panel.show_candidate(SHOP, CandidateStatus.UNREVIEWED)

    # then
    assert "“샘플쇼핑 회원가입이 완료되었습니다.”" in panel.evidence_list.item(0).text()
    assert "%" not in panel.evidence_list.item(0).text()


def test_모델의_삭제추정은_탈퇴완료로_설명하지않는다():
    # given / when / then
    assert "모델의 추정" in explain_score(UNKNOWN)
    assert "이미 탈퇴했을 가능성" not in explain_score(UNKNOWN)


def test_명시적_삭제완료도_현재상태로_단정하지않는다():
    candidate = AccountCandidate(
        "샘플", "sample.example", 0.05, (Evidence("x", EvidenceType.DELETED, 1.0),), T, T
    )
    assert "과거 탈퇴 완료" in explain_score(candidate)
    assert "재가입" in explain_score(candidate)


def test_광고만있는_후보는_가입미확인으로_설명한다():
    candidate = AccountCandidate(
        "샘플", "sample.example", 0, (Evidence("x", EvidenceType.PROMO, 0.9),), T, T
    )
    assert "약한 흔적" in explain_score(candidate)


def test_후보를_고르기_전에는_안내만_보인다(panel):
    # given / when / then
    assert panel.empty_label.isVisible()
    assert not panel.content.isVisible()


def test_후보를_고르면_서비스_날짜_가입_방식_근거_메일이_보인다(panel):
    # given / when
    panel.show_candidate(SHOP, CandidateStatus.UNREVIEWED)

    # then
    assert "샘플쇼핑" in panel.title_label.text()
    assert "처음 메일 2024.03.11" in panel.dates_label.text()
    assert panel.login_label.text() == "메일에 적힌 가입 방식: 카카오"
    rows = [panel.evidence_list.item(i).text() for i in range(panel.evidence_list.count())]
    assert rows[0] == (
        "2024.03.11  가입을 환영합니다\n[가입·인증] “샘플쇼핑 회원가입이 완료되었습니다.”"
    )
    assert rows[1] == "[광고·초대] · 메일 <m2@shop>"  # 가져온 메일에 없으면 ID만


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


def test_플레이북이_없는_서비스는_탈퇴_준비_버튼이_꺼지고_이유가_보인다(panel):
    # given / when
    panel.show_candidate(UNKNOWN)

    # then
    assert not panel.guide_button.isEnabled()
    assert "안내 정보(플레이북)가 없어" in panel.agent_hint.text()


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
    assert page.detail.status_label.text() == "확정"
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


# --- 로그인·복구·탈퇴 전 조건 안내 (#14) ---


@pytest.fixture
def guide(qtbot, panel):
    OPENED.clear()
    panel.show_candidate(SHOP)
    panel.guide_button.click()
    return panel.guide_dialog


def test_탈퇴_준비를_누르면_로그인_링크와_조건이_있는_안내_창이_열린다(guide):
    # given / when: fixture에서 '탈퇴 준비' 클릭

    # then
    assert guide is not None and guide.isVisible()
    assert [b.text() for b in guide.condition_boxes] == [
        "적립금 잔액은 탈퇴 시 소멸됩니다",
        "유료 멤버십은 먼저 해지해야 합니다",
        "탈퇴하면 계정과 데이터를 되돌릴 수 없다는 것을 확인했습니다",
    ]


def test_조건을_모두_확인하기_전에는_진행_버튼이_꺼져_있다(guide):
    # given / when: 하나만 빼고 체크
    for box in guide.condition_boxes[:-1]:
        box.setChecked(True)

    # then
    assert not guide.proceed_button.isEnabled()
    assert "1개가 남았습니다" in guide.proceed_hint.text()


def test_조건을_모두_확인하고_진행하면_에이전트_요청이_간다(qtbot, panel, guide):
    # given
    for box in guide.condition_boxes:
        box.setChecked(True)

    # when
    with qtbot.waitSignal(panel.agent_requested) as blocker:
        guide.proceed_button.click()

    # then
    assert blocker.args[0] is SHOP


def test_메일로_확인된_가입_방식은_로그인_방법_맨_앞에_표시한다(guide):
    # given: 샘플쇼핑 플레이북은 이메일·카카오·네이버, 메일로 확인된 방식은 카카오

    # when / then
    assert guide.login_lines[0].startswith("카카오 로그인 — 메일에서")
    assert guide.login_lines[1:] == ["이메일·비밀번호", "네이버 로그인"]


def test_로그인_재설정_링크는_플레이북_주소를_기본_브라우저로_연다(guide):
    # given / when
    guide.login_button.click()
    guide.reset_button.click()

    # then
    playbook = SAMPLE_PLAYBOOKS["sample_shop"]
    assert OPENED == [playbook.login_url, playbook.password_reset_url]


def test_조건이_없는_서비스도_되돌릴_수_없다는_확인은_받는다(qtbot):
    # given: 탈퇴 전 조건이 비어 있는 플레이북
    from dataclasses import replace

    from PySide6.QtWidgets import QLabel

    from account_cleaner.ui.candidates.guide import NO_CONDITIONS, WithdrawGuideDialog

    playbook = replace(SAMPLE_PLAYBOOKS["sample_shop"], pre_withdraw_conditions=())

    # when
    dialog = WithdrawGuideDialog(SHOP, playbook, open_url=lambda u: None)
    qtbot.addWidget(dialog)

    # then
    assert len(dialog.condition_boxes) == 1
    assert not dialog.proceed_button.isEnabled()
    assert any(label.text() == NO_CONDITIONS for label in dialog.findChildren(QLabel))
