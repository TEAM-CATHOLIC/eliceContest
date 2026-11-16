"""실제 Chrome(headless)과 로컬 데모 사이트로 넘겨주기 → 재개 → 탈퇴 화면 도달을 끝까지 확인한다.

Chrome이 없으면 건너뛴다. 네트워크 밖으로 나가지 않는다 (127.0.0.1).
"""

import asyncio
import threading
import time
from contextlib import asynccontextmanager

import pytest

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
