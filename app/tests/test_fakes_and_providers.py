import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner import providers
from account_cleaner.browser.withdraw_agent import PlaywrightWithdrawAgent
from account_cleaner.contracts import (
    AgentStatus,
    AnalysisCancelled,
    EvidenceType,
    LoginMethod,
    ParsedMail,
    load_playbooks,
)
from account_cleaner.fakes import SAMPLE_PLAYBOOK_DIR, FakeAnalyzer, FakeWithdrawAgent

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
    def test_같은_서비스_메일을_묶고_근거_유형과_가입_방식을_찾는다(self):
        # given: MAILS (샘플쇼핑 2통, 뉴스 1통, 음악 2통)

        # when
        result = FakeAnalyzer().analyze(MAILS)

        # then
        shop = {c.domain: c for c in result}["shop.example.com"]
        assert len(shop.evidence) == 2
        assert {e.type for e in shop.evidence} == {EvidenceType.SIGNUP, EvidenceType.ACTIVITY}
        assert shop.confirmed_login_method is LoginMethod.KAKAO
        assert (shop.first_seen, shop.last_seen) == (MAILS[0].date, MAILS[1].date)

    def test_탈퇴_완료_메일이_있는_서비스는_삭제_근거를_가진다(self):
        # given: MAILS (음악 서비스에 탈퇴 완료 메일)

        # when
        result = FakeAnalyzer().analyze(MAILS)

        # then
        assert {c.domain: c for c in result}["music.example.net"].has_deleted_evidence

    def test_결과는_점수_내림차순이고_진행률은_전체_수로_끝난다(self):
        # given
        progress = []

        # when
        result = FakeAnalyzer().analyze(MAILS, on_progress=lambda n, t: progress.append((n, t)))

        # then
        assert result[0].domain == "shop.example.com"
        assert [c.score for c in result] == sorted((c.score for c in result), reverse=True)
        assert progress[-1] == (5, 5)

    def test_취소를_요청하면_AnalysisCancelled를_던진다(self):
        # given: 항상 취소를 요청하는 확인 함수

        # when / then
        with pytest.raises(AnalysisCancelled):
            FakeAnalyzer().analyze(MAILS, should_cancel=lambda: True)

    def test_메일이_없으면_빈_목록을_돌려준다(self):
        # given / when
        result = FakeAnalyzer().analyze([])

        # then
        assert result == []


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
    return load_playbooks(SAMPLE_PLAYBOOK_DIR)["sample_shop"]


class TestFakeWithdrawAgent:
    def test_로그인_차례에서_다른_스레드가_resume하면_탈퇴_화면까지_간다(self, tmp_path, playbook):
        # given: 작업 스레드에서 실행 중이고 로그인 차례에서 멈춘 에이전트
        agent = FakeWithdrawAgent(tmp_path, step_delay=0)
        t, events, done = run_in_thread(agent, playbook)
        wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)

        # when: UI 스레드 역할
        agent.resume()
        t.join(2)

        # then
        assert [e.status for e in events] == [
            AgentStatus.NAVIGATING,
            AgentStatus.USER_TURN,
            AgentStatus.NAVIGATING,
            AgentStatus.REACHED,
        ]
        assert [e.step.index for e in events] == [1, 1, 2, 3]
        assert {e.step.total for e in events} == {3}
        assert done["final"].status is AgentStatus.REACHED

    def test_사용자_차례가_아닐_때_누른_resume은_무시된다(self, tmp_path, playbook):
        # given: 실행 전에 resume을 미리 누름
        agent = FakeWithdrawAgent(tmp_path, step_delay=0)
        agent.resume()

        # when
        t, events, _ = run_in_thread(agent, playbook)
        wait_for(lambda: events and events[-1].status is AgentStatus.USER_TURN)

        # then: 사용자 차례에서 계속 기다림
        assert t.is_alive()
        agent.stop()
        t.join(2)
        assert events[-1].status is AgentStatus.STOPPED

    def test_시작_직전에_온_stop도_무시하지_않고_중단한다(self, tmp_path, playbook):
        # given
        agent = FakeWithdrawAgent(tmp_path, step_delay=0)
        agent.stop()

        # when
        final = agent.run(playbook, lambda e: None)

        # then
        assert final.status is AgentStatus.STOPPED

    def test_실패_단계를_지정하면_FAILED로_끝난다(self, tmp_path, playbook):
        # given
        agent = FakeWithdrawAgent(tmp_path, step_delay=0, fail_at_step=0)

        # when
        final = agent.run(playbook, lambda e: None)

        # then
        assert final.status is AgentStatus.FAILED

    def test_clear_session_호출은_순서대로_기록된다(self, tmp_path):
        # given
        agent = FakeWithdrawAgent(tmp_path)

        # when
        agent.clear_session(("shop.example.com",))
        agent.clear_session()

        # then
        assert agent.cleared == [("shop.example.com",), None]


class TestProviders:
    def test_플레이북을_Fake로_지정하면_예시_플레이북_3개를_불러온다(self, monkeypatch):
        # given
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "playbooks")

        # when
        playbooks = providers.get_playbooks()

        # then
        assert set(playbooks) == {"sample_shop", "sample_sns", "sample_music"}

    def test_기본값이면_브라우저_플레이북과_실제_에이전트를_쓴다(self, monkeypatch, tmp_path):
        # given
        monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)

        # when
        playbooks = providers.get_playbooks()
        agent = providers.get_withdraw_agent(tmp_path)

        # then
        assert set(playbooks) == {"github", "dropbox", "linkedin"}
        assert isinstance(agent, PlaywrightWithdrawAgent)

    def test_기본값이면_모델이_설정되지_않은_분석기는_Fake를_쓴다(self, monkeypatch):
        # given
        monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)
        monkeypatch.delenv("ACCOUNT_CLEANER_MODEL_DIR", raising=False)

        # when / then
        assert isinstance(providers.get_analyzer(), FakeAnalyzer)

    def test_none이면_실제_구현이_없을_때_오류를_낸다(self, monkeypatch):
        # given
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "none")

        # when / then
        with pytest.raises(providers.ProviderError, match="create_analyzer"):
            providers.get_analyzer()

    def test_목록에_적은_것만_Fake를_쓴다(self, monkeypatch, tmp_path):
        # given: 에이전트만 Fake, 분석기는 실제(모델 미설정)
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "agent")
        monkeypatch.delenv("ACCOUNT_CLEANER_MODEL_DIR", raising=False)

        # when / then
        assert isinstance(providers.get_withdraw_agent(tmp_path), FakeWithdrawAgent)
        with pytest.raises(providers.ProviderError):
            providers.get_analyzer()

    def test_모르는_값이면_그_값을_알려주며_오류를_낸다(self, monkeypatch):
        # given: 오타
        monkeypatch.setenv("ACCOUNT_CLEANER_FAKE", "analyser")

        # when / then
        with pytest.raises(providers.ProviderError, match="analyser"):
            providers.get_analyzer()

    def test_실제_구현이_있으면_그것을_쓴다(self, monkeypatch, tmp_path):
        # given: classifier.create_analyzer가 있는 상태
        from account_cleaner import classifier

        sentinel = FakeAnalyzer()
        monkeypatch.setattr(classifier, "create_analyzer", lambda: sentinel, raising=False)
        monkeypatch.setattr(classifier, "is_configured", lambda: True)
        monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)

        # when
        analyzer = providers.get_analyzer()

        # then
        assert analyzer is sentinel
