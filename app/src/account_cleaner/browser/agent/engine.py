from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .generic import GenericNavigator
from .handoff import detect_handoff
from .llm import NextClickSelector
from .models import Action, AgentResult, AgentStatus, Playbook, Step
from .policy import PolicyViolation, SafetyPolicy
from .redaction import redact_sensitive

log = logging.getLogger(__name__)

IS_LINK_SCRIPT = "e => e.tagName === 'A' || e.getAttribute('role') === 'link'"
"""메뉴 클릭 단계의 요소가 링크인지 (최종 탈퇴는 보통 폼 제출 버튼이다)."""

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class BrowserAgent:
    def __init__(
        self,
        playbook: Playbook,
        on_event: EventHandler | None = None,
        next_click_selector: NextClickSelector | None = None,
        private_values: tuple[str, ...] = (),
    ):
        self.playbook = playbook
        self.policy = SafetyPolicy(playbook.allowed_domains, playbook.auth_domains)
        self.on_event = on_event
        self.next_click_selector = next_click_selector
        self.private_values = private_values
        self._generic: GenericNavigator | None = None

    async def _emit(self, event: dict[str, Any]) -> None:
        safe = {key: redact_sensitive(str(value)) for key, value in event.items()}
        if self.on_event:
            result = self.on_event(safe)
            if inspect.isawaitable(result):
                await result

    async def _current_url(self, page: Any) -> str:
        url = page.url
        return await url() if callable(url) else str(url)

    @staticmethod
    def _candidate_selectors(step: Step) -> tuple[str, ...]:
        return (step.value, *(f"text={text}" for text in step.fallback_texts))

    async def _click_locator(self, page: Any, step: Step) -> Any:
        candidates = self._candidate_selectors(step)
        for index, selector in enumerate(candidates):
            locator = page.locator(selector).first
            if await locator.count() > 0:
                if index:
                    await self._emit({"status": "fallback_used", "selector": selector})
                return locator
        return page.locator(step.value).first

    async def _wait_for_locator(self, page: Any, step: Step) -> Any:
        last_error: Exception | None = None
        candidates = self._candidate_selectors(step)
        for index, selector in enumerate(candidates):
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=6_000 if index == 0 else 3_000)
                if index:
                    await self._emit({"status": "fallback_used", "selector": selector})
                return locator
            except Exception as exc:  # noqa: BLE001 — 다음 후보 셀렉터를 시도한다
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("사용 가능한 셀렉터가 없습니다")

    async def run(self, page: Any, start_step: int = 0, navigate_entry: bool = True) -> AgentResult:
        current_step = start_step
        try:
            if navigate_entry:
                self.policy.require_allowed_url(self.playbook.entry_url)
                await page.goto(self.playbook.entry_url, wait_until="domcontentloaded")
            if not self.playbook.steps:
                if self.next_click_selector is None:
                    url = await self._current_url(page)
                    return AgentResult(
                        AgentStatus.FAILED,
                        self.playbook.service_id,
                        "범용 AI 안내를 사용하려면 Anthropic API 키가 필요합니다",
                        start_step,
                        url,
                        "missing_llm",
                    )
                if self._generic is None:
                    self._generic = GenericNavigator(
                        self.next_click_selector,
                        self.policy,
                        self.playbook.service_id,
                        self._emit,
                        self.private_values,
                    )
                return await self._generic.run(page, start_step)
            for index in range(start_step, len(self.playbook.steps)):
                current_step = index
                current_url = await self._current_url(page)
                if self.policy.is_auth_url(current_url):
                    await self._emit(
                        {
                            "status": "waiting_for_user",
                            "reason": "external_auth",
                            "url": current_url,
                        }
                    )
                    return AgentResult(
                        AgentStatus.WAITING_FOR_USER,
                        self.playbook.service_id,
                        "외부 로그인은 사용자가 직접 완료해야 합니다",
                        index,
                        current_url,
                        "external_auth",
                    )
                self.policy.require_allowed_url(current_url)
                handoff = await detect_handoff(page)
                if handoff:
                    await self._emit(
                        {"status": "waiting_for_user", "reason": handoff.reason, "url": current_url}
                    )
                    return AgentResult(
                        AgentStatus.WAITING_FOR_USER,
                        self.playbook.service_id,
                        "사용자 인증 또는 입력이 필요합니다",
                        index,
                        current_url,
                        handoff.reason,
                    )

                step = self.playbook.steps[index]
                await self._emit(
                    {"status": "running", "step": index, "action": step.action, "url": current_url}
                )
                if step.action == Action.NAVIGATE:
                    self.policy.require_allowed_url(step.value)
                    await page.goto(step.value, wait_until="domcontentloaded")
                elif step.action == Action.CLICK:
                    locator = await self._click_locator(page, step)
                    text = await locator.inner_text(timeout=1500)
                    if step.menu:
                        is_link = await locator.evaluate(IS_LINK_SCRIPT)
                        self.policy.require_safe_menu_click(step.value, text, bool(is_link))
                    else:
                        self.policy.require_safe_click(step.value, text)
                    await locator.click()
                elif step.action == Action.WAIT_FOR:
                    await self._wait_for_locator(page, step)
                elif step.action == Action.REACH_TARGET:
                    await self._wait_for_locator(page, step)
                    url = await self._current_url(page)
                    await self._emit({"status": "reached_withdrawal", "step": index, "url": url})
                    return AgentResult(
                        AgentStatus.REACHED_WITHDRAWAL,
                        self.playbook.service_id,
                        "탈퇴 직전 또는 계정 종료 안내 화면에 도달했습니다",
                        index + 1,
                        url,
                    )

                new_url = await self._current_url(page)
                if self.policy.is_auth_url(new_url):
                    await self._emit(
                        {"status": "waiting_for_user", "reason": "external_auth", "url": new_url}
                    )
                    return AgentResult(
                        AgentStatus.WAITING_FOR_USER,
                        self.playbook.service_id,
                        "외부 로그인은 사용자가 직접 완료해야 합니다",
                        index + 1,
                        new_url,
                        "external_auth",
                    )
                self.policy.require_allowed_url(new_url)

            return AgentResult(
                AgentStatus.REACHED_WITHDRAWAL,
                self.playbook.service_id,
                "플레이북을 완료했습니다",
                len(self.playbook.steps),
                await self._current_url(page),
            )
        except PolicyViolation as exc:
            url = await self._current_url(page)
            await self._emit({"status": "blocked", "reason": str(exc), "url": url})
            return AgentResult(
                AgentStatus.BLOCKED, self.playbook.service_id, str(exc), current_step, url, "policy"
            )
        except Exception as exc:
            url = await self._current_url(page)
            # Playwright 호출 기록(수십 줄)은 로그에만, 화면에는 첫 줄만
            log.warning("에이전트 실행 오류", exc_info=True)
            message = redact_sensitive(str(exc).strip().splitlines()[0] if str(exc).strip() else "")
            await self._emit({"status": "failed", "reason": message, "url": url})
            return AgentResult(
                AgentStatus.FAILED, self.playbook.service_id, message, current_step, url, "runtime"
            )
