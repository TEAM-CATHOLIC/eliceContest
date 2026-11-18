"""에이전트 전용 Chrome을 보통 프로그램처럼 띄우고 Playwright로 연결한다 (#64).

Playwright가 Chrome을 직접 띄우면 `--enable-automation`이 붙어 `navigator.webdriver`가 true가 되고,
Google이 "안전하지 않은 브라우저"로 보고 로그인을 막는다. 그래서:

1. 설치된 Chrome을 전용 프로필(`--user-data-dir`)로 직접 실행한다. 자동화 옵션은 없다.
2. 디버깅 포트는 `127.0.0.1`의 빈 포트 번호를 골라 연다. `--remote-debugging-port=0`(Chrome이
   고르게 함)을 쓰면 Chrome이 `navigator.webdriver`를 true로 바꾸므로 쓰지 않는다 (#64에서 확인).
3. Playwright는 `connect_over_cdp`로 그 Chrome에 붙는다.
4. 끝나면 `Browser.close`로 정상 종료해(쿠키가 디스크에 남음) 안 닫히면 강제 종료한다.
"""

import asyncio
import logging
import socket
import subprocess
import time
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from account_cleaner.core.chrome import find_chrome

log = logging.getLogger(__name__)

STARTUP_TIMEOUT = 20.0
SHUTDOWN_TIMEOUT = 10.0
CHROME_ARGS = (
    "--remote-debugging-address=127.0.0.1",
    "--disable-sync",
    "--no-default-browser-check",
    "--no-first-run",
)


class ChromeStartError(RuntimeError):
    pass


@dataclass
class ChromeProcess:
    process: subprocess.Popen
    port: int

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def chrome_command(chrome: Path, profile_dir: Path, port: int, headless: bool) -> list[str]:
    return [
        str(chrome),
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        *CHROME_ARGS,
        *(["--headless=new"] if headless else []),
        "about:blank",
    ]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def debugger_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5):
            return True
    except OSError:
        return False


def spawn(command: list[str]) -> subprocess.Popen:
    """Chrome 프로세스를 띄우기만 한다 (기다리지 않으므로 이벤트 루프를 막지 않는다)."""
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def start_chrome(profile_dir: Path, headless: bool = False) -> ChromeProcess:
    chrome = find_chrome()
    if chrome is None:
        raise ChromeStartError("Chrome을 찾지 못했습니다")
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    process = spawn(chrome_command(chrome, profile_dir, port, headless))
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if await asyncio.to_thread(debugger_ready, port):
            return ChromeProcess(process, port)
        if process.poll() is not None:
            # 같은 프로필로 이미 떠 있는 Chrome이 있으면 새 프로세스는 그쪽에 창만 넘기고 바로 끝난다
            raise ChromeStartError(
                "에이전트용 Chrome이 이미 열려 있습니다. 그 창을 모두 닫고 다시 시작해 주세요."
            )
        await asyncio.sleep(0.1)
    stop_process(process)
    raise ChromeStartError("Chrome이 제때 시작되지 않았습니다")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()


async def close_browser(browser: Any, chrome: ChromeProcess) -> None:
    """정상 종료를 먼저 시도한다 (강제 종료하면 마지막 쿠키가 저장되지 않을 수 있다)."""
    from playwright.async_api import Error as PlaywrightError

    if browser.is_connected():
        try:
            session = await browser.new_browser_cdp_session()
            await session.send("Browser.close")
        except PlaywrightError:  # 사용자가 이미 닫았거나 연결이 끊김
            pass
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT
    while chrome.process.poll() is None and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    stop_process(chrome.process)


@asynccontextmanager
async def attached_chrome(profile_dir: Path, headless: bool = False) -> AsyncIterator[Any]:
    """전용 프로필 Chrome을 띄워 연결하고 첫 페이지를 준다. 나가면 Chrome을 닫는다."""
    from playwright.async_api import async_playwright

    chrome = await start_chrome(profile_dir, headless)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(chrome.endpoint)
            try:
                session = await browser.new_browser_cdp_session()
                await session.send("Browser.setDownloadBehavior", {"behavior": "deny"})
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                yield page
            finally:
                await close_browser(browser, chrome)
    finally:
        stop_process(chrome.process)
