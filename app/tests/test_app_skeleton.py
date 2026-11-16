import logging
import threading
import time

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from account_cleaner.core.log_setup import LOG_FILE, redact_emails, setup_logging
from account_cleaner.core.paths import HOME_ENV, resolve_app_paths
from account_cleaner.core.settings import AppSettings
from account_cleaner.ui.main_window import FIRST_RUN_PAGE, MainWindow, PageId
from account_cleaner.ui.workers import BackgroundTask, TaskContext


def 끝없이_도는_작업(ctx: TaskContext) -> None:
    while True:
        ctx.raise_if_cancelled()
        time.sleep(0.01)


# --- 경로·설정·로그 ---


def test_환경변수로_앱_데이터_폴더를_바꾸면_하위_폴더가_그_안에_만들어진다(monkeypatch, tmp_path):
    # given: 앱 데이터 폴더를 바꾸는 환경변수
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "home"))

    # when
    paths = resolve_app_paths()

    # then
    assert paths.root == tmp_path / "home"
    assert paths.browser_profile.is_dir()
    assert paths.logs.is_dir()
    assert paths.database.parent == paths.root


def test_저장한_설정은_다시_열어도_유지된다(tmp_path):
    # given
    settings = AppSettings(tmp_path / "settings.ini")

    # when
    settings.set("ui/answer", 42)
    settings.sync()

    # then
    assert AppSettings(tmp_path / "settings.ini").get("ui/answer", type_=int) == 42


@pytest.mark.parametrize("key", ["naver/password", "gmail/token"])
def test_비밀번호나_토큰_설정키는_저장을_거부한다(tmp_path, key):
    # given
    settings = AppSettings(tmp_path / "settings.ini")

    # when / then
    with pytest.raises(ValueError):
        settings.set(key, "x")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("login hong@gmail.com ok", "login h***@gmail.com ok"),
        ("a.b+c@mail.shop.example.com", "a***@mail.shop.example.com"),
        ("no email here @ all", "no email here @ all"),
    ],
)
def test_이메일_주소는_첫_글자와_도메인만_남기고_가린다(text, expected):
    # given: text

    # when
    result = redact_emails(text)

    # then
    assert result == expected


def test_로그_파일에는_가린_이메일만_한_번_기록된다(tmp_path):
    # given: 로그 설정을 두 번 호출 (핸들러 중복 여부 확인)
    setup_logging(tmp_path)
    setup_logging(tmp_path)

    # when
    logging.getLogger("t").warning("user %s", "hong@gmail.com")
    for h in logging.getLogger().handlers:
        h.flush()

    # then
    content = (tmp_path / LOG_FILE).read_text(encoding="utf-8")
    assert "h***@gmail.com" in content
    assert "hong@gmail.com" not in content
    assert content.count("user h***") == 1


# --- 백그라운드 작업 ---


def test_작업은_다른_스레드에서_돌고_진행률과_결과는_UI_스레드로_온다(qtbot):
    # given: 진행률을 5번 보고하고 "ok"를 돌려주는 작업
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

    # when
    with qtbot.waitSignals([task.succeeded, task.finished], timeout=3000):
        task.start()

    # then
    assert results == ["ok"]
    assert seen_threads[0] != main_thread
    assert [p[:2] for p in progress] == [(i, 5) for i in range(1, 6)]
    assert all(p[2] == main_thread for p in progress)


def test_작업이_예외를_던지면_failed_시그널로_예외가_전달된다(qtbot):
    # given
    def job(ctx):
        raise ValueError("boom")

    task = BackgroundTask(job)

    # when
    with qtbot.waitSignal(task.failed, timeout=3000) as blocker:
        task.start()

    # then
    assert isinstance(blocker.args[0], ValueError)


def test_실행_중인_작업을_취소하면_cancelled와_finished가_온다(qtbot):
    # given: 시작을 알린 뒤 취소될 때까지 도는 작업
    started = threading.Event()

    def job(ctx: TaskContext):
        started.set()
        끝없이_도는_작업(ctx)

    task = BackgroundTask(job)

    # when / then
    with qtbot.waitSignals([task.cancelled, task.finished], timeout=3000):
        task.start()
        assert started.wait(2)
        task.cancel()


