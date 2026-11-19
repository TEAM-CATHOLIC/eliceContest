"""AI 안내용 API 키 설정 (#81): 입력 창, 키체인 저장·삭제, 사이드바 상태."""

import pytest

from account_cleaner.browser.agent import llm
from account_cleaner.ui.api_key_dialog import ApiKeyDialog, ai_status_text
from account_cleaner.ui.main_window import MainWindow

VALID_KEY = "sk-ant-api03-test-0123456789abcdef"


class FakeStore:
    def __init__(self, source=None, fail=None):
        self.saved: list[str] = []
        self.deleted = 0
        self.current = source
        self.fail = fail

    def save(self, key):
        if self.fail:
            raise self.fail
        llm_key = key.strip()
        if not llm_key.startswith(llm.KEY_PREFIX):
            raise ValueError("Anthropic API 키는 sk-ant- 로 시작합니다")
        self.saved.append(llm_key)
        self.current = "keychain"

    def delete(self):
        self.deleted += 1
        self.current = None

    def source(self):
        return self.current


def dialog_with(qtbot, store):
    dialog = ApiKeyDialog(save=store.save, delete=store.delete, source=store.source)
    qtbot.addWidget(dialog)
    return dialog


def test_키를_넣고_저장하면_키체인에_저장하고_변경_신호를_보낸다(qtbot):
    # given
    store = FakeStore()
    dialog = dialog_with(qtbot, store)
    dialog.key_edit.setText(f"  {VALID_KEY}  ")

    # when
    with qtbot.waitSignal(dialog.key_changed):
        dialog.save_button.click()

    # then
    assert store.saved == [VALID_KEY]
    assert dialog.key_edit.text() == ""  # 화면에 키를 남기지 않는다
    assert "켜짐" in dialog.status_label.text()


def test_입력칸은_기본으로_가려지고_키_보기로_보여_줄_수_있다(qtbot):
    # given
    dialog = dialog_with(qtbot, FakeStore())

    # then
    assert dialog.key_edit.echoMode() is dialog.key_edit.EchoMode.Password
    dialog.show_key.setChecked(True)
    assert dialog.key_edit.echoMode() is dialog.key_edit.EchoMode.Normal


def test_형식이_틀린_키는_저장하지_않고_안내한다(qtbot):
    # given
    store = FakeStore()
    dialog = dialog_with(qtbot, store)
    dialog.key_edit.setText("hello")

    # when
    dialog.save_button.click()

    # then
    assert store.saved == []
    assert "sk-ant-" in dialog.message_label.text()


def test_키체인이_없으면_환경변수로_실행하라고_안내한다(qtbot):
    # given
    store = FakeStore(fail=llm.ApiKeyStoreError("쓸 수 있는 키체인이 없습니다"))
    dialog = dialog_with(qtbot, store)
    dialog.key_edit.setText(VALID_KEY)

    # when
    dialog.save_button.click()

    # then
    assert "ANTHROPIC_API_KEY" in dialog.message_label.text()


def test_저장된_키는_지울_수_있고_환경변수_키는_지우기_버튼이_꺼진다(qtbot):
    # given
    stored = FakeStore(source="keychain")
    dialog = dialog_with(qtbot, stored)

    # when
    with qtbot.waitSignal(dialog.key_changed):
        dialog.delete_button.click()

    # then
    assert stored.deleted == 1
    assert "꺼짐" in dialog.status_label.text()
    assert not dialog_with(qtbot, FakeStore(source="env")).delete_button.isEnabled()


def test_사이드바_AI_키_설정_버튼은_요청_신호를_보낸다(qtbot):
    # given
    window = MainWindow()
    qtbot.addWidget(window)

    # when / then
    with qtbot.waitSignal(window.sidebar_footer.api_key_requested):
        window.sidebar_footer.api_key_button.click()


def test_사이드바_상태_문구():
    # then
    assert ai_status_text(None) == "꺼짐 (API 키 없음)"
    assert ai_status_text("keychain") == "켜짐"
    assert ai_status_text("env") == "켜짐 (환경변수)"


@pytest.fixture
def memory_keyring(monkeypatch):
    """실제 OS 키체인 대신 메모리 키링으로 저장·삭제를 확인한다."""
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordDeleteError

    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.values = {}

        def get_password(self, service, username):
            return self.values.get((service, username))

        def set_password(self, service, username, password):
            self.values[(service, username)] = password

        def delete_password(self, service, username):
            if (service, username) not in self.values:
                raise PasswordDeleteError(username)
            del self.values[(service, username)]

    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    monkeypatch.delenv(llm.API_KEY_ENV, raising=False)
    yield backend
    keyring.set_keyring(previous)


def test_키체인에_저장한_키를_범용_안내가_읽고_지우면_다시_꺼진다(memory_keyring):
    # when
    llm.save_api_key(VALID_KEY)

    # then
    assert llm.anthropic_api_key() == VALID_KEY
    assert llm.api_key_source() == "keychain"
    llm.delete_api_key()
    assert llm.api_key_source() is None
    llm.delete_api_key()  # 없는 키를 지워도 오류 없음


def test_환경변수_키가_키체인보다_먼저_쓰인다(memory_keyring, monkeypatch):
    # given
    llm.save_api_key(VALID_KEY)
    monkeypatch.setenv(llm.API_KEY_ENV, "sk-ant-from-env-0123456789")

    # then
    assert llm.api_key_source() == "env"
    assert llm.anthropic_api_key() == "sk-ant-from-env-0123456789"


def test_키_입력_창은_폭이_고정되고_안내_글이_잘리지_않게_줄바꿈된다(qtbot):
    # given (#83): 줄바꿈 글은 폭이 정해져야 높이가 맞게 계산된다
    from PySide6.QtWidgets import QLabel

    from account_cleaner.ui.api_key_dialog import DIALOG_WIDTH

    dialog = dialog_with(qtbot, FakeStore())
    dialog.show()
    qtbot.waitExposed(dialog)

    # then
    assert dialog.width() == DIALOG_WIDTH
    for label in dialog.findChildren(QLabel):
        if label.isVisible() and label.wordWrap() and label.text():
            assert label.height() >= label.heightForWidth(label.width()) - 1, label.text()
    assert not dialog.message_label.isVisible()  # 빈 안내 줄은 자리를 차지하지 않는다
