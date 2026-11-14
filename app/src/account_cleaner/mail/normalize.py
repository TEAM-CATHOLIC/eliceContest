"""메일 원문 → `ParsedMail`. 파일·Gmail·네이버가 모두 이 함수를 거친다.

한국 메일에서 흔한 문제를 여기서 처리한다.
- `euc-kr`이라고 적혀 있어도 실제로는 `cp949`(확장 완성형)인 경우가 많다 → 처음부터 `cp949`로 읽는다.
- 인코딩 표시가 없거나 틀린 경우 → UTF-8, cp949 순서로 시도하고 마지막에는 깨진 글자만 대체한다.
- 헤더에 인코딩 없이 8비트 글자가 그대로 들어온 경우 → 같은 규칙으로 해석한다.
"""

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from email import message_from_bytes
from email.header import Header, decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from account_cleaner.contracts import ParsedMail
from account_cleaner.mail.html_text import html_to_text

_KOREAN_ALIASES = {
    "euc-kr", "euc_kr", "euckr", "ks_c_5601-1987", "ks_c_5601", "ksc5601", "ks_c_5601_1987",
    "x-windows-949", "windows-949", "ms949", "uhc", "cp949",
}  # fmt: skip
_FALLBACKS = ("utf-8", "cp949")
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u034f\u00ad]")
_BLANK_LINES = re.compile(r"\n{3,}")
_HORIZONTAL_SPACE = re.compile(r"[ \t\f\v\xa0]+")
_RECEIVED_DATE = re.compile(r";\s*([^;]+)$")
PLAIN_ENOUGH = 0.5
"""평문 파트가 HTML 글자 수의 이 비율 이상이면 평문을 쓴다 ("HTML로 보세요" 같은 짧은 평문 대비)."""


class MailParseError(ValueError):
    """이 메일은 건너뛴다. 메시지는 기록용이며 메일 내용을 담지 않는다."""


def decode_bytes(data: bytes, charset: str | None) -> str:
    """선언된 charset → UTF-8 → cp949 순서로 시도하고, 다 실패하면 깨진 글자만 대체한다."""
    declared = (charset or "").strip().strip('"').lower()
    if declared in _KOREAN_ALIASES:
        declared = "cp949"
    for candidate in (declared, *_FALLBACKS):
        if not candidate:
            continue
        try:
            return data.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def decode_header_value(value: str | Header | None) -> str:
    """RFC 2047 인코딩 헤더(=?utf-8?B?...?=)와 인코딩 없는 8비트 헤더를 모두 문자열로.

    8비트 바이트가 섞인 헤더는 `msg.get()`이 `Header`(charset unknown-8bit)로 돌려준다.
    `str()`로 바꾸면 글자가 깨지므로 그대로 `decode_header`에 넘긴다.
    """
    if value is None:
        return ""
    pieces = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            pieces.append(decode_bytes(part, charset))
        else:
            pieces.append(part)
    text = "".join(pieces)
    if any("\udc80" <= ch <= "\udcff" for ch in text):
        # 파서가 해석 못 한 8비트 바이트(surrogateescape)를 원래 바이트로 되돌려 다시 해석
        text = decode_bytes(text.encode("utf-8", "surrogateescape"), None)
    return " ".join(text.split())


def clean_text(text: str) -> str:
    """NFC 정규화, 보이지 않는 문자 제거, 줄 끝 공백·빈 줄 정리."""
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = (_HORIZONTAL_SPACE.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _is_attachment(part: Message) -> bool:
    disposition = (part.get("Content-Disposition") or "").split(";")[0].strip().lower()
    return disposition == "attachment" or part.get_filename() is not None


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    return decode_bytes(payload, part.get_content_charset())


def extract_body(msg: Message) -> str:
    """첨부를 뺀 본문 전체를 평문으로. 평문 파트를 우선하고, 없거나 너무 짧으면 HTML을 쓴다."""
    plain, html = [], []
    for part in msg.walk():
        if part.is_multipart() or _is_attachment(part):
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain.append(_part_text(part))
        elif content_type == "text/html":
            html.append(html_to_text(_part_text(part)))
    plain_text = clean_text("\n\n".join(plain))
    html_text = clean_text("\n\n".join(html))
    if plain_text and len(plain_text) >= PLAIN_ENOUGH * len(html_text):
        return plain_text
    return html_text or plain_text


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def extract_date(msg: Message) -> datetime:
    """Date 헤더, 없거나 잘못됐으면 가장 먼저 받은 서버의 Received 시각."""
    date = _parse_date(decode_header_value(msg.get("Date")))
    if date:
        return date
    for received in reversed(msg.get_all("Received") or []):
        match = _RECEIVED_DATE.search(" ".join(str(received).split()))
        if match and (date := _parse_date(match.group(1))):
            return date
    raise MailParseError("날짜 없음")


def extract_sender(msg: Message) -> tuple[str, str]:
    """(발신 주소, 소문자 도메인). 주소의 도메인 부분은 소문자로 맞춘다."""
    _, address = parseaddr(decode_header_value(msg.get("From")))
    local, at, domain = address.strip().rpartition("@")
    domain = domain.strip().strip(".").lower()
    if not at or not local or "." not in domain or " " in domain:
        raise MailParseError("발신 주소 없음")
    return f"{local}@{domain}", domain


def message_id(msg: Message, data: bytes) -> str:
    """Message-ID, 없으면 원문 해시."""
    value = decode_header_value(msg.get("Message-ID"))
    if value:
        return value
    return "sha256:" + hashlib.sha256(data).hexdigest()[:32]


def parse_mail(data: bytes) -> ParsedMail:
    """메일 원문 한 통을 `ParsedMail`로. 쓸 수 없는 메일이면 `MailParseError`."""
    msg = message_from_bytes(data)
    sender, domain = extract_sender(msg)
    return ParsedMail(
        id=message_id(msg, data),
        sender=sender,
        sender_domain=domain,
        subject=decode_header_value(msg.get("Subject")),
        date=extract_date(msg),
        body_text=extract_body(msg),
    )
