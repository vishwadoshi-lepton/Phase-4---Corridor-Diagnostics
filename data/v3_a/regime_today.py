"""Build today's per-segment regime arrays from today's observations + ff_tt baseline.

Spec §4.4. The output is a 720-element list per segment so v2.1's helper functions
(detect_primary_windows_lenweighted, bertini_activations, systemic_analysis,
systemic_contiguity, head_bottleneck_intervals) can consume it unmodified.

Buckets ABOVE the anchor are padded with TT == ff_tt → regime "FREE", so post-anchor
slots never trigger a false Bertini.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Mapping

from data.corridor_diagnostics_v2 import classify_regimes

from .data_pull import TodayPull
from .progress import IST


BUCKETS_PER_DAY = 720
BUCKET_MIN = 2


def bucket_of(event_time: datetime, day_start: datetime) -> int:
    """Map a tz-aware IST event_time to a 2-min bucket index in [0, 720)."""
    return int((event_time - day_start).total_seconds() // (BUCKET_MIN * 60))


def anchor_bucket_of(anchor_ts: datetime) -> int:
    """The bucket index containing ``anchor_ts``."""
    if anchor_ts.tzinfo is None:
        anchor_ts = anchor_ts.replace(tzinfo=IST)
    day_start = anchor_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return bucket_of(anchor_ts, day_start)


def build_today_tts(
    today: TodayPull,
    *,
    anchor_ts: datetime,
    segment_order: list[str],
    ff_tt_by_seg: Mapping[str, float],
    baseline_profile_by_seg: Mapping[str, Mapping[int, float]],
) -> tuple[dict[str, list[float]], int]:
    """For each segment, build a 720-element list of TT (sec).

    Filling rules:
      * For buckets in [0, anchor_bucket] with one or more today observations:
          take the median of those observations.
      * For buckets in [0, anchor_bucket] WITHOUT today observations:
          forward-fill from the most recent today bucket; if none yet,
          backward-fill from the first today bucket; if today has no obs at
          all, fall back to ``baseline_profile[minute_of_day]``; if even
          baseline lacks that minute, use ``ff_tt``.
      * For buckets > anchor_bucket: TT = ff_tt → regime FREE.

    Returns (today_tts_by_seg, anchor_bucket).
    """
    if anchor_ts.tzinfo is None:
        anchor_ts = anchor_ts.replace(tzinfo=IST)
    day_start = anchor_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    anchor_bucket = bucket_of(anchor_ts, day_start)

    out: dict[str, list[float]] = {}
    for seg in segment_order:
        ff_tt = float(ff_tt_by_seg.get(seg) or 60.0)
        baseline_seg = baseline_profile_by_seg.get(seg, {})

        # Bucketize today's observations
        bucket_obs: dict[int, list[float]] = {}
        for row in today.by_seg.get(seg, []):
            b = bucket_of(row.event_time, day_start)
            if 0 <= b <= anchor_bucket:
                bucket_obs.setdefault(b, []).append(row.travel_time_sec)

        # Forward-fill within [0, anchor_bucket]
        seg_tts: list[float] = [ff_tt] * BUCKETS_PER_DAY  # post-anchor stays at ff_tt
        last_known: float | None = None
        for b in range(anchor_bucket + 1):
            if b in bucket_obs:
                seg_tts[b] = float(statistics.median(bucket_obs[b]))
                last_known = seg_tts[b]
            else:
                if last_known is not None:
                    seg_tts[b] = last_known
                else:
                    minute = b * BUCKET_MIN
                    seg_tts[b] = float(baseline_seg.get(minute, ff_tt))

        # Backward-fill: if there were leading buckets that fell back to baseline
        # but today actually has data, replace the leading-baseline slice with the
        # earliest today observation. This avoids the case where a brief gap at
        # 6:00 makes early-morning regimes look broken.
        if bucket_obs:
            first_today_bucket = min(bucket_obs.keys())
            first_today_tt = float(statistics.median(bucket_obs[first_today_bucket]))
            for b in range(first_today_bucket):
                # only overwrite if we previously fell back to baseline (no last_known yet at that point)
                # since forward-fill handled buckets after first_today_bucket already.
                if seg_tts[b] != ff_tt and seg_tts[b] != last_known:
                    seg_tts[b] = first_today_tt

        out[seg] = seg_tts

    return out, anchor_bucket


def build_today_regimes_and_speeds(
    today: TodayPull,
    *,
    anchor_ts: datetime,
    segment_order: list[str],
    segment_meta: Mapping[str, dict],
    ff_tt_by_seg: Mapping[str, float],
    baseline_profile_by_seg: Mapping[str, Mapping[int, float]],
) -> tuple[dict[str, list[str]], dict[str, list[float]], int]:
    """Wrap ``build_today_tts`` with regime classification + speed conversion.

    Returns (regimes_by_seg, speeds_kmph_by_seg, anchor_bucket).
    """
    tts_by_seg, anchor_bucket = build_today_tts(
        today,
        anchor_ts=anchor_ts,
        segment_order=segment_order,
        ff_tt_by_seg=ff_tt_by_seg,
        baseline_profile_by_seg=baseline_profile_by_seg,
    )

    regimes_by_seg: dict[str, list[str]] = {}
    speeds_by_seg: dict[str, list[float]] = {}
    for seg in segment_order:
        seg_tts = tts_by_seg[seg]
        ff_tt = float(ff_tt_by_seg.get(seg) or 60.0)
        # classify_regimes wants list[int]
        regimes_by_seg[seg] = classify_regimes([int(round(t)) for t in seg_tts], ff_tt)
        length_m = float(segment_meta[seg].get("length_m", 0)) or 1.0
        speeds_by_seg[seg] = [length_m / max(t, 1.0) * 3.6 for t in seg_tts]

    return regimes_by_seg, speeds_by_seg, anchor_bucket


__all__ = [
    "BUCKETS_PER_DAY",
    "BUCKET_MIN",
    "bucket_of",
    "anchor_bucket_of",
    "build_today_tts",
    "build_today_regimes_and_speeds",
]
