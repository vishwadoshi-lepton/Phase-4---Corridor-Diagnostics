"""Baseline assembly: 22-weekday typical-day profile + same-DOW samples. Spec §5.4.2 / §5.4.3.

Consumes ``HistoricalAggPull`` from ``data_pull`` (already SQL-aggregated to per
(seg, day, 2-min-bucket) median) and produces the v2.1-compatible ``profile_by_seg``
plus DOW sample metadata.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from .data_pull import HistoricalAggPull
from .errors import InsufficientBaseline


@dataclass
class BaselineResult:
    """The 22-weekday typical-day profile in the v2.1-compatible shape."""

    profile_by_seg: dict[str, dict[int, float]]  # seg -> {minute_of_day -> tt_sec}
    n_actual_days: int
    distinct_days: list[date]
    thin: bool


@dataclass
class DowSamples:
    """Per-day TT samples for the same-DOW deviation track."""

    by_seg_by_day: dict[str, dict[date, dict[int, float]]]
    distinct_days: list[date]
    n_samples: int
    dow: int                 # 1..7 (ISO)
    available: bool


def build_baseline_profile(
    hist: HistoricalAggPull,
    *,
    n_target_days: int = 22,
    min_days: int = 5,
    thin_threshold: int = 14,
) -> BaselineResult:
    """Build the typical-day profile.

    Steps:
        1. Pick the most-recent ``n_target_days`` distinct weekdays from the pull.
        2. For each (seg, minute_of_day), take the median across those days.
        3. If fewer than ``min_days`` days are available → raise ``InsufficientBaseline``.
        4. If fewer than ``thin_threshold`` days are available → set ``thin=True``.

    The returned ``profile_by_seg`` is the exact shape v2.1's ``diagnose_v21`` expects.
    """
    distinct = sorted(hist.distinct_days, reverse=True)[:n_target_days]
    if len(distinct) < min_days:
        raise InsufficientBaseline(
            f"Only {len(distinct)} distinct weekdays available; need >= {min_days}",
            n_actual_days=len(distinct),
            min_days=min_days,
        )

    use_set = set(distinct)
    profile: dict[str, dict[int, float]] = {}
    for seg, by_day in hist.by_seg_by_day.items():
        per_minute: dict[int, list[float]] = {}
        for day, by_minute in by_day.items():
            if day not in use_set:
                continue
            for minute, tt in by_minute.items():
                per_minute.setdefault(minute, []).append(tt)
        profile[seg] = {m: float(statistics.median(tts)) for m, tts in per_minute.items()}

    return BaselineResult(
        profile_by_seg=profile,
        n_actual_days=len(distinct),
        distinct_days=sorted(distinct),
        thin=len(distinct) < thin_threshold,
    )


def build_dow_samples(
    hist: HistoricalAggPull,
    target_dow: int,
    *,
    min_samples: int = 3,
) -> DowSamples:
    """Build same-DOW sample container. ``available`` iff n_samples >= min_samples."""
    distinct = sorted(hist.distinct_days)
    return DowSamples(
        by_seg_by_day=hist.by_seg_by_day,
        distinct_days=distinct,
        n_samples=len(distinct),
        dow=target_dow,
        available=len(distinct) >= min_samples,
    )


__all__ = [
    "BaselineResult",
    "DowSamples",
    "build_baseline_profile",
    "build_dow_samples",
]
