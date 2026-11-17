"""근거 메일 칸 단위 암호화 (#52, 논의사항 D-08).

- 암호화: AES-256-GCM. 저장 형식은 `nonce(12바이트) + 암호문·태그`.
- 암호문마다 "어느 칸·어느 행"인지(`context`)를 함께 묶는다(AAD). 다른 칸에 옮겨 붙인 값은 풀리지 않는다.
- 키: OS 키체인(macOS 키체인, Windows 자격 증명 관리자, 리눅스 Secret Service)에 둔다.
  키체인을 쓸 수 없으면 앱 데이터 폴더의 키 파일로 대신하고 `KeySource.FILE`로 알린다.
- 복구 키는 없다. 키를 잃으면 근거 메일 표만 비우고 메일을 다시 불러온다.
"""

import base64
import logging
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

KEY_BYTES = 32
NONCE_BYTES = 12
KEYRING_SERVICE = "account-cleaner"
KEYRING_USERNAME = "evidence-field-key"
KEY_STORE_ENV = "ACCOUNT_CLEANER_KEY_STORE"
"""`file`이면 키체인을 건너뛰고 키 파일을 쓴다 (개발·테스트용)."""


class DecryptError(Exception):
    """키가 다르거나 값이 손상돼 풀 수 없다."""


class KeyStoreUnavailable(Exception):
    """이 환경에서는 이 저장소를 쓸 수 없다 (키체인 없음 등)."""


class KeySource(StrEnum):
    KEYCHAIN = "keychain"
    FILE = "file"

    @property
    def label(self) -> str:
        return {KeySource.KEYCHAIN: "OS 키체인", KeySource.FILE: "키 파일"}[self]


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError(f"키 길이는 {KEY_BYTES}바이트여야 합니다")
        self._aead = AESGCM(key)

    def encrypt(self, text: str, context: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, text.encode("utf-8"), context.encode("utf-8"))

    def decrypt(self, blob: bytes, context: str) -> str:
        if len(blob) <= NONCE_BYTES:
            raise DecryptError("암호문이 너무 짧습니다")
        nonce, body = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
        try:
            return self._aead.decrypt(nonce, body, context.encode("utf-8")).decode("utf-8")
        except InvalidTag as e:
            raise DecryptError("키가 다르거나 값이 손상됐습니다") from e


# --- 키 저장소 ---


def encode_key(key: bytes) -> str:
    return base64.b64encode(key).decode("ascii")


def decode_key(text: str) -> bytes:
    key = base64.b64decode(text.strip(), validate=True)
    if len(key) != KEY_BYTES:
        raise ValueError("저장된 키의 길이가 맞지 않습니다")
    return key


class KeyStore(ABC):
    source: KeySource

    @abstractmethod
    def load(self) -> bytes | None:
        """저장된 키. 없으면 None. 쓸 수 없는 환경이면 `KeyStoreUnavailable`."""

    @abstractmethod
    def save(self, key: bytes) -> None: ...

    @abstractmethod
    def delete(self) -> None: ...


class KeyringKeyStore(KeyStore):
    source = KeySource.KEYCHAIN

    def __init__(self, service: str = KEYRING_SERVICE, username: str = KEYRING_USERNAME) -> None:
        self.service = service
        self.username = username

    def _backend(self):
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 0) <= 0:
            raise KeyStoreUnavailable(f"쓸 수 있는 키체인이 없습니다 ({type(backend).__name__})")
        return backend

    def load(self) -> bytes | None:
        try:
            text = self._backend().get_password(self.service, self.username)
        except KeyStoreUnavailable:
            raise
        except Exception as e:  # 백엔드마다 오류 종류가 다르다 (D-Bus 없음, 잠김 등)
            raise KeyStoreUnavailable(f"키체인을 읽지 못했습니다 ({type(e).__name__})") from e
        return decode_key(text) if text else None

    def save(self, key: bytes) -> None:
        try:
            self._backend().set_password(self.service, self.username, encode_key(key))
        except KeyStoreUnavailable:
            raise
        except Exception as e:
            raise KeyStoreUnavailable(f"키체인에 저장하지 못했습니다 ({type(e).__name__})") from e

    def delete(self) -> None:
        from keyring.errors import PasswordDeleteError

        try:
            self._backend().delete_password(self.service, self.username)
        except (KeyStoreUnavailable, PasswordDeleteError):  # 처음부터 없던 키
            log.info("지울 키가 키체인에 없습니다")


class FileKeyStore(KeyStore):
    """키체인이 없을 때만 쓴다. 파일 권한을 본인만 읽게 둔다 (Windows는 사용자 폴더 권한에 맡김)."""

    source = KeySource.FILE

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> bytes | None:
        if not self.path.is_file():
            return None
        return decode_key(self.path.read_text(encoding="ascii"))

    def save(self, key: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(encode_key(key))

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class LoadedKey:
    key: bytes
    source: KeySource
    created: bool
    """이번에 새로 만든 키면 True (전에 암호화한 값이 있었다면 풀 수 없다)"""

    def cipher(self) -> FieldCipher:
        return FieldCipher(self.key)


def default_key_stores(key_file: Path) -> list[KeyStore]:
    if os.environ.get(KEY_STORE_ENV, "").lower() == "file":
        return [FileKeyStore(key_file)]
    return [KeyringKeyStore(), FileKeyStore(key_file)]


def load_or_create_key(stores: list[KeyStore]) -> LoadedKey:
    """앞에서부터 쓸 수 있는 저장소의 키를 쓴다. 키가 없으면 그 저장소에 새로 만든다.

    읽을 수 없는 키(손상)는 새 키로 바꾼다. 이전 암호문은 풀리지 않으므로 호출한 쪽이 정리한다.
    """
    for store in stores:
        try:
            try:
                key = store.load()
            except ValueError:
                log.warning("%s의 키를 읽지 못해 새로 만듭니다", store.source.label)
                key = None
            if key is not None:
                return LoadedKey(key, store.source, created=False)
            key = secrets.token_bytes(KEY_BYTES)
            store.save(key)
            return LoadedKey(key, store.source, created=True)
        except (KeyStoreUnavailable, OSError) as e:
            log.warning("%s 사용 불가: %s", store.source.label, e)
    raise KeyStoreUnavailable("암호화 키를 둘 곳이 없습니다")
