"""로컬 SQLite 연결과 스키마 버전 관리.

- 연결은 스레드마다 따로 연다 (SQLite 연결은 스레드끼리 공유하지 않는다).
- 스키마는 `MIGRATIONS` 순서대로 한 번씩만 적용한다. 새 테이블은 목록 끝에 추가한다.
- 메일 본문·후보(#7)는 D-08(암호화·본문 보관) 결정 뒤에 다음 버전으로 추가한다.
"""

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

Clock = Callable[[], datetime]

MIGRATIONS: list[str] = [
    # 1: 사용자 확인·진행·재알림·세션 (#8)
    """
    CREATE TABLE user_labels (
        domain      TEXT PRIMARY KEY,
        service     TEXT NOT NULL,
        status      TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE withdraw_progress (
        domain        TEXT PRIMARY KEY,
        service       TEXT NOT NULL,
        last_result   TEXT NOT NULL,
        started_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        completed_at  TEXT
    );
    CREATE TABLE reminders (
        domain   TEXT PRIMARY KEY,
        due_at   TEXT NOT NULL
    );
    CREATE TABLE sessions (
        domain      TEXT PRIMARY KEY,
        kept_since  TEXT NOT NULL
    );
    """,
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def from_text(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Database:
    def __init__(self, path: Path, clock: Clock = utc_now) -> None:
        self.path = path
        self.clock = clock
        self._local = threading.local()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection()
        with conn:  # 성공하면 commit, 예외면 rollback
            yield conn

    def schema_version(self) -> int:
        return self.connection().execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        conn = self.connection()
        current = self.schema_version()
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            # 한 버전의 테이블 생성과 버전 기록을 한 트랜잭션으로 (중간 실패 시 둘 다 취소)
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
