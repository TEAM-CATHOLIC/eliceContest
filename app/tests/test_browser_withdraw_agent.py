"""계약 `WithdrawAgent` 어댑터 테스트. 실제 브라우저 대신 가짜 페이지를 연다."""

import threading
import time
from contextlib import asynccontextmanager

from test_browser_agent_engine import PASSWORD, FakePage

from account_cleaner.browser import PLAYBOOK_DIR
from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent, to_engine_playbook
from account_cleaner.contracts import AgentStatus, HandoffReason, Playbook, load_playbooks

TARGET = "text=Delete section"


def contract_playbook(*steps):
    return Playbook.from_dict(
        {
            "schema_version": 1,
            "id": "example",
            "service": "예시",
            "domains": ["example.com"],
            "login_methods": ["email"],
            "login_url": "https://example.com/login",
            "password_reset_url": "https://example.com/reset",
            "withdraw_url": "https://example.com/settings",
            "steps": list(steps),
        }
    )


PLAYBOOK = contract_playbook(
    {"action": "wait_for", "value": "main", "description": "설정 화면 대기"},
    {"action": "reach_target", "value": TARGET, "description": "탈퇴 구역 확인"},
)


def agent_with(page, tmp_path):
    @asynccontextmanager
    async def opener(profile_dir):
        yield page

    return PlaywrightWithdrawAgent(tmp_path / "profile", page_opener=opener)


def run_in_thread(agent, playbook):
    events, done = [], {}
    thread = threading.Thread(
        target=lambda: done.setdefault("final", agent.run(playbook, events.append))
    )
    thread.start()
    return thread, events, done


def wait_for(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timeout"
        time.sleep(0.01)


def test_계약_플레이북을_엔진_플레이북으로_바꾸면_탈퇴_화면에서_시작한다():
    # given / when
    engine = to_engine_playbook(PLAYBOOK)

    # then
    assert engine.entry_url == "https://example.com/settings"
    assert engine.allowed_domains == ("example.com",)
    assert [s.description for s in engine.steps] == ["설정 화면 대기", "탈퇴 구역 확인"]


def test_브라우저_플레이북은_모두_계약_형식과_엔진_사전_검사를_통과한다():
    # given
    from account_cleaner.browser.agent.validation import validate_playbook

    # when
    reports = {
        k: validate_playbook(to_engine_playbook(p)) for k, p in load_playbooks(PLAYBOOK_DIR).items()
    }

    # then
    assert set(reports) == {"github", "dropbox", "linkedin"}
    assert all(r.valid for r in reports.values())


def test_로그인_화면에서_멈췄다가_resume하면_같은_페이지에서_이어가_탈퇴_화면에_도착한다(tmp_path):
    # given: 처음엔 로그인 화면
    page = FakePage(url="https://example.com/login", visible={PASSWORD})
    agent = agent_with(page, tmp_path)
    thread, events, done = run_in_thread(agent, PLAYBOOK)
    wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)

    # when: 사용자가 로그인을 마침 (UI 스레드에서 resume)
    page.visible = {"main", TARGET}
    agent.resume()
    thread.join(3)

    # then
    user_turn = next(e for e in events if e.status is AgentStatus.USER_TURN)
    assert user_turn.reason is HandoffReason.LOGIN
    assert done["final"].status is AgentStatus.REACHED
    assert done["final"].step.index == 2 and done["final"].step.total == 2
    assert page.gotos == ["https://example.com/settings"]  # 재개 때 다시 이동하지 않음
    assert page.clicks == []


def test_사용자_차례에서_stop하면_STOPPED로_끝난다(tmp_path):
    # given
    agent = agent_with(FakePage(url="https://example.com/login", visible={PASSWORD}), tmp_path)
    thread, events, done = run_in_thread(agent, PLAYBOOK)
    wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)

    # when
    agent.stop()
    thread.join(3)

    # then
    assert done["final"].status is AgentStatus.STOPPED


def test_사용자_차례가_아닐_때_누른_resume은_무시된다(tmp_path):
    # given: 실행 전에 resume
    agent = agent_with(FakePage(url="https://example.com/login", visible={PASSWORD}), tmp_path)
    agent.resume()

    # when
    thread, events, _ = run_in_thread(agent, PLAYBOOK)
    wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)

    # then
    time.sleep(0.2)
    assert thread.is_alive()
    agent.stop()
    thread.join(3)


