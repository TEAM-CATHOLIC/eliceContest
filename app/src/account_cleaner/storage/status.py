"""사용자 확인·탈퇴 진행·재알림·세션 보관 (#8, PRD F-04·F-08, 논의사항 D-05).

서비스 이름과 상태 값만 저장한다 (메일 본문 없음). 상태 값은 문자열로 저장하고, 화면의 열거형
(`CandidateStatus`, `AgentStatus`)으로 바꾸는 일은 화면 쪽이 한다.

D-05 규칙: 탈퇴를 끝낸 서비스의 로그인 세션은 바로 지우고, 끝내지 못한 서비스는 보관 시작부터
`SESSION_RETENTION`이 지나면 지운다.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from account_cleaner.storage.db import Database, from_text, to_text

SESSION_RETENTION = timedelta(days=14)
REMINDER_DELAY = timedelta(days=14)
"""탈퇴 화면까지 갔지만 끝내지 못한 서비스를 다시 알려 줄 때까지의 기간 (F-08, D-05와 같은 주기)."""


@dataclass(frozen=True)
class Progress:
    domain: str
    service: str
    last_result: str
    """마지막 에이전트 결과 (`AgentStatus` 값) 또는 "started" """
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class EventKind(StrEnum):
    """진행 기록에 남기는 일."""

    LABEL = "label"
    """사용자 확인을 바꿈 (detail: 상태 값)"""
    STARTED = "started"
    FINISHED = "finished"
    """에이전트 안내가 끝남 (detail: `AgentStatus` 값)"""
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    SESSION_CLEARED = "session_cleared"
    ALL_SESSIONS_CLEARED = "all_sessions_cleared"


@dataclass(frozen=True)
class HistoryEvent:
    domain: str
    service: str
    at: datetime
    kind: EventKind
    detail: str


SERVICE_OF = (
    "COALESCE((SELECT service FROM withdraw_progress WHERE domain = :domain),"
    " (SELECT service FROM user_labels WHERE domain = :domain), :domain)"
)


class StatusStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _now(self) -> str:
        return to_text(self._db.clock())

    def _event(
        self, conn: sqlite3.Connection, domain: str, kind: EventKind, detail: str = ""
    ) -> None:
        conn.execute(
            f"INSERT INTO progress_events (domain, service, at, kind, detail)"
            f" VALUES (:domain, {SERVICE_OF}, :at, :kind, :detail)",
            {"domain": domain, "at": self._now(), "kind": kind.value, "detail": detail},
        )

    # --- 사용자 확인 (F-04) ---

    def set_label(self, domain: str, service: str, status: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_labels (domain, service, status, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(domain) DO UPDATE SET service = excluded.service,"
                " status = excluded.status, updated_at = excluded.updated_at",
                (domain, service, status, self._now()),
            )
            self._event(conn, domain, EventKind.LABEL, status)

    def labels(self) -> dict[str, str]:
        rows = self._db.connection().execute("SELECT domain, status FROM user_labels")
        return {r["domain"]: r["status"] for r in rows}

    # --- 탈퇴 진행 ---

    def agent_started(
        self, domain: str, service: str, known_mail_ids: set[str] | None = None
    ) -> None:
        """에이전트 안내 시작. 로그인 세션 보관도 이때부터 센다."""
        now = self._now()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO withdraw_progress"
                " (domain, service, last_result, started_at, updated_at) VALUES (?, ?, 'started', ?, ?)"
                " ON CONFLICT(domain) DO UPDATE SET service = excluded.service,"
                " last_result = 'started', started_at = excluded.started_at,"
                " completed_at = NULL, updated_at = excluded.updated_at",
                (domain, service, now, now),
            )
            conn.execute(
                "INSERT INTO sessions (domain, kept_since) VALUES (?, ?) ON CONFLICT(domain) DO NOTHING",
                (domain, now),
            )
            self._event(conn, domain, EventKind.STARTED)
            conn.execute("DELETE FROM completion_watch WHERE domain = ?", (domain,))
            if known_mail_ids is not None:
                conn.execute(
                    "INSERT INTO completion_watch VALUES (?, ?, ?)",
                    (domain, now, json.dumps(sorted(known_mail_ids))),
                )
            conn.execute("DELETE FROM reminders WHERE domain = ?", (domain,))

    def completion_watch(self, domain: str) -> tuple[datetime, set[str]] | None:
        row = (
            self._db.connection()
            .execute(
                "SELECT started_at, known_ids FROM completion_watch WHERE domain = ?", (domain,)
            )
            .fetchone()
        )
        if row is None:
            return None
        return from_text(row["started_at"]), set(json.loads(row["known_ids"]))

    def agent_finished(self, domain: str, result: str, reached: bool) -> None:
        """에이전트가 끝남. 탈퇴 화면에 도착했으면(최종 버튼은 사용자 몫) 재알림을 잡는다."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE withdraw_progress SET last_result = ?, updated_at = ? WHERE domain = ?",
                (result, self._now(), domain),
            )
            self._event(conn, domain, EventKind.FINISHED, result)
            if reached:
                due = to_text(self._db.clock() + REMINDER_DELAY)
                conn.execute(
                    "INSERT INTO reminders (domain, due_at) VALUES (?, ?)"
                    " ON CONFLICT(domain) DO UPDATE SET due_at = excluded.due_at",
                    (domain, due),
                )

    def mark_completed(self, domain: str) -> None:
        """사용자가 탈퇴를 끝냈다고 확인. 재알림은 없애고 세션은 바로 '삭제 대상'이 된다 (D-05)."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE withdraw_progress SET completed_at = ?, updated_at = ? WHERE domain = ?",
                (self._now(), self._now(), domain),
            )
            conn.execute("DELETE FROM reminders WHERE domain = ?", (domain,))
            self._event(conn, domain, EventKind.COMPLETED)

    def progress(self, domain: str) -> Progress | None:
        row = (
            self._db.connection()
            .execute("SELECT * FROM withdraw_progress WHERE domain = ?", (domain,))
            .fetchone()
        )
        return None if row is None else self._progress_of(row)

    @staticmethod
    def _progress_of(row: sqlite3.Row) -> Progress:
        return Progress(
            row["domain"],
            row["service"],
            row["last_result"],
            from_text(row["started_at"]),
            from_text(row["updated_at"]),
            from_text(row["completed_at"]),
        )

    # --- 재알림 (F-08) ---

    def due_reminders(self) -> list[str]:
        """지금 알려야 할 서비스 도메인 (앱이 실행될 때 확인한다)."""
        rows = self._db.connection().execute(
            "SELECT domain FROM reminders WHERE due_at <= ? ORDER BY due_at", (self._now(),)
        )
        return [r["domain"] for r in rows]

    def snooze_reminder(self, domain: str, delay: timedelta = REMINDER_DELAY) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE reminders SET due_at = ? WHERE domain = ?",
                (to_text(self._db.clock() + delay), domain),
            )
            self._event(conn, domain, EventKind.SNOOZED, str(delay.days))

    def reminders(self) -> dict[str, datetime]:
        """재알림이 잡힌 서비스와 알릴 시각 (지난 것 포함)."""
        rows = self._db.connection().execute("SELECT domain, due_at FROM reminders")
        return {r["domain"]: from_text(r["due_at"]) for r in rows}

    # --- 로그인 세션 보관 (D-05) ---

    def sessions_to_clear(self) -> list[str]:
        """지울 세션: 탈퇴를 끝낸 서비스 + 보관 기한이 지난 서비스."""
        expired_before = to_text(self._db.clock() - SESSION_RETENTION)
        rows = self._db.connection().execute(
            "SELECT s.domain FROM sessions s LEFT JOIN withdraw_progress p ON p.domain = s.domain"
            " WHERE p.completed_at IS NOT NULL OR s.kept_since <= ? ORDER BY s.domain",
            (expired_before,),
        )
        return [r["domain"] for r in rows]

    def session_cleared(self, domain: str) -> None:
        with self._db.transaction() as conn:
            if conn.execute("DELETE FROM sessions WHERE domain = ?", (domain,)).rowcount:
                self._event(conn, domain, EventKind.SESSION_CLEARED)

    def clear_all_sessions(self) -> None:
        """'저장된 로그인 모두 지우기' 뒤 기록도 비운다."""
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute(
                "INSERT INTO progress_events (domain, service, at, kind) VALUES ('*', '전체', ?, ?)",
                (self._now(), EventKind.ALL_SESSIONS_CLEARED.value),
            )

    # --- 진행 기록 화면 ---

    def all_progress(self) -> list[Progress]:
        """에이전트 안내를 시작한 적 있는 서비스. 최근에 바뀐 것부터."""
        rows = self._db.connection().execute(
            "SELECT * FROM withdraw_progress ORDER BY updated_at DESC, domain"
        )
        return [self._progress_of(r) for r in rows]

    def history(self, limit: int = 200) -> list[HistoryEvent]:
        """최근 일부터."""
        rows = self._db.connection().execute(
            "SELECT * FROM progress_events ORDER BY at DESC, id DESC LIMIT ?", (limit,)
        )
        return [
            HistoryEvent(
                r["domain"], r["service"], from_text(r["at"]), EventKind(r["kind"]), r["detail"]
            )
            for r in rows
        ]
