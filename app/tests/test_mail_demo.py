import asyncio
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent, open_chrome_page
from account_cleaner.classifier.analyzer import LocalAccountAnalyzer
from account_cleaner.classifier.completion import find_completion
from account_cleaner.classifier.model import explicit_rule
from account_cleaner.contracts import AgentEvent, AgentStatus
from account_cleaner.core.chrome import find_chrome
from account_cleaner.demo_mail import DemoWindow
from account_cleaner.demo_mail_flow import DOMAIN, DemoSession, start_site
from account_cleaner.mail import FileMailSource, ImportStats, iter_parsed_mails
from account_cleaner.ui.candidates.model import CandidateStatus


class RulePredictor:
    def predict(self, rows, on_progress=None, should_cancel=None):
        return [
            {
                "type": explicit_rule(r["subject"], r["body_text"])[0],
                "decision_source": "rule",
                "classification_score": 0.2,
                "stage_hint": "unknown",
            }
            for r in rows
        ]


def stub_analyzer():
    analyzer = object.__new__(LocalAccountAnalyzer)
    analyzer.predictor = RulePredictor()
    return analyzer


def test_시연_메일을_읽고_도착만으로는_완료하지않으며_새메일로_완료한다(qtbot, tmp_path):
    window = DemoWindow(tmp_path, analyzer_factory=stub_analyzer)
    qtbot.addWidget(window)
    window.show()
    window.load_button.click()
    qtbot.waitUntil(lambda: window.guide_button.isEnabled(), timeout=5000)
    assert window.inventory.model.rowCount() == 1
    window.session.started_at = datetime.now(UTC) - timedelta(seconds=2)
    window._agent_event(AgentEvent(AgentStatus.REACHED))
    window.check_completion()
    assert not window.completed
    assert not window.notification.isVisible()
    window.session.complete_by_user()
    qtbot.waitUntil(lambda: window.completed, timeout=5000)
    assert "시연" in window.notification.text()
    assert window.inventory.model.status_of(DOMAIN) is CandidateStatus.DONE
    window.close()


def test_시연_완료메일은_도착전에는_만들수없고_재요청시_중복생성하지않는다(tmp_path):
    session = DemoSession(tmp_path)
    with pytest.raises(ValueError):
        session.complete_by_user()
    session.start()
    session.reached = True
    path = session.complete_by_user()
    original = path.read_bytes()
    assert session.complete_by_user().read_bytes() == original


@pytest.mark.skipif(find_chrome() is None, reason="Chrome 없음")
def test_실제_브라우저는_최종버튼앞에서_멈추고_사용자역할_클릭후_완료메일이_생긴다(tmp_path):
    session = DemoSession(tmp_path)
    server, playbook = start_site(session)
    shared = {}
    events = []
    final = {}

    @asynccontextmanager
    async def opener(profile):
        async with open_chrome_page(profile, headless=True) as page:
            shared.update(page=page, loop=asyncio.get_running_loop())
            yield page

    agent = PlaywrightWithdrawAgent(session.root / "profile", page_opener=opener)
    session.start()

    def on_event(event):
        events.append(event)
        if event.status is AgentStatus.REACHED:
            session.reached = True

    worker = threading.Thread(
        target=lambda: final.setdefault("event", agent.run(playbook, on_event))
    )
    worker.start()

    def wait_for(status):
        deadline = time.monotonic() + 30
        while not any(e.status is status for e in events):
            assert time.monotonic() < deadline and worker.is_alive(), events
            time.sleep(0.05)

    try:
        wait_for(AgentStatus.USER_TURN)

        async def user_login():
            page = shared["page"]
            await page.get_by_role("button", name="시연 계정으로 계속").click()
            await page.wait_for_url("**/settings")
            assert await page.get_by_role(
                "button", name="계정 영구 삭제 (시연용 메일 생성)"
            ).is_disabled()

        asyncio.run_coroutine_threadsafe(user_login(), shared["loop"]).result(15)
        agent.resume()
        wait_for(AgentStatus.REACHED)
        assert not session.completion_path.exists()  # 에이전트가 최종 버튼을 누르지 않음

        async def user_completes():
            await (
                shared["page"]
                .get_by_role("button", name="계정 영구 삭제 (시연용 메일 생성)")
                .click()
            )
            await shared["page"].wait_for_url("**/done")

        asyncio.run_coroutine_threadsafe(user_completes(), shared["loop"]).result(15)
        mails = list(iter_parsed_mails(FileMailSource([session.completion_path]), ImportStats()))
        evidence = find_completion(mails, DOMAIN, session.started_at, set())
        assert (
            evidence is not None
            and "삭제" in evidence.statement
            or evidence is not None
            and "완료" in evidence.statement
        )
    finally:
        agent.stop()
        worker.join(30)
        server.shutdown()
        server.server_close()
    assert final["event"].status is AgentStatus.REACHED


def test_도착전_성급한_완료요청은_오류화면대신_설정화면으로_돌아간다(tmp_path):
    from http.client import HTTPConnection
    from urllib.parse import urlencode

    session = DemoSession(tmp_path)
    session.start()
    server, _playbook = start_site(session)
    base = f"http://127.0.0.1:{server.server_port}"
    client = HTTPConnection("127.0.0.1", server.server_port)
    try:
        client.request(
            "POST",
            "/complete",
            urlencode({"token": session.token}),
            {
                "Origin": base,
                "Cookie": f"demo_session={session.token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response = client.getresponse()
        assert response.status == 303
        assert response.getheader("Location") == "/settings"
        assert not session.completion_path.exists()
        response.read()
    finally:
        client.close()
        server.shutdown()
        server.server_close()
