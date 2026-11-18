"""에이전트 전용 Chrome을 보통 프로그램처럼 띄워 연결하는 테스트 (#64).

실제 Chrome이 필요한 테스트는 Chrome이 없으면 건너뛴다.
"""

import asyncio
import os
import sys

import pytest

from account_cleaner.browser import chrome_process
from account_cleaner.browser.chrome_process import (
    ChromeStartError,
    attached_chrome,
    chrome_command,
    free_port,
    start_chrome,
)
from account_cleaner.core.chrome import find_chrome

needs_chrome = pytest.mark.skipif(find_chrome() is None, reason="Chrome이 설치되어 있지 않음")
has_screen = not os.environ.get("CI") and (
    sys.platform != "linux" or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
)
needs_screen = pytest.mark.skipif(
    not has_screen, reason="창을 띄울 화면이 없음 (headless Chrome은 항상 webdriver=true)"
)


def test_자동화_옵션_없이_전용_프로필과_이_PC_안에서만_열리는_포트로_띄운다(tmp_path):
    # when
    command = chrome_command(tmp_path / "chrome", tmp_path / "profile", 41925, headless=False)

    # then
    assert f"--user-data-dir={tmp_path / 'profile'}" in command
    assert "--remote-debugging-address=127.0.0.1" in command
    assert "--remote-debugging-port=41925" in command
    assert not any("enable-automation" in arg for arg in command)
    assert not any("headless" in arg for arg in command)


def test_포트를_Chrome에_맡기지_않는다():
    # given: --remote-debugging-port=0이면 Chrome이 navigator.webdriver를 true로 바꾼다 (#64)
    from pathlib import Path

    # when
    command = chrome_command(Path("chrome"), Path("profile"), free_port(), headless=False)

    # then
    assert "--remote-debugging-port=0" not in command


def test_같은_프로필_Chrome이_이미_떠_있어_바로_끝나면_안내한다(tmp_path, monkeypatch):
    # given: 실행하자마자 끝나는 프로그램 (이미 열린 Chrome에 창만 넘기고 끝나는 경우와 같음)
    monkeypatch.setattr(chrome_process, "find_chrome", lambda: tmp_path / "chrome")
    monkeypatch.setattr(
        chrome_process,
        "chrome_command",
        lambda *_args: [sys.executable, "-c", "pass"],
    )

    # when / then
    with pytest.raises(ChromeStartError, match="이미 열려"):
        asyncio.run(start_chrome(tmp_path / "profile"))


def test_Chrome이_없으면_ChromeStartError(tmp_path, monkeypatch):
    # given
    monkeypatch.setattr(chrome_process, "find_chrome", lambda: None)

    # when / then
    with pytest.raises(ChromeStartError, match="찾지 못했습니다"):
        asyncio.run(start_chrome(tmp_path / "profile"))


@needs_chrome
@needs_screen
def test_연결한_Chrome은_자동화로_보이지_않는다(tmp_path):
    # given: 실제 창을 잠깐 띄운다 (Google이 보는 것과 같은 조건)
    async def webdriver_flag():
        async with attached_chrome(tmp_path / "profile", headless=False) as page:
            await page.goto("data:text/html,<title>t</title>")
            return await page.evaluate("navigator.webdriver")

    # when
    flag = asyncio.run(webdriver_flag())

    # then
    assert flag is False


@needs_chrome
def test_정상_종료하면_로그인_쿠키가_프로필에_남아_다음에_다시_쓸_수_있다(tmp_path):
    # given
    profile = tmp_path / "profile"
    cookie = {
        "name": "session",
        "value": "kept",
        "domain": "example.com",
        "path": "/",
        "expires": 4_102_444_800,  # 2100년
    }

    async def save():
        async with attached_chrome(profile, headless=True) as page:
            await page.context.add_cookies([cookie])

    async def load():
        async with attached_chrome(profile, headless=True) as page:
            return await page.context.cookies("https://example.com")

    # when
    asyncio.run(save())
    cookies = asyncio.run(load())

    # then
    assert [(c["name"], c["value"]) for c in cookies] == [("session", "kept")]
