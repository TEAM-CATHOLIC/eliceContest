"""로그인 세션 정리와 '탈퇴를 끝냈어요' 테스트 (#16, 논의사항 D-05). 시각은 가짜 시계."""

from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.storage import Database, StatusStore
from account_cleaner.ui.candidates.model import CandidateStatus
from account_cleaner.ui.session_cleaner import SessionCleaner, cookie_domains


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 1, 9, tzinfo=UTC)

    def __call__(self):
        return self.now


class RecordingAgent:
    """`clear_session` 호출만 기록하는 가짜 에이전트."""

    def __init__(self, fail: bool = False):
        self.calls: list[tuple[str, ...] | None] = []
        self.fail = fail

    def clear_session(self, domains=None):
        if self.fail:
            raise RuntimeError("Chrome 없음")
        self.calls.append(domains)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    db = Database(tmp_path / "app.sqlite3", clock=clock)
    yield StatusStore(db)
    db.close()


@pytest.fixture
def agent():
    return RecordingAgent()


def make_cleaner(store, agent, tmp_path, busy=lambda: False, playbook=None):
    return SessionCleaner(
        store,
        tmp_path / "profile",
        agent_factory=lambda _dir: agent,
        playbook_lookup=lambda _domain: playbook,
        agent_busy=busy,
    )


def wait_done(qtbot, cleaner):
    qtbot.waitUntil(lambda: not cleaner.is_running(), timeout=3000)


def test_탈퇴를_끝낸_서비스의_세션을_지우고_기록에서도_뺀다(qtbot, store, agent, tmp_path):
    # given
    store.agent_started("github.com", "GitHub")
    store.agent_started("dropbox.com", "Dropbox")
    store.mark_completed("github.com")
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    with qtbot.waitSignal(cleaner.cleared) as blocker:
        assert cleaner.clear_due()
    wait_done(qtbot, cleaner)

    # then
    assert agent.calls == [("github.com",)]
    assert blocker.args == [["github.com"]]
    assert store.sessions_to_clear() == []


def test_보관_기한이_지난_세션은_탈퇴를_안_끝냈어도_지운다(qtbot, store, agent, clock, tmp_path):
    # given
    store.agent_started("dropbox.com", "Dropbox")
    clock.now += timedelta(days=14)
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    with qtbot.waitSignal(cleaner.cleared):
        cleaner.clear_due()
    wait_done(qtbot, cleaner)

    # then
    assert agent.calls == [("dropbox.com",)]


def test_지울_세션이_없으면_에이전트를_부르지_않는다(store, agent, clock, tmp_path):
    # given: 보관 13일째
    store.agent_started("dropbox.com", "Dropbox")
    clock.now += timedelta(days=13)
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    started = cleaner.clear_due()

    # then
    assert not started and agent.calls == []


def test_안내가_진행_중이면_미뤘다가_안내가_끝나면_지운다(qtbot, store, agent, tmp_path):
    # given
    store.agent_started("github.com", "GitHub")
    store.mark_completed("github.com")
    busy = [True]
    cleaner = make_cleaner(store, agent, tmp_path, busy=lambda: busy[0])

    # when
    assert not cleaner.clear_due()
    busy[0] = False
    with qtbot.waitSignal(cleaner.cleared):
        cleaner.retry_pending()
    wait_done(qtbot, cleaner)

    # then
    assert agent.calls == [("github.com",)]


def test_플레이북의_도메인과_로그인_도메인도_함께_지운다():
    # given
    from dataclasses import replace

    from test_candidate_detail import SAMPLE_PLAYBOOKS

    playbook = replace(
        SAMPLE_PLAYBOOKS["sample_shop"],
        domains=("shop.example.com", "www.shop.example.com"),
        auth_domains=("accounts.example.com",),
    )

    # when
    domains = cookie_domains("Shop.Example.com", playbook)

    # then
    assert domains == ("shop.example.com", "www.shop.example.com", "accounts.example.com")


