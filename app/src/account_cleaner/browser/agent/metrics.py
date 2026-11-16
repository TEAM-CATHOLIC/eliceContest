from __future__ import annotations

import time
from collections import Counter
from typing import Any

from .models import AgentResult


class SessionMetrics:
    """Collect privacy-safe reliability metrics for one browser-agent session."""

    def __init__(self, service_id: str, clock=time.monotonic):
        self.service_id = service_id
        self._clock = clock
        self._started = clock()
        self._events: Counter[str] = Counter()
        self._visited_steps: set[int] = set()

    def observe(self, event: dict[str, Any]) -> None:
        self._events[str(event.get("status", "unknown"))] += 1
        if "step" in event:
            try:
                self._visited_steps.add(int(event["step"]))
            except (TypeError, ValueError):
                pass

    def finalize(self, result: AgentResult) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "outcome": str(result.status),
            "duration_ms": max(0, round((self._clock() - self._started) * 1000)),
            "steps_observed": len(self._visited_steps),
            "handoff_count": self._events["waiting_for_user"],
            "fallback_count": self._events["fallback_used"],
            "policy_block_count": self._events["blocked"],
            "reached_withdrawal": str(result.status) == "reached_withdrawal",
        }
