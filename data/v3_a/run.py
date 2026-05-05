"""Main orchestrator — ``run_diagnostic``. Spec §6 / §10.

Flow:

    validate inputs → pull baseline & DOW & today → run v2.1 stages
        → build Tier-1 Context → run Tier-1 modules → DOW anomaly
        → assemble envelope → return.

Cache and async lifecycle live in ``api.py``; this module is purely synchronous.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from data.v2_1 import corridor_diagnostics_v2_1 as v2_1

from . import EngineConfig, ENGINE_VERSION
from .baseline import BaselineResult, DowSamples, build_baseline_profile, build_dow_samples
from .data_pull import (
    HistoricalAggPull,
    TodayPull,
    pick_connection,
    pull_baseline_aggregated,
    pull_same_dow_aggregated,
    pull_today_observations,
)
from .dow_anomaly import compute_dow_anomaly
from .envelope import build_envelope
from .errors import (
    AnchorPreHistory,
    BadConfig,
    FutureAnchor,
    HardError,
    NoTodayData,
    SoftWarn,
    UnknownCorridor,
    Warning_,
)
from .progress import IST, ListEmitter, NullEmitter, ProgressEmitter, StageEvent, now_ist_iso
from .regime_today import build_today_regimes_and_speeds, build_today_tts
from .stages_v21 import V21StagesResult, run_v21_stages
from .tier1 import BertiniEvent, Context
from .tier1 import run_all as tier1_run_all


log = logging.getLogger("data.v3_a")


# --------------------------------------------------------------------------- #
# Public entry                                                                #
# --------------------------------------------------------------------------- #


def run_diagnostic(
    corridor_id: str,
    anchor_ts: str | datetime,
    *,
    mode: str = "today_as_of_T",
    progress: ProgressEmitter | None = None,
    config: EngineConfig | None = None,
    today_pull_override: TodayPull | None = None,
    baseline_override: BaselineResult | None = None,
    dow_samples_override: DowSamples | None = None,
    raw_onsets_override: list[tuple[str, str, int]] | None = None,
) -> dict:
    """Run a full v3-A diagnostic for one corridor at one anchor.

    The ``*_override`` parameters are for tests — they short-circuit the DB pull
    and let callers inject fixture data. None of them are exposed through the
    CLI/API.
    """
    cfg = config or EngineConfig.default()
    progress = progress or NullEmitter()

    # 1. Validate
    anchor = _normalize_anchor(anchor_ts, progress=progress)
    corridor = _load_corridor(corridor_id)
    chain = corridor["chain"]
    segment_order = [s["road_id"] for s in chain]
    segment_meta = {
        s["road_id"]: {
            "name": s["road_name"],
            "length_m": s["length_m"],
            "road_class": s.get("road_class", "unknown"),
        }
        for s in chain
    }
    corridor_name = corridor["name"]

    # 2. Pull data (or use overrides)
    progress.emit(StageEvent(run_id="", stage="pull_data", status="started", ts=now_ist_iso()))
    if baseline_override is not None and (mode == "retrospective" or today_pull_override is not None):
        baseline = baseline_override
        dow_samples = dow_samples_override or DowSamples({}, [], 0, anchor.isoweekday(), False)
        today_pull = today_pull_override
        raw_onsets = raw_onsets_override
    else:
        baseline, dow_samples, today_pull, raw_onsets = _pull_all(
            corridor_id=corridor_id,
            segment_order=segment_order,
            anchor=anchor,
            mode=mode,
            cfg=cfg,
        )
    progress.emit(StageEvent(run_id="", stage="pull_data", status="completed", ts=now_ist_iso()))

    # 3. Run v2.1 stages
    stages = run_v21_stages(
        corridor_id=corridor_id, corridor_name=corridor_name,
        segment_order=segment_order, segment_meta=segment_meta,
        baseline=baseline, raw_onsets=raw_onsets, today_pull=today_pull,
        anchor_ts=anchor, mode=mode,
    )
    for stage_name in ("s1_freeflow", "s2_regimes_today", "s2b_primary_windows_today",
                       "s3_bertini_today", "s4_shockwave", "s5_systemic_today",
                       "s6_recurrence", "s7_confidence_verdicts"):
        progress.emit(StageEvent(run_id="", stage=stage_name, status="completed", ts=now_ist_iso()))

    # 4. Build Tier-1 Context
    historical_onsets_by_seg = _bucket_historical_onsets(raw_onsets, anchor)
    today_onsets_by_seg = _today_onsets(stages.regimes_today_by_seg, segment_order, stages.anchor_bucket)
    bertini_events = _bertini_event_objects(stages.bertini_today, stages.head_bottleneck_today, segment_order)
    ctx = Context(
        corridor_id=corridor_id,
        corridor_name=corridor_name,
        anchor_ts=anchor,
        anchor_bucket=stages.anchor_bucket,
        today_date=anchor.date(),
        segment_order=tuple(segment_order),
        segment_meta=segment_meta,
        total_length_m=float(sum(segment_meta[s]["length_m"] for s in segment_order)),
        n_buckets=stages.anchor_bucket + 1,
        regimes_today_by_idx=tuple(tuple(stages.regimes_today_by_seg[s]) for s in segment_order),
        regimes_typical_by_idx=tuple(tuple(stages.typical_v21.v2.regimes[s]) for s in segment_order),
        bertini_events=tuple(bertini_events["bertini"]),
        head_bottleneck_events=tuple(bertini_events["head"]),
        primary_windows_today=tuple(stages.primary_windows_today),
        historical_onsets_by_seg=historical_onsets_by_seg,
        today_onsets_by_seg=today_onsets_by_seg,
        speed_today_by_idx=tuple(tuple(stages.speeds_today_kmph_by_seg[s]) for s in segment_order),
        ff_speed_kmph_by_seg={s: float(stages.typical_v21.v2.ff_meta[s]["ff_speed_kmph"]) for s in segment_order},
        v21_verdicts=dict(stages.typical_v21.verdicts),
        config=cfg,
    )

    # 5. Run Tier-1 modules (mode = today_as_of_T only; retrospective skips Tier-1)
    if mode == "today_as_of_T":
        tier1_payloads, tier1_warnings = tier1_run_all(ctx, progress)
        # Compute DOW anomaly using today's bucketed TTs (same as regime_today's input)
        if today_pull is not None:
            today_tts, _ab = build_today_tts(
                today_pull,
                anchor_ts=anchor,
                segment_order=segment_order,
                ff_tt_by_seg={s: float(stages.typical_v21.v2.freeflow[s]) for s in segment_order},
                baseline_profile_by_seg=baseline.profile_by_seg,
            )
        else:
            today_tts = {s: [] for s in segment_order}
        progress.emit(StageEvent(run_id="", stage="dow_anomaly", status="started", ts=now_ist_iso()))
        try:
            dow_payload = compute_dow_anomaly(
                today_tts_by_seg=today_tts,
                dow_samples=dow_samples,
                segment_order=segment_order,
                anchor_bucket=stages.anchor_bucket,
                min_samples=cfg.dow_anomaly_min_samples,
            )
        except Exception as exc:
            dow_payload = {"available": False, "n_samples": dow_samples.n_samples, "reason": "compute_failed"}
            tier1_warnings.append(Warning_(code=SoftWarn.DOW_FAILED, message=str(exc), context={}))
        progress.emit(StageEvent(run_id="", stage="dow_anomaly", status="completed", ts=now_ist_iso()))
    else:
        tier1_payloads = {}
        tier1_warnings = []
        dow_payload = {"available": False, "n_samples": 0, "reason": "retrospective_mode"}

    # 6. Hoist all warnings (today_pull gaps + thin baseline + tier1 + DOW)
    pre_warnings: list[dict] = []
    if today_pull is not None:
        pre_warnings.extend(w.to_dict() for w in today_pull.gap_warnings)
    if baseline.thin:
        pre_warnings.append(Warning_(
            code=SoftWarn.THIN_BASELINE,
            message=f"Only {baseline.n_actual_days} weekdays in baseline",
            context={"n_actual_days": baseline.n_actual_days},
        ).to_dict())
    pre_warnings.extend(w.to_dict() for w in tier1_warnings)

    # 7. Build envelope
    progress.emit(StageEvent(run_id="", stage="envelope_assembly", status="started", ts=now_ist_iso()))
    envelope = build_envelope(
        corridor_id=corridor_id, corridor_name=corridor_name,
        anchor_ts=anchor, mode=mode, config=cfg,
        stages=stages, tier1_payloads=tier1_payloads,
        dow_anomaly_payload=dow_payload,
        baseline_result=baseline, dow_samples=dow_samples,
        warnings=pre_warnings,
        anchor_ts_received=str(anchor_ts),
    )
    progress.emit(StageEvent(run_id="", stage="envelope_assembly", status="completed", ts=now_ist_iso()))
    return envelope


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _normalize_anchor(anchor_ts: str | datetime, *, progress: ProgressEmitter) -> datetime:
    """Parse + bucket-truncate. Validates not-in-future."""
    if isinstance(anchor_ts, str):
        try:
            dt = datetime.fromisoformat(anchor_ts)
        except ValueError as ve:
            raise BadConfig(f"Cannot parse anchor_ts: {anchor_ts}") from ve
    else:
        dt = anchor_ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
        progress.emit(StageEvent(run_id="", stage="anchor_normalize", status="completed", ts=now_ist_iso(),
                                 detail={"warning": "tz_assumed_ist"}))
    # Truncate to bucket start (2-minute grid)
    minute = dt.minute - (dt.minute % 2)
    dt = dt.replace(minute=minute, second=0, microsecond=0)
    if dt > datetime.now(IST):
        raise FutureAnchor(f"anchor_ts {dt.isoformat()} is in the future", hint="Pick a past or current time")
    return dt


def _load_corridor(corridor_id: str) -> dict:
    path = Path(__file__).resolve().parents[1] / "v2_1" / "validation_corridors.json"
    with open(path) as f:
        cors = json.load(f)
    if corridor_id not in cors:
        raise UnknownCorridor(f"corridor_id {corridor_id!r} not found in validation_corridors.json")
    return cors[corridor_id]


def _pull_all(
    *,
    corridor_id: str,
    segment_order: list[str],
    anchor: datetime,
    mode: str,
    cfg: EngineConfig,
) -> tuple[BaselineResult, DowSamples, TodayPull | None, list[tuple[str, str, int]] | None]:
    conn = pick_connection(corridor_id)
    try:
        baseline_pull = pull_baseline_aggregated(conn, segment_order, anchor)
        baseline = build_baseline_profile(
            baseline_pull,
            n_target_days=cfg.baseline_n_weekdays,
            min_days=cfg.baseline_min_weekdays,
            thin_threshold=cfg.baseline_thin_threshold,
        )
        if mode == "today_as_of_T":
            dow_pull = pull_same_dow_aggregated(conn, segment_order, anchor, n_weeks_lookback=cfg.dow_anomaly_n_weeks_lookback)
            dow_samples = build_dow_samples(dow_pull, anchor.isoweekday(), min_samples=cfg.dow_anomaly_min_samples)
            today_pull = pull_today_observations(conn, segment_order, anchor)
            if not today_pull.rows:
                raise NoTodayData(f"No observations for {corridor_id} in [start_of_day, {anchor.isoformat()}]")
        else:
            dow_samples = DowSamples({}, [], 0, anchor.isoweekday(), False)
            today_pull = None
    finally:
        conn.close()

    raw_onsets = _load_filtered_onsets(segment_order, anchor.date())
    return baseline, dow_samples, today_pull, raw_onsets


def _load_filtered_onsets(road_ids: list[str], anchor_date: date) -> list[tuple[str, str, int]] | None:
    """Load cached onsets file and filter to anchor's date constraint.

    For v3-A MVP we use the file-cached ``all_onsets_weekday.json``; for live runs
    callers can refresh it via ``data/v2_1/pull_onsets.py`` before invocation.
    """
    path = Path(__file__).resolve().parents[1] / "v2_1" / "onsets" / "all_onsets_weekday.json"
    if not path.exists():
        return None
    with open(path) as f:
        rows = json.load(f)
    rid_set = set(road_ids)
    cutoff = anchor_date.isoformat()
    return [(r["rid"], r["dt"], int(r["om"])) for r in rows
            if r["rid"] in rid_set and r["dt"] < cutoff]


def _bucket_historical_onsets(
    raw_onsets: list[tuple[str, str, int]] | None,
    anchor: datetime,
) -> dict[str, tuple[tuple[date, int], ...]]:
    """Group raw onsets by segment, dropping any on/after anchor's date."""
    out: dict[str, list[tuple[date, int]]] = {}
    if not raw_onsets:
        return {}
    for sid, dt_str, om in raw_onsets:
        d = date.fromisoformat(dt_str)
        if d >= anchor.date():
            continue
        bucket = om // 2
        out.setdefault(sid, []).append((d, bucket))
    return {s: tuple(sorted(lst)) for s, lst in out.items()}


