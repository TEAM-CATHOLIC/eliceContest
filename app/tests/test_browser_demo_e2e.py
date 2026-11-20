"""실제 Chrome(headless)과 로컬 데모 사이트로 넘겨주기 → 재개 → 탈퇴 화면 도달을 끝까지 확인한다.

Chrome이 없으면 건너뛴다. 네트워크 밖으로 나가지 않는다 (127.0.0.1).
"""

import asyncio
import threading
import time
from contextlib import asynccontextmanager

import pytest
from playwright.sync_api import sync_playwright

from account_cleaner.browser.agent import BrowserAgent, NextClick
from account_cleaner.browser.agent.models import AgentStatus as EngineStatus
from account_cleaner.browser.agent.models import Playbook as EnginePlaybook
from account_cleaner.browser.demo import demo_playbook, start_demo_server
from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent, open_chrome_page
from account_cleaner.contracts import AgentStatus, HandoffReason
from account_cleaner.core.chrome import find_chrome

pytestmark = pytest.mark.skipif(find_chrome() is None, reason="Chrome이 설치되어 있지 않음")


@pytest.fixture
def demo_site():
    server = start_demo_server()
    yield server.server_address[1]
    server.shutdown()


def test_데모_사이트에서_로그인을_넘겨받고_재개하면_최종_버튼_앞에서_멈춘다(tmp_path, demo_site):
    # given: 페이지와 이벤트 루프를 테스트에서 쓸 수 있게 열어 두는 opener (사용자 역할용)
    shared = {}

    @asynccontextmanager
    async def opener(profile_dir):
        async with open_chrome_page(profile_dir, headless=True) as page:
            shared["page"], shared["loop"] = page, asyncio.get_running_loop()
            yield page

    agent = PlaywrightWithdrawAgent(tmp_path / "profile", page_opener=opener)
    events, done = [], {}
    worker = threading.Thread(
        target=lambda: done.setdefault("final", agent.run(demo_playbook(demo_site), events.append))
    )
    worker.start()
    deadline = time.monotonic() + 30
    while not (events and events[-1].status is AgentStatus.USER_TURN):
        assert time.monotonic() < deadline and worker.is_alive(), events
        time.sleep(0.05)

    # when: 사용자가 Chrome에서 직접 로그인 (에이전트는 비밀번호를 입력하지 않음)
    async def user_logs_in():
        page = shared["page"]
        await page.fill("#password", "demo")
        await page.click("button[type=submit]")
        await page.wait_for_url("**/settings")

    asyncio.run_coroutine_threadsafe(user_logs_in(), shared["loop"]).result(15)
    agent.resume()
    deadline = time.monotonic() + 30
    while not any(e.status is AgentStatus.REACHED for e in events):
        assert time.monotonic() < deadline and worker.is_alive(), events
        time.sleep(0.05)
    time.sleep(0.5)
    browser_kept_open = worker.is_alive()  # 사용자가 최종 버튼을 누를 수 있게 열려 있음
    agent.stop()  # 사용자가 끝냄 (창 닫기와 같은 효과)
    worker.join(30)

    # then
    user_turn = next(e for e in events if e.status is AgentStatus.USER_TURN)
    assert user_turn.reason is HandoffReason.LOGIN
    assert done["final"].status is AgentStatus.REACHED
    assert done["final"].url.endswith("/settings")
    assert browser_kept_open


def test_사용자_차례에_실제_Chrome_창을_닫으면_오류_없이_중단으로_끝난다(
    tmp_path, demo_site, caplog
):
    """회귀: 닫힌 창을 다시 닫다가 TargetClosedError가 나 ERROR 로그와 FAILED로 끝났다."""
    # given: 로그인 화면에서 사용자 차례
    shared = {}

    @asynccontextmanager
    async def opener(profile_dir):
        async with open_chrome_page(profile_dir, headless=True) as page:
            shared["page"], shared["loop"] = page, asyncio.get_running_loop()
            yield page

    agent = PlaywrightWithdrawAgent(tmp_path / "profile", page_opener=opener)
    events, done = [], {}
    worker = threading.Thread(
        target=lambda: done.setdefault("final", agent.run(demo_playbook(demo_site), events.append))
    )
    worker.start()
    deadline = time.monotonic() + 30
    while not (events and events[-1].status is AgentStatus.USER_TURN):
        assert time.monotonic() < deadline and worker.is_alive(), events
        time.sleep(0.05)

    # when: 사용자가 Chrome 창을 닫음
    asyncio.run_coroutine_threadsafe(shared["page"].close(), shared["loop"]).result(15)
    worker.join(30)

    # then
    assert done["final"].status is AgentStatus.STOPPED
    assert "창을 닫아" in done["final"].message
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


def test_실제_Playwright에서_범용모드가_개인정보를_가리고_최종버튼_앞에서_멈춘다(demo_site):
    class FirstCandidateSelector:
        def __init__(self):
            self.payloads = []

        async def choose(self, **payload):
            self.payloads.append(payload)
            return NextClick(0, "계정 설정 링크")

    selector = FirstCandidateSelector()

    class AsyncLocatorAdapter:
        def __init__(self, locator):
            self._locator = locator

        @property
        def first(self):
            return AsyncLocatorAdapter(self._locator.first)

        def nth(self, index):
            return AsyncLocatorAdapter(self._locator.nth(index))

        async def count(self):
            return self._locator.count()

        async def evaluate(self, script):
            return self._locator.evaluate(script)

        async def click(self):
            self._locator.click()

    class AsyncPageAdapter:
        def __init__(self, page):
            self._page = page

        @property
        def url(self):
            return self._page.url

        def locator(self, query):
            return AsyncLocatorAdapter(self._page.locator(query))

        async def goto(self, url, **kwargs):
            self._page.goto(url, **kwargs)

        async def wait_for_timeout(self, milliseconds):
            self._page.wait_for_timeout(milliseconds)

    def run_immediate(coroutine):
        try:
            coroutine.send(None)
        except StopIteration as finished:
            return finished.value
        raise AssertionError("동기 Playwright 어댑터가 외부 I/O를 기다렸습니다")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(find_chrome()), headless=True)
        try:
            sync_page = browser.new_page()
            playbook = EnginePlaybook(
                service_id="generic:demo",
                display_name="범용 데모",
                entry_url=f"http://127.0.0.1:{demo_site}/generic",
                allowed_domains=("127.0.0.1",),
                steps=(),
            )
            result = run_immediate(
                BrowserAgent(
                    playbook,
                    next_click_selector=selector,
                    private_values=("홍길동", "hong", "hong@example.com"),
                ).run(AsyncPageAdapter(sync_page))
            )
            url = sync_page.url
        finally:
            browser.close()

    assert result.status is EngineStatus.REACHED_WITHDRAWAL
    assert url.endswith("/generic/account")
    sent = str(selector.payloads)
    assert "홍길동" not in sent and "hong@example.com" not in sent
    assert "[PRIVATE]" in sent
