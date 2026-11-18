"""로컬 SQLite 연결과 스키마 버전 관리.

- 연결은 스레드마다 따로 연다 (SQLite 연결은 스레드끼리 공유하지 않는다).
- 스키마는 `MIGRATIONS` 순서대로 한 번씩만 적용한다. 새 테이블은 목록 끝에 추가한다.
- 근거 메일의 보낸 사람·제목·본문 앞부분은 암호문(BLOB)으로만 저장한다 (`inventory`, D-08).
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
    # 2: 마지막으로 가져온 계정 후보와 근거 메일 (#7, #52). 메일 본문 전체는 저장하지 않는다.
    """
    CREATE TABLE inventory_meta (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL
    );
    CREATE TABLE candidates (
        domain        TEXT PRIMARY KEY,
        position      INTEGER NOT NULL,
        service       TEXT NOT NULL,
        score         REAL NOT NULL,
        first_seen    TEXT NOT NULL,
        last_seen     TEXT NOT NULL,
        login_method  TEXT
    );
    CREATE TABLE evidence (
        domain       TEXT NOT NULL REFERENCES candidates(domain) ON DELETE CASCADE,
        position     INTEGER NOT NULL,
        mail_id      TEXT NOT NULL,
        type         TEXT NOT NULL,
        probability  REAL NOT NULL,
        PRIMARY KEY (domain, position)
    );
    CREATE TABLE evidence_mails (
        mail_id  TEXT PRIMARY KEY,
        date     TEXT NOT NULL,
        sender   BLOB NOT NULL,
        subject  BLOB NOT NULL,
        preview  BLOB NOT NULL
    );
    """,
    # 3: 진행 기록 (#16). 언제 무엇을 했는지만 남긴다 (메일 내용 없음).
    """
    CREATE TABLE progress_events (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        domain   TEXT NOT NULL,
        service  TEXT NOT NULL,
        at       TEXT NOT NULL,
        kind     TEXT NOT NULL,
        detail   TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX progress_events_at ON progress_events (at);
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
