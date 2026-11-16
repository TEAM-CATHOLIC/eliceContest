"""브라우저 에이전트 안전 장치 테스트 (원본: 브라우저 담당 `08_실행및검증/tests/`).

정책(도메인·최종 버튼), 플레이북 사전 검사, 민감정보 가리기, 감사 로그, 성과 지표.
"""

import json

import pytest

from account_cleaner.browser.agent.audit import AuditLog, verify_audit_log
from account_cleaner.browser.agent.metrics import SessionMetrics
from account_cleaner.browser.agent.models import (
    Action,
    AgentResult,
    AgentStatus,
    Playbook,
    Step,
)
from account_cleaner.browser.agent.policy import PolicyViolation, SafetyPolicy
from account_cleaner.browser.agent.redaction import redact_sensitive
from account_cleaner.browser.agent.validation import validate_playbook


@pytest.fixture
def policy():
    return SafetyPolicy(("example.com",))


# --- 정책 ---


def test_허용_도메인과_그_하위_도메인은_허용한다(policy):
    # given / when / then
    assert policy.is_url_allowed("https://example.com/settings")
    assert policy.is_url_allowed("https://login.example.com/")


def test_허용_도메인을_흉내_낸_도메인은_거부한다(policy):
    # given / when / then
    assert not policy.is_url_allowed("https://example.com.evil.test/")


def test_http_https가_아닌_주소는_거부한다(policy):
    # given / when / then
    assert not policy.is_url_allowed("file:///etc/passwd")


def test_서비스_도메인도_http는_거부하고_로컬_데모_주소만_예외로_허용한다(monkeypatch):
    # given
    monkeypatch.delenv("ACCOUNT_CLEANER_ALLOW_LOCAL_HTTP", raising=False)
    policy = SafetyPolicy(("example.com", "127.0.0.1"))

    # when / then
    assert not policy.is_url_allowed("http://example.com/settings")
    assert policy.is_url_allowed("http://127.0.0.1:8765/settings")
    monkeypatch.setenv("ACCOUNT_CLEANER_ALLOW_LOCAL_HTTP", "0")
    assert not policy.is_url_allowed("http://127.0.0.1:8765/settings")


def test_인증_도메인은_https만_인정하고_서비스_도메인으로_보지_않는다():
    # given
    policy = SafetyPolicy(("example.com",), ("accounts.identity.test",))

    # when / then
    assert policy.is_auth_url("https://accounts.identity.test/login")
    assert not policy.is_auth_url("http://accounts.identity.test/login")
    assert not policy.is_url_allowed("https://accounts.identity.test/login")


@pytest.mark.parametrize(
    "text", ["Delete my account", "Permanently delete", "회원 탈퇴", "계정 영구 삭제"]
)
def test_최종_탈퇴_문구가_있는_클릭은_영어와_한국어_모두_차단한다(policy, text):
    # given: text

    # when / then
    with pytest.raises(PolicyViolation):
        policy.require_safe_click("button", text)


# --- 플레이북 사전 검사 ---


def test_안전한_플레이북은_100점으로_통과한다():
    # given
    playbook = Playbook(
        "safe",
        "Safe",
        "https://example.com/settings",
        ("example.com",),
        (Step(Action.REACH_TARGET, "text=Delete section", "target"),),
    )

    # when
    report = validate_playbook(playbook)

    # then
    assert report.valid
    assert report.score == 100


def test_외부_이동과_최종_버튼_클릭_단계가_있으면_거부한다():
    # given
    playbook = Playbook(
        "unsafe",
        "Unsafe",
        "https://example.com",
        ("example.com",),
        (
            Step(Action.NAVIGATE, "https://evil.test", "external"),
            Step(Action.CLICK, "text=Delete my account", "danger"),
        ),
    )

    # when
    report = validate_playbook(playbook)

    # then
    assert not report.valid
    assert {"unsafe_navigation", "final_action_click"} <= {i.code for i in report.issues}


def test_서비스_도메인과_인증_도메인이_겹치면_거부한다():
    # given
    playbook = Playbook(
        "overlap",
        "Overlap",
        "https://example.com",
        ("example.com",),
        (Step(Action.REACH_TARGET, "main", "target"),),
        auth_domains=("example.com",),
    )

    # when
    report = validate_playbook(playbook)

    # then
    assert not report.valid
    assert "auth_domain_overlap" in {i.code for i in report.issues}


def test_최종_문구가_있는_메뉴_링크_단계는_오류_대신_확인_경고를_남긴다():
    # given
    playbook = Playbook(
        "kr",
        "국내 서비스",
        "https://example.com/my",
        ("example.com",),
        (
            Step(Action.CLICK, "a.leave", "탈퇴 메뉴", fallback_texts=("회원탈퇴",), menu=True),
            Step(Action.REACH_TARGET, "main", "target"),
        ),
    )

    # when
    report = validate_playbook(playbook)

    # then
    assert report.valid
    assert "menu_final_text" in {i.code for i in report.issues if i.severity == "warning"}


# --- 민감정보·감사 로그·지표 ---


def test_이메일_인증번호_카드번호를_가린다():
    # given
    text = "mail user@example.com otp 123456 card 4111 1111 1111 1111"

    # when
    result = redact_sensitive(text)

    # then
    for secret in ("user@example.com", "123456", "4111"):
        assert secret not in result
    for mark in ("[EMAIL]", "[OTP]", "[CARD]"):
        assert mark in result


def test_감사_로그는_민감정보를_가리고_수정되면_검증에_실패한다(tmp_path):
    # given
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append({"status": "waiting", "email": "user@example.com", "otp": "123456"})
    log.append({"status": "complete"})
    text = path.read_text(encoding="utf-8")

    # when: 첫 기록을 고침
    records = text.splitlines()
    first = json.loads(records[0])
    first["event"]["status"] = "tampered"
    records[0] = json.dumps(first, ensure_ascii=False)
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_text("\n".join(records) + "\n", encoding="utf-8")

    # then
    assert verify_audit_log(path)
    assert "user@example.com" not in text
    assert "123456" not in text
    assert not verify_audit_log(tampered)


def test_성과_지표는_주소_없이_시간과_넘겨주기_수만_모은다():
    # given
    ticks = iter((10.0, 10.25))
    metrics = SessionMetrics("demo", clock=lambda: next(ticks))
    metrics.observe({"status": "running", "step": "0", "url": "secret"})
    metrics.observe({"status": "waiting_for_user"})
    metrics.observe({"status": "fallback_used", "step": "1"})

    # when
    summary = metrics.finalize(AgentResult(AgentStatus.REACHED_WITHDRAWAL, "demo", "done", 2))

    # then
    assert summary["duration_ms"] == 250
    assert summary["steps_observed"] == 2
    assert summary["handoff_count"] == 1
    assert summary["fallback_count"] == 1
    assert "url" not in summary