def test_안전_정책에_막히면_FAILED로_이유를_알린다(tmp_path):
    # given: 최종 버튼을 클릭하는 잘못된 플레이북
    page = FakePage(
        url="https://example.com/settings", visible={"button.x"}, texts={"button.x": "회원 탈퇴"}
    )
    playbook = contract_playbook({"action": "click", "value": "button.x", "description": "클릭"})

    # when
    final = agent_with(page, tmp_path).run(playbook, lambda e: None)

    # then
    assert final.status is AgentStatus.FAILED
    assert "안전 정책" in final.message
    assert page.clicks == []


def test_이동_중_이벤트에는_단계_번호와_제목이_담긴다(tmp_path):
    # given
    page = FakePage(url="https://example.com/settings", visible={"main", TARGET})
    events = []

    # when
    agent_with(page, tmp_path).run(PLAYBOOK, events.append)

    # then
    navigating = [e for e in events if e.status is AgentStatus.NAVIGATING]
    assert [(e.step.index, e.step.title) for e in navigating] == [
        (1, "설정 화면 대기"),
        (2, "탈퇴 구역 확인"),
    ]


def test_전체_세션_지우기는_전용_프로필_폴더를_비운다(tmp_path):
    # given
    agent = agent_with(FakePage(), tmp_path)
    (agent.profile_dir / "Default").mkdir(parents=True)
    (agent.profile_dir / "Default" / "Cookies").write_text("x")

    # when
    agent.clear_session()

    # then
    assert agent.profile_dir.is_dir()
    assert list(agent.profile_dir.iterdir()) == []


class FakeContext:
    def __init__(self, page):
        self.pages = [page]


class ClosablePage(FakePage):
    """실제 페이지처럼 context와 닫힘 상태를 가진 가짜 페이지."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.closed = False
        self.context = FakeContext(self)

    def is_closed(self):
        return self.closed


def test_탈퇴_화면에_도착하면_사용자가_창을_닫을_때까지_브라우저를_열어_둔다(tmp_path):
    """회귀: REACHED를 보내자마자 브라우저를 닫아 사용자가 최종 버튼을 누를 수 없었다."""
    # given: 바로 탈퇴 화면인 페이지
    page = ClosablePage(url="https://example.com/settings", visible={"main", TARGET})
    agent = agent_with(page, tmp_path)
    thread, events, done = run_in_thread(agent, PLAYBOOK)
    wait_for(lambda: events and events[-1].status is AgentStatus.REACHED)

    # when: 잠시 뒤 사용자가 창을 닫음
    time.sleep(0.2)
    still_open = thread.is_alive()
    page.closed = True
    thread.join(3)

    # then
    assert still_open
    assert done["final"].status is AgentStatus.REACHED
    assert [e.status for e in events].count(AgentStatus.REACHED) == 1


def test_사용자_차례에_Chrome_창을_닫으면_중단으로_끝난다(tmp_path):
    """회귀: 창을 닫으면 브라우저 정리 중 오류가 나 '실행하지 못했습니다(FAILED)'로 끝났다."""
    # given: 로그인 화면에서 사용자 차례
    page = ClosablePage(url="https://example.com/login", visible={PASSWORD})
    agent = agent_with(page, tmp_path)
    thread, events, done = run_in_thread(agent, PLAYBOOK)
    wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)

    # when: 사용자가 창을 닫음
    page.closed = True
    thread.join(3)

    # then
    assert done["final"].status is AgentStatus.STOPPED
    assert "창을 닫아" in done["final"].message


def test_시작_직전에_온_stop도_무시하지_않고_중단한다(tmp_path):
    """회귀: run()이 시작할 때 stop 신호를 비워, '안내 시작' 직후 누른 '중단'이 사라졌다."""
    # given: 실행 전에 stop
    agent = agent_with(FakePage(url="https://example.com/login", visible={PASSWORD}), tmp_path)
    agent.stop()

    # when
    final = agent.run(PLAYBOOK, lambda e: None)

    # then
    assert final.status is AgentStatus.STOPPED


def test_에이전트용_Chrome이_이미_열려_있으면_닫으라는_안내를_그대로_보여_준다(tmp_path):
    # given: Chrome을 띄우지 못함 (#70: 예전엔 "ChromeStartError" 이름만 보였다)
    from account_cleaner.browser.chrome_process import ChromeStartError

    message = "에이전트용 Chrome이 이미 열려 있습니다. 그 창을 모두 닫고 다시 시작해 주세요."

    @asynccontextmanager
    async def opener(profile_dir):
        raise ChromeStartError(message)
        yield

    agent = PlaywrightWithdrawAgent(tmp_path / "profile", page_opener=opener)

    # when
    result = agent.run(PLAYBOOK, lambda _event: None)

    # then
    assert result.status is AgentStatus.FAILED
    assert result.message == message
