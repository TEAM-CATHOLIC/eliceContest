"""근거 메일 칸 단위 암호화와 키 저장소 테스트 (#52). 실제 OS 키체인은 건드리지 않는다."""

import os
import sys

import pytest

from account_cleaner.storage.crypto import (
    KEY_BYTES,
    DecryptError,
    FieldCipher,
    FileKeyStore,
    KeyringKeyStore,
    KeySource,
    KeyStore,
    KeyStoreUnavailable,
    default_key_stores,
    load_or_create_key,
)


class MemoryKeyStore(KeyStore):
    source = KeySource.KEYCHAIN

    def __init__(self, key: bytes | None = None, available: bool = True) -> None:
        self.key = key
        self.available = available
        self.saved = 0

    def load(self):
        if not self.available:
            raise KeyStoreUnavailable("없음")
        return self.key

    def save(self, key):
        if not self.available:
            raise KeyStoreUnavailable("없음")
        self.key = key
        self.saved += 1

    def delete(self):
        self.key = None


@pytest.fixture
def cipher():
    return FieldCipher(b"k" * KEY_BYTES)


def test_암호화한_값은_같은_키와_같은_칸에서만_풀린다(cipher):
    # given
    text = "GitHub에 가입해 주셔서 감사합니다 — 본문 앞부분"

    # when
    blob = cipher.encrypt(text, "evidence_mails.preview:m1")

    # then
    assert text.encode() not in blob
    assert cipher.decrypt(blob, "evidence_mails.preview:m1") == text


def test_같은_글도_암호화할_때마다_다른_값이_된다(cipher):
    # given
    text = "noreply@github.com"

    # when
    first = cipher.encrypt(text, "c")
    second = cipher.encrypt(text, "c")

    # then
    assert first != second


def test_다른_칸이나_다른_행에_옮겨_붙인_암호문은_풀리지_않는다(cipher):
    # given
    blob = cipher.encrypt("제목", "evidence_mails.subject:m1")

    # when / then
    with pytest.raises(DecryptError):
        cipher.decrypt(blob, "evidence_mails.subject:m2")
    with pytest.raises(DecryptError):
        cipher.decrypt(blob, "evidence_mails.sender:m1")


def test_키가_다르거나_값이_손상되면_DecryptError(cipher):
    # given
    blob = cipher.encrypt("본문", "c")
    other = FieldCipher(b"x" * KEY_BYTES)
    broken = blob[:-1] + bytes([blob[-1] ^ 1])

    # when / then
    with pytest.raises(DecryptError):
        other.decrypt(blob, "c")
    with pytest.raises(DecryptError):
        cipher.decrypt(broken, "c")
    with pytest.raises(DecryptError):
        cipher.decrypt(b"short", "c")


def test_키_길이가_맞지_않으면_만들지_않는다():
    # when / then
    with pytest.raises(ValueError):
        FieldCipher(b"short")


def test_키가_없으면_첫_저장소에_새로_만들고_다음엔_그_키를_쓴다():
    # given
    store = MemoryKeyStore()

    # when
    first = load_or_create_key([store])
    second = load_or_create_key([store])

    # then
    assert first.created and not second.created
    assert first.key == second.key and len(first.key) == KEY_BYTES
    assert first.source is KeySource.KEYCHAIN
    assert store.saved == 1


def test_키체인을_쓸_수_없으면_키_파일로_대신한다(tmp_path):
    # given
    keychain = MemoryKeyStore(available=False)
    file_store = FileKeyStore(tmp_path / "evidence.key")

    # when
    loaded = load_or_create_key([keychain, file_store])

    # then
    assert loaded.source is KeySource.FILE
    assert file_store.load() == loaded.key
    assert load_or_create_key([keychain, file_store]).key == loaded.key


def test_저장된_키가_손상됐으면_새_키를_만든다(tmp_path):
    # given
    path = tmp_path / "evidence.key"
    path.write_text("not-base64!!", encoding="ascii")

    # when
    loaded = load_or_create_key([FileKeyStore(path)])

    # then
    assert loaded.created
    assert FileKeyStore(path).load() == loaded.key


def test_어느_저장소도_쓸_수_없으면_KeyStoreUnavailable():
    # when / then
    with pytest.raises(KeyStoreUnavailable):
        load_or_create_key([MemoryKeyStore(available=False)])


@pytest.mark.skipif(sys.platform == "win32", reason="Windows는 POSIX 권한이 없다")
def test_키_파일은_본인만_읽을_수_있다(tmp_path):
    # given
    store = FileKeyStore(tmp_path / "evidence.key")

    # when
    store.save(b"k" * KEY_BYTES)

    # then
    assert os.stat(store.path).st_mode & 0o777 == 0o600


def test_환경변수로_키_파일만_쓰게_할_수_있다(tmp_path, monkeypatch):
    # given
    monkeypatch.setenv("ACCOUNT_CLEANER_KEY_STORE", "file")

    # when
    stores = default_key_stores(tmp_path / "evidence.key")

    # then
    assert [type(s) for s in stores] == [FileKeyStore]


def test_기본은_키체인을_먼저_쓰고_키_파일은_대체용이다(tmp_path, monkeypatch):
    # given
    monkeypatch.delenv("ACCOUNT_CLEANER_KEY_STORE", raising=False)

    # when
    stores = default_key_stores(tmp_path / "evidence.key")

    # then
    assert [type(s) for s in stores] == [KeyringKeyStore, FileKeyStore]


def test_키체인_백엔드가_없으면_KeyStoreUnavailable로_알린다(monkeypatch):
    # given
    import keyring
    from keyring.backends import fail

    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())

    # when / then
    with pytest.raises(KeyStoreUnavailable):
        KeyringKeyStore().load()


def test_키체인_백엔드_오류는_KeyStoreUnavailable로_바꾼다(monkeypatch):
    # given
    import keyring

    class Broken:
        priority = 5

        def get_password(self, *_):
            raise RuntimeError("dbus 없음")

        def set_password(self, *_):
            raise RuntimeError("잠김")

    monkeypatch.setattr(keyring, "get_keyring", lambda: Broken())

    # when / then
    with pytest.raises(KeyStoreUnavailable):
        KeyringKeyStore().load()
    with pytest.raises(KeyStoreUnavailable):
        KeyringKeyStore().save(b"k" * KEY_BYTES)
