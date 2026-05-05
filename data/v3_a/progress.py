"""Run lifecycle primitives — RunStatus, StageEvent, RunRecord, ProgressEmitter.

Spec §10.1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Literal, Optional


IST = timezone(timedelta(hours=5, minutes=30))


def now_ist_iso() -> str:
    return datetime.now(IST).isoformat(timespec="milliseconds")


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StageEvent:
    run_id: str
    stage: str
    status: Literal["started", "completed", "skipped", "failed"]
    ts: str
    duration_ms: Optional[int] = None
    detail: Optional[dict] = None

    def to_dict(self) -> dict:
        d: dict = {"run_id": self.run_id, "stage": self.stage, "status": self.status, "ts": self.ts}
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.detail is not None:
            d["detail"] = self.detail
        return d


@dataclass
class RunRecord:
    run_id: str
    corridor_id: str
    anchor_ts: str
    mode: str
    config_signature: str
    status: RunStatus = RunStatus.PENDING
    submitted_at: str = field(default_factory=now_ist_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    events: list[StageEvent] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "corridor_id": self.corridor_id,
            "anchor_ts": self.anchor_ts,
            "mode": self.mode,
            "config_signature": self.config_signature,
            "status": self.status.value,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "events": [e.to_dict() for e in self.events],
            "result": self.result,
            "error": self.error,
        }


class ProgressEmitter(ABC):
    """Abstract callback receiver. Concrete impls live in api.py."""

    @abstractmethod
    def emit(self, event: StageEvent) -> None:
        ...


class NullEmitter(ProgressEmitter):
    """Drops all events. Useful in unit tests where progress is not under test."""

    def emit(self, event: StageEvent) -> None:
        return None


class ListEmitter(ProgressEmitter):
    """Captures events into a list. Useful in tests and for synthesised cache-hit events."""

    def __init__(self) -> None:
        self.events: list[StageEvent] = []

    def emit(self, event: StageEvent) -> None:
        self.events.append(event)


__all__ = [
    "IST",
    "now_ist_iso",
    "RunStatus",
    "StageEvent",
    "RunRecord",
    "ProgressEmitter",
    "NullEmitter",
    "ListEmitter",
]
