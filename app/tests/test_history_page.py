"""진행 기록·재알림 테스트 (#16, PRD F-08). 시각은 가짜 시계."""

from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.storage import Database, EventKind, StatusStore
from account_cleaner.ui.history_page import HistoryPage, event_text


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


def reach(store, domain="github.com", service="GitHub"):
    store.agent_started(domain, service)
    store.agent_finished(domain, "reached", reached=True)


@pytest.fixture
def page(qtbot, store):
    widget = HistoryPage(store)
    qtbot.addWidget(widget)
    widget.show()
    return widget


# --- 저장소: 진행 기록 ---


def test_한_일은_순서대로_진행_기록에_남고_최근_일부터_보인다(store, clock):
    # given
    store.set_label("github.com", "GitHub", "confirmed")
    clock.advance(minutes=1)
    reach(store)
    clock.advance(minutes=1)
    store.mark_completed("github.com")
    clock.advance(minutes=1)
    store.session_cleared("github.com")

    # when
    kinds = [e.kind for e in store.history()]

    # then
    assert kinds == [
        EventKind.SESSION_CLEARED,
        EventKind.COMPLETED,
        EventKind.FINISHED,
        EventKind.STARTED,
        EventKind.LABEL,
    ]
    assert {e.service for e in store.history()} == {"GitHub"}


def test_지울_세션이_없었으면_세션_삭제를_기록하지_않는다(store):
    # when
    store.session_cleared("github.com")

    # then
    assert store.history() == []


def test_진행_목록은_최근에_바뀐_서비스부터_보인다(store, clock):
    # given
    reach(store, "github.com", "GitHub")
    clock.advance(hours=1)
    store.agent_started("dropbox.com", "Dropbox")

    # when
    domains = [p.domain for p in store.all_progress()]

    # then
    assert domains == ["dropbox.com", "github.com"]


def test_진행_기록_문장은_시각_서비스_한_일을_보여준다(store):
    # given
    reach(store)

    # when
    lines = [event_text(e) for e in store.history()]

    # then
    assert lines[0].endswith("GitHub — 안내 끝: 탈퇴 화면 도착 (최종 버튼은 직접)")
    assert lines[1].endswith("GitHub — 안내 시작")


# --- 화면 ---


def test_진행이_없으면_안내_문구만_보이고_재알림_칸은_숨긴다(page):
    # then
    assert page.empty_label.isVisible()
    assert not page.table.isVisible()
    assert not page.reminder_box.isVisible()


def test_서비스별_진행과_재알림_날짜가_표에_보인다(store, page):
    # given
    reach(store)

    # when
    page.refresh()

    # then
    assert page.table.rowCount() == 1
    row = [page.table.item(0, c).text() for c in range(page.table.columnCount())]
    assert row[:3] == ["GitHub", "github.com", "탈퇴 화면 도착 (최종 버튼은 직접)"]
    assert row[5].startswith("2026-11-15")
    assert page.event_list.count() == 2


def test_14일이_지나기_전에는_재알림이_뜨지_않고_지나면_뜬다(store, clock, page):
    # given
    reach(store)
    clock.advance(days=13)
    page.refresh()
    before = page.reminder_box.isVisible()

    # when
    clock.advance(days=1)
    page.refresh()

    # then
    assert not before
    assert page.reminder_box.isVisible()
    assert page.due_domains() == ["github.com"]
    assert "1곳" in page.reminder_title.text()


def test_14일_뒤_다시_알림을_누르면_재알림이_사라졌다가_14일_뒤_다시_뜬다(store, clock, page):
    # given
    reach(store)
    clock.advance(days=14)
    page.refresh()

    # when
    page.snooze_button.click()
    hidden = not page.reminder_box.isVisible()
    clock.advance(days=14)
    page.refresh()

    # then
    assert hidden
    assert page.due_domains() == ["github.com"]
    assert store.history()[0].kind is EventKind.SNOOZED


def test_다시_안내와_끝냈어요는_고른_서비스_도메인으로_요청이_간다(qtbot, store, clock, page):
    # given
    reach(store)
    clock.advance(days=14)
    page.refresh()

    # when / then
    with qtbot.waitSignal(page.restart_requested) as restart:
        page.restart_button.click()
    with qtbot.waitSignal(page.done_requested) as done:
        page.done_button.click()
    assert restart.args == ["github.com"]
    assert done.args == ["github.com"]


# --- 앱 연결 ---


def test_앱을_켰을_때_재알림_대상이_있으면_서비스_이름으로_알린다(store, clock):
    # given
    from account_cleaner.main import reminder_message

    reach(store, "github.com", "GitHub")
    reach(store, "dropbox.com", "Dropbox")
    no_message = reminder_message(store)

    # when
    clock.advance(days=14)
    text = reminder_message(store)

    # then
    assert no_message is None
    assert "외 1곳" in text and ("GitHub" in text or "Dropbox" in text)


def test_재알림을_띄우면_진행_기록_화면을_연다(qtbot, store, clock):
    # given
    from account_cleaner.main import notify_reminders
    from account_cleaner.ui.main_window import MainWindow, PageId

    window = MainWindow()
    qtbot.addWidget(window)
    reach(store)
    clock.advance(days=14)

    # when
    notify_reminders(window, store)

    # then
    assert window.current_page() is PageId.HISTORY


def test_인벤토리에_없는_서비스도_재알림에서_끝냈어요로_완료되고_재알림이_없어진다(
    qtbot, store, clock, page
):
    # given: 메일을 다시 불러오지 않아 인벤토리가 비어 있음
    from account_cleaner.main import complete_from_history
    from account_cleaner.ui.candidates.page import InventoryPage

    inventory = InventoryPage()
    qtbot.addWidget(inventory)
    reach(store)
    clock.advance(days=14)

    # when
    complete_from_history(inventory, store, None, page, "github.com")

    # then
    assert store.progress("github.com").completed_at is not None
    assert store.due_reminders() == []
    assert store.labels() == {"github.com": "done"}
    assert not page.reminder_box.isVisible()


def test_인벤토리에_없는_서비스도_재알림에서_다시_안내를_시작한다(qtbot, store, tmp_path):
    # given
    from account_cleaner.contracts import load_playbooks
    from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR, FakeWithdrawAgent
    from account_cleaner.main import restart_from_history
    from account_cleaner.ui.agent_page import AgentPage
    from account_cleaner.ui.candidates.page import InventoryPage
    from account_cleaner.ui.main_window import MainWindow, PageId
    from account_cleaner.ui.workers import BackgroundTask

    window, inventory = MainWindow(), InventoryPage()
    qtbot.addWidget(window)
    qtbot.addWidget(inventory)
    agent_page = AgentPage(
        tmp_path / "profile",
        agent_factory=lambda d: FakeWithdrawAgent(d, step_delay=0.01),
        playbook_loader=lambda: load_playbooks(SAMPLE_PLAYBOOK_DIR),
        include_demo=False,
    )
    window.set_page(PageId.AGENT, agent_page)

    # when
    restart_from_history(window, inventory, agent_page, store, "shop.example.com")

    # then
    assert window.current_page() is PageId.AGENT
    assert agent_page.current_domain == "shop.example.com"
    assert store.progress("shop.example.com").last_result == "started"
    agent_page.stop()  # 탈퇴 화면 도착 뒤에는 사용자가 닫을 때까지 기다리므로 직접 멈춘다
    BackgroundTask.shutdown_all()
