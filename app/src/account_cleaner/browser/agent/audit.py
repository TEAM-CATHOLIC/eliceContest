from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .redaction import redact_sensitive

GENESIS_HASH = "0" * 64


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return redact_sensitive(str(value))


class AuditLog:
    """Append-only, locally stored audit log with a SHA-256 hash chain."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.previous_hash = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        last = self.path.read_text(encoding="utf-8").splitlines()[-1]
        return str(json.loads(last)["hash"])

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "previous_hash": self.previous_hash,
            "event": _sanitize(event),
        }
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        record["hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self.previous_hash = record["hash"]
        return record


def verify_audit_log(path: str | Path) -> bool:
    previous_hash = GENESIS_HASH
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        actual_hash = record.pop("hash")
        if record.get("previous_hash") != previous_hash:
            return False
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != actual_hash:
            return False
        previous_hash = actual_hash
    return True
