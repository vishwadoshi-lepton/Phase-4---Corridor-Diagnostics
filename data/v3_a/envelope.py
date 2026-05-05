"""Unified output envelope assembly. Spec §9.

Every key is required and emitted in the order specified in the spec. This is
the single point that v3-A's output passes through; downstream consumers
(Trafficure UI, CLI, replay tooling) can rely on the schema being stable.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime
from typing import Any

from data.v2_1 import corridor_diagnostics_v2_1 as v2_1

from . import ENGINE_VERSION, SCHEMA_VERSION, EngineConfig
from .baseline import BaselineResult, DowSamples
from .progress import IST, now_ist_iso
from .stages_v21 import V21StagesResult


def make_run_id(*, corridor_id: str, anchor_ts: datetime, mode: str, config_signature: str) -> str:
    """Deterministic run_id: same canonical inputs → same id (so cache lookups hit).

    Format: ``v3a-{YYYYMMDDTHHMMSS}-{corridor_id}-{4-hex-suffix}``.
    """
    canonical = f"{corridor_id}|{anchor_ts.isoformat(timespec='seconds')}|{mode}|{config_signature}"
    suffix = hashlib.sha256(canonical.encode()).hexdigest()[:4]
    ts = anchor_ts.strftime("%Y%m%dT%H%M%S")
    return f"v3a-{ts}-{corridor_id}-{suffix}"


def _stages_v21_payload(stages: V21StagesResult, mode: str) -> dict:
    """Hand the v2.1 stages result back as a plain dict in the expected order."""
    typical = stages.typical_v21
    base = v2_1.to_plain_dict(typical)
    if mode == "retrospective":
        return base

    # Mode B: replace the today-side fields, keep everything else from baseline-driven typical
    base["primary_windows_today"] = list(stages.primary_windows_today)
    base["bertini"] = {
        s: list(stages.bertini_today.get(s, [])) for s in typical.segment_order
    }
    base["head_bottleneck"] = list(stages.head_bottleneck_today)
    base["systemic_v2"] = stages.systemic_v2_today
    base["systemic_v21"] = stages.systemic_v21_today
    return base


def build_envelope(
    *,
    corridor_id: str,
    corridor_name: str,
    anchor_ts: datetime,
    mode: str,
    config: EngineConfig,
    stages: V21StagesResult,
    tier1_payloads: dict[str, dict | None],
    dow_anomaly_payload: dict,
    baseline_result: BaselineResult,
    dow_samples: DowSamples,
    warnings: list[dict],
    anchor_ts_received: str,
) -> dict:
    sig = config.signature()
    run_id = make_run_id(
        corridor_id=corridor_id, anchor_ts=anchor_ts, mode=mode, config_signature=sig,
    )
    anchor_bucket = stages.anchor_bucket

    # Hoist any module-internal warnings into meta.warnings
    all_warnings: list[dict] = list(warnings)
    for name, payload in tier1_payloads.items():
        if isinstance(payload, dict):
            for w in payload.pop("warnings", []) or []:
                all_warnings.append(w)

    skipped = [name for name, p in tier1_payloads.items() if p is None]

    partial = bool(all_warnings) or bool(skipped) or any(p is None for p in tier1_payloads.values())

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "mode": mode,
        "corridor_id": corridor_id,
        "corridor_name": corridor_name,
        "anchor_ts": anchor_ts.isoformat(timespec="seconds"),
        "run_id": run_id,
        "computed_at": now_ist_iso(),

        "meta": {
            "anchor_ts_received": anchor_ts_received,
            "anchor_bucket": anchor_bucket,
            "today_date": anchor_ts.date().isoformat(),
            "tz": "Asia/Kolkata",
            "engine_version": ENGINE_VERSION,
            "config_signature": sig,
            "baseline_window": {
                "primary": {
                    "type": "trailing_n_weekdays",
                    "n_target_days": config.baseline_n_weekdays,
                    "n_actual_days": baseline_result.n_actual_days,
                    "start_date": baseline_result.distinct_days[0].isoformat() if baseline_result.distinct_days else None,
                    "end_date": baseline_result.distinct_days[-1].isoformat() if baseline_result.distinct_days else None,
                    "thin_baseline": baseline_result.thin,
                },
                "dow_anomaly": {
                    "type": "same_dow_trailing_n_weeks",
                    "n_weeks_lookback": config.dow_anomaly_n_weeks_lookback,
                    "n_samples": dow_samples.n_samples,
                    "dow": dow_samples.dow,
                    "available": dow_samples.available,
                },
            },
            "stages_run": [
                "s1_freeflow", "s2_regimes_today", "s2b_primary_windows_today",
                "s3_bertini_today", "s4_shockwave", "s5_systemic_today",
                "s6_recurrence", "s7_confidence_verdicts",
            ],
            "tier1_modules_run": [name for name, p in tier1_payloads.items() if p is not None],
            "tier1_modules_skipped": skipped,
            "partial": partial,
            "warnings": all_warnings,
            "errors": [],
        },

        "payload": {
            "stages_v21": _stages_v21_payload(stages, mode),
            "tier1": {name: p for name, p in tier1_payloads.items()},
            "dow_anomaly": dow_anomaly_payload,
        },
    }


__all__ = ["build_envelope", "make_run_id"]