def _today_onsets(
    regimes_today_by_seg: Mapping[str, list[str]],
    segment_order: list[str],
    anchor_bucket: int,
) -> dict[str, int]:
    """First bucket each seg entered CONG/SEVR today.

    Either bucket 0 (already CONG at start of day) or first FREE/APPR → CONG/SEVR
    transition.
    """
    out: dict[str, int] = {}
    cong = ("CONGESTED", "SEVERE")
    free = ("FREE", "APPROACHING")
    for s in segment_order:
        rs = regimes_today_by_seg.get(s, [])
        if not rs:
            continue
        if rs[0] in cong:
            out[s] = 0
            continue
        for b in range(1, anchor_bucket + 1):
            if rs[b] in cong and rs[b - 1] in free:
                out[s] = b
                break
    return out


def _bertini_event_objects(
    bertini_today: Mapping[str, list[tuple[int, int]]],
    head_today: list[tuple[int, int]],
    segment_order: list[str],
) -> dict[str, list[BertiniEvent]]:
    """Convert v2.1's bare-tuple events to ``BertiniEvent`` instances with stable ordinals."""
    bertini: list[BertiniEvent] = []
    for idx, sid in enumerate(segment_order):
        for ord_, (t0, t1) in enumerate(bertini_today.get(sid, []), start=1):
            bertini.append(BertiniEvent(sid, idx, t0, t1, "BERTINI", ord_))
    head_events: list[BertiniEvent] = []
    if segment_order:
        head_seg = segment_order[0]
        for ord_, (t0, t1) in enumerate(head_today, start=1):
            head_events.append(BertiniEvent(head_seg, 0, t0, t1, "HEAD", ord_))
    return {"bertini": bertini, "head": head_events}


__all__ = ["run_diagnostic"]
