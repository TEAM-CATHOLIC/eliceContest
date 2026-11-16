"""Synthetic-only contract tests; no ML downloads or private mail required."""

from datetime import UTC, datetime, timedelta

import pytest

from account_cleaner import classifier, providers
from account_cleaner.classifier.analyzer import LocalAccountAnalyzer, resolve_service
from account_cleaner.classifier.model import explicit_rule, model_text, stage_hint
from account_cleaner.contracts import AnalysisCancelled, EvidenceType, ParsedMail


def mail(n, subject="가입 완료", body="", domain="sample.example"):
    return ParsedMail(
        str(n),
        f"noreply@{domain}",
        domain,
        subject,
        datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=n),
        body,
    )


class StubPredictor:
    def __init__(self, values):
        self.values = values

    def predict(self, rows, on_progress=None, should_cancel=None):
        if should_cancel and should_cancel():
            raise InterruptedError()
        if on_progress:
            on_progress(len(rows), len(rows))
        return [
            {
                "type": self.values[r["id"]][0],
                "stage_hint": self.values[r["id"]][1],
                "classification_score": 0.9,
                "decision_source": "model",
            }
            for r in rows
        ]


def analyzer(values):
    instance = object.__new__(LocalAccountAnalyzer)
    instance.predictor = StubPredictor(values)
    return instance


def test_개인메일없이_계약에_맞는_후보와_진행률을_돌려준다():
    # given
    a = analyzer({"1": ("signup", "unknown"), "2": ("activity", "unknown")})
    messages = [mail(1), mail(2)]
    progress = []
    # when
    result = a.analyze(messages, on_progress=lambda n, t: progress.append((n, t)))
    # then
    assert len(result) == 1
    assert result[0].domain == "sample.example"
    assert len(result[0].evidence) == 2
    assert result[0].evidence[0].type is EvidenceType.SIGNUP
    assert progress[-1] == (2, 2)
    assert result[0].confirmed_login_method is None


def test_중복아이디와_광고만있는_후보를_제외한다():
    # given / when
    a = analyzer({"1": ("signup", "unknown"), "2": ("promo", "unknown")})
    result = a.analyze([mail(1), mail(1), mail(2, domain="ads.example")])
    # then
    assert len(result) == 1
    assert len(result[0].evidence) == 1


def test_빈입력과_취소를_지원한다():
    # given
    a = analyzer({})
    # when / then
    assert a.analyze([]) == []
    with pytest.raises(AnalysisCancelled):
        a.analyze([mail(1)], should_cancel=lambda: True)


def test_탈퇴이후_새가입근거는_최근날짜로_판단한다():
    # given
    a = analyzer({"1": ("deleted", "account_deleted_completed"), "2": ("signup", "unknown")})
    # when
    after_rejoin = a.analyze([mail(2), mail(1)])[0]
    deleted_last = analyzer(
        {"1": ("signup", "unknown"), "2": ("deleted", "account_deleted_completed")}
    ).analyze([mail(2), mail(1)])[0]
    # then
    assert after_rejoin.score > deleted_last.score
    assert deleted_last.score <= 0.1
    assert after_rejoin.has_deleted_evidence  # historical evidence retained, not current status


def test_인증요청과_가입거절은_낮은후보점수로_남긴다():
    # given / when
    for stage in ("requested", "account_not_found", "existing_address_signup_blocked"):
        result = analyzer({"1": ("signup", stage)}).analyze([mail(1)])
        # then
        assert result[0].score <= 0.25


def test_결제대행사를_상점계정으로_오인하지않는다():
    # given / when / then
    assert resolve_service(mail(1, body="일반 결제 내역", domain="inicis.com")) is None
    assert resolve_service(mail(1, body="샘플 상점", domain="cafe24shop.com")) is None


def test_제목광고와_가입인증과_삭제완료를_구분한다():
    # given / when / then
    assert explicit_rule("(광고) 주문 금액 환불", "혜택을 받아보세요")[0] == "promo"
    assert (
        stage_hint("가입을 환영합니다", "이메일 인증은 회원가입의 필수적인 단계입니다.")
        == "requested"
    )
    assert explicit_rule("안내", "계정은 30일 후 삭제될 예정입니다.")[0] is None
    assert explicit_rule("안내", "고객님의 서비스 계정이 안전하게 파기되었습니다.")[0] == "deleted"
    assert explicit_rule("해지 완료", "이모티콘 플러스가 해지되었습니다.")[0] is None


def test_정답주석은_모델입력에_포함하지않는다():
    # given / when / then
    assert (
        model_text({"subject": "제목", "body_text": "본문", "label": "deleted"})
        == "query: 제목\n본문"
    )


def test_명시한_모델경로가_틀리면_Fake로_숨기지않는다(monkeypatch, tmp_path):
    # given
    monkeypatch.setenv("ACCOUNT_CLEANER_MODEL_DIR", str(tmp_path))
    monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)
    # when / then
    assert classifier.is_configured()
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        providers.get_analyzer()


def test_미설정이면_ml패키지없이_Fake를_사용한다(monkeypatch):
    # given
    from account_cleaner.fakes import FakeAnalyzer

    monkeypatch.delenv("ACCOUNT_CLEANER_MODEL_DIR", raising=False)
    monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)
    # when / then
    assert isinstance(providers.get_analyzer(), FakeAnalyzer)
