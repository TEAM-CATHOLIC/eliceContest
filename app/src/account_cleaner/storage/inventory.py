"""마지막으로 가져온 계정 후보와 근거 메일 저장 (#7, #52, 논의사항 D-08).

- 메일 본문 전체는 저장하지 않는다. 후보의 근거(`evidence[].mail_id`)로 쓰인 메일만 남기고,
  그중에서도 보낸 사람·제목·본문 앞부분(`PREVIEW_CHARS`)만 남긴다.
- 그 세 칸은 `FieldCipher`로 암호화한다. 날짜·메일 ID·후보 정보는 평문이다.
- 한 번에 하나의 결과만 둔다. 새로 가져오면 이전 후보·근거 메일을 모두 바꾼다.
- 키가 바뀌어 근거 메일을 풀 수 없으면 근거 메일 표만 비운다. 후보는 그대로 보인다.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from account_cleaner.contracts import (
    AccountCandidate,
    Evidence,
    EvidenceType,
    LoginMethod,
    ParsedMail,
)
from account_cleaner.storage.crypto import DecryptError, FieldCipher
from account_cleaner.storage.db import Database, from_text, to_text

log = logging.getLogger(__name__)

PREVIEW_CHARS = 600
"""근거 미리보기에 남기는 본문 앞부분 길이. 더 길면 끝에 "…"를 붙여 저장한다."""
ENCRYPTED_FIELDS = ("sender", "subject", "preview")


def context(field_name: str, mail_id: str) -> str:
    """암호문을 칸과 행에 묶는 값 (다른 칸·행에 옮겨 붙이면 풀리지 않는다)."""
    return f"evidence_mails.{field_name}:{mail_id}"


def preview_of(body: str) -> str:
    return body[:PREVIEW_CHARS] + ("…" if len(body) > PREVIEW_CHARS else "")


def evidence_mail_ids(candidates: Iterable[AccountCandidate]) -> set[str]:
    return {e.mail_id for c in candidates for e in c.evidence}


@dataclass(frozen=True)
class SavedInventory:
    source_name: str
    candidates: list[AccountCandidate]
    mails: dict[str, ParsedMail] = field(default_factory=dict)
    """근거 메일 (본문은 앞부분만). 키가 없거나 풀 수 없으면 비어 있다."""
    mails_lost: bool = False
    """저장된 근거 메일을 풀 수 없어 지웠다 (키 분실·변경)"""

    def mail_lookup(self) -> Callable[[str], ParsedMail | None]:
        return self.mails.get


class InventoryStore:
    def __init__(self, db: Database, cipher: FieldCipher | None) -> None:
        """`cipher`가 None이면(키를 둘 곳이 없음) 근거 메일은 저장하지 않고 후보만 저장한다."""
        self._db = db
        self._cipher = cipher

    @property
    def encrypts_mail(self) -> bool:
        return self._cipher is not None

    # --- 저장 ---

    def save(
        self,
        source_name: str,
        candidates: list[AccountCandidate],
        mails: Mapping[str, ParsedMail],
    ) -> int:
        """후보와 근거 메일로 저장 내용을 바꾼다. 저장한 근거 메일 수를 돌려준다."""
        needed = [mails[i] for i in sorted(evidence_mail_ids(candidates)) if i in mails]
        rows = [self._encrypt(m) for m in needed] if self._cipher else []
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM evidence")
            conn.execute("DELETE FROM candidates")
            conn.execute("DELETE FROM evidence_mails")
            conn.executemany(
                "INSERT INTO candidates (domain, position, service, score, first_seen, last_seen,"
                " login_method) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.domain,
                        pos,
                        c.service,
                        c.score,
                        to_text(c.first_seen),
                        to_text(c.last_seen),
                        c.confirmed_login_method.value if c.confirmed_login_method else None,
                    )
                    for pos, c in enumerate(candidates)
                ],
            )
            conn.executemany(
                "INSERT INTO evidence (domain, position, mail_id, type, probability)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (c.domain, pos, e.mail_id, e.type.value, e.probability)
                    for c in candidates
                    for pos, e in enumerate(c.evidence)
                ],
            )
            conn.executemany(
                "INSERT INTO evidence_mails (mail_id, date, sender, subject, preview)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute(
                "INSERT INTO inventory_meta (key, value) VALUES ('source_name', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (source_name,),
            )
        return len(rows)

    def _encrypt(self, mail: ParsedMail) -> tuple:
        assert self._cipher is not None
        values = {
            "sender": mail.sender,
            "subject": mail.subject,
            "preview": preview_of(mail.body_text),
        }
        return (
            mail.id,
            to_text(mail.date),
            *(self._cipher.encrypt(values[f], context(f, mail.id)) for f in ENCRYPTED_FIELDS),
        )

    # --- 읽기 ---

    def load(self) -> SavedInventory | None:
        """저장된 결과. 저장한 적이 없으면 None."""
        conn = self._db.connection()
        meta = conn.execute("SELECT value FROM inventory_meta WHERE key = 'source_name'").fetchone()
        if meta is None:
            return None
        evidence: dict[str, list[Evidence]] = {}
        for r in conn.execute("SELECT * FROM evidence ORDER BY domain, position"):
            evidence.setdefault(r["domain"], []).append(
                Evidence(r["mail_id"], EvidenceType(r["type"]), r["probability"])
            )
        candidates = [
            AccountCandidate(
                service=r["service"],
                domain=r["domain"],
                score=r["score"],
                evidence=tuple(evidence.get(r["domain"], ())),
                first_seen=from_text(r["first_seen"]),
                last_seen=from_text(r["last_seen"]),
                confirmed_login_method=LoginMethod(r["login_method"])
                if r["login_method"]
                else None,
            )
            for r in conn.execute("SELECT * FROM candidates ORDER BY position")
        ]
        mails, lost = self._load_mails()
        return SavedInventory(meta["value"], candidates, mails, lost)

    def _load_mails(self) -> tuple[dict[str, ParsedMail], bool]:
        rows = self._db.connection().execute("SELECT * FROM evidence_mails").fetchall()
        if not rows or self._cipher is None:
            return {}, False
        try:
            mails = {r["mail_id"]: self._decrypt(r) for r in rows}
        except DecryptError:
            log.warning("근거 메일 %d통을 풀 수 없어 지웁니다 (암호화 키가 바뀜)", len(rows))
            self.clear_mails()
            return {}, True
        return mails, False

    def _decrypt(self, row) -> ParsedMail:
        assert self._cipher is not None
        mail_id = row["mail_id"]
        sender, subject, preview = (
            self._cipher.decrypt(row[f], context(f, mail_id)) for f in ENCRYPTED_FIELDS
        )
        return ParsedMail(
            id=mail_id,
            sender=sender,
            sender_domain=sender.rpartition("@")[2].lower(),
            subject=subject,
            date=from_text(row["date"]),
            body_text=preview,
        )

    # --- 지우기 ---

    def clear_mails(self) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM evidence_mails")

    def clear(self) -> None:
        with self._db.transaction() as conn:
            for table in ("evidence", "candidates", "evidence_mails", "inventory_meta"):
                conn.execute(f"DELETE FROM {table}")  # 고정된 표 이름