def test_작업이_도는_동안에도_UI_이벤트_루프가_멈추지_않는다(qtbot):
    # given: 풀어 줄 때까지 기다리는 작업과 10ms마다 도는 타이머
    release = threading.Event()
    task = BackgroundTask(lambda ctx: release.wait(5))
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)

    # when
    task.start()
    qtbot.wait(200)

    # then
    assert len(ticks) >= 5
    release.set()
    timer.stop()
    assert task.wait(2000)


def test_한_번_시작한_작업은_다시_시작할_수_없다(qtbot):
    # given: 이미 끝난 작업
    task = BackgroundTask(lambda ctx: None)
    with qtbot.waitSignal(task.finished, timeout=3000):
        task.start()

    # when / then
    with pytest.raises(RuntimeError):
        task.start()


def test_UI_스레드가_wait로_막혀_있어도_종료_시_작업이_끝난다(qtbot):
    """교착 회귀 테스트 (PR #22 결정 3)."""
    # given: 실행 중인 작업
    task = BackgroundTask(끝없이_도는_작업)
    task.start()
    qtbot.wait(50)

    # when: 앱 종료처럼 이벤트 루프 없이 일괄 정리
    started = time.monotonic()
    BackgroundTask.shutdown_all(timeout_ms=2000)

    # then
    assert time.monotonic() - started < 1.5
    assert not task.is_running()


# --- 메인 창 ---


def test_처음_실행하면_메일_소스_연결_페이지가_열린다(qtbot):
    # given / when
    window = MainWindow()
    qtbot.addWidget(window)

    # then
    assert window.current_page() is FIRST_RUN_PAGE


def test_페이지를_바꾸면_page_changed_시그널이_온다(qtbot):
    # given
    window = MainWindow()
    qtbot.addWidget(window)

    # when
    with qtbot.waitSignal(window.page_changed) as blocker:
        window.show_page(PageId.INVENTORY)

    # then
    assert blocker.args == [PageId.INVENTORY.value]
    assert window.current_page() is PageId.INVENTORY


def test_자리표시_페이지를_실제_위젯으로_바꿀_수_있다(qtbot):
    # given: 메일 소스 연결 페이지를 보고 있는 창
    window = MainWindow()
    qtbot.addWidget(window)
    window.show_page(PageId.SOURCES)
    real = QLabel("real")

    # when
    window.set_page(PageId.SOURCES, real)

    # then
    assert window.page(PageId.SOURCES) is real
    assert window._stack.currentWidget() is real


def test_창을_다시_열면_마지막으로_본_페이지가_열린다(qtbot, tmp_path):
    # given: 에이전트 페이지를 보다가 닫은 창
    first = MainWindow(AppSettings(tmp_path / "settings.ini"))
    qtbot.addWidget(first)
    first.show_page(PageId.AGENT)
    first.close()

    # when
    second = MainWindow(AppSettings(tmp_path / "settings.ini"))
    qtbot.addWidget(second)

    # then
    assert second.current_page() is PageId.AGENT


def test_검색창에_입력하면_search_changed_시그널이_온다(qtbot):
    # given
    window = MainWindow()
    qtbot.addWidget(window)

    # when
    with qtbot.waitSignal(window.top_bar.search_changed) as blocker:
        window.top_bar.search.setText("netflix")

    # then
    assert blocker.args == ["netflix"]


def test_사이드바_아래_엔진_암호화_상태는_미정에서_바꿀_수_있다(qtbot):
    # given
    window = MainWindow()
    qtbot.addWidget(window)
    footer = window.sidebar_footer
    assert footer.status("엔진 암호화") == "미정"

    # when
    footer.set_status("엔진 암호화", "적용됨")

    # then
    assert footer.status("엔진 암호화") == "적용됨"


def test_저장된_로그인_모두_지우기_버튼을_누르면_요청_시그널이_온다(qtbot):
    # given
    window = MainWindow()
    qtbot.addWidget(window)
    footer = window.sidebar_footer

    # when / then
    with qtbot.waitSignal(footer.clear_logins_requested):
        footer.clear_logins_button.click()
