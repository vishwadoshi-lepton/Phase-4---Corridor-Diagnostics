"""LiveContextBuilder — assemble per-segment context for the forecaster.

C2 policy: context = N same-weekday history days (weekday median, concatenated)
+ today-so-far (from the held-out-day trace, sliced up to anchor_min).

The history portion is reconstructed from the weekday-median profile (same
value each of the N days, reflecting that the v2.1 pipeline stored medians
rather than per-day traces). When real probe data is available, this module
swaps in actual past-days pulled from traffic_observation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from . import config as C


@dataclass
class SegmentContext:
    segment_idx: str
    rid: str
    context: np.ndarray            # float32, length = N_hist*720 + anchor_bucket
    context_len: int
    observed_today_len: int        # how many samples from today-so-far (for logging)


def build_segment_context(
    profile: Dict[int, float],
    today_trace: List[float],
    anchor_min: int,
    n_history_days: int = C.HISTORY_DAYS_CONCAT,
) -> SegmentContext:
    """Assemble context for one segment at one anchor.

    Args:
        profile: weekday-median profile {min_of_day: tt_sec}
        today_trace: full 720-bucket trace for the held-out day
        anchor_min: minute-of-day of the anchor (e.g. 840 = 14:00)
        n_history_days: how many same-weekday history days to prepend
    """
    profile_arr = np.array(
        [profile.get(i * C.BUCKET_MIN, 0.0) for i in range(C.BUCKETS_PER_DAY)],
        dtype=np.float32,
    )
    history = np.tile(profile_arr, n_history_days)
    anchor_bucket = anchor_min // C.BUCKET_MIN
    today_so_far = np.array(today_trace[:anchor_bucket], dtype=np.float32)
    ctx = np.concatenate([history, today_so_far])
    return SegmentContext(
        segment_idx="",
        rid="",
        context=ctx,
        context_len=len(ctx),
        observed_today_len=len(today_so_far),
    )


def build_corridor_context(
    corridor_chain: List[dict],
    profiles: Dict[str, Dict[int, float]],
    held_out_segments: Dict[str, List[float]],
    anchor_min: int,
) -> List[SegmentContext]:
    """Return one SegmentContext per chain segment, in chain order."""
    out: List[SegmentContext] = []
    for i, seg in enumerate(corridor_chain):
        rid = seg["road_id"]
        sc = build_segment_context(
            profile=profiles.get(rid, {}),
            today_trace=held_out_segments[rid],
            anchor_min=anchor_min,
        )
        sc.segment_idx = f"S{i+1:02d}"
        sc.rid = rid
        out.append(sc)
    return out
