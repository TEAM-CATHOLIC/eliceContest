from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit


class LocatorLike(Protocol):
    async def count(self) -> int: ...


class PageForDetection(Protocol):
    def locator(self, selector: str) -> LocatorLike: ...


@dataclass(frozen=True)
class HandoffMatch:
    reason: str
    selector: str


HANDOFF_RULES = (
    ("password", "input[type='password']:visible"),
    ("otp_or_2fa", "input[autocomplete='one-time-code']:visible"),
    (
        "captcha",
        "iframe[src*='captcha']:visible, [class*='captcha' i]:visible, [id*='captcha' i]:visible",
    ),
    ("identity_verification", "text=/본인.?인증|verify your identity|identity verification/i"),
    ("payment", "input[autocomplete='cc-number']:visible, iframe[src*='payment']:visible"),
)

LOGIN_EMAIL_SELECTOR = "input[type='email']:visible, input[autocomplete='username']:visible"


async def detect_handoff(page: PageForDetection) -> HandoffMatch | None:
    # Email-first login flows may not show a password field until the next page.
    # Limit this to explicit login routes so newsletter forms do not cause handoff.
    url = getattr(page, "url", "")
    login_path = isinstance(url, str) and urlsplit(url).path.rstrip("/").split("/")[-1].lower() in {
        "login",
        "signin",
        "sign-in",
    }
    if login_path and await page.locator(LOGIN_EMAIL_SELECTOR).count() > 0:
        return HandoffMatch(reason="password", selector=LOGIN_EMAIL_SELECTOR)
    for reason, selector in HANDOFF_RULES:
        if await page.locator(selector).count() > 0:
            return HandoffMatch(reason=reason, selector=selector)
    return None
