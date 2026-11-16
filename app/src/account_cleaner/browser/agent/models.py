from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class AgentStatus(StrEnum):
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    REACHED_WITHDRAWAL = "reached_withdrawal"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Action(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    WAIT_FOR = "wait_for"
    REACH_TARGET = "reach_target"


@dataclass(frozen=True)
class Step:
    action: Action
    value: str
    description: str = ""
    fallback_texts: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        return cls(
            action=Action(data["action"]),
            value=data["value"],
            description=data.get("description", ""),
            fallback_texts=tuple(data.get("fallback_texts", ())),
        )


@dataclass(frozen=True)
class Playbook:
    service_id: str
    display_name: str
    entry_url: str
    allowed_domains: tuple[str, ...]
    steps: tuple[Step, ...]
    auth_domains: tuple[str, ...] = ()
    version: str = "1"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Playbook:
        return cls(
            service_id=data["service_id"],
            display_name=data["display_name"],
            entry_url=data["entry_url"],
            allowed_domains=tuple(data["allowed_domains"]),
            steps=tuple(Step.from_dict(item) for item in data["steps"]),
            auth_domains=tuple(data.get("auth_domains", ())),
            version=str(data.get("version", "1")),
        )


@dataclass(frozen=True)
class AgentResult:
    status: AgentStatus
    service_id: str
    message: str
    next_step: int
    current_url: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LaunchConfig:
    profile_dir: Path
    chrome_path: Path | None = None
    headless: bool = False
    slow_mo_ms: int = 100
