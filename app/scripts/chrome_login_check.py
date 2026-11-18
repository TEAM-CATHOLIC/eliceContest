"""Google 로그인 차단("브라우저 또는 앱이 안전하지 않을 수 있습니다") 실험 (개발용).

Chrome을 세 가지 방식으로 띄워 Dropbox 로그인 화면을 연다. 열린 창에서 "Google로 계속"을 눌러
로그인이 되는지 직접 확인한다. 실험마다 **빈 임시 프로필**을 쓰고 끝나면 지운다
(앱의 전용 프로필과 평소 쓰는 Chrome은 건드리지 않는다).

    cd app
    uv run python scripts/chrome_login_check.py current   # 지금 앱 방식 (막히는지 재확인)
    uv run python scripts/chrome_login_check.py c         # C: 자동화 표시만 끔
    uv run python scripts/chrome_login_check.py b         # B: Chrome을 보통 프로그램처럼 띄우고 나중에 연결

다른 주소로 시작하려면 --url을 준다. 창에서 확인이 끝나면 터미널에서 Enter를 누른다.
"""

import argparse
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from account_cleaner.core.chrome import find_chrome

DEFAULT_URL = "https://www.dropbox.com/login"
COMMON_ARGS = ["--disable-sync", "--no-default-browser-check", "--no-first-run"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_debugger(port: int, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                return json.load(r)["Browser"]
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("Chrome 디버깅 포트가 열리지 않았습니다")


def report(page) -> None:
    webdriver = page.evaluate("navigator.webdriver")
    print(f"  navigator.webdriver = {webdriver}  (true면 자동화로 보임)")
    print("\n창에서 'Google로 계속'을 눌러 로그인해 보세요. 확인이 끝나면 여기서 Enter.")
    input()


def run_launch(profile: Path, url: str, hide_automation: bool) -> None:
    """current / C: Playwright가 Chrome을 직접 띄운다."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            headless=False,
            args=COMMON_ARGS
            + (["--disable-blink-features=AutomationControlled"] if hide_automation else []),
            ignore_default_args=["--enable-automation"] if hide_automation else None,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        report(page)
        context.close()


def run_attach(profile: Path, url: str) -> None:
    """B: Chrome을 보통 프로세스로 띄우고(이 PC 안에서만 열리는 디버깅 포트), Playwright가 붙는다."""
    chrome = find_chrome()
    if chrome is None:
        raise SystemExit("Chrome을 찾지 못했습니다")
    port = free_port()
    process = subprocess.Popen(
        [
            str(chrome),
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            *COMMON_ARGS,
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,  # Chrome 자체 경고 로그는 숨긴다
    )
    try:
        print(f"  {wait_for_debugger(port)} (포트 {port})")
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url)
            report(page)
            browser.close()  # 연결만 끊는다. Chrome은 아래에서 종료
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["current", "c", "b"])
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    profile = Path(tempfile.mkdtemp(prefix="chrome-login-check-"))
    print(f"[{args.mode}] 임시 프로필: {profile}")
    try:
        if args.mode == "b":
            run_attach(profile, args.url)
        else:
            run_launch(profile, args.url, hide_automation=args.mode == "c")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
        print("임시 프로필을 지웠습니다.")


if __name__ == "__main__":
    main()
