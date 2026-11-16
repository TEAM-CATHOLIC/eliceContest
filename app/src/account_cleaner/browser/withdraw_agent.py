"""`contracts.WithdrawAgent` 구현: 브라우저 담당 엔진(`browser.agent`)을 데스크톱 인터페이스에 연결한다.

- `run()`은 데스크톱 작업 스레드에서 불린다. 그 스레드 안에서 이벤트 루프를 만들어 Playwright(async)와
  엔진을 돌리고, 끝날 때까지 블로킹한다.
- 엔진이 사용자 차례(`WAITING_FOR_USER`)를 돌려주면 브라우저는 열어 둔 채 `USER_TURN`을 보내고,
  `resume()`이 오면 같은 페이지에서 다음 단계부터 다시 실행한다.
- `resume()`·`stop()`은 UI 스레드에서 불리므로 `threading.Event`로 신호만 보낸다.
"""

import asyncio
import logging
import shutil
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

from account_cleaner.browser.agent import BrowserAgent
from account_cleaner.browser.agent import Playbook as EnginePlaybook
from account_cleaner.browser.agent.models import AgentResult, Step
from account_cleaner.browser.agent.models import AgentStatus as EngineStatus
from account_cleaner.contracts import (
    AgentEvent,
    AgentStatus,
    AgentStep,
    EventCallback,
    HandoffReason,
    Playbook,
    WithdrawAgent,
)
from account_cleaner.core.chrome import CHROME_DOWNLOAD_URL, find_chrome

log = logging.getLogger(__name__)

PageOpener = Callable[[Path], AbstractAsyncContextManager[Any]]
"""전용 프로필로 페이지 하나를 열어 주는 함수. 테스트에서는 가짜 페이지를 넘긴다."""

POLL_SECONDS = 0.1

HANDOFF_REASONS = {
    "password": HandoffReason.LOGIN,
    "otp_or_2fa": HandoffReason.TWO_FACTOR,
    "captcha": HandoffReason.CAPTCHA,
    "identity_verification": HandoffReason.IDENTITY,
    "payment": HandoffReason.PAYMENT,
    "external_auth": HandoffReason.EXTERNAL_AUTH,
}
HANDOFF_MESSAGES = {
    HandoffReason.LOGIN: "로그인해 주세요. 비밀번호는 직접 입력합니다.",
    HandoffReason.TWO_FACTOR: "2단계 인증을 직접 완료해 주세요.",
    HandoffReason.CAPTCHA: "자동 입력 방지 문자를 직접 풀어 주세요.",
    HandoffReason.IDENTITY: "본인인증을 직접 완료해 주세요.",
    HandoffReason.PAYMENT: "결제 정보 화면입니다. 직접 확인해 주세요.",
    HandoffReason.EXTERNAL_AUTH: "외부 로그인(구글·애플 등)을 직접 완료해 주세요.",
    HandoffReason.UNKNOWN: "다음 동작을 찾지 못했습니다. 화면을 직접 확인해 주세요.",
}
DONE_SUFFIX = " 끝나면 '계속'을 누르세요."


def to_engine_playbook(playbook: Playbook) -> EnginePlaybook:
    """계약 플레이북 → 엔진 플레이북. 시작 주소는 탈퇴 화면 (로그인이 필요하면 서비스가 돌려보냄)."""
    return EnginePlaybook(
        service_id=playbook.id,
        display_name=playbook.service,
        entry_url=playbook.withdraw_url,
        allowed_domains=playbook.domains,
        steps=tuple(Step.from_dict(step) for step in playbook.steps),
        auth_domains=playbook.auth_domains,
    )


