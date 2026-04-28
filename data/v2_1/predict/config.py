"""Prediction pipeline configuration.

Defines corridors, held-out replay days, and forecasting hyperparameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


REPO_ROOT = Path(__file__).resolve().parents[3]

V21_DIR          = REPO_ROOT / "data" / "v2_1"
PROFILES_PATH    = V21_DIR / "profiles" / "all_profiles_weekday.json"
ONSETS_PATH      = V21_DIR / "onsets" / "all_onsets_weekday.json"
CORRIDORS_PATH   = V21_DIR / "validation_corridors.json"
DIAGNOSIS_PATH   = REPO_ROOT / "runs" / "v2_1" / "v2_1_validation_weekday_structured.json"

PREDICT_DIR      = V21_DIR / "predict"
HELD_OUT_PATH    = PREDICT_DIR / "held_out_days.json"
FORECASTS_DIR    = PREDICT_DIR / "forecasts"
REPLAY_HTML_DIR  = REPO_ROOT / "docs" / "replay"


# ----- replay parameters -----

BUCKET_MIN        = 2                # minute resolution of the profile
BUCKETS_PER_DAY   = 720              # 1440 / 2

ANCHOR_START_MIN  = 2 * 60           # 02:00 IST — earliest allowed anchor
ANCHOR_END_MIN    = 20 * 60          # 20:00 IST — latest allowed anchor
ANCHOR_STEP_MIN   = 30               # one anchor every 30 min (keeps precompute feasible on CPU)

HORIZON_MIN       = 90               # 90-minute forecast horizon
HORIZON_STEPS     = HORIZON_MIN // BUCKET_MIN   # 45 bucket steps


# ----- context policy (C2: history + today-so-far) -----

HISTORY_DAYS_CONCAT = 1              # N same-weekday history days (lowered from 7 to keep
                                     # TimesFM context ≤1200 samples for CPU-feasible latency)
MIN_OBSERVED_CTX    = 60             # min samples of today-so-far required to run prediction


# ----- regime thresholds (v2.1 consistent) -----
# speed_ratio = ff_tt / current_tt
REGIME_FREE_MIN = 0.80
REGIME_APPR_MIN = 0.50
REGIME_CONG_MIN = 0.30


REGIMES = ["FREE", "APPROACHING", "CONGESTED", "SEVERE"]
REGIME_COLOR = {
    "FREE":        "#22c55e",
    "APPROACHING": "#fbbf24",
    "CONGESTED":   "#f97316",
    "SEVERE":      "#dc2626",
}


# ----- held-out day selection -----
# One held-out day per corridor. Pick dates that are NOT in the primary training window
# but are still inside the onsets/profile data span (mid-to-late April 2026).
# Selection rule: pick the most recent 3 weekdays that also appear in the onsets table,
# so that there's real per-day onset data for them. These will be excluded from the
# "history" context and used as the replay ground truth.

HELD_OUT_DATES: List[str] = [
    "2026-04-21",  # Tuesday
    "2026-04-22",  # Wednesday
    "2026-04-23",  # Thursday (today)
]


# ----- quantile bands we care about in the UI -----
Q10_IDX = 1
Q50_IDX = 5
Q90_IDX = 9


# ----- corridors to include in the prediction demo -----
# Default: all validation corridors.
CORRIDORS_TO_RUN: List[str] = ["PUNE_A", "PUNE_B", "PUNE_C", "KOL_A", "KOL_B", "KOL_C"]


@dataclass
class PredictConfig:
    bucket_min: int = BUCKET_MIN
    buckets_per_day: int = BUCKETS_PER_DAY
    anchor_start_min: int = ANCHOR_START_MIN
    anchor_end_min: int = ANCHOR_END_MIN
    anchor_step_min: int = ANCHOR_STEP_MIN
    horizon_min: int = HORIZON_MIN
    horizon_steps: int = HORIZON_STEPS
    history_days_concat: int = HISTORY_DAYS_CONCAT
    min_observed_ctx: int = MIN_OBSERVED_CTX
    corridors: List[str] = field(default_factory=lambda: list(CORRIDORS_TO_RUN))
    held_out_dates: List[str] = field(default_factory=lambda: list(HELD_OUT_DATES))


CFG = PredictConfig()


def anchor_ticks_min() -> List[int]:
    """Return the list of anchor minute-of-day values we precompute forecasts at."""
    step = CFG.anchor_step_min
    out: List[int] = []
    t = CFG.anchor_start_min
    while t <= CFG.anchor_end_min:
        out.append(t)
        t += step
    return out


def mod_to_clock(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"
