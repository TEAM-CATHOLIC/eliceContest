"""플레이북이 없는 사이트를 위한 제한된 범용 탐색 루프."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .handoff import detect_handoff
from .llm import ElementCandidate, NextClickSelector
from .models import AgentResult, AgentStatus
from .policy import SafetyPolicy
from .redaction import redact_for_llm

MAX_CANDIDATES = 60
MAX_STEPS = 12
MAX_TEXT = 80
INTERACTIVE_SELECTOR = "a:visible, button:visible, [role=link]:visible, [role=button]:visible"
FORBIDDEN_ACTION = re.compile(
    r"\b(pay\s+now|buy\s+now|purchase|subscribe|upload)\b|결제\s*(하기|진행)|구매\s*하기|구독\s*하기|업로드",
    re.IGNORECASE,
)

ELEMENT_INFO_SCRIPT = """element => {
  const href = element.href || '';
  let hrefPath = '';
  if (href) {
    try {
      const url = new URL(href, location.href);
      hrefPath = url.origin === location.origin ? url.pathname + url.search : '';
    } catch (_) {}
  }
  return {
    text: (element.innerText || element.textContent || '').trim(),
    ariaLabel: element.getAttribute('aria-label') || '',
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute('role') || '',
    href: href,
    hrefPath: hrefPath
  };
}"""


@dataclass(slots=True)
class ExtractedElement:
    candidate: ElementCandidate
    locator: Any
    href: str

    @property
    def fingerprint(self) -> str:
        item = self.candidate
        return f"{item.tag}|{item.role}|{item.text}|{item.aria_label}|{item.href_path}"


async def extract_elements(
    page: Any, private_values: tuple[str, ...] = ()
) -> list[ExtractedElement]:
    """보이는 링크·버튼의 최소 메타데이터만 추출한다. 입력값과 HTML은 읽지 않는다."""
    collection = page.locator(INTERACTIVE_SELECTOR)
    count = min(await collection.count(), MAX_CANDIDATES)
    extracted: list[ExtractedElement] = []
    for index in range(count):
        locator = collection.nth(index)
        try:
            raw = await locator.evaluate(ELEMENT_INFO_SCRIPT)
        except Exception:  # noqa: BLE001, S112 — 추출 중 DOM에서 사라진 요소는 건너뛴다
            continue
        text = redact_for_llm(str(raw.get("text", "")), private_values)[:MAX_TEXT]
        aria = redact_for_llm(str(raw.get("ariaLabel", "")), private_values)[:MAX_TEXT]
        if not text and not aria:
            continue
        candidate = ElementCandidate(
            id=len(extracted),
            text=text,
            aria_label=aria,
            tag=str(raw.get("tag", "")),
            role=str(raw.get("role", "")),
            href_path=redact_for_llm(str(raw.get("hrefPath", "")), private_values)[:160],
        )
        extracted.append(ExtractedElement(candidate, locator, str(raw.get("href", ""))))
    return extracted


class GenericNavigator:
    def __init__(
        self,
        selector: NextClickSelector,
        policy: SafetyPolicy,
        service_id: str,
        emit,
        private_values: tuple[str, ...] = (),
    ) -> None:
        self.selector = selector
        self.policy = policy
        self.service_id = service_id
        self.emit = emit
        self.private_values = private_values
        self.visited: set[str] = set()
        self.history: list[str] = []

    async def run(self, page: Any, start_step: int = 0) -> AgentResult:
        for attempt in range(start_step, MAX_STEPS):
            current_url = str(page.url() if callable(page.url) else page.url)
            if self.policy.is_auth_url(current_url):
                return AgentResult(
                    AgentStatus.WAITING_FOR_USER,
                    self.service_id,
                    "외부 로그인은 사용자가 직접 완료해야 합니다",
                    attempt,
                    current_url,
                    "external_auth",
                )
            self.policy.require_allowed_url(current_url)
            handoff = await detect_handoff(page)
            if handoff:
                return AgentResult(
                    AgentStatus.WAITING_FOR_USER,
                    self.service_id,
                    "사용자 인증 또는 입력이 필요합니다",
                    attempt,
                    current_url,
                    handoff.reason,
                )

            elements = await extract_elements(page, self.private_values)
            final = next(
                (
                    item
                    for item in elements
                    if self.policy.is_final_action(
                        f"{item.candidate.text} {item.candidate.aria_label}"
                    )
                    and item.candidate.tag != "a"
                    and item.candidate.role != "link"
                ),
                None,
            )
            if final:
                await self.emit(
                    {"status": "reached_withdrawal", "step": attempt, "url": current_url}
                )
                return AgentResult(
                    AgentStatus.REACHED_WITHDRAWAL,
                    self.service_id,
                    "최종 탈퇴 버튼이 보이는 화면에 도달했습니다",
                    attempt + 1,
                    current_url,
                )
            if not elements:
                return self._failed(attempt, current_url, "선택할 수 있는 링크나 버튼이 없습니다")

            parsed = urlparse(current_url)
            decision = await self.selector.choose(
                domain=parsed.hostname or "",
                path=redact_for_llm(parsed.path or "/", self.private_values)[:160],
                candidates=tuple(item.candidate for item in elements),
                previous_actions=tuple(self.history),
            )
            by_id = {item.candidate.id: item for item in elements}
            chosen = by_id.get(decision.choice) if decision.choice is not None else None
            if chosen is None:
                return self._failed(
                    attempt, current_url, decision.reason or "다음 동작을 찾지 못했습니다"
                )
            text = f"{chosen.candidate.text} {chosen.candidate.aria_label}".strip()
            if FORBIDDEN_ACTION.search(text):
                return self._failed(
                    attempt, current_url, "결제·구매·구독·업로드 동작을 차단했습니다"
                )
            is_link = chosen.candidate.tag == "a" or chosen.candidate.role == "link"
            if is_link:
                self.policy.require_safe_menu_click("generic", text, True)
            else:
                self.policy.require_safe_click("generic", text)
            if chosen.href and not (
                self.policy.is_url_allowed(chosen.href) or self.policy.is_auth_url(chosen.href)
            ):
                return self._failed(
                    attempt, current_url, "허용되지 않은 도메인 링크를 차단했습니다"
                )
            fingerprint = f"{current_url}|{chosen.fingerprint}"
            if fingerprint in self.visited:
                return self._failed(attempt, current_url, "같은 동작이 반복되어 중단했습니다")
            self.visited.add(fingerprint)
            self.history.append(
                f"{chosen.candidate.text or chosen.candidate.aria_label}: {decision.reason}"
            )
            await self.emit(
                {
                    "status": "running",
                    "step": attempt,
                    "action": "llm_click",
                    "reason": decision.reason,
                    "url": current_url,
                }
            )
            await chosen.locator.click()
            wait = getattr(page, "wait_for_timeout", None)
            if wait is not None:
                await wait(350)

        current_url = str(page.url() if callable(page.url) else page.url)
        return self._failed(MAX_STEPS, current_url, "최대 탐색 단계를 초과했습니다")

    def _failed(self, step: int, url: str, reason: str) -> AgentResult:
        return AgentResult(
            AgentStatus.FAILED,
            self.service_id,
            reason,
            step,
            url,
            "generic_navigation",
        )
