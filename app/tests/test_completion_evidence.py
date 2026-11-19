from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.classifier.completion import find_completion
from account_cleaner.contracts import ParsedMail

START = datetime(2026, 1, 1, tzinfo=UTC)


def mail(body, domain="demo.example", date=None, subject="탈퇴 안내", key="new"):
    return ParsedMail(
        key, f"notice@{domain}", domain, subject, date or START + timedelta(seconds=2), body
    )


@pytest.mark.parametrize(
    "text",
    [
        "회원 탈퇴 처리가 완료되었습니다.",
        "회원탈퇴가 완료되었습니다.",
        "계정이 삭제되었습니다.",
        "고객님의 계정이 안전하게 파기되었습니다.",
        "회원님의 탈퇴가 정상적으로 처리되었습니다.",
        "계정 삭제가 완료됐어요.",
        "탈퇴안내 고객님 귀하 귀사의 서비스 사용이 해지되었습니다.",
        "Your account has been permanently deleted.",
        "This email confirms that your Devhub account was deleted.",
        "We've closed your account. Your profile is no longer visible.",
    ],
)
def test_새로운_동일서비스의_명시적_탈퇴완료를_근거로_반환한다(text):
    result = find_completion([mail(text)], "demo.example", START, set())
    assert result is not None
    assert result.mail_id == "new" and result.statement


@pytest.mark.parametrize(
    "text",
    [
        "회원 탈퇴 요청이 접수되었습니다.",
        "계정은 다음 달 삭제될 예정입니다.",
        "회원 탈퇴가 완료되면 다시 가입할 수 있습니다.",
        "회원 탈퇴가 완료되지 않았습니다.",
        "구독 해지가 완료되었습니다.",
        "개인정보처리방침 안내입니다.",
        "이모티콘 플러스가 해지되었습니다. 해지 완료되었습니다.",
        "회원 탈퇴 신청에 따라 30일 후 계정이 삭제됩니다.",
        "Your account will be permanently deleted in 30 days.",
        "We received your account deletion request.",
        "Your subscription has been cancelled. Your account remains active.",
    ],
)
def test_요청_예정_조건문_구독해지는_완료로_처리하지않는다(text):
    assert find_completion([mail(text)], "demo.example", START, set()) is None


def test_과거메일_알려진메일_다른서비스_전달메일을_제외한다():
    body = "계정이 삭제되었습니다."
    assert (
        find_completion([mail(body, date=START - timedelta(days=1))], "demo.example", START, set())
        is None
    )
    assert find_completion([mail(body)], "demo.example", START, {"new"}) is None
    assert (
        find_completion([mail(body, domain="other.example")], "demo.example", START, set()) is None
    )
    assert (
        find_completion([mail(body, subject="Fwd: 탈퇴 완료")], "demo.example", START, set())
        is None
    )
    assert (
        find_completion(
            [mail("안내입니다.\n> 계정이 삭제되었습니다.")], "demo.example", START, set()
        )
        is None
    )


def test_시작시각은_시간대가_필요하다():
    with pytest.raises(ValueError):
        find_completion([], "demo.example", datetime(2026, 1, 1), set())
