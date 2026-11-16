import tempfile

import pytest
from playwright.sync_api import Error, sync_playwright

from account_cleaner.ui.main_window import MainWindow


def test_메인_창을_열면_앱_이름이_제목에_보인다(qtbot):
    # given / when
    window = MainWindow()
    qtbot.addWidget(window)

    # then
    assert window.windowTitle() == "계정 정리 AI 에이전트"


def test_설치된_Chrome을_전용_프로필로_띄울_수_있다():
    """PRD 5장: 브라우저 에이전트는 설치된 Chrome을 앱 전용 프로필로 띄운다."""
    # given: 비어 있는 임시 프로필 폴더
    with tempfile.TemporaryDirectory() as profile, sync_playwright() as p:
        # when
        try:
            ctx = p.chromium.launch_persistent_context(profile, channel="chrome", headless=True)
        except Error as e:
            if "is not found" in str(e) or "Executable doesn't exist" in str(e):
                pytest.skip("Chrome이 설치되어 있지 않음")
            raise
        page = ctx.new_page()
        page.set_content("<title>ok</title>")

        # then
        assert page.title() == "ok"
        ctx.close()
