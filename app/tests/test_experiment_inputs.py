import pytest

from account_cleaner.classifier.experiment import validate_rows


def record(**changes):
    return {
        "id": "synthetic",
        "group": "sample.example",
        "subject": "합성 제목",
        "body_text": "합성 본문",
        "provenance": "human_verified",
        "weight": 2.0,
        "type_label": "signup",
        "stage_label": None,
        "relevance_label": "candidate",
        **changes,
    }


def test_검토출처와_보류라벨을_명시한_입력을_허용한다():
    validate_rows([record()])


@pytest.mark.parametrize("role", ["reserved_candidate", "test", "final_evaluation"])
def test_최종평가용으로_보관한_자료의_학습을_차단한다(role):
    with pytest.raises(ValueError, match="Reserved"):
        validate_rows([record(role=role)])


def test_중복과_출처없는라벨과_무한가중치를_거부한다():
    for rows in [[record(), record()], [record(provenance=None)], [record(weight=float("inf"))]]:
        with pytest.raises(ValueError):
            validate_rows(rows)
