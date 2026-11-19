"""AI 에이전트 정리 화면 테스트. 가짜 에이전트(브라우저 없음)로 화면 흐름만 확인한다."""

import pytest

from account_cleaner.contracts import AgentStatus, load_playbooks
from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR, FakeWithdrawAgent
from account_cleaner.ui.agent_page import FINAL_STEP_TITLE, AgentPage, StepList
from account_cleaner.ui.workers import BackgroundTask


@pytest.fixture
def page(qtbot, tmp_path):
    widget = AgentPage(
        tmp_path / "profile",
        agent_factory=lambda d: FakeWithdrawAgent(d, step_delay=0.01),
        playbook_loader=lambda: load_playbooks(SAMPLE_PLAYBOOK_DIR),
        include_demo=False,
    )
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.stop()
    BackgroundTask.shutdown_all()


def test_서비스_목록에는_플레이북_서비스명이_보인다(page):
    # given / when
    names = [page.service_combo.itemText(i) for i in range(page.service_combo.count())]

    # then
    assert set(names) == {"샘플쇼핑", "샘플SNS", "샘플뮤직"}


def test_시작하면_사용자_차례에서_안내와_계속_버튼이_보인다(qtbot, page):
    # given / when
    page.start()
    qtbot.waitUntil(lambda: page.turn_box.isVisible(), timeout=3000)

    # then
    assert "로그인" in page.turn_label.text()
    assert not page.start_button.isEnabled()
    assert page.stop_button.isEnabled()
    assert any(row.startswith("⏸") for row in page.steps.rows())


def test_계속을_누르면_탈퇴_화면까지_가고_최종_단계만_사용자_몫으로_남는다(qtbot, page):
    # given: 사용자 차례
    page.start()
    qtbot.waitUntil(lambda: page.turn_box.isVisible(), timeout=3000)

    # when
    with qtbot.waitSignal(page.run_finished, timeout=3000) as blocker:
        page.resume_button.click()

    # then
    assert blocker.args[0].status is AgentStatus.REACHED
    rows = page.steps.rows()
    assert all(row.startswith("✓") for row in rows[:-1])
    assert rows[-1] == f"▶  {FINAL_STEP_TITLE}"
    assert "최종 버튼" in page.status_label.text()
    qtbot.waitUntil(lambda: page.start_button.isEnabled(), timeout=3000)


def test_중단하면_STOPPED로_끝나고_다시_시작할_수_있다(qtbot, page):
    # given: 사용자 차례
    page.start()
    qtbot.waitUntil(lambda: page.turn_box.isVisible(), timeout=3000)

    # when
    with qtbot.waitSignal(page.run_finished, timeout=3000) as blocker:
        page.stop_button.click()

    # then
    assert blocker.args[0].status is AgentStatus.STOPPED
    qtbot.waitUntil(lambda: page.start_button.isEnabled(), timeout=3000)
    assert not page.turn_box.isVisible()


def test_진행_로그에는_에이전트_메시지가_시간순으로_쌓인다(qtbot, page):
    # given / when
    page.start()
    qtbot.waitUntil(lambda: page.turn_box.isVisible(), timeout=3000)

    # then
    lines = page.log_lines()
    assert "안내를 시작합니다" in lines[0]
    assert any("로그인 페이지 여는 중" in line for line in lines)


def test_단계_표시는_이벤트_전에는_최종_단계만_잠긴_채로_보인다():
    # given / when
    steps = StepList()

    # then
    assert steps.rows() == [f"🔒  {FINAL_STEP_TITLE}"]


def test_취소하면_작업에_등록한_중단_함수를_바로_부른다(qtbot):
    # given
    called = []
    task = BackgroundTask(lambda ctx: None, on_cancel=lambda: called.append(True))

    # when
    task.cancel()

    # then
    assert called == [True]


def test_안내_시작_버튼은_탈퇴_전_확인_창을_먼저_띄우고_바로_시작하지_않는다(page):
    # when
    page.start_button.click()

    # then
    assert page.guide_dialog is not None and page.guide_dialog.isVisible()
    assert not page.is_running()


def test_탈퇴_전_확인을_모두_체크하고_진행하면_안내가_시작된다(qtbot, page):
    # given
    page.start_button.click()
    dialog = page.guide_dialog
    for box in dialog.condition_boxes:
        box.setChecked(True)

    # when
    dialog.proceed_button.click()

    # then
    qtbot.waitUntil(page.is_running, timeout=3000)


def test_인벤토리에_후보가_있으면_확인_창에_그_후보의_가입_방식을_보여_준다(qtbot, page):
    # given
    from datetime import UTC, datetime

    from account_cleaner.contracts import AccountCandidate, Evidence, EvidenceType, LoginMethod

    playbook = page._playbooks[page.service_combo.currentData()]
    candidate = AccountCandidate(
        service=playbook.service,
        domain=playbook.domains[0],
        score=0.9,
        evidence=(Evidence("m", EvidenceType.SIGNUP, 0.9),),
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        confirmed_login_method=LoginMethod.KAKAO,
    )
    page.set_candidate_lookup(lambda d: candidate if d == candidate.domain else None)

    # when
    page.start_button.click()

    # then
    assert page.guide_dialog.candidate is candidate
    assert any("카카오" in line for line in page.guide_dialog.login_lines)


def test_안전_데모는_확인_창_없이_바로_시작한다(qtbot, tmp_path):
    # given
    page = AgentPage(
        tmp_path / "profile",
        agent_factory=lambda d: FakeWithdrawAgent(d, step_delay=0.01),
        playbook_loader=dict,
        include_demo=True,
    )
    qtbot.addWidget(page)

    # when
    page.start_button.click()

    # then
    assert page.guide_dialog is None
    qtbot.waitUntil(page.is_running, timeout=3000)
    page.stop()
    BackgroundTask.shutdown_all()


def test_안내가_돌아가는_동안_움직이는_진행_표시와_걸린_시간을_보여_준다(qtbot, page):
    # given (#83)
    assert not page.activity.isVisible()
    with qtbot.waitSignal(page.running_changed) as started:
        page.start()

    # then: 시작하자마자 보이고 막대가 움직인다
    assert started.args == [True]
    assert page.activity.isVisible()
    assert page.activity.bar.is_animating()
    assert " · 0:0" in page.activity.text()

    # when: 사용자 차례 → 막대는 멈추고 기다린다는 문구
    qtbot.waitUntil(lambda: page.turn_box.isVisible(), timeout=3000)
    assert not page.activity.bar.is_animating()
    assert "기다리는 중" in page.activity.text()

    # when: 중단하면 사라진다
    with qtbot.waitSignal(page.running_changed, timeout=3000) as finished:
        page.stop_button.click()
    assert finished.args == [False]
    qtbot.waitUntil(lambda: not page.activity.isVisible(), timeout=3000)


def test_걸린_시간은_분과_초로_보여_준다():
    # given
    from account_cleaner.ui.activity import elapsed_text

    # then
    assert elapsed_text(5) == "0:05"
    assert elapsed_text(75) == "1:15"
