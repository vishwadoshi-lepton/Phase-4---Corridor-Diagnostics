"""Day-of-week anomaly track. Spec §8.

Computes percent deviation between today's corridor-summed travel time and the
median same-DOW typical at each 2-min bucket. Self-gating: when fewer than
``min_samples`` (default 3) same-DOW days are available, returns
``{"available": False, ...}`` and the rest of the payload is omitted.
"""

from __future__ import annotations

import statistics
from typing import Mapping

from .baseline import DowSamples


_DOW_NAMES = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def compute_dow_anomaly(
    *,
    today_tts_by_seg: Mapping[str, list[float]],
    dow_samples: DowSamples,
    segment_order: list[str],
    anchor_bucket: int,
    min_samples: int = 3,
) -> dict:
    if not dow_samples.available or dow_samples.n_samples < min_samples:
        return {
            "available": False,
            "n_samples": dow_samples.n_samples,
            "reason": "insufficient_samples",
        }

    n = anchor_bucket + 1

    # today_corridor_tt(b) = sum over segs of today TT at bucket b (if all present)
    today_trace: list[float | None] = []
    for b in range(n):
        total = 0.0
        ok = True
        for seg in segment_order:
            tts = today_tts_by_seg.get(seg)
            if not tts or b >= len(tts):
                ok = False
                break
            total += tts[b]
        today_trace.append(total if ok else None)

    # dow_typical_tt(b) — median across same-DOW days of corridor-sum
    dow_typical: list[float | None] = []
    for b in range(n):
        minute = b * 2
        per_day_sums: list[float] = []
        for day in dow_samples.distinct_days:
            day_total = 0.0
            ok = True
            for seg in segment_order:
                seg_data = dow_samples.by_seg_by_day.get(seg, {})
                day_block = seg_data.get(day, {})
                if minute not in day_block:
                    ok = False
                    break
                day_total += day_block[minute]
            if ok:
                per_day_sums.append(day_total)
        dow_typical.append(float(statistics.median(per_day_sums)) if per_day_sums else None)

    deviation: list[float | None] = []
    for b in range(n):
        if today_trace[b] is None or dow_typical[b] is None or dow_typical[b] <= 0:
            deviation.append(None)
        else:
            deviation.append(100.0 * (today_trace[b] - dow_typical[b]) / dow_typical[b])

    valid_devs = [(b, d) for b, d in enumerate(deviation) if d is not None]
    if valid_devs:
        b_max, _ = max(valid_devs, key=lambda x: abs(x[1]))
        max_dev_bucket = b_max
        max_dev_pct = deviation[b_max]
    else:
        max_dev_bucket = None
        max_dev_pct = None

    return {
        "available": True,
        "n_samples": dow_samples.n_samples,
        "dow": _DOW_NAMES[dow_samples.dow],
        "today_corridor_tt_trace_sec": today_trace,
        "dow_typical_tt_trace_sec": dow_typical,
        "deviation_pct_trace": deviation,
        "max_deviation_bucket": max_dev_bucket,
        "max_deviation_pct": max_dev_pct,
    }


__all__ = ["compute_dow_anomaly"]
