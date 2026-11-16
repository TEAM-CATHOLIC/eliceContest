"""사용자 확인·진행·재알림·세션 보관 저장소 테스트. 시각은 주입한 가짜 시계."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.storage import Database, StatusStore
from account_cleaner.storage.db import MIGRATIONS


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 1, 9, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    db = Database(tmp_path / "app.sqlite3", clock=clock)
    yield StatusStore(db)
    db.close()


def test_새_DB는_마지막_스키마_버전까지_만들어지고_다시_열어도_그대로다(tmp_path):
    # given
    path = tmp_path / "app.sqlite3"

    # when
    first = Database(path)
    first.close()
    second = Database(path)

    # then
    assert second.schema_version() == len(MIGRATIONS)


def test_사용자_확인은_앱을_다시_열어도_남는다(tmp_path, clock):
    # given
    path = tmp_path / "app.sqlite3"
    StatusStore(Database(path, clock)).set_label("shop.example.com", "샘플쇼핑", "confirmed")

    # when
    labels = StatusStore(Database(path, clock)).labels()

    # then
    assert labels == {"shop.example.com": "confirmed"}


def test_같은_서비스의_확인을_바꾸면_마지막_값만_남는다(store):
    # given / when
    store.set_label("shop.example.com", "샘플쇼핑", "confirmed")
    store.set_label("shop.example.com", "샘플쇼핑", "excluded")

    # then
    assert store.labels() == {"shop.example.com": "excluded"}


def test_에이전트를_시작하면_진행과_세션_보관이_기록된다(store, clock):
    # given / when
    store.agent_started("shop.example.com", "샘플쇼핑")

    # then
    progress = store.progress("shop.example.com")
    assert progress.last_result == "started"
    assert progress.started_at == clock.now
    assert progress.completed_at is None
    assert store.sessions_to_clear() == []


def test_탈퇴_화면에_도착하고_14일이_지나면_재알림_대상이_된다(store, clock):
    # given
    store.agent_started("shop.example.com", "샘플쇼핑")
    store.agent_finished("shop.example.com", "reached", reached=True)

    # when / then
    clock.advance(days=13)
    assert store.due_reminders() == []
    clock.advance(days=1)
    assert store.due_reminders() == ["shop.example.com"]


def test_중단으로_끝나면_재알림을_잡지_않는다(store, clock):
    # given
    store.agent_started("shop.example.com", "샘플쇼핑")

    # when
    store.agent_finished("shop.example.com", "stopped", reached=False)
    clock.advance(days=30)

    # then
    assert store.due_reminders() == []
    assert store.progress("shop.example.com").last_result == "stopped"


def test_재알림을_미루면_그만큼_뒤에_다시_알린다(store, clock):
    # given: 재알림 대상
    store.agent_started("shop.example.com", "샘플쇼핑")
    store.agent_finished("shop.example.com", "reached", reached=True)
    clock.advance(days=14)

    # when
    store.snooze_reminder("shop.example.com", timedelta(days=3))

    # then
    assert store.due_reminders() == []
    clock.advance(days=3)
    assert store.due_reminders() == ["shop.example.com"]


def test_탈퇴를_끝냈다고_확인하면_재알림이_없어지고_세션은_바로_삭제_대상이다(store, clock):
    """D-05: 완료 즉시 삭제."""
    # given
    store.agent_started("shop.example.com", "샘플쇼핑")
    store.agent_finished("shop.example.com", "reached", reached=True)

    # when
    store.mark_completed("shop.example.com")

    # then
    clock.advance(days=30)
    assert store.due_reminders() == []
    assert store.sessions_to_clear() == ["shop.example.com"]
    assert store.progress("shop.example.com").completed_at is not None


def test_끝내지_못한_서비스의_세션은_14일이_지나면_삭제_대상이다(store, clock):
    """D-05: 미완료는 14일 보관."""
    # given
    store.agent_started("shop.example.com", "샘플쇼핑")

    # when / then
    clock.advance(days=13, hours=23)
    assert store.sessions_to_clear() == []
    clock.advance(hours=1)
    assert store.sessions_to_clear() == ["shop.example.com"]


def test_세션을_지우면_삭제_대상에서_빠지고_다시_시작하면_보관이_새로_시작된다(store, clock):
    # given: 기한이 지난 세션을 지움
    store.agent_started("shop.example.com", "샘플쇼핑")
    clock.advance(days=15)
    store.session_cleared("shop.example.com")

    # when
    store.agent_started("shop.example.com", "샘플쇼핑")
    clock.advance(days=1)

    # then
    assert store.sessions_to_clear() == []


def test_저장된_로그인_모두_지우기는_세션_기록을_모두_비운다(store, clock):
    # given
    store.agent_started("shop.example.com", "샘플쇼핑")
    store.agent_started("sns.example.org", "샘플SNS")
    clock.advance(days=20)

    # when
    store.clear_all_sessions()

    # then
    assert store.sessions_to_clear() == []


def test_작업_스레드에서도_자기_연결로_읽고_쓴다(store):
    # given
    errors = []

    def worker():
        try:
            store.set_label("sns.example.org", "샘플SNS", "deferred")
        except Exception as e:  # noqa: BLE001 — 스레드 안 예외를 테스트로 넘긴다
            errors.append(e)

    # when
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    # then
    assert errors == []
    assert store.labels() == {"sns.example.org": "deferred"}


# --- 화면 연결 ---


def test_다시_가져와도_전에_정한_확인_상태가_그대로_보인다(qtbot, store, tmp_path):
    # given: 전에 '제외'로 정한 서비스
    from test_mail_import import mbox_of, raw_mail

    from account_cleaner.fakes import FakeAnalyzer
    from account_cleaner.main import show_import_result
    from account_cleaner.pipeline import run_pipeline
    from account_cleaner.ui.candidates.model import CandidateStatus
    from account_cleaner.ui.candidates.page import InventoryPage
    from account_cleaner.ui.main_window import MainWindow, PageId
    from account_cleaner.ui.sources_page import file_opener

    store.set_label("shop.example.com", "샘플쇼핑", "excluded")
    mbox = tmp_path / "a.mbox"
    mbox.write_bytes(mbox_of(raw_mail(subject="[샘플쇼핑] 가입을 환영합니다")))
    outcome = run_pipeline(file_opener([mbox]), FakeAnalyzer(), lambda *a: None, lambda: False)
    window, inventory = MainWindow(), InventoryPage()
    qtbot.addWidget(window)
    window.set_page(PageId.INVENTORY, inventory)

    # when
    show_import_result(window, inventory, outcome, store)

    # then
    assert inventory.model.status_of("shop.example.com") is CandidateStatus.EXCLUDED


def test_인벤토리에서_상태를_바꾸면_저장용_시그널에_서비스명이_함께_온다(qtbot):
    # given
    from test_candidate_detail import SHOP

    from account_cleaner.ui.candidates.model import CandidateStatus
    from account_cleaner.ui.candidates.page import InventoryPage

    page = InventoryPage()
    qtbot.addWidget(page)
    page.set_candidates([SHOP])

    # when
    with qtbot.waitSignal(page.status_changed) as blocker:
        page.set_status("shop.example.com", CandidateStatus.CONFIRMED)

    # then
    assert blocker.args == ["shop.example.com", "샘플쇼핑", CandidateStatus.CONFIRMED]


def test_후보에서_시작한_안내가_탈퇴_화면에_도착하면_진행과_재알림이_기록된다(
    qtbot, store, clock, tmp_path
):
    # given: 가짜 에이전트로 샘플쇼핑 안내 시작
    from test_candidate_detail import SHOP

    from account_cleaner.contracts import load_playbooks
    from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR, FakeWithdrawAgent
    from account_cleaner.main import record_agent_result, start_agent_for
    from account_cleaner.ui.agent_page import AgentPage
    from account_cleaner.ui.candidates.page import InventoryPage
    from account_cleaner.ui.main_window import MainWindow, PageId
    from account_cleaner.ui.workers import BackgroundTask

    window, inventory = MainWindow(), InventoryPage()
    agent_page = AgentPage(
        tmp_path / "profile",
        agent_factory=lambda d: FakeWithdrawAgent(d, step_delay=0.01),
        playbook_loader=lambda: load_playbooks(SAMPLE_PLAYBOOK_DIR),
        include_demo=False,
    )
    qtbot.addWidget(window)
    window.set_page(PageId.INVENTORY, inventory)
    window.set_page(PageId.AGENT, agent_page)
    agent_page.run_finished.connect(lambda e: record_agent_result(agent_page, store, e))
    inventory.set_candidates([SHOP])

    # when: 시작 → 사용자 차례에서 계속 → 도착
    start_agent_for(window, inventory, agent_page, SHOP, store)
    qtbot.waitUntil(lambda: not agent_page.turn_box.isHidden(), timeout=3000)
    with qtbot.waitSignal(agent_page.run_finished, timeout=3000):
        agent_page.resume()

    # then
    assert store.progress("shop.example.com").last_result == "reached"
    clock.advance(days=14)
    assert store.due_reminders() == ["shop.example.com"]
    BackgroundTask.shutdown_all()
