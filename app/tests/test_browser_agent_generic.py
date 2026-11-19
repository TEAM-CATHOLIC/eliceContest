from __future__ import annotations

from account_cleaner.browser.agent import BrowserAgent, NextClick
from account_cleaner.browser.agent.generic import INTERACTIVE_SELECTOR
from account_cleaner.browser.agent.models import AgentStatus, Playbook


class FakeElement:
    def __init__(self, page, data):
        self.page = page
        self.data = data

    async def evaluate(self, _script):
        return self.data

    async def click(self):
        self.page.clicks.append(self.data["text"])
        if self.data.get("next") is not None:
            self.page.elements = self.data["next"]
        if self.data.get("next_url"):
            self.page.url = self.data["next_url"]


class FakeCollection:
    def __init__(self, page, enabled=True):
        self.page = page
        self.enabled = enabled

    async def count(self):
        return len(self.page.elements) if self.enabled else 0

    def nth(self, index):
        return FakeElement(self.page, self.page.elements[index])


class FakePage:
    def __init__(self, elements):
        self.url = "https://example.com/settings"
        self.elements = elements
        self.clicks = []
        self.gotos = []

    def locator(self, selector):
        return FakeCollection(self, selector == INTERACTIVE_SELECTOR)

    async def goto(self, url, **_kwargs):
        self.url = url
        self.gotos.append(url)

    async def wait_for_timeout(self, _milliseconds):
        return None


class FakeSelector:
    def __init__(self, *choices):
        self.choices = list(choices)
        self.payloads = []

    async def choose(self, **payload):
        self.payloads.append(payload)
        return NextClick(self.choices.pop(0), "계정 설정으로 이동")


def element(text, *, tag="a", href="https://example.com/account", next=None):
    return {
        "text": text,
        "ariaLabel": "",
        "tag": tag,
        "role": "link" if tag == "a" else "button",
        "href": href if tag == "a" else "",
        "hrefPath": "/account" if tag == "a" else "",
        "next": next,
    }


def playbook():
    return Playbook(
        service_id="generic:example.com",
        display_name="example.com",
        entry_url="https://example.com",
        allowed_domains=("example.com",),
        steps=(),
    )


def run(coro):
    try:
        coro.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("가짜 코루틴이 외부 I/O를 기다림")


def test_llm이_고른_안전한_링크를_누르고_최종버튼_앞에서_멈춘다():
    final = [element("Delete my account", tag="button")]
    page = FakePage([element("Account settings", next=final)])
    selector = FakeSelector(0)

    result = run(BrowserAgent(playbook(), next_click_selector=selector).run(page))

    assert result.status is AgentStatus.REACHED_WITHDRAWAL
    assert page.clicks == ["Account settings"]
    assert len(selector.payloads) == 1


def test_최종_탈퇴버튼은_llm에_보내거나_클릭하지_않는다():
    page = FakePage([element("회원 탈퇴하기", tag="button")])
    selector = FakeSelector(0)

    result = run(BrowserAgent(playbook(), next_click_selector=selector).run(page))

    assert result.status is AgentStatus.REACHED_WITHDRAWAL
    assert page.clicks == []
    assert selector.payloads == []


def test_llm_페이로드에서_이메일_전화번호와_사용자이름을_가린다():
    page = FakePage([element("홍길동 hong@example.com 010-1234-5678 계정")])
    page.url = "https://example.com/users/hong@example.com/settings"
    selector = FakeSelector(None)

    run(
        BrowserAgent(playbook(), next_click_selector=selector, private_values=("홍길동",)).run(page)
    )

    payload = str(selector.payloads[0]["candidates"])
    assert "hong@example.com" not in payload
    assert "010-1234-5678" not in payload
    assert "홍길동" not in payload
    assert "[EMAIL]" in payload and "[PHONE]" in payload and "[PRIVATE]" in payload
    assert "hong@example.com" not in selector.payloads[0]["path"]


def test_llm이_목록에_없는_번호를_고르면_실패하고_클릭하지_않는다():
    page = FakePage([element("Settings")])
    result = run(BrowserAgent(playbook(), next_click_selector=FakeSelector(99)).run(page))

    assert result.status is AgentStatus.FAILED
    assert page.clicks == []


def test_외부_도메인_링크는_코드가_차단한다():
    item = element("Account settings")
    item["href"] = "https://evil.example/account"
    item["hrefPath"] = "https://evil.example/account"
    page = FakePage([item])

    result = run(BrowserAgent(playbook(), next_click_selector=FakeSelector(0)).run(page))

    assert result.status is AgentStatus.FAILED
    assert page.clicks == []


def test_api키가_없는_범용_플레이북은_명확히_실패한다():
    result = run(BrowserAgent(playbook()).run(FakePage([element("Settings")])))

    assert result.status is AgentStatus.FAILED
    assert result.reason == "missing_llm"


class BrokenSelector:
    async def choose(self, **_payload):
        raise ConnectionError("network down")


def test_llm_호출이_실패하면_브라우저_오류가_아니라_ai_응답_안내로_끝낸다():
    # given (#79)
    from account_cleaner.browser.agent.generic import LLM_FAILED_MESSAGE

    page = FakePage([element("Settings")])

    # when
    result = run(BrowserAgent(playbook(), next_click_selector=BrokenSelector()).run(page))

    # then
    assert result.status is AgentStatus.FAILED
    assert result.message == LLM_FAILED_MESSAGE
    assert page.clicks == []


def test_모델이_거절하거나_응답이_잘리면_선택_없음으로_돌려준다():
    # given (#79)
    import asyncio
    from types import SimpleNamespace

    from account_cleaner.browser.agent.llm import AnthropicNextClickSelector

    def selector_returning(stop_reason):
        class FakeMessages:
            async def parse(self, **_kwargs):
                return SimpleNamespace(stop_reason=stop_reason, parsed_output=None)

        selector = AnthropicNextClickSelector("test-key")
        selector._client = SimpleNamespace(messages=FakeMessages())
        return selector

    async def choose(stop_reason):
        return await selector_returning(stop_reason).choose(
            domain="example.com", path="/", candidates=(), previous_actions=()
        )

    # when
    refused = asyncio.run(choose("refusal"))
    cut = asyncio.run(choose("max_tokens"))

    # then
    assert refused.choice is None and "거절" in refused.reason
    assert cut.choice is None and "잘려" in cut.reason


def test_범용_안내는_서비스_이름만_찾은_후보나_주소_조각에는_켜지지_않는다():
    # given (#79)
    from account_cleaner.ui.agent_page import generic_domain_ok

    # then
    assert generic_domain_ok("notion.so")
    assert not generic_domain_ok("샘플서비스.invalid")
    assert not generic_domain_ok("localhost")
    assert not generic_domain_ok("evil.com/path")


def test_범용_플레이북은_소셜_로그인_도메인을_사용자_차례로_넘긴다(qtbot, tmp_path):
    # given (#79): Google 로그인을 거쳐도 도메인 위반으로 끝나지 않게
    from account_cleaner.browser.agent.generic import COMMON_AUTH_DOMAINS
    from account_cleaner.ui.agent_page import AgentPage

    page = AgentPage(
        tmp_path / "profile",
        playbook_loader=dict,
        include_demo=False,
        generic_available=lambda: True,
    )
    qtbot.addWidget(page)

    # when
    generic = page.playbook_for_domain("notion.so")

    # then
    assert generic is not None and generic.id == "generic:notion.so"
    assert "accounts.google.com" in generic.auth_domains
    assert set(COMMON_AUTH_DOMAINS) <= set(generic.auth_domains)
