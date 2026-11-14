import pytest

from account_cleaner.ui.main_window import MainWindow


def test_main_window_opens(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "계정 정리 AI 에이전트"


def test_playwright_chrome_channel():
    """설치된 Chrome을 전용 프로필로 띄울 수 있는지 확인 (PRD 5장)."""
    import tempfile

    from playwright.sync_api import Error, sync_playwright

    with tempfile.TemporaryDirectory() as profile, sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(profile, channel="chrome", headless=True)
        except Error as e:
            if "is not found" in str(e) or "Executable doesn't exist" in str(e):
                pytest.skip("Chrome이 설치되어 있지 않음")
            raise
        page = ctx.new_page()
        page.set_content("<title>ok</title>")
        assert page.title() == "ok"
        ctx.close()
