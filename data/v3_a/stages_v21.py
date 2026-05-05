"""Wrappers over data/v2_1 with anchor-time semantics. Spec §6.

Two paths:

  * ``mode="retrospective"`` — reproduces v2.1's diagnose_v21 byte-for-byte.
    Uses the trailing-22-weekday baseline as the typical-day profile and
    historical onsets, exactly as v2.1 does today. Used for the b1 gate.

  * ``mode="today_as_of_T"`` — runs v2.1 with the baseline (typical-day)
    profile to compute Stage 1 free-flow, recurrence, confidence, verdicts,
    and shockwave (which all ride on historical signal). Then reruns
    Stage 2b primary windows + Stage 3 Bertini + R3 head + Stage 5 systemic
    on today's regimes only. The result keeps both views available so the
    UI can show "structural" + "today" side-by-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from data import corridor_diagnostics_v2 as v2
from data.v2_1 import corridor_diagnostics_v2_1 as v2_1

from .baseline import BaselineResult
from .data_pull import TodayPull
from .regime_today import build_today_regimes_and_speeds


# --------------------------------------------------------------------------- #
# Result container                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class V21StagesResult:
    typical_v21: Any  # v2_1.CorridorDiagnosisV21
    # The "today-side" recomputations. In retrospective mode these mirror typical.
    primary_windows_today: list[tuple[int, int]]
    bertini_today: dict[str, list[tuple[int, int]]]
    head_bottleneck_today: list[tuple[int, int]]
    systemic_v2_today: dict
    systemic_v21_today: dict
    regimes_today_by_seg: dict[str, list[str]]
    speeds_today_kmph_by_seg: dict[str, list[float]]
    anchor_bucket: int


# --------------------------------------------------------------------------- #
# Main entry                                                                  #
# --------------------------------------------------------------------------- #


def run_v21_stages(
    *,
    corridor_id: str,
    corridor_name: str,
    segment_order: list[str],
    segment_meta: dict[str, dict],
    baseline: BaselineResult,
    raw_onsets: list[tuple[str, str, int]] | None,
    today_pull: TodayPull | None,
    anchor_ts: datetime,
    mode: str,
) -> V21StagesResult:
    # 1. Always: run v2.1 on the typical-day baseline. This is v2.1's contract.
    typical = v2_1.diagnose_v21(
        corridor_id,
        corridor_name,
        segment_order,
        segment_meta,
        baseline.profile_by_seg,
        raw_onsets=raw_onsets,
    )

    if mode == "retrospective":
        # No today-side recomputation; the "today" fields mirror the typical fields
        # so the envelope shape stays uniform across modes.
        bertini_typical = {s: list(typical.v2.bertini.get(s, [])) for s in segment_order}
        regimes_typical = {s: list(typical.v2.regimes[s]) for s in segment_order}
        speeds_typical = _speeds_from_typical(typical, segment_meta, segment_order)
        return V21StagesResult(
            typical_v21=typical,
            primary_windows_today=list(typical.primary_windows_v21),
            bertini_today=bertini_typical,
            head_bottleneck_today=list(typical.head_bottleneck),
            systemic_v2_today=dict(typical.v2.systemic),
            systemic_v21_today=dict(typical.systemic_v21),
            regimes_today_by_seg=regimes_typical,
            speeds_today_kmph_by_seg=speeds_typical,
            anchor_bucket=719,  # full day in retrospective mode
        )

    # 2. mode == "today_as_of_T" → recompute today-side stages on today's regimes.
    if today_pull is None:
        raise ValueError("today_pull is required when mode='today_as_of_T'")

    ff_tt_by_seg = {s: float(typical.v2.freeflow[s]) for s in segment_order}
    regimes_today, speeds_today, anchor_bucket = build_today_regimes_and_speeds(
        today_pull,
        anchor_ts=anchor_ts,
        segment_order=segment_order,
        segment_meta=segment_meta,
        ff_tt_by_seg=ff_tt_by_seg,
        baseline_profile_by_seg=baseline.profile_by_seg,
    )

    regimes_by_idx = [regimes_today[s] for s in segment_order]
    lengths_m = [int(segment_meta[s]["length_m"]) for s in segment_order]

    # Stage 2b — length-weighted primary windows on TODAY
    primary_windows_today = v2_1.detect_primary_windows_lenweighted(regimes_by_idx, lengths_m)

    # Stage 3 — Bertini, then R3 head + terminus suppression
    bertini_raw = v2.bertini_activations(regimes_by_idx, primary_windows_today)
    bertini_today: dict[str, list[tuple[int, int]]] = {
        s: list(bertini_raw[i]) for i, s in enumerate(segment_order)
    }
    head_today = list(v2_1.head_bottleneck_intervals(regimes_by_idx, None))
    if segment_order:
        bertini_today[segment_order[0]] = []
        bertini_today[segment_order[-1]] = []

    # Stage 5 — both v2 and v2.1 systemic rules on TODAY
    systemic_v2_today = dict(v2.systemic_analysis(regimes_by_idx))
    systemic_v21_today = dict(v2_1.systemic_contiguity(regimes_by_idx, lengths_m))

    return V21StagesResult(
        typical_v21=typical,
        primary_windows_today=list(primary_windows_today),
        bertini_today=bertini_today,
        head_bottleneck_today=head_today,
        systemic_v2_today=systemic_v2_today,
        systemic_v21_today=systemic_v21_today,
        regimes_today_by_seg=regimes_today,
        speeds_today_kmph_by_seg=speeds_today,
        anchor_bucket=anchor_bucket,
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _speeds_from_typical(typical, segment_meta, segment_order) -> dict[str, list[float]]:
    """Build typical-day speeds (kmph) by length / TT * 3.6 from v2.1's profile_by_seg via ff_meta?

    Actually we don't have per-bucket TTs from typical_v21 directly — only ff_tt and the regimes.
    For retrospective mode this field is informational only; we use ff_speed_kmph as a constant.
    """
    out: dict[str, list[float]] = {}
    for s in segment_order:
        ff_speed = float(typical.v2.ff_meta[s].get("ff_speed_kmph", 0.0))
        out[s] = [ff_speed] * 720
    return out


__all__ = ["V21StagesResult", "run_v21_stages"]
