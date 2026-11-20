"""모든 테스트 공통 설정."""

import pytest


@pytest.fixture(autouse=True)
def _no_real_anthropic_key(monkeypatch):
    """개발자 PC에 저장된 실제 API 키(환경변수·키체인)가 테스트 결과를 바꾸지 않게 한다 (#79).

    키체인 항목 이름을 테스트 전용으로 바꿔, 실제 `account-cleaner` 항목은 읽지도 쓰지도 않는다.
    """
    from account_cleaner.browser.agent import llm

    monkeypatch.delenv(llm.API_KEY_ENV, raising=False)
    monkeypatch.setattr(llm, "KEYRING_SERVICE", "account-cleaner-pytest")
