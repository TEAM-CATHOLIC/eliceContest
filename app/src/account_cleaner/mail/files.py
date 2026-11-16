"""파일 소스: MBOX, EML, 그리고 그 둘을 담은 폴더·zip (Gmail 테이크아웃 등).

- MBOX는 한 줄씩 읽어 메일 한 통씩 내보낸다. 수 GB 파일도 메모리에 올리지 않는다.
  `mailbox` 모듈은 실제 파일 경로가 필요해 zip 안의 MBOX를 읽을 수 없으므로 직접 나눈다.
- 진행률 단위는 바이트다.
"""

import re
import zipfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from account_cleaner.mail.source import MailSource, RawMail

MBOX_EXTENSIONS = {".mbox", ".mbx"}
EML_EXTENSIONS = {".eml"}
ZIP_EXTENSIONS = {".zip"}
SUPPORTED_EXTENSIONS = MBOX_EXTENSIONS | EML_EXTENSIONS | ZIP_EXTENSIONS

_ESCAPED_FROM = re.compile(rb"^>+From ")


class UnsupportedFileError(ValueError):
    pass


def iter_mbox(stream: IO[bytes]) -> Iterator[tuple[bytes, int]]:
    """MBOX를 메일 단위로 나눈다. (메일 원문, 지금까지 읽은 바이트)를 내보낸다.

    "From "으로 시작하는 줄이 구분선이다. 본문 안의 ">From "은 ">"를 하나 걷어낸다 (mboxrd).
    """
    lines: list[bytes] = []
    consumed = 0
    started = False
    for line in stream:
        consumed += len(line)
        if line.startswith(b"From "):
            if lines:
                yield b"".join(lines), consumed - len(line)
            lines, started = [], True
            continue
        if not started:
            continue
        lines.append(line[1:] if _ESCAPED_FROM.match(line) else line)
    if lines:
        yield b"".join(lines), consumed


def looks_like_mbox(head: bytes) -> bool:
    return head.startswith(b"From ")


@dataclass(frozen=True)
class _Entry:
    """메일 파일 하나 (디스크 파일 또는 zip 안의 파일)."""

    label: str
    kind: str  # "mbox" | "eml"
    size: int
    open: Callable[[], AbstractContextManager[IO[bytes]]]


def _kind_by_name(name: str) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix in MBOX_EXTENSIONS:
        return "mbox"
    if suffix in EML_EXTENSIONS:
        return "eml"
    return None


def _disk_entry(path: Path, kind: str, label: str) -> _Entry:
    return _Entry(label, kind, path.stat().st_size, lambda: path.open("rb"))


def _zip_entries(path: Path) -> list[_Entry]:
    entries = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            kind = _kind_by_name(info.filename)
            if info.is_dir() or kind is None or "__MACOSX/" in info.filename:
                continue

            def opener(name: str = info.filename) -> AbstractContextManager[IO[bytes]]:
                return _ZipMember(path, name)

            entries.append(_Entry(f"{path.name}:{info.filename}", kind, info.file_size, opener))
    return entries


class _ZipMember(AbstractContextManager):
    """zip 안 파일 하나를 열고, 닫을 때 zip도 같이 닫는다."""

    def __init__(self, path: Path, name: str) -> None:
        self._zf = zipfile.ZipFile(path)
        self._fp = self._zf.open(name)

    def __enter__(self) -> IO[bytes]:
        return self._fp

    def __exit__(self, *exc) -> None:
        self._fp.close()
        self._zf.close()


def _collect(path: Path) -> list[_Entry]:
    if path.is_dir():
        entries: list[_Entry] = []
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            if child.suffix.lower() in ZIP_EXTENSIONS:
                entries.extend(_zip_entries(child))
            elif kind := _kind_by_name(child.name):
                entries.append(_disk_entry(child, kind, str(child.relative_to(path.parent))))
        return entries
    suffix = path.suffix.lower()
    if suffix in ZIP_EXTENSIONS:
        return _zip_entries(path)
    if kind := _kind_by_name(path.name):
        return [_disk_entry(path, kind, path.name)]
    # 확장자가 없거나 다르면 내용으로 판단 (테이크아웃 파일 이름이 바뀐 경우 등)
    with path.open("rb") as fp:
        kind = "mbox" if looks_like_mbox(fp.read(5)) else "eml"
    return [_disk_entry(path, kind, path.name)]


class FileMailSource(MailSource):
    """사용자가 고른 파일·폴더들. 진행률 단위는 바이트."""

    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths = [Path(p) for p in paths]
        if not self._paths:
            raise UnsupportedFileError("파일을 고르지 않았습니다.")
        self._entries = [entry for p in self._paths for entry in _collect(p)]
        if not self._entries:
            raise UnsupportedFileError("MBOX·EML 파일을 찾지 못했습니다 (.mbox, .eml, .zip, 폴더).")

    @property
    def name(self) -> str:
        first = self._paths[0].name
        return first if len(self._paths) == 1 else f"{first} 외 {len(self._paths) - 1}개"

    @property
    def file_count(self) -> int:
        return len(self._entries)

    def total(self) -> int:
        return sum(e.size for e in self._entries)

    def __iter__(self) -> Iterator[RawMail]:
        done = 0
        for entry in self._entries:
            with entry.open() as stream:
                if entry.kind == "eml":
                    data = stream.read()
                    yield RawMail(data, entry.label, done + entry.size)
                else:
                    for index, (data, consumed) in enumerate(iter_mbox(stream)):
                        yield RawMail(data, f"{entry.label}#{index}", done + consumed)
            done += entry.size