def test_정리에_실패하면_기록을_남겨_두고_실패를_알린다(qtbot, store, tmp_path):
    # given
    store.agent_started("github.com", "GitHub")
    store.mark_completed("github.com")
    cleaner = make_cleaner(store, RecordingAgent(fail=True), tmp_path)

    # when
    with qtbot.waitSignal(cleaner.failed) as blocker:
        cleaner.clear_due()
    wait_done(qtbot, cleaner)

    # then
    assert "지우지 못했습니다" in blocker.args[0]
    assert store.sessions_to_clear() == ["github.com"]


def test_모두_지우기는_프로필_전체를_지우고_세션_기록을_비운다(qtbot, store, agent, tmp_path):
    # given
    store.agent_started("dropbox.com", "Dropbox")
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    with qtbot.waitSignal(cleaner.cleared) as blocker:
        assert cleaner.clear_all()
    wait_done(qtbot, cleaner)

    # then
    assert agent.calls == [None]
    assert blocker.args == [[SessionCleaner.ALL]]
    assert store._db.connection().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_안내_중에는_모두_지우기를_하지_않고_이유를_알린다(qtbot, store, agent, tmp_path):
    # given
    cleaner = make_cleaner(store, agent, tmp_path, busy=lambda: True)

    # when
    with qtbot.waitSignal(cleaner.failed) as blocker:
        assert not cleaner.clear_all()

    # then
    assert agent.calls == [] and "진행 중" in blocker.args[0]


# --- 화면 연결 ---


def test_모두_지우기는_확인을_받아야만_지운다(qtbot, store, agent, tmp_path):
    # given
    from PySide6.QtWidgets import QWidget

    from account_cleaner.main import confirm_clear_logins

    parent = QWidget()
    qtbot.addWidget(parent)
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    declined = confirm_clear_logins(parent, cleaner, ask=lambda *_: False)
    with qtbot.waitSignal(cleaner.cleared):
        accepted = confirm_clear_logins(parent, cleaner, ask=lambda *_: True)
    wait_done(qtbot, cleaner)

    # then
    assert not declined and accepted
    assert agent.calls == [None]


def test_탈퇴를_끝냈어요는_완료로_기록하고_그_세션을_바로_지운다(qtbot, store, agent, tmp_path):
    # given
    from account_cleaner.main import record_status

    store.agent_started("github.com", "GitHub")
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    with qtbot.waitSignal(cleaner.cleared):
        record_status(store, cleaner, "github.com", "GitHub", CandidateStatus.DONE)
    wait_done(qtbot, cleaner)

    # then
    assert store.labels() == {"github.com": "done"}
    assert store.progress("github.com").completed_at is not None
    assert agent.calls == [("github.com",)]


def test_완료가_아닌_확인은_세션을_건드리지_않는다(store, agent, tmp_path):
    # given
    from account_cleaner.main import record_status

    store.agent_started("github.com", "GitHub")
    cleaner = make_cleaner(store, agent, tmp_path)

    # when
    record_status(store, cleaner, "github.com", "GitHub", CandidateStatus.CONFIRMED)

    # then
    assert agent.calls == []
    assert store.progress("github.com").completed_at is None


def test_탈퇴를_끝냈어요_버튼은_정리_중인_후보에만_보이고_누르면_완료로_바뀐다(qtbot):
    # given
    from test_candidate_detail import SHOP

    from account_cleaner.ui.candidates.page import InventoryPage

    page = InventoryPage()
    qtbot.addWidget(page)
    page.show()
    page.set_candidates([SHOP])
    page.select_row(0)
    button = page.detail.done_button
    hidden_before = not button.isVisible()

    # when
    page.set_status(SHOP.domain, CandidateStatus.IN_PROGRESS)
    shown = button.isVisible()
    with qtbot.waitSignal(page.status_changed) as blocker:
        button.click()

    # then
    assert hidden_before and shown
    assert blocker.args == [SHOP.domain, SHOP.service, CandidateStatus.DONE]
    assert page.model.status_of(SHOP.domain) is CandidateStatus.DONE
    assert not button.isVisible()
