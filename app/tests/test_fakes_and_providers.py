import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner import providers
from account_cleaner.contracts import (
    AgentStatus,
    AnalysisCancelled,
    EvidenceType,
    LoginMethod,
    ParsedMail,
)
from account_cleaner.fakes import FakeAnalyzer, FakeWithdrawAgent

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def mail(n, domain, subject):
    return ParsedMail(
        id=f"<{n}@x>",
        sender=f"no-reply@{domain}",
        sender_domain=domain,
        subject=subject,
        date=T0 + timedelta(days=n),
        body_text="",
    )


MAILS = [
    mail(1, "shop.example.com", "[샘플쇼핑] 카카오로 가입을 환영합니다"),
    mail(2, "mail.shop.example.com", "주문하신 상품이 배송되었습니다"),
    mail(3, "news.example.org", "이번 주 특가 소식"),
    mail(4, "music.example.net", "이메일 인증을 완료해 주세요"),
    mail(5, "music.example.net", "회원 탈퇴가 완료되었습니다"),
]


class TestFakeAnalyzer:
    def test_groups_and_scores(self):
        progress = []
        result = FakeAnalyzer().analyze(MAILS, on_progress=lambda n, t: progress.append((n, t)))
        by_domain = {c.domain: c for c in result}

        shop = by_domain["shop.example.com"]
        assert len(shop.evidence) == 2
        assert {e.type for e in shop.evidence} == {EvidenceType.SIGNUP, EvidenceType.ACTIVITY}
        assert shop.confirmed_login_method is LoginMethod.KAKAO
        assert (shop.first_seen, shop.last_seen) == (MAILS[0].date, MAILS[1].date)

        assert by_domain["music.example.net"].has_deleted_evidence
        assert result[0].domain == "shop.example.com"  # score 내림차순
        assert [c.score for c in result] == sorted((c.score for c in result), reverse=True)
        assert progress[-1] == (5, 5)

    def test_cancel(self):
        with pytest.raises(AnalysisCancelled):
            FakeAnalyzer().analyze(MAILS, should_cancel=lambda: True)

    def test_empty(self):
        assert FakeAnalyzer().analyze([]) == []


def run_in_thread(agent, playbook):
    events, done = [], {}

    def target():
        done["final"] = agent.run(playbook, events.append)

    t = threading.Thread(target=target)
    t.start()
    return t, events, done


def wait_for(cond, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timeout")


@pytest.fixture
def playbook():
    return providers.get_playbooks()["sample_shop"]


class TestFakeWithdrawAgent:
    def test_full_flow_with_resume_from_other_thread(self, tmp_path, playbook):
        agent = FakeWithdrawAgent(tmp_path, step_delay=0)
        t, events, done = run_in_thread(agent, playbook)
        wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)
        agent.resume()  # UI 스레드 역할
        t.join(2)
        assert [e.status for e in events] == [
            AgentStatus.NAVIGATING,
            AgentStatus.USER_TURN,
            AgentStatus.NAVIGATING,
            AgentStatus.REACHED,
        ]
        assert done["final"].status is AgentStatus.REACHED

    def test_resume_outside_user_turn_is_ignored(self, tmp_path, playbook):
        agent = FakeWithdrawAgent(tmp_path, step_delay=0)
        agent.resume()
        t, events, _ = run_in_thread(agent, playbook)
        wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)
        assert t.is_alive()  # 미리 누른 resume으로 넘어가지 않음
        agent.stop()
        t.join(2)
        assert events[-1].status is AgentStatus.STOPPED

    def test_failure(self, tmp_path, playbook):
        agent = FakeWithdrawAgent(tmp_path, step_delay=0, fail_at_step=0)
        assert agent.run(playbook, lambda e: None).status is AgentStatus.FAILED

    def test_clear_session_recorded(self, tmp_path):
        agent = FakeWithdrawAgent(tmp_path)
        agent.clear_session(("shop.example.com",))
        agent.clear_session()
        assert agent.cleared == [("shop.example.com",), None]


class TestProviders:
    def test_sample_playbooks_load(self):
        assert set(providers.get_playbooks()) == {"sample_shop", "sample_sns", "sample_music"}

    def test_auto_falls_back_to_fake(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)
        assert isinstance(providers.get_analyzer(), FakeAnalyzer)
        assert isinstance(providers.get_withdraw_agent(tmp_path), FakeWithdrawAgent)

    def test_none_requires_real(self, monkeypatch):
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "none")
        with pytest.raises(providers.ProviderError, match="create_analyzer"):
            providers.get_analyzer()

    def test_partial_list(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "analyzer")
        assert isinstance(providers.get_analyzer(), FakeAnalyzer)
        with pytest.raises(providers.ProviderError):
            providers.get_withdraw_agent(tmp_path)

    def test_unknown_value(self, monkeypatch):
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "analyser")
        with pytest.raises(providers.ProviderError, match="analyser"):
            providers.get_analyzer()

    def test_real_implementation_used_when_present(self, monkeypatch, tmp_path):
        from account_cleaner import classifier

        sentinel = FakeAnalyzer()
        monkeypatch.setattr(classifier, "create_analyzer", lambda: sentinel, raising=False)
        monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)
        assert providers.get_analyzer() is sentinel
