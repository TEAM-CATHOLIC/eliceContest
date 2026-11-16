"""브라우저 에이전트 엔진 테스트 (원본: 브라우저 담당 `08_실행및검증/tests/test_engine.py`).

실제 브라우저 없이 가짜 페이지로 엔진의 판단만 확인한다.
"""

from account_cleaner.browser.agent import BrowserAgent
from account_cleaner.browser.agent.models import Action, AgentStatus, Playbook, Step

PASSWORD = "input[type='password']:visible"


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self.selector in self.page.visible else 0

    async def wait_for(self, **kwargs):
        if self.selector not in self.page.visible:
            raise TimeoutError(f"not visible: {self.selector}")

    async def inner_text(self, **kwargs):
        return self.page.texts.get(self.selector, "")

    async def click(self):
        self.page.clicks.append(self.selector)


class FakePage:
    def __init__(self, url="https://example.com/start", visible=None, texts=None):
        self.url = url
        self.visible = set(visible or ())
        self.texts = dict(texts or {})
        self.clicks = []
        self.gotos = []

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url

    def locator(self, selector):
        return FakeLocator(self, selector)


def make_playbook(*steps, auth_domains=()):
    return Playbook(
        service_id="example",
        display_name="Example",
        entry_url="https://example.com/settings",
        allowed_domains=("example.com",),
        steps=tuple(steps),
        auth_domains=auth_domains,
    )


def run_immediate(coroutine):
    """가짜 I/O 코루틴을 이벤트 루프 없이 끝까지 실행한다."""
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("가짜 코루틴이 외부 I/O를 기다림")


def test_탈퇴_화면에_도달하면_목표_버튼을_누르지_않고_멈춘다():
    # given
    page = FakePage(visible={"main", "text=Delete section"})
    agent = BrowserAgent(
        make_playbook(
            Step(Action.WAIT_FOR, "main"),
            Step(Action.REACH_TARGET, "text=Delete section"),
        )
    )

    # when
    result = run_immediate(agent.run(page))

    # then
    assert result.status is AgentStatus.REACHED_WITHDRAWAL
    assert page.clicks == []


def test_비밀번호_입력칸이_보이면_사용자에게_넘긴다():
    # given
    page = FakePage(visible={PASSWORD})
    agent = BrowserAgent(make_playbook(Step(Action.WAIT_FOR, "main")))

    # when
    result = run_immediate(agent.run(page))

    # then
    assert result.status is AgentStatus.WAITING_FOR_USER
    assert result.reason == "password"


def test_최종_탈퇴_문구가_있는_버튼은_클릭하지_않고_차단한다():
    # given
    selector = "button.delete"
    page = FakePage(visible={selector}, texts={selector: "Delete my account"})
    agent = BrowserAgent(make_playbook(Step(Action.CLICK, selector)))

    # when
    result = run_immediate(agent.run(page))

    # then
    assert result.status is AgentStatus.BLOCKED
    assert page.clicks == []


def test_허용_도메인_밖으로_이동하는_단계는_차단한다():
    # given
    agent = BrowserAgent(make_playbook(Step(Action.NAVIGATE, "https://evil.test/")))

    # when
    result = run_immediate(agent.run(FakePage()))

    # then
    assert result.status is AgentStatus.BLOCKED


def test_재개하면_시작_페이지로_다시_이동하지_않는다():
    # given: 사용자가 로그인을 마친 뒤의 페이지
    page = FakePage(url="https://example.com/settings", visible={"text=Delete section"})
    agent = BrowserAgent(make_playbook(Step(Action.REACH_TARGET, "text=Delete section")))

    # when
    result = run_immediate(agent.run(page, start_step=0, navigate_entry=False))

    # then
    assert result.status is AgentStatus.REACHED_WITHDRAWAL
    assert page.gotos == []


def test_셀렉터가_바뀌면_버튼_글자로_다시_찾는다():
    # given: 원래 셀렉터는 없고 글자만 남은 화면
    events = []
    page = FakePage(visible={"text=Account removal"})
    step = Step(Action.REACH_TARGET, "#old-selector", fallback_texts=("Account removal",))
    agent = BrowserAgent(make_playbook(step), on_event=events.append)

    # when
    result = run_immediate(agent.run(page))

    # then
    assert result.status is AgentStatus.REACHED_WITHDRAWAL
    assert any(event.get("status") == "fallback_used" for event in events)


def test_외부_인증_도메인으로_가면_사용자에게_넘긴다():
    # given: 소셜 로그인 화면
    page = FakePage(url="https://accounts.identity.test/login")
    playbook = make_playbook(
        Step(Action.WAIT_FOR, "main"), auth_domains=("accounts.identity.test",)
    )

    # when
    result = run_immediate(BrowserAgent(playbook).run(page, navigate_entry=False))

    # then
    assert result.status is AgentStatus.WAITING_FOR_USER
    assert result.reason == "external_auth"


def test_이벤트에_담긴_이메일은_가려서_내보낸다():
    # given: 주소에 이메일이 들어간 페이지
    events = []
    page = FakePage(url="https://example.com/u/hong@gmail.com", visible={"main"})
    agent = BrowserAgent(make_playbook(Step(Action.WAIT_FOR, "main")), on_event=events.append)

    # when
    run_immediate(agent.run(page, navigate_entry=False))

    # then
    assert all("hong@gmail.com" not in str(event) for event in events)
