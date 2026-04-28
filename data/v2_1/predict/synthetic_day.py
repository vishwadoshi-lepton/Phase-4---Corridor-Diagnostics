"""Synthesize a held-out day's full 2-min travel-time trace per segment.

Since raw per-day rows aren't in the repo and Postgres isn't reachable in this
environment, we deterministically synthesise a realistic held-out day by:
  1. Taking the weekday median profile as the baseline.
  2. Adding seeded Gaussian noise (amplitude scaled by local profile slope).
  3. Injecting a small "today is slightly different" perturbation: the PM peak
     is shifted +/- 10 min vs. the median, with per-day magnitude variation.
  4. If the segment has a historical onset on the held-out date (from onsets),
     lock the onset to match that time (pull forward the regime transition).

The result is labelled as SYNTHETIC in the downstream UI so nobody thinks this
is a real probe trace. When real DB access is available, this module is
replaced by a direct pull from traffic_observation keeping the same output
shape.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List

import numpy as np

from . import config as C
from .data_loader import (
    load_corridors, load_profiles, load_onsets, onsets_by_rid_date,
)


# ----- RNG seeding: deterministic per (rid, date) -----

def _seed_for(rid: str, date_str: str) -> int:
    h = hashlib.sha256(f"{rid}|{date_str}".encode()).hexdigest()
    return int(h[:8], 16)


def _rng(rid: str, date_str: str) -> np.random.Generator:
    return np.random.default_rng(_seed_for(rid, date_str))


# ----- per-segment trace synthesis -----

def synthesise_trace(
    rid: str,
    date_str: str,
    median_profile: Dict[int, float],
    onset_min: int | None = None,
) -> List[float]:
    """Produce a len=720 trace of travel-time-in-seconds for the given (rid, date).

    Args:
        rid: road_id
        date_str: ISO date (e.g. '2026-04-21')
        median_profile: {min_of_day: tt_sec} from weekday medians, 720 buckets
        onset_min: if known from the onsets table for this exact date, we align
                   the transition to match.

    Returns:
        List of 720 travel-time floats in seconds.
    """
    rng = _rng(rid, date_str)
    trace = np.zeros(C.BUCKETS_PER_DAY, dtype=np.float32)
    median = np.array([median_profile.get(i * C.BUCKET_MIN, 0.0) for i in range(C.BUCKETS_PER_DAY)])

    # baseline noise: ~4% of local tt (heavier where tt is high = noisy peaks)
    noise = rng.normal(0.0, median * 0.04)

    # timing jitter: shift the profile by a random ±10 min on this day
    #   positive shift = later onset; negative = earlier
    jitter_buckets = int(rng.normal(0.0, 3.0))  # ~2σ = 12 min jitter
    jitter_buckets = max(-8, min(8, jitter_buckets))
    shifted = np.roll(median, jitter_buckets)

    # magnitude scaling: this day's peaks are ±15% of the median peaks
    mag = 1.0 + rng.normal(0.0, 0.08)
    mag = max(0.80, min(1.25, mag))

    # compose the day's raw trace
    trace = shifted * mag + noise
    trace = np.maximum(trace, median.min() * 0.9)  # never dip below reasonable

    # if we know the historical onset for this exact day, enforce it —
    # nudge a sharp rise exactly at that minute so the replay has a
    # "truthful" onset event matching the onsets table
    if onset_min is not None:
        bkt = onset_min // C.BUCKET_MIN
        bkt = max(0, min(C.BUCKETS_PER_DAY - 1, bkt))
        # gentle blend: push local tt upward for a 30-min post-onset window
        decay = np.zeros_like(trace)
        for k in range(15):  # 30 min @ 2-min step
            idx = bkt + k
            if idx >= C.BUCKETS_PER_DAY:
                break
            decay[idx] = max(0.0, 1.0 - k / 15.0)
        local_peak = float(median[bkt : bkt + 15].max() if bkt + 15 < len(median) else median[-1])
        trace = trace + decay * local_peak * 0.15

    return trace.tolist()


# ----- orchestration: build held_out_days.json -----

@dataclass
class SegTrace:
    rid: str
    road_name: str
    segment_idx: str
    length_m: int
    road_class: str
    trace: List[float]          # 720 values, tt_sec per 2-min bucket
    onset_min: int | None       # if observed in onsets for this date


@dataclass
class HeldOutDay:
    corridor_id: str
    corridor_name: str
    city: str
    date: str
    source: str                 # "synthetic" | "postgres"
    segments: List[SegTrace]


def build_held_out_days() -> Dict[str, Dict[str, HeldOutDay]]:
    """Return {corridor_id: {date_str: HeldOutDay}}."""
    corridors = load_corridors()
    profiles = load_profiles()
    onsets = load_onsets()
    onsets_idx = onsets_by_rid_date(onsets)

    out: Dict[str, Dict[str, HeldOutDay]] = {}

    for cid in C.CFG.corridors:
        if cid not in corridors:
            continue
        cdef = corridors[cid]
        out[cid] = {}

        for date_str in C.CFG.held_out_dates:
            segs: List[SegTrace] = []
            for i, seg in enumerate(cdef["chain"]):
                rid = seg["road_id"]
                prof = profiles.get(rid, {})
                onset_min = onsets_idx.get(rid, {}).get(date_str)

                trace = synthesise_trace(rid, date_str, prof, onset_min)

                segs.append(SegTrace(
                    rid=rid,
                    road_name=seg["road_name"],
                    segment_idx=f"S{i+1:02d}",
                    length_m=int(seg["length_m"]),
                    road_class=seg["road_class"],
                    trace=trace,
                    onset_min=onset_min,
                ))

            out[cid][date_str] = HeldOutDay(
                corridor_id=cid,
                corridor_name=cdef["name"],
                city=cdef["city"],
                date=date_str,
                source="synthetic",
                segments=segs,
            )

    return out


def save_held_out_days(out: Dict[str, Dict[str, HeldOutDay]]) -> None:
    serialisable = {
        cid: {
            d: {
                **{k: v for k, v in asdict(hod).items() if k != "segments"},
                "segments": [asdict(s) for s in hod.segments],
            }
            for d, hod in by_date.items()
        }
        for cid, by_date in out.items()
    }
    C.HELD_OUT_PATH.write_text(json.dumps(serialisable))


if __name__ == "__main__":
    C.PREDICT_DIR.mkdir(parents=True, exist_ok=True)
    out = build_held_out_days()
    save_held_out_days(out)
    total_traces = sum(len(hod.segments) for by_date in out.values() for hod in by_date.values())
    print(f"Wrote {C.HELD_OUT_PATH}: {len(out)} corridors × {len(C.CFG.held_out_dates)} dates = {total_traces} traces")
