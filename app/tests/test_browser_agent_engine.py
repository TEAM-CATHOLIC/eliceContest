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

    async def evaluate(self, script):
        # 엔진은 링크 여부 확인에만 evaluate를 쓴다
        return self.selector in self.page.links


class FakePage:
    def __init__(self, url="https://example.com/start", visible=None, texts=None, links=()):
        self.url = url
        self.visible = set(visible or ())
        self.texts = dict(texts or {})
        self.links = set(links)
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


def test_이메일을_먼저_묻는_로그인도_입력없이_사용자에게_넘긴다():
    from account_cleaner.browser.agent.handoff import LOGIN_EMAIL_SELECTOR

    page = FakePage(url="https://example.com/login?cont=settings", visible={LOGIN_EMAIL_SELECTOR})
    agent = BrowserAgent(make_playbook(Step(Action.WAIT_FOR, "main")))
    result = run_immediate(agent.run(page, navigate_entry=False))
    assert result.status is AgentStatus.WAITING_FOR_USER
    assert result.reason == "password"
    assert page.clicks == [] and page.gotos == []


def test_일반화면의_뉴스레터_이메일칸은_로그인으로_오인하지않는다():
    from account_cleaner.browser.agent.handoff import LOGIN_EMAIL_SELECTOR

    page = FakePage(url="https://example.com/newsletter", visible={LOGIN_EMAIL_SELECTOR, "main"})
    agent = BrowserAgent(make_playbook(Step(Action.WAIT_FOR, "main")))
    result = run_immediate(agent.run(page, navigate_entry=False))
    assert result.status is AgentStatus.REACHED_WITHDRAWAL


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


# --- 메뉴 링크 클릭 (한국 사이트의 "회원탈퇴" 메뉴) ---

MENU = "a.leave"


def test_메뉴로_표시한_회원탈퇴_링크는_클릭한다():
    # given: 탈퇴 화면으로 가는 "회원탈퇴" 메뉴 링크
    page = FakePage(visible={MENU}, texts={MENU: "회원탈퇴"}, links={MENU})
    step = Step(Action.CLICK, MENU, "탈퇴 메뉴로 이동", menu=True)

    # when
    result = run_immediate(BrowserAgent(make_playbook(step)).run(page))

    # then
    assert page.clicks == [MENU]
    assert result.status is AgentStatus.REACHED_WITHDRAWAL


def test_메뉴로_표시했어도_링크가_아닌_버튼이면_차단한다():
    """메뉴 표시를 실수로 최종 버튼에 붙여도 버튼이면 누르지 않는다."""
    # given: 같은 글자지만 버튼
    page = FakePage(visible={"button.leave"}, texts={"button.leave": "회원탈퇴"})
    step = Step(Action.CLICK, "button.leave", "잘못 표시한 최종 버튼", menu=True)

    # when
    result = run_immediate(BrowserAgent(make_playbook(step)).run(page))

    # then
    assert result.status is AgentStatus.BLOCKED
    assert page.clicks == []


def test_메뉴_표시가_없으면_링크여도_최종_문구_클릭은_차단한다():
    # given
    page = FakePage(visible={MENU}, texts={MENU: "회원탈퇴"}, links={MENU})

    # when
    result = run_immediate(BrowserAgent(make_playbook(Step(Action.CLICK, MENU))).run(page))

    # then
    assert result.status is AgentStatus.BLOCKED
    assert page.clicks == []


def test_플레이북의_menu_값을_읽는다():
    # given / when
    step = Step.from_dict({"action": "click", "value": MENU, "menu": True})

    # then
    assert step.menu
    assert not Step.from_dict({"action": "click", "value": MENU}).menu
