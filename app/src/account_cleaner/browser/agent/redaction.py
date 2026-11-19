from __future__ import annotations

import re

EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]{1,64})@([\w.-]+\.[A-Za-z]{2,})")
OTP = re.compile(r"(?<!\d)\d{6}(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")
PHONE = re.compile(r"(?<!\d)(?:\+?82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)")


def redact_sensitive(value: str) -> str:
    value = EMAIL.sub("[EMAIL]", value)
    value = CARD.sub("[CARD]", value)
    value = OTP.sub("[OTP]", value)
    value = PHONE.sub("[PHONE]", value)
    return value


def redact_for_llm(value: str, private_values: tuple[str, ...] = ()) -> str:
    """기본 패턴과 앱이 알고 있는 사용자 이름·메일 문자열을 함께 가린다."""
    value = redact_sensitive(value)
    for private in sorted((v.strip() for v in private_values), key=len, reverse=True):
        if len(private) >= 2:
            value = re.sub(re.escape(private), "[PRIVATE]", value, flags=re.IGNORECASE)
    return " ".join(value.split())
