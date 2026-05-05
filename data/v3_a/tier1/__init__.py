"""Tier-1 module registry. Spec §7.

Modules register themselves on import in fixed order:
    growth_rate → percolation → jam_tree → mfd
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping

from ..progress import ProgressEmitter, StageEvent, now_ist_iso
from ..errors import SoftWarn, Warning_


# --------------------------------------------------------------------------- #
# Context — the immutable input to every Tier-1 module                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BertiniEvent:
    segment_id: str
    segment_idx: int
    t0_bucket: int
    t1_bucket_inclusive: int
    kind: str  # "BERTINI" or "HEAD"
    ordinal: int  # per-segment 1-indexed

    @property
    def event_id(self) -> str:
        return f"{self.kind}-{self.segment_id}-{self.ordinal}"


@dataclass(frozen=True)
class Context:
    corridor_id: str
    corridor_name: str
    anchor_ts: datetime
    anchor_bucket: int
    today_date: date
    segment_order: tuple[str, ...]
    segment_meta: Mapping[str, dict]
    total_length_m: float
    n_buckets: int
    regimes_today_by_idx: tuple[tuple[str, ...], ...]
    regimes_typical_by_idx: tuple[tuple[str, ...], ...]
    bertini_events: tuple[BertiniEvent, ...]
    head_bottleneck_events: tuple[BertiniEvent, ...]
    primary_windows_today: tuple[tuple[int, int], ...]
    historical_onsets_by_seg: Mapping[str, tuple[tuple[date, int], ...]]
    today_onsets_by_seg: Mapping[str, int]
    speed_today_by_idx: tuple[tuple[float, ...], ...]
    ff_speed_kmph_by_seg: Mapping[str, float]
    v21_verdicts: Mapping[str, str]   # seg_id -> v2.1 verdict label (for jam-tree reclassification)
    config: object  # data.v3_a.EngineConfig — avoids circular import


# --------------------------------------------------------------------------- #
# Module ABC and registry                                                      #
# --------------------------------------------------------------------------- #


class Tier1Module(ABC):
    name: str

    @abstractmethod
    def required_inputs(self) -> set[str]:
        """Names of Context attributes the module reads. Documentation only."""

    @abstractmethod
    def run(self, ctx: Context) -> dict:
        """Return the module's payload as a plain dict."""


REGISTRY: list[Tier1Module] = []


def register(module: Tier1Module) -> None:
    REGISTRY.append(module)


def list_modules() -> list[Tier1Module]:
    return list(REGISTRY)


def run_all(ctx: Context, progress: ProgressEmitter) -> tuple[dict[str, dict | None], list[Warning_]]:
    """Run every registered module sequentially.

    On a per-module exception: log a SOFT_WARN_TIER1_<NAME>_FAILED, set the
    payload to None, continue with the next module. Soft contract per spec §11.2.
    """
    payloads: dict[str, dict | None] = {}
    warnings: list[Warning_] = []
    for module in REGISTRY:
        stage = f"tier1.{module.name}"
        progress.emit(StageEvent(run_id="", stage=stage, status="started", ts=now_ist_iso()))
        try:
            payloads[module.name] = module.run(ctx)
            progress.emit(StageEvent(run_id="", stage=stage, status="completed", ts=now_ist_iso()))
        except Exception as exc:  # NOT BaseException — preserve KeyboardInterrupt etc.
            payloads[module.name] = None
            warnings.append(
                Warning_(
                    code=SoftWarn.tier1_failed(module.name),
                    message=str(exc),
                    context={"exception_type": type(exc).__name__},
                )
            )
            progress.emit(
                StageEvent(
                    run_id="",
                    stage=stage,
                    status="failed",
                    ts=now_ist_iso(),
                    detail={"exception": type(exc).__name__, "message": str(exc)},
                )
            )
    return payloads, warnings


# Concrete modules register themselves below. Import order = execution order.
from .growth_rate import GrowthRate  # noqa: E402
from .percolation import Percolation  # noqa: E402
from .jam_tree import JamTree  # noqa: E402
from .mfd import MFD  # noqa: E402

register(GrowthRate())
register(Percolation())
register(JamTree())
register(MFD())


__all__ = [
    "BertiniEvent",
    "Context",
    "Tier1Module",
    "REGISTRY",
    "register",
    "list_modules",
    "run_all",
]
