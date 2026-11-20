"""Hand-written phishing signals. Not learned; a mail is flagged on one strong or two weak signals.

Phishing that imitates account notices (mailbox expiry, password "keep" links, fake parcel or
payment problems) must not become account evidence or deletion evidence.
"""

import re

_SIGNALS = {
    # Strong: legitimate services do not ask for these.
    "credential_request": r"(?:비밀번호|암호|카드\s*번호|계좌\s*번호|주민등록번호|password|card number)"
    r"[^.\n]{0,40}(?:다시\s*입력|회신|re-?enter|reply)|re-?enter\s+your\s+(?:card|password)"
    r"|update your card",
    "keep_password": r"(?:동일한|같은|현재|기존)\s*(?:비밀번호|암호)[^.\n]{0,15}"
    r"(?:유지|계속\s*사용|로\s*계속)|keep\s+(?:your\s+)?(?:current|same)\s+password",
    "mailbox_quota": r"용량\s*(?:초과|부족)|할당량|storage full|almost full|\d+\s*%\s*full|mail\s*quota"
    r"|(?:대기|보류)\s*중인\s*(?:메일|메시지|이메일)|보류된\s*메시지"
    r"|(?:pending|suspended incoming)\s+messages|전달되지\s*(?:않은|못한)\s*(?:메일|메시지)\s*\d"
    r"|\d+\s*(?:건|개|통)의?\s*(?:메일|메시지)[^.\n]{0,20}(?:보관|대기|반송|전달되지)",
    "prize": r"당첨[^.\n]{0,30}(?:수령|회신)|보상금을\s*받으셨|compensation money"
    r"|funds left behind|late relative",
    # Weak: each appears in real notices too, so two are needed.
    "password_expiry": r"(?:비밀번호|암호|password)[^.\n]{0,25}(?:만료|expire)",
    "mailbox": r"사서함|메일함|이메일\s*계정|메일\s*계정|email account|your mailbox",
    "deadline_threat": r"(?:정지|중단|삭제|차단|종료|폐쇄|제한|비활성화|suspend|terminat|deactivat|delet)"
    r"[\s\S]{0,80}(?:\d+\s*시간|즉시|\d+\s*hours|immediately)"
    r"|(?:\d+\s*시간|\d+\s*hours)\s*(?:이내|안에|내|within)?[\s\S]{0,80}"
    r"(?:정지|중단|삭제|차단|종료|suspend|terminat|delet)"
    r"|인증\s*마감|자동\s*삭제될\s*수|계정\s*이용에\s*차질|will be (?:deactivated|suspended|lost)",
    "urgent_action": r"(?:지금|즉시|아래|여기)[^.\n]{0,20}(?:인증|확인|검증|업데이트)[^.\n]{0,10}"
    r"(?:하십시오|하세요|해\s*주십시오|해\s*주세요|!)|지금\s*(?:업데이트|계정\s*보안)"
    r"|인증\s*다시\s*진행|계정\s*확인하기|(?:verify|validate)\s+(?:now|your\s+"
    r"(?:email|identity|account|mailbox))|click here to|re-?verif|재검증|재확인하",
    "parcel": r"(?:택배|배송|DHL|FedEx|UPS)[\s\S]{0,80}(?:주소|정보|서류)[\s\S]{0,30}"
    r"(?:수정|불명|확인할\s*수\s*없|다시\s*한번\s*확인)",
}
_STRONG = frozenset({"credential_request", "keep_password", "mailbox_quota", "prize"})
_PATTERNS = {name: re.compile(p, re.IGNORECASE) for name, p in _SIGNALS.items()}
_ALERT_SUBJECT = re.compile(
    r"보안\s*경고|중요\s*공지|긴급|경고|최종\s*안내|마지막\s*경고|URGENT|ACTION REQUIRED|final notice"
    r"|security alert|계정\s*(?:정지|종료|비활성화)|인식하지\s*못한|승인되지\s*않은",
    re.IGNORECASE,
)


def phishing_signals(subject: str, body: str) -> set[str]:
    text = subject + "\n" + body[:1500]
    found = {name for name, pattern in _PATTERNS.items() if pattern.search(text)}
    if _ALERT_SUBJECT.search(subject):
        found.add("alert_subject")
    return found


def looks_like_phishing(subject: str, body: str) -> bool:
    found = phishing_signals(subject, body)
    return bool(found & _STRONG) or len(found) >= 2
