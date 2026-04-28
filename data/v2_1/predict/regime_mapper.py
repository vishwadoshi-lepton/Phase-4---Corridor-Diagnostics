"""Map predicted travel-time-in-seconds to v2.1 regime labels.

Uses the same speed-ratio thresholds v2.1 uses for regime classification:
    speed_ratio = ff_tt / current_tt
    ≥ 0.80  -> FREE
    [0.50, 0.80) -> APPROACHING
    [0.30, 0.50) -> CONGESTED
    < 0.30 -> SEVERE
"""
from __future__ import annotations

from typing import List

from . import config as C


def tt_to_regime(tt_sec: float, ff_tt_sec: float) -> str:
    if ff_tt_sec <= 0 or tt_sec <= 0:
        return "FREE"
    ratio = ff_tt_sec / tt_sec
    if ratio >= C.REGIME_FREE_MIN:
        return "FREE"
    if ratio >= C.REGIME_APPR_MIN:
        return "APPROACHING"
    if ratio >= C.REGIME_CONG_MIN:
        return "CONGESTED"
    return "SEVERE"


def series_to_regimes(tts: List[float], ff_tt_sec: float) -> List[str]:
    return [tt_to_regime(t, ff_tt_sec) for t in tts]
