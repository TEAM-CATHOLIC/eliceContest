"""플레이북이 없는 사이트를 위한 제한된 범용 탐색 루프."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .handoff import detect_handoff
from .llm import ElementCandidate, NextClick, NextClickSelector
from .models import AgentResult, AgentStatus
from .policy import SafetyPolicy
from .redaction import redact_for_llm

log = logging.getLogger(__name__)

COMMON_AUTH_DOMAINS = (
    "accounts.google.com",
    "appleid.apple.com",
    "accounts.kakao.com",
    "kauth.kakao.com",
    "nid.naver.com",
    "facebook.com",
    "login.microsoftonline.com",
)
"""처음 보는 사이트의 소셜 로그인 도메인. 여기서는 조작하지 않고 사용자에게 넘긴다 (#79)."""
LLM_FAILED_MESSAGE = "AI 응답을 받지 못했어요. 인터넷 연결과 Anthropic API 키를 확인해 주세요."

LOAD_WAIT_MS = 15_000
"""느린 사이트에서 링크·버튼이 보일 때까지 기다리는 최대 시간"""
POLL_MS = 1_000
MAX_CANDIDATES = 60
MAX_SCAN = 400
"""화면의 링크·버튼을 이만큼까지 훑고, 계정·설정·로그인 관련을 앞에 두어 60개를 고른다"""
PRIORITY = re.compile(
    r"계정|설정|마이|내\s*정보|회원\s*정보|프로필|탈퇴|개인\s*정보|보안|로그인|"
    r"account|setting|profile|my\s*page|privacy|security|log\s*in|sign\s*in",
    re.IGNORECASE,
)
MENU = re.compile(
    r"메뉴|더\s*보기|프로필|내\s*정보|마이|계정|menu|more|profile|avatar|account|my\s*page|user",
    re.IGNORECASE,
)
"""계정 항목이 숨어 있을 수 있는 메뉴·프로필 버튼"""
MAX_MENU_TRIES = 2
LOGIN = re.compile(r"로그인|log\s*in|sign\s*in", re.IGNORECASE)
"""로그아웃 상태의 로그인 진입점"""
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
  // 글자가 없는 아이콘 버튼(프로필 사진·햄버거 메뉴)은 title·alt·클래스 이름으로 무엇인지 알린다
  const img = element.querySelector('img[alt]');
  const svgTitle = element.querySelector('svg title');
  const names = [element.id, String(element.className && element.className.baseVal !== undefined
    ? element.className.baseVal : element.className || ''), element.getAttribute('data-testid') || '']
    .join(' ').toLowerCase();
  const hint = (names.match(/profile|avatar|user|account|mypage|my-page|setting|menu|gnb|hamburger|more/g) || [])
    .filter((v, i, a) => a.indexOf(v) === i).slice(0, 3).join(' ');
  const label = element.getAttribute('aria-label') || element.getAttribute('title')
    || (img && img.alt) || (svgTitle && svgTitle.textContent) || '';
  return {
    text: (element.innerText || element.textContent || '').trim(),
    ariaLabel: label || (hint ? `[아이콘: ${hint}]` : ''),
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


ALL_INFO_SCRIPT = "(elements, limit) => elements.slice(0, limit).map(" + ELEMENT_INFO_SCRIPT + ")"


async def _raw_infos(collection: Any, count: int) -> list[tuple[int, dict]]:
    """한 번의 호출로 모든 요소 정보를 읽는다 (요소마다 부르면 400개에 10초 이상 걸림)."""
    evaluate_all = getattr(collection, "evaluate_all", None)
    if evaluate_all is not None:
        try:
            raws = await evaluate_all(ALL_INFO_SCRIPT, count)
            return list(enumerate(raws))
        except Exception:  # 실패하면 하나씩 읽는다
            log.debug("evaluate_all 실패, 하나씩 읽음", exc_info=True)
    infos: list[tuple[int, dict]] = []
    for index in range(count):
        try:
            raw = await collection.nth(index).evaluate(ELEMENT_INFO_SCRIPT)
        except Exception:  # noqa: BLE001, S112 — 추출 중 DOM에서 사라진 요소는 건너뛴다
            continue
        infos.append((index, raw))
    return infos


def _priority(raw: dict) -> int:
    text = f"{raw.get('text', '')} {raw.get('ariaLabel', '')} {raw.get('hrefPath', '')}"
    return 0 if PRIORITY.search(text) else 1


async def extract_elements(
    page: Any, private_values: tuple[str, ...] = ()
) -> list[ExtractedElement]:
    """보이는 링크·버튼의 최소 메타데이터만 추출한다. 입력값과 HTML은 읽지 않는다.

    첫 화면은 강의·상품 링크가 수백 개라 앞 60개만 자르면 계정·로그인 메뉴가 빠진다 (#79).
    최대 400개를 훑고 계정·설정·로그인 관련 요소를 앞에 둔 뒤(같은 묶음 안은 화면 순서) 60개를 고른다.
    """
    collection = page.locator(INTERACTIVE_SELECTOR)
    infos = await _raw_infos(collection, min(await collection.count(), MAX_SCAN))
    infos.sort(key=lambda item: _priority(item[1]))  # 안정 정렬: 같은 묶음은 화면 순서 유지
    extracted: list[ExtractedElement] = []
    for index, raw in infos:
        if len(extracted) >= MAX_CANDIDATES:
            break
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
        extracted.append(
            ExtractedElement(candidate, collection.nth(index), str(raw.get("href", "")))
        )
    return extracted


async def _settle(page: Any) -> None:
    """페이지 로드(load 이벤트)를 잠깐 기다린다. 광고·분석 스크립트로 늦어지면 그냥 넘어간다."""
    wait_load = getattr(page, "wait_for_load_state", None)
    if wait_load is None:
        return
    try:
        await wait_load("load", timeout=10_000)
    except Exception:  # noqa: BLE001, S110 — 시간 초과여도 지금 화면으로 계속한다
        pass


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
        self._waited = False
        self.login_tried = False
        self.menu_tried: set[str] = set()
        """로그인 진입점을 이미 한 번 눌렀다 (두 번째부터는 누르지 않고 사용자에게 넘긴다)"""
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
            await _settle(page)
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

            elements = await self._elements_when_ready(page, attempt, current_url)
            if self._waited:
                # 늦게 뜬 화면이 로그인 화면일 수 있다
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
                return self._failed(
                    attempt,
                    current_url,
                    "15초를 기다려도 누를 수 있는 링크나 버튼이 보이지 않습니다",
                )

            parsed = urlparse(current_url)
            try:
                decision = await self.selector.choose(
                    domain=parsed.hostname or "",
                    path=redact_for_llm(parsed.path or "/", self.private_values)[:160],
                    candidates=tuple(item.candidate for item in elements),
                    previous_actions=tuple(self.history),
                )
            except Exception:  # 네트워크·키·응답 형식 오류는 모두 안내 후 종료 (#79)
                log.warning("범용 안내 LLM 호출 실패", exc_info=True)
                return self._failed(attempt, current_url, LLM_FAILED_MESSAGE)
            by_id = {item.candidate.id: item for item in elements}
            chosen = by_id.get(decision.choice) if decision.choice is not None else None
            if chosen is None:
                fallback = self._fallback(elements, attempt, current_url, decision)
                if isinstance(fallback, AgentResult):
                    return fallback
                chosen, decision = fallback
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

    async def _elements_when_ready(
        self, page: Any, attempt: int, url: str
    ) -> list[ExtractedElement]:
        """링크·버튼이 하나도 안 보이면(로딩 화면, 늦게 그리는 사이트) 최대 15초 다시 본다 (#79)."""
        self._waited = False
        elements = await extract_elements(page, self.private_values)
        wait = getattr(page, "wait_for_timeout", None)
        waited = 0
        while not elements and wait is not None and waited < LOAD_WAIT_MS:
            if not self._waited:
                self._waited = True
                await self.emit(
                    {
                        "status": "running",
                        "step": attempt,
                        "reason": "화면이 뜨기를 기다리는 중입니다",
                        "url": url,
                    }
                )
            await wait(POLL_MS)
            waited += POLL_MS
            elements = await extract_elements(page, self.private_values)
        return elements

    def _fallback(
        self, elements: list[ExtractedElement], attempt: int, url: str, decision: NextClick
    ) -> AgentResult | tuple[ExtractedElement, NextClick]:
        """AI가 아무것도 고르지 못했을 때 (#79).

        1. 로그아웃 상태(로그인 버튼이 보임): 로그인 화면으로 한 번 데려가고, 그다음엔 사람을 기다린다.
        2. 로그인 상태: 계정 항목이 숨어 있을 수 있는 메뉴·프로필 버튼을 최대 2개까지 열어 보고 다시 묻는다.
        3. 둘 다 아니면 실패.
        """
        login = self._login_entry(elements)
        if login is not None:
            if self.login_tried:
                return AgentResult(
                    AgentStatus.WAITING_FOR_USER,
                    self.service_id,
                    "로그인이 필요해 보입니다",
                    attempt,
                    url,
                    "password",
                )
            self.login_tried = True
            return login, NextClick(
                login.candidate.id, "로그인이 필요해 로그인 화면으로 이동합니다"
            )
        menu = self._menu_entry(elements)
        if menu is not None:
            self.menu_tried.add(menu.fingerprint)
            return menu, NextClick(menu.candidate.id, "계정 메뉴를 찾으려고 메뉴를 열어 봅니다")
        return self._failed(attempt, url, decision.reason or "다음 동작을 찾지 못했습니다")

    def _menu_entry(self, elements: list[ExtractedElement]) -> ExtractedElement | None:
        if len(self.menu_tried) >= MAX_MENU_TRIES:
            return None
        return next(
            (
                item
                for item in elements
                if item.fingerprint not in self.menu_tried
                and MENU.search(f"{item.candidate.text} {item.candidate.aria_label}")
                and not LOGIN.search(item.candidate.text)
                and "로그아웃" not in item.candidate.text
                and "log out" not in item.candidate.text.casefold()
            ),
            None,
        )

    @staticmethod
    def _login_entry(elements: list[ExtractedElement]) -> ExtractedElement | None:
        return next(
            (
                item
                for item in elements
                if LOGIN.search(f"{item.candidate.text} {item.candidate.aria_label}")
                and "로그아웃" not in item.candidate.text
                and "log out" not in item.candidate.text.casefold()
            ),
            None,
        )

    def _failed(self, step: int, url: str, reason: str) -> AgentResult:
        return AgentResult(
            AgentStatus.FAILED,
            self.service_id,
            reason,
            step,
            url,
            "generic_navigation",
        )
