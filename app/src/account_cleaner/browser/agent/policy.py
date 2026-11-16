from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

FINAL_ACTION_PATTERNS = (
    r"\bdelete\s+(my\s+)?account\b",
    r"\bclose\s+(my\s+)?account\b",
    r"\bpermanently\s+delete\b",
    r"계정\s*(영구\s*)?삭제",
    r"회원\s*탈퇴",
    r"탈퇴\s*(확정|완료|하기)",
)


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SafetyPolicy:
    allowed_domains: tuple[str, ...]
    auth_domains: tuple[str, ...] = ()

    @staticmethod
    def _normalize_host(host: str) -> str:
        return host.lower().rstrip(".")

    def is_url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = self._normalize_host(parsed.hostname or "")
        return any(
            host == self._normalize_host(domain)
            or host.endswith("." + self._normalize_host(domain))
            for domain in self.allowed_domains
        )

    def is_auth_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return False
        host = self._normalize_host(parsed.hostname or "")
        return any(
            host == self._normalize_host(domain)
            or host.endswith("." + self._normalize_host(domain))
            for domain in self.auth_domains
        )

    def require_allowed_url(self, url: str) -> None:
        if not self.is_url_allowed(url):
            raise PolicyViolation(f"허용되지 않은 도메인 이동 차단: {url}")

    def is_final_action(self, text: str) -> bool:
        normalized = " ".join(text.casefold().split())
        return any(
            re.search(pattern, normalized, re.IGNORECASE) for pattern in FINAL_ACTION_PATTERNS
        )

    def require_safe_click(self, selector: str, accessible_text: str = "") -> None:
        candidate = f"{selector} {accessible_text}"
        if self.is_final_action(candidate):
            raise PolicyViolation("최종 탈퇴 동작은 에이전트가 실행할 수 없습니다")

    def require_safe_menu_click(self, selector: str, accessible_text: str, is_link: bool) -> None:
        """플레이북이 메뉴로 표시한 클릭. 링크면 최종 문구여도 허용, 링크가 아니면 일반 클릭과 같다."""
        if not is_link:
            self.require_safe_click(selector, accessible_text)
