import json
from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.contracts import (
    AccountAnalyzer,
    AccountCandidate,
    AgentEvent,
    AgentStatus,
    AgentStep,
    Evidence,
    EvidenceType,
    HandoffReason,
    ParsedMail,
    Playbook,
    PlaybookError,
    WithdrawAgent,
    host_matches,
    load_playbook,
)

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def mail(**kw):
    base = {
        "id": "<1@x>",
        "sender": "a@shop.example.com",
        "sender_domain": "shop.example.com",
        "subject": "s",
        "date": NOW,
        "body_text": "",
    }
    return ParsedMail(**(base | kw))


def candidate(**kw):
    base = {
        "service": "shop",
        "domain": "shop.example.com",
        "score": 0.5,
        "evidence": (Evidence("<1@x>", EvidenceType.SIGNUP, 0.9),),
        "first_seen": NOW,
        "last_seen": NOW,
    }
    return AccountCandidate(**(base | kw))


VALID_PLAYBOOK = {
    "schema_version": 1,
    "id": "shop",
    "service": "샵",
    "domains": ["Shop.Example.com"],
    "auth_domains": ["kauth.kakao.com"],
    "login_methods": ["email", "kakao"],
    "login_url": "https://shop.example.com/login",
    "password_reset_url": "https://www.shop.example.com/reset",
    "withdraw_url": "https://shop.example.com/leave",
}


class TestParsedMail:
    def test_valid(self):
        assert mail().sender_domain == "shop.example.com"

    @pytest.mark.parametrize(
        "kw",
        [
            {"id": ""},
            {"sender_domain": "Shop.example.com"},
            {"date": datetime(2026, 1, 1)},
        ],
    )
    def test_invalid(self, kw):
        with pytest.raises(ValueError):
            mail(**kw)


class TestAccountCandidate:
    @pytest.mark.parametrize(
        "kw",
        [
            {"score": 1.5},
            {"evidence": ()},
            {"domain": "Shop.example.com"},
            {"first_seen": NOW + timedelta(days=1)},
        ],
    )
    def test_invalid(self, kw):
        with pytest.raises(ValueError):
            candidate(**kw)

    def test_evidence_probability_range(self):
        with pytest.raises(ValueError):
            Evidence("m", EvidenceType.PROMO, -0.1)

    def test_deleted_flag(self):
        assert not candidate().has_deleted_evidence
        ev = (Evidence("m", EvidenceType.DELETED, 1.0),)
        assert candidate(evidence=ev).has_deleted_evidence

    def test_evidence_label(self):
        assert EvidenceType.SIGNUP.label == "가입·인증"


class TestAgentEvent:
    def test_user_turn_needs_reason(self):
        with pytest.raises(ValueError):
            AgentEvent(AgentStatus.USER_TURN)
        with pytest.raises(ValueError):
            AgentEvent(AgentStatus.NAVIGATING, reason=HandoffReason.LOGIN)
        AgentEvent(AgentStatus.USER_TURN, reason=HandoffReason.CAPTCHA)

    def test_step(self):
        step = AgentStep(2, 3, "탈퇴 메뉴 진입")
        assert AgentEvent(AgentStatus.NAVIGATING, step=step).step == step
        for bad in [(0, 3, "a"), (4, 3, "a"), (1, 3, " ")]:
            with pytest.raises(ValueError):
                AgentStep(*bad)

    def test_final_states(self):
        finals = {s for s in AgentStatus if s.is_final}
        assert finals == {AgentStatus.REACHED, AgentStatus.STOPPED, AgentStatus.FAILED}


class TestAbstractEnforcement:
    def test_analyzer_missing_method(self):
        class Broken(AccountAnalyzer):
            pass

        with pytest.raises(TypeError):
            Broken()

    def test_agent_missing_method(self, tmp_path):
        class Broken(WithdrawAgent):
            def run(self, playbook, on_event): ...

        with pytest.raises(TypeError):
            Broken(tmp_path)


class TestPlaybook:
    def test_host_matches(self):
        assert host_matches("shop.example.com", ("shop.example.com",))
        assert host_matches("a.shop.example.com", ("shop.example.com",))
        assert not host_matches("evilshop.example.com", ("shop.example.com",))
        assert not host_matches("shop.example.com.evil.io", ("shop.example.com",))

    def test_from_dict(self):
        pb = Playbook.from_dict(VALID_PLAYBOOK)
        assert pb.domains == ("shop.example.com",)
        assert pb.allows("https://m.shop.example.com/x")
        assert pb.allows("https://kauth.kakao.com/oauth")
        assert not pb.allows("http://shop.example.com/x")
        assert not pb.allows("https://evil.example.com/")
        assert pb.matches_domain("mail.shop.example.com")

    @pytest.mark.parametrize(
        "change",
        [
            {"schema_version": 2},
            {"login_methods": ["fax"]},
            {"domains": []},
            {"withdraw_url": "https://evil.example.com/leave"},
            {"login_url": "http://shop.example.com/login"},
        ],
    )
    def test_invalid(self, change):
        with pytest.raises(PlaybookError):
            Playbook.from_dict(VALID_PLAYBOOK | change)

    def test_missing_field(self):
        data = dict(VALID_PLAYBOOK)
        del data["withdraw_url"]
        with pytest.raises(PlaybookError, match="withdraw_url"):
            Playbook.from_dict(data)

    def test_load_checks_file_name(self, tmp_path):
        path = tmp_path / "other.json"
        path.write_text(json.dumps(VALID_PLAYBOOK), encoding="utf-8")
        with pytest.raises(PlaybookError, match="파일 이름"):
            load_playbook(path)

    def test_load_bad_json(self, tmp_path):
        path = tmp_path / "shop.json"
        path.write_text("{", encoding="utf-8")
        with pytest.raises(PlaybookError, match="JSON"):
            load_playbook(path)
