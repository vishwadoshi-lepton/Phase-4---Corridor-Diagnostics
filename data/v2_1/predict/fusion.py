"""PredictionFusion — reconcile TimesFM forecast with v2.1 prior.

Inputs per segment:
    - verdict           v2.1 final verdict (HEAD_BOTTLENECK / ACTIVE_BOTTLENECK / ...)
    - confidence        v2.1 R7 confidence dict (score + label)
    - recurrence        v2.1 Stage 6 dict (frac, label)
    - historical_onsets list of historical onset minutes (same weekday window)
    - predicted_regimes list of predicted regimes at t+2, t+4, ..., t+90
    - anchor_min        the anchor minute-of-day

Outputs per segment:
    - skipped           true if v2.1 says FREE_FLOW with HIGH confidence
    - congestion_onset_predicted    minute-of-day when tf-forecast first hits CONG,
                                    or None if never within horizon
    - congestion_onset_typical      median historical onset (from onsets), or None
    - agreement         "AGREE" | "EARLIER_THAN_USUAL" | "LATER_THAN_USUAL" |
                        "NO_HISTORICAL" | "NO_PREDICTED"
    - fusion_note       short string for the UI tooltip
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import median
from typing import List, Optional

from . import config as C


ONSET_AGREEMENT_TOL_MIN = 20  # within ±20 min → AGREE


@dataclass
class SegmentFusion:
    skipped: bool
    skip_reason: Optional[str]
    congestion_onset_predicted_min: Optional[int]
    congestion_onset_typical_min: Optional[int]
    agreement: str
    fusion_note: str

    def to_dict(self) -> dict:
        return asdict(self)


def _first_congested_step_min(
    predicted_regimes: List[str], anchor_min: int
) -> Optional[int]:
    """Return minute-of-day when the forecast first enters CONGESTED or SEVERE."""
    for k, r in enumerate(predicted_regimes):
        if r in ("CONGESTED", "SEVERE"):
            return anchor_min + (k + 1) * C.BUCKET_MIN
    return None


def fuse(
    verdict: str,
    confidence_label: str,
    recurrence_label: str,
    historical_onsets: List[int],
    predicted_regimes: List[str],
    anchor_min: int,
) -> SegmentFusion:
    # Gate: skip clearly-free segments with high confidence
    skipped = False
    skip_reason = None
    if verdict == "FREE_FLOW" and confidence_label == "HIGH":
        skipped = True
        skip_reason = "v2.1 says FREE_FLOW with HIGH confidence — forecast not meaningful"

    predicted_onset = _first_congested_step_min(predicted_regimes, anchor_min)

    # Filter historical onsets to those within the forecast window [anchor, anchor+horizon].
    # This answers "did this segment typically congest in a window like this one?"
    # — NOT "what's the all-time-of-day average onset?".
    window_end = anchor_min + C.HORIZON_MIN
    in_window = [o for o in historical_onsets if anchor_min <= o <= window_end]
    typical_onset: Optional[int] = None
    if in_window:
        typical_onset = int(median(in_window))

    # Agreement assessment
    if predicted_onset is None and typical_onset is None:
        agreement = "NO_HISTORICAL"
        note = "No typical onset in history; forecast shows no congestion in horizon."
    elif predicted_onset is None and typical_onset is not None:
        agreement = "NO_PREDICTED"
        note = (
            f"Historically congested around {typical_onset // 60:02d}:{typical_onset % 60:02d}, "
            f"but forecast shows no congestion in next {C.HORIZON_MIN} min."
        )
    elif predicted_onset is not None and typical_onset is None:
        agreement = "NO_HISTORICAL"
        note = (
            f"Forecast shows congestion at "
            f"{predicted_onset // 60:02d}:{predicted_onset % 60:02d}; "
            "no historical onset pattern to compare."
        )
    else:
        delta = predicted_onset - typical_onset  # type: ignore[operator]
        if abs(delta) <= ONSET_AGREEMENT_TOL_MIN:
            agreement = "AGREE"
            note = (
                f"Forecast onset {predicted_onset // 60:02d}:{predicted_onset % 60:02d}  "
                f"matches typical {typical_onset // 60:02d}:{typical_onset % 60:02d} "
                f"(Δ {delta:+d} min)."
            )
        elif delta < 0:
            agreement = "EARLIER_THAN_USUAL"
            note = (
                f"Forecast onset {predicted_onset // 60:02d}:{predicted_onset % 60:02d} "
                f"is {-delta} min earlier than typical — possible unusual pressure."
            )
        else:
            agreement = "LATER_THAN_USUAL"
            note = (
                f"Forecast onset {predicted_onset // 60:02d}:{predicted_onset % 60:02d} "
                f"is {delta} min later than typical."
            )

    return SegmentFusion(
        skipped=skipped,
        skip_reason=skip_reason,
        congestion_onset_predicted_min=predicted_onset,
        congestion_onset_typical_min=typical_onset,
        agreement=agreement,
        fusion_note=note,
    )