@asynccontextmanager
async def open_chrome_page(profile_dir: Path, headless: bool = False) -> AsyncIterator[Any]:
    """설치된 Chrome을 앱 전용 프로필로 띄운다 (사용자의 기본 Chrome 프로필과 분리)."""
    from playwright.async_api import async_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile_dir),
            channel="chrome",
            headless=headless,
            accept_downloads=False,
            args=["--disable-sync", "--no-default-browser-check", "--no-first-run"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            yield page
        finally:
            await context.close()


class PlaywrightWithdrawAgent(WithdrawAgent):
    def __init__(self, profile_dir: Path, page_opener: PageOpener | None = None) -> None:
        super().__init__(profile_dir)
        self._open_page = page_opener or open_chrome_page
        self._resume = threading.Event()
        self._stop = threading.Event()
        self._front = threading.Event()
        self._awaiting_user = False

    # --- UI 스레드에서 호출 ---

    def resume(self) -> None:
        if self._awaiting_user:
            self._resume.set()

    def stop(self) -> None:
        self._stop.set()

    def bring_to_front(self) -> None:
        self._front.set()

    async def _sleep_and_serve(self, page: Any) -> None:
        """대기 중에 UI 요청(창 앞으로 가져오기)을 처리한다. 실패해도 진행에는 영향 없음."""
        if self._front.is_set():
            self._front.clear()
            raise_window = getattr(page, "bring_to_front", None)
            if raise_window is not None:
                try:
                    await raise_window()
                except Exception:  # 창이 이미 닫혔을 수 있음
                    log.debug("창 앞으로 가져오기 실패", exc_info=True)
        await asyncio.sleep(POLL_SECONDS)

    # --- 작업 스레드에서 호출 ---

    def run(self, playbook: Playbook, on_event: EventCallback) -> AgentEvent:
        self._resume.clear()
        self._stop.clear()
        self._awaiting_user = False
        if self._open_page is open_chrome_page and find_chrome() is None:
            message = (
                f"Google Chrome이 필요합니다. 설치 후 다시 시도해 주세요. {CHROME_DOWNLOAD_URL}"
            )
            return self._finish(on_event, AgentEvent(AgentStatus.FAILED, message))
        try:
            return asyncio.run(self._run(to_engine_playbook(playbook), on_event))
        except Exception as e:
            log.exception("브라우저 에이전트 실행 실패")
            message = f"브라우저를 실행하지 못했습니다 ({type(e).__name__})."
            return self._finish(on_event, AgentEvent(AgentStatus.FAILED, message))

    async def _run(self, playbook: EnginePlaybook, on_event: EventCallback) -> AgentEvent:
        total = max(len(playbook.steps), 1)

        def step_info(index: int) -> AgentStep:
            index = min(max(index, 0), total - 1)
            step = playbook.steps[index] if playbook.steps else None
            title = (step.description or str(step.action)) if step else playbook.display_name
            return AgentStep(index + 1, total, title)

        def on_engine_event(event: dict[str, str]) -> None:
            if event.get("status") == "running":
                index = int(event.get("step", 0))
                url = event.get("url") or None
                on_event(
                    AgentEvent(
                        AgentStatus.NAVIGATING,
                        step_info(index).title,
                        url=url,
                        step=step_info(index),
                    )
                )

        agent = BrowserAgent(playbook, on_event=on_engine_event)
        async with self._open_page(self.profile_dir) as page:
            start, navigate_entry = 0, True
            while True:
                result = await self._run_engine(agent, page, start, navigate_entry)
                if result is None:
                    return self._finish(on_event, AgentEvent(AgentStatus.STOPPED, "중단했습니다."))
                if result.status is not EngineStatus.WAITING_FOR_USER:
                    final = self._finish(on_event, self._final_event(result, step_info))
                    if final.status is AgentStatus.REACHED:
                        # 최종 버튼은 사용자가 누른다 → 사용자가 창을 닫을 때까지 브라우저를 열어 둔다
                        await self._wait_until_closed(page)
                    return final
                reason = HANDOFF_REASONS.get(result.reason, HandoffReason.UNKNOWN)
                # resume()이 USER_TURN 직후 바로 와도 놓치지 않도록 먼저 대기 상태로 둔다.
                self._awaiting_user = True
                on_event(
                    AgentEvent(
                        AgentStatus.USER_TURN,
                        HANDOFF_MESSAGES[reason] + DONE_SUFFIX,
                        reason=reason,
                        url=result.current_url or None,
                        step=step_info(result.next_step),
                    )
                )
                if not await self._wait_for_user(page):
                    return self._finish(on_event, AgentEvent(AgentStatus.STOPPED, "중단했습니다."))
                start, navigate_entry = result.next_step, False

    async def _run_engine(
        self, agent: BrowserAgent, page: Any, start: int, navigate_entry: bool
    ) -> AgentResult | None:
        """엔진을 실행하고, 도중에 `stop()`이 오면 취소한 뒤 None을 돌려준다."""
        task = asyncio.create_task(agent.run(page, start_step=start, navigate_entry=navigate_entry))
        while not task.done():
            if self._stop.is_set():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                return None
            await self._sleep_and_serve(page)
        return task.result()

    async def _wait_until_closed(self, page: Any) -> None:
        """사용자가 Chrome 창을 모두 닫거나 `stop()`이 올 때까지 기다린다."""
        context = getattr(page, "context", None)
        if context is None:
            return
        while not self._stop.is_set():
            if all(p.is_closed() for p in context.pages):
                return
            await self._sleep_and_serve(page)

    async def _wait_for_user(self, page: Any) -> bool:
        """`resume()`이면 True, `stop()`이면 False."""
        try:
            while not self._resume.is_set():
                if self._stop.is_set():
                    return False
                await self._sleep_and_serve(page)
            return True
        finally:
            self._awaiting_user = False
            self._resume.clear()

    @staticmethod
    def _final_event(result: AgentResult, step_info: Callable[[int], AgentStep]) -> AgentEvent:
        url = result.current_url or None
        if result.status is EngineStatus.REACHED_WITHDRAWAL:
            message = "탈퇴 화면에 도착했습니다. 조건을 확인하고 최종 버튼은 직접 누르세요."
            return AgentEvent(
                AgentStatus.REACHED, message, url=url, step=step_info(result.next_step - 1)
            )
        if result.status is EngineStatus.CANCELLED:
            return AgentEvent(AgentStatus.STOPPED, "중단했습니다.", url=url)
        if result.status is EngineStatus.BLOCKED:
            return AgentEvent(
                AgentStatus.FAILED, f"안전 정책으로 멈췄습니다: {result.message}", url=url
            )
        return AgentEvent(AgentStatus.FAILED, f"진행하지 못했습니다: {result.message}", url=url)

    def _finish(self, on_event: EventCallback, event: AgentEvent) -> AgentEvent:
        on_event(event)
        return event

    def clear_session(self, domains: tuple[str, ...] | None = None) -> None:
        """전용 프로필의 로그인 세션을 지운다 (D-05). `run()` 중에는 불리지 않는다."""
        if domains is None:
            shutil.rmtree(self.profile_dir, ignore_errors=True)
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            return
        asyncio.run(self._clear_cookies(domains))

    async def _clear_cookies(self, domains: tuple[str, ...]) -> None:
        import re

        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(self.profile_dir), channel="chrome", headless=True
            )
            try:
                for domain in domains:
                    pattern = re.compile(rf"(^|\.){re.escape(domain.lstrip('.'))}$")
                    await context.clear_cookies(domain=pattern)
            finally:
                await context.close()
