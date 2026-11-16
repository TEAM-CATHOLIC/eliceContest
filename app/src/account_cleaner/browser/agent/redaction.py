from __future__ import annotations

import re

EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]{1,64})@([\w.-]+\.[A-Za-z]{2,})")
OTP = re.compile(r"(?<!\d)\d{6}(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")


def redact_sensitive(value: str) -> str:
    value = EMAIL.sub("[EMAIL]", value)
    value = CARD.sub("[CARD]", value)
    value = OTP.sub("[OTP]", value)
    return value
