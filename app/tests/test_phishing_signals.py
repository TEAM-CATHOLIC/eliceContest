from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.classifier.completion import find_completion
from account_cleaner.classifier.model import explicit_rule, stage_hint
from account_cleaner.classifier.phishing import looks_like_phishing
from account_cleaner.contracts import ParsedMail


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        (
            "비밀번호 재설정이 진행 중입니다",
            "비밀번호가 곧 만료됩니다. 동일한 비밀번호를 계속 사용하려면 아래를 클릭하세요.",
        ),
        ("메일함 용량 초과 안내", "메일함 용량이 99% 찼습니다. 아래 링크에서 로그인하세요."),
        ("결제 실패", "서비스 중단을 막으려면 카드 번호와 비밀번호를 다시 입력해 주세요."),
        (
            "[긴급] 계정이 정지되었습니다",
            "24시간 안에 본인 확인을 하지 않으면 계정이 영구 삭제됩니다.",
        ),
        ("Final notice", "Your password expires today. Keep your current password using the link."),
        ("Payment declined", "Re-enter your card number and password to avoid interruption."),
        (
            "이메일 계정 보안 경고",
            "이전 인증 경고 거부로 인해 계정이 삭제되었습니다. 24시간 후 삭제됩니다.",
        ),
    ],
)
def test_계정_알림을_흉내낸_피싱_문구를_찾는다(subject, body):
    assert looks_like_phishing(subject, body)


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        (
            "보안 알림",
            "Windows 기기에서 내 Google 계정에 새로 로그인했습니다. 본인이 아니라면 계정을 보호하세요.",
        ),
        (
            "비밀번호 변경완료",
            "고객님의 비밀번호가 변경되어 안내 드립니다. 변경 일시 2026-09-15 14:08.",
        ),
        ("이메일 주소를 인증하세요", "가입을 완료하려면 먼저 이메일 주소를 인증해야 합니다."),
        (
            "장기 미접속 회원정보 삭제 예정 안내",
            "1년 동안 접속하지 않은 회원님의 가입정보를 삭제하고 있습니다.",
        ),
        (
            "Undelivered Mail Returned to Sender",
            "Your message could not be delivered to the recipient's mailbox.",
        ),
        (
            "New sign-in to your OpenAI account",
            "We noticed a new sign-in. If this was you, no action is needed.",
        ),
    ],
)
def test_실제_서비스의_보안_알림과_인증_요청은_피싱으로_보지_않는다(subject, body):
    assert not looks_like_phishing(subject, body)


def test_피싱은_명시적_규칙보다_먼저_걸러져_탈퇴완료로도_쓰이지_않는다():
    # given
    subject, body = (
        "이메일 계정 보안 경고",
        "인증 경고 거부로 계정이 삭제되었습니다. 24시간 후 철거됩니다.",
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    mail = ParsedMail("p", "a@demo.example", "demo.example", subject, start + timedelta(1), body)
    # when / then
    assert stage_hint(subject, body) == "phishing_suspected"
    assert explicit_rule(subject, body) == (None, None)
    assert find_completion([mail], "demo.example", start, set()) is None
