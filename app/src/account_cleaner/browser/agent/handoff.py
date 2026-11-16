from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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


async def detect_handoff(page: PageForDetection) -> HandoffMatch | None:
    for reason, selector in HANDOFF_RULES:
        if await page.locator(selector).count() > 0:
            return HandoffMatch(reason=reason, selector=selector)
    return None
