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
                "gate": (self.values[r["id"]] + (None,))[2],
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


def test_중복아이디를_제외하고_광고만있는_후보는_약한흔적으로_남긴다():
    # given / when
    a = analyzer({"1": ("signup", "unknown"), "2": ("promo", "unknown")})
    result = a.analyze([mail(1), mail(1), mail(2, domain="ads.example")])
    # then
    assert len(result) == 2
    assert len(result[0].evidence) == 1
    assert result[1].domain == "ads.example"
    assert result[1].score == 0


def test_관련성판정이_의심_업무메일은_후보에서_빼고_광고는_약한흔적으로_낮춘다():
    # given
    a = analyzer(
        {
            "1": ("security", "unknown", "suspicious"),
            "2": ("activity", "unknown", "unrelated"),
            "3": ("activity", "unknown", "promo"),
            "4": ("signup", "unknown", "usage"),
        }
    )
    messages = [
        mail(1, domain="phish.example"),
        mail(2, domain="work.example"),
        mail(3, domain="ads.example"),
        mail(4),
    ]
    # when
    result = a.analyze(messages)
    # then
    assert [c.domain for c in result] == ["sample.example", "ads.example"]
    assert result[1].evidence[0].type is EvidenceType.PROMO
    assert result[1].score == 0


def test_관련성판정_가중치는_임계값_미만이면_판정하지_않는다():
    # given
    np = pytest.importorskip("numpy")
    from account_cleaner.classifier.model import GateHead

    coef = np.zeros((2, 384))
    coef[0, 0] = 5.0
    head = GateHead(
        {"classes": ["suspicious", "usage"], "coef": coef, "intercept": [0, 0], "threshold": 0.6}
    )
    x = np.zeros((2, 384))
    x[0, 0] = 1.0
    # when / then
    assert head.predict(x) == ["suspicious", None]


def test_공유발신자에서_서비스별로_구분하고_주소를_추측하지않는다():
    first = resolve_service(
        mail(1, subject="Google 계정 데이터 일부를 OpenAI에 공유하셨습니다", domain="google.com")
    )
    assert first == ("OpenAI", "openai.com")
    assert resolve_service(mail(1, subject="보안 알림", domain="google.com")) == (
        "Google",
        "google.com",
    )
    a = resolve_service(mail(1, subject="[샘플A] 가입 안내", domain="cafe24shop.com"))
    b = resolve_service(mail(2, subject="[샘플B] 가입 안내", domain="cafe24shop.com"))
    assert a[0] == "샘플A" and a[1].endswith(".invalid")
    assert a[1] != b[1]
    assert resolve_service(mail(1, subject="[광고] 할인", domain="cafe24shop.com")) is None


def test_모델의_삭제추정은_명시적인_탈퇴완료로_확정하지않는다():
    result = analyzer({"1": ("signup", "unknown"), "2": ("deleted", "unknown")}).analyze(
        [mail(1), mail(2)]
    )[0]
    assert result.score > 0.1
    assert result.evidence[-1].probability < 1


def test_서로_다른_종류의_근거는_점수를_올리고_같은_종류의_반복은_올리지_않는다():
    # given / when
    one = analyzer({"1": ("security", "unknown")}).analyze([mail(1)])[0]
    repeated = analyzer({"1": ("security", "unknown"), "2": ("security", "unknown")}).analyze(
        [mail(1), mail(2)]
    )[0]
    mixed = analyzer({"1": ("security", "unknown"), "2": ("terms", "unknown")}).analyze(
        [mail(1), mail(2)]
    )[0]
    # then
    assert repeated.score == one.score
    assert one.score < mixed.score < 1


def test_개인_메일_주소에서_온_메일은_그_메일_서비스의_계정_후보로_묶지_않는다():
    # given / when
    result = analyzer({"1": ("activity", "unknown"), "2": ("signup", "unknown")}).analyze(
        [mail(1, domain="gmail.com"), mail(2)]
    )
    # then
    assert [c.domain for c in result] == ["sample.example"]
    assert resolve_service(mail(1, domain="navercorp.com")) == ("네이버", "naver.com")


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


def test_미설정이면_ml패키지없이_Fake를_사용한다(monkeypatch, tmp_path):
    # given
    from account_cleaner.fakes import FakeAnalyzer

    monkeypatch.delenv("ACCOUNT_CLEANER_MODEL_DIR", raising=False)
    monkeypatch.delenv("ACCOUNT_CLEANER_FAKE", raising=False)
    monkeypatch.setattr(classifier, "BUNDLED_MODEL_DIR", tmp_path)
    # when / then
    assert isinstance(providers.get_analyzer(), FakeAnalyzer)


def test_경로를_지정하지_않아도_앱에_묶인_모델이_있으면_그_모델을_쓴다(monkeypatch, tmp_path):
    # given
    monkeypatch.delenv("ACCOUNT_CLEANER_MODEL_DIR", raising=False)
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(classifier, "BUNDLED_MODEL_DIR", tmp_path)
    # when / then
    assert classifier.is_configured()
    with pytest.raises(FileNotFoundError, match="weights.json"):
        classifier.create_analyzer()
