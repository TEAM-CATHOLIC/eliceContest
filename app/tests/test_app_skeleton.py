import logging
import threading
import time

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from account_cleaner.core.log_setup import LOG_FILE, redact_emails, setup_logging
from account_cleaner.core.paths import HOME_ENV, resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.main_window import MainWindow, PageId
from account_cleaner.ui.workers import BackgroundTask, TaskContext

# --- 경로·설정·로그 ---


def test_resolve_paths_with_override(monkeypatch, tmp_path):
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "home"))
    paths = resolve_app_paths()
    assert paths.root == tmp_path / "home"
    assert paths.browser_profile.is_dir()
    assert paths.logs.is_dir()
    assert paths.database.parent == paths.root


def test_settings_roundtrip_and_forbidden_keys(tmp_path):
    s = AppSettings(tmp_path / "settings.ini")
    s.set("ui/answer", 42)
    s.sync()
    assert AppSettings(tmp_path / "settings.ini").get("ui/answer", type_=int) == 42
    with pytest.raises(ValueError):
        s.set("naver/password", "x")
    with pytest.raises(ValueError):
        s.set("gmail/token", "x")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("login hong@gmail.com ok", "login h***@gmail.com ok"),
        ("a.b+c@mail.shop.example.com", "a***@mail.shop.example.com"),
        ("no email here @ all", "no email here @ all"),
    ],
)
def test_redact_emails(text, expected):
    assert redact_emails(text) == expected


def test_log_file_is_redacted(tmp_path):
    setup_logging(tmp_path)
    setup_logging(tmp_path)  # 두 번 불러도 중복 기록되지 않음
    logging.getLogger("t").warning("user %s", "hong@gmail.com")
    for h in logging.getLogger().handlers:
        h.flush()
    content = (tmp_path / LOG_FILE).read_text(encoding="utf-8")
    assert "h***@gmail.com" in content
    assert "hong@gmail.com" not in content
    assert content.count("user h***") == 1


# --- 백그라운드 작업 ---


def test_task_reports_progress_and_result(qtbot):
    main_thread = threading.get_ident()
    seen_threads = []

    def job(ctx: TaskContext):
        seen_threads.append(threading.get_ident())
        for i in range(5):
            ctx.progress(i + 1, 5)
        return "ok"

    task = BackgroundTask(job, name="test")
    progress = []
    task.progress.connect(lambda d, t: progress.append((d, t, threading.get_ident())))
    results = []
    task.succeeded.connect(results.append)
    with qtbot.waitSignals([task.succeeded, task.finished], timeout=3000):
        task.start()

    assert results == ["ok"]
    assert seen_threads[0] != main_thread  # 작업은 다른 스레드에서
    assert [p[:2] for p in progress] == [(i, 5) for i in range(1, 6)]
    assert all(p[2] == main_thread for p in progress)  # 시그널은 UI 스레드에서


def test_task_failure(qtbot):
    def job(ctx):
        raise ValueError("boom")

    task = BackgroundTask(job)
    with qtbot.waitSignal(task.failed, timeout=3000) as blocker:
        task.start()
    assert isinstance(blocker.args[0], ValueError)


def test_task_cancel(qtbot):
    started = threading.Event()

    def job(ctx: TaskContext):
        started.set()
        while True:
            ctx.raise_if_cancelled()
            time.sleep(0.01)

    task = BackgroundTask(job)
    with qtbot.waitSignals([task.cancelled, task.finished], timeout=3000):
        task.start()
        assert started.wait(2)
        task.cancel()


def test_ui_stays_responsive_during_task(qtbot):
    """작업이 도는 동안 UI 이벤트 루프가 계속 돈다."""
    release = threading.Event()
    task = BackgroundTask(lambda ctx: release.wait(5))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    task.start()
    qtbot.wait(200)
    assert len(ticks) >= 5
    release.set()
    timer.stop()
    assert task.wait(2000)


def test_task_cannot_start_twice(qtbot):
    task = BackgroundTask(lambda ctx: None)
    with qtbot.waitSignal(task.finished, timeout=3000):
        task.start()
    with pytest.raises(RuntimeError):
        task.start()


# --- 메인 창 ---


def test_pages_navigation(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    with qtbot.waitSignal(window.page_changed) as blocker:
        window.show_page(PageId.CANDIDATES)
    assert blocker.args == [PageId.CANDIDATES.value]
    assert window.current_page() is PageId.CANDIDATES
    window.show_page(PageId.PROGRESS)
    assert window.current_page() is PageId.PROGRESS


def test_set_page_replaces_placeholder(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show_page(PageId.IMPORT)
    real = QLabel("real")
    window.set_page(PageId.IMPORT, real)
    assert window.page(PageId.IMPORT) is real
    assert window._stack.currentWidget() is real


def test_last_page_and_geometry_restored(qtbot, tmp_path):
    settings = AppSettings(tmp_path / "settings.ini")
    first = MainWindow(settings)
    qtbot.addWidget(first)
    first.show_page(PageId.PROGRESS)
    first.close()

    second = MainWindow(AppSettings(tmp_path / "settings.ini"))
    qtbot.addWidget(second)
    assert second.current_page() is PageId.PROGRESS


def test_shutdown_all_without_event_loop(qtbot):
    """앱 종료 시처럼 UI 스레드가 wait()으로 막혀 있어도 작업이 끝난다 (교착 회귀 테스트)."""

    def job(ctx: TaskContext):
        while True:
            ctx.raise_if_cancelled()
            time.sleep(0.01)

    task = BackgroundTask(job)
    task.start()
    qtbot.wait(50)
    started = time.monotonic()
    BackgroundTask.shutdown_all(timeout_ms=2000)
    assert time.monotonic() - started < 1.5
    assert not task.is_running()
