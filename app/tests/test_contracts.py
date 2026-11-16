import json
from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner.contracts import (
    LOCAL_HTTP_ENV,
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
    is_secure_url,
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
    def test_올바른_값이면_만들어진다(self):
        # given / when
        m = mail()

        # then
        assert m.sender_domain == "shop.example.com"

    @pytest.mark.parametrize(
        "kw",
        [
            {"id": ""},
            {"sender_domain": "Shop.example.com"},
            {"date": datetime(2026, 1, 1)},
        ],
    )
    def test_빈_id_대문자_도메인_시간대_없는_날짜는_거부한다(self, kw):
        # given: kw

        # when / then
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
    def test_점수_범위_밖_근거_없음_대문자_도메인_날짜_역전은_거부한다(self, kw):
        # given: kw

        # when / then
        with pytest.raises(ValueError):
            candidate(**kw)

    def test_근거_확률이_0과_1_사이가_아니면_거부한다(self):
        # given: 음수 확률

        # when / then
        with pytest.raises(ValueError):
            Evidence("m", EvidenceType.PROMO, -0.1)

    def test_탈퇴_완료_근거가_있을_때만_has_deleted_evidence가_참이다(self):
        # given
        normal = candidate()
        deleted = candidate(evidence=(Evidence("m", EvidenceType.DELETED, 1.0),))

        # when / then
        assert not normal.has_deleted_evidence
        assert deleted.has_deleted_evidence

    def test_근거_유형은_한국어_라벨을_가진다(self):
        # given / when
        label = EvidenceType.SIGNUP.label

        # then
        assert label == "가입·인증"


class TestAgentEvent:
    def test_reason은_USER_TURN일_때만_그리고_반드시_채운다(self):
        # given / when / then: USER_TURN인데 reason 없음
        with pytest.raises(ValueError):
            AgentEvent(AgentStatus.USER_TURN)
        # given / when / then: USER_TURN이 아닌데 reason 있음
        with pytest.raises(ValueError):
            AgentEvent(AgentStatus.NAVIGATING, reason=HandoffReason.LOGIN)
        # given / when / then: 올바른 조합
        AgentEvent(AgentStatus.USER_TURN, reason=HandoffReason.CAPTCHA)

    def test_이벤트에_현재_단계를_담을_수_있다(self):
        # given
        step = AgentStep(2, 3, "탈퇴 메뉴 진입")

        # when
        event = AgentEvent(AgentStatus.NAVIGATING, step=step)

        # then
        assert event.step == step

    @pytest.mark.parametrize("bad", [(0, 3, "a"), (4, 3, "a"), (1, 3, " ")])
    def test_단계_번호가_범위_밖이거나_제목이_비면_거부한다(self, bad):
        # given: bad

        # when / then
        with pytest.raises(ValueError):
            AgentStep(*bad)

    def test_종료_상태는_REACHED_STOPPED_FAILED뿐이다(self):
        # given / when
        finals = {s for s in AgentStatus if s.is_final}

        # then
        assert finals == {AgentStatus.REACHED, AgentStatus.STOPPED, AgentStatus.FAILED}


class TestAbstractEnforcement:
    def test_분석기가_analyze를_구현하지_않으면_만들_수_없다(self):
        # given
        class Broken(AccountAnalyzer):
            pass

        # when / then
        with pytest.raises(TypeError):
            Broken()

    def test_에이전트가_필수_메서드를_다_구현하지_않으면_만들_수_없다(self, tmp_path):
        # given: run만 구현
        class Broken(WithdrawAgent):
            def run(self, playbook, on_event): ...

        # when / then
        with pytest.raises(TypeError):
            Broken(tmp_path)


LOCAL_PLAYBOOK = VALID_PLAYBOOK | {
    "id": "demo",
    "domains": ["127.0.0.1"],
    "login_url": "http://127.0.0.1:8765/login",
    "password_reset_url": "http://127.0.0.1:8765/login",
    "withdraw_url": "http://127.0.0.1:8765/settings",
}


class TestLocalHttp:
    def test_로컬_데모_주소는_기본값에서_http도_허용한다(self, monkeypatch):
        # given
        monkeypatch.delenv(LOCAL_HTTP_ENV, raising=False)

        # when
        pb = Playbook.from_dict(LOCAL_PLAYBOOK)

        # then
        assert pb.allows("http://127.0.0.1:8765/settings")

    def test_배포_설정에서_로컬_http를_끄면_https만_허용한다(self, monkeypatch):
        # given
        monkeypatch.setenv(LOCAL_HTTP_ENV, "0")

        # when / then
        with pytest.raises(PlaybookError, match="https"):
            Playbook.from_dict(LOCAL_PLAYBOOK)
        assert not is_secure_url("http://localhost/")

    @pytest.mark.parametrize(
        "url", ["http://example.com/", "http://127.0.0.1.evil.io/", "ftp://127.0.0.1/"]
    )
    def test_루프백이_아닌_http나_다른_scheme은_항상_거부한다(self, monkeypatch, url):
        # given
        monkeypatch.delenv(LOCAL_HTTP_ENV, raising=False)

        # when / then
        assert not is_secure_url(url)


class TestPlaybook:
    def test_도메인과_그_하위_도메인만_일치로_본다(self):
        # given
        domains = ("shop.example.com",)

        # when / then
        assert host_matches("shop.example.com", domains)
        assert host_matches("a.shop.example.com", domains)
        assert not host_matches("evilshop.example.com", domains)
        assert not host_matches("shop.example.com.evil.io", domains)

    def test_JSON에서_읽은_플레이북은_https와_허용_도메인만_허락한다(self):
        # given / when
        pb = Playbook.from_dict(VALID_PLAYBOOK)

        # then
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
    def test_잘못된_버전_로그인_방식_도메인_URL은_거부한다(self, change):
        # given: 올바른 플레이북에서 한 필드만 잘못 바꿈

        # when / then
        with pytest.raises(PlaybookError):
            Playbook.from_dict(VALID_PLAYBOOK | change)

    def test_필수_필드가_빠지면_그_이름을_알려준다(self):
        # given
        data = dict(VALID_PLAYBOOK)
        del data["withdraw_url"]

        # when / then
        with pytest.raises(PlaybookError, match="withdraw_url"):
            Playbook.from_dict(data)

    def test_파일_이름과_id가_다르면_거부한다(self, tmp_path):
        # given: id가 shop인 플레이북을 other.json으로 저장
        path = tmp_path / "other.json"
        path.write_text(json.dumps(VALID_PLAYBOOK), encoding="utf-8")

        # when / then
        with pytest.raises(PlaybookError, match="파일 이름"):
            load_playbook(path)

    def test_JSON_문법이_깨진_파일은_거부한다(self, tmp_path):
        # given
        path = tmp_path / "shop.json"
        path.write_text("{", encoding="utf-8")

        # when / then
        with pytest.raises(PlaybookError, match="JSON"):
            load_playbook(path)
