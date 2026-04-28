"""Precompute forecasts for every (corridor, held-out-day, anchor) combination.

Output: one JSON per (corridor, date) in data/v2_1/predict/forecasts/,
consumed by the HTML replay renderer.

Batching strategy:
  Forecasts are made per (date, anchor) — all corridors' segments are concatenated
  into a single batched forecast call, then demultiplexed back per corridor.
  This amortises the model's fixed per-call overhead (~2-3s on CPU).

Usage:
    python3 -m data.v2_1.predict.precompute            # uses TimesFM if installed
    python3 -m data.v2_1.predict.precompute --baseline # forces statistical baseline
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

from . import config as C
from .data_loader import (
    load_corridors, load_profiles, load_onsets,
    load_diagnosis, onsets_by_rid_date,
)
from .forecaster import Forecaster, load_forecaster, StatisticalBaselineForecaster
from .live_context import build_corridor_context
from .regime_mapper import series_to_regimes, tt_to_regime
from .fusion import fuse


def _same_weekday_onsets_excluding(
    onsets_idx: Dict[str, Dict[str, int]],
    rid: str,
    excluded_dates: List[str],
) -> List[int]:
    by_date = onsets_idx.get(rid, {})
    excluded = set(excluded_dates)
    return [om for dt, om in by_date.items() if dt not in excluded]


def precompute_all(
    forecaster: Forecaster,
    corridors: dict,
    profiles: Dict[str, Dict[int, float]],
    held_out_data: dict,
    diagnosis: dict,
    onsets_idx: Dict[str, Dict[str, int]],
    anchor_ticks: List[int],
) -> Dict[str, dict]:
    """Returns {f'{cid}_{date}': result_dict}."""
    results: Dict[str, dict] = {}

    # Pre-build per-corridor static header info (does not depend on anchor)
    static_headers: Dict[str, dict] = {}
    for cid in C.CFG.corridors:
        if cid not in corridors:
            continue
        cdef = corridors[cid]
        diag = diagnosis.get(cid, {}) or {}
        ff_by_rid = diag.get("freeflow", {}) or {}
        verdicts = diag.get("verdicts", {}) or {}
        conf_by_rid = diag.get("confidence", {}) or {}
        rec_by_rid = diag.get("recurrence", {}) or {}

        header_segs = []
        for i, seg in enumerate(cdef["chain"]):
            rid = seg["road_id"]
            ff_raw = ff_by_rid.get(rid, {}).get("ff_tt", 0.0) or 0.0
            ff = float(ff_raw)
            header_segs.append({
                "segment_idx": f"S{i+1:02d}",
                "rid": rid,
                "road_name": seg["road_name"],
                "length_m": int(seg["length_m"]),
                "road_class": seg["road_class"],
                "verdict": verdicts.get(rid, "FREE_FLOW"),
                "confidence_score": (conf_by_rid.get(rid, {}) or {}).get("score", 0.0),
                "confidence_label": (conf_by_rid.get(rid, {}) or {}).get("label", "MEDIUM"),
                "recurrence_label": (rec_by_rid.get(rid, {}) or {}).get("label", "NEVER"),
                "recurrence_frac": (rec_by_rid.get(rid, {}) or {}).get("frac", 0.0),
                "ff_tt": ff,
            })
        static_headers[cid] = {
            "corridor_id": cid,
            "corridor_name": cdef["name"],
            "city": cdef["city"],
            "chain_header": header_segs,
            "chain_def": cdef["chain"],
            "ff_by_rid": ff_by_rid,
            "verdicts": verdicts,
            "conf_by_rid": conf_by_rid,
            "rec_by_rid": rec_by_rid,
        }

    # Pre-compute actual-day regime tracks (per corridor × per held-out-date)
    # and scaffold the per-(corridor,date) result dict structure.
    for cid, hdr in static_headers.items():
        for date_str in C.CFG.held_out_dates:
            hod = held_out_data.get(cid, {}).get(date_str)
            if not hod:
                continue
            actual_day_packed = []
            traces_by_rid = {seg["rid"]: seg["trace"] for seg in hod["segments"]}
            for seg in hdr["chain_header"]:
                rid = seg["rid"]
                ff = seg["ff_tt"] or float(min(traces_by_rid[rid]))
                regimes = [tt_to_regime(t, ff) for t in traces_by_rid[rid]]
                actual_day_packed.append({
                    "segment_idx": seg["segment_idx"],
                    "rid": rid,
                    "trace": [round(v, 2) for v in traces_by_rid[rid]],
                    "regimes": regimes,
                })
            results[f"{cid}_{date_str}"] = {
                "corridor_id": cid,
                "corridor_name": hdr["corridor_name"],
                "city": hdr["city"],
                "date": date_str,
                "source": hod.get("source", "synthetic"),
                "forecaster_name": forecaster.name,
                "horizon_min": C.HORIZON_MIN,
                "bucket_min": C.BUCKET_MIN,
                "anchor_step_min": C.ANCHOR_STEP_MIN,
                "anchor_ticks": list(anchor_ticks),
                "chain": hdr["chain_header"],
                "actual_day": actual_day_packed,
                "forecasts_by_anchor": {},
            }

    # Iterate (date, anchor) outer loop, batch all corridor segments per call.
    total_calls = 0
    t_start = time.time()
    for date_str in C.CFG.held_out_dates:
        for anchor_min in anchor_ticks:
            batch_ctxs: List[np.ndarray] = []
            batch_meta: List[dict] = []  # parallel list of (cid, seg_idx, rid, ff)

            for cid, hdr in static_headers.items():
                hod = held_out_data.get(cid, {}).get(date_str)
                if not hod:
                    continue
                traces_by_rid = {seg["rid"]: seg["trace"] for seg in hod["segments"]}
                contexts = build_corridor_context(
                    corridor_chain=hdr["chain_def"],
                    profiles=profiles,
                    held_out_segments=traces_by_rid,
                    anchor_min=anchor_min,
                )
                for i, sc in enumerate(contexts):
                    seg_hdr = hdr["chain_header"][i]
                    batch_ctxs.append(sc.context)
                    batch_meta.append({
                        "cid": cid,
                        "segment_idx": seg_hdr["segment_idx"],
                        "rid": sc.rid,
                        "ff": seg_hdr["ff_tt"],
                    })

            if not batch_ctxs:
                continue

            t_call = time.time()
            try:
                point, quantiles = forecaster.forecast(C.HORIZON_STEPS, batch_ctxs)
            except Exception as e:
                print(f"[precompute] FAIL date={date_str} anchor={anchor_min}: {e}",
                      file=sys.stderr, flush=True)
                point = np.zeros((len(batch_ctxs), C.HORIZON_STEPS), dtype=np.float32)
                for i, ctx in enumerate(batch_ctxs):
                    point[i, :] = float(ctx[-1]) if len(ctx) else 0.0
                quantiles = np.stack([point] * 10, axis=-1)
            dt = time.time() - t_call
            total_calls += 1

            # demultiplex per (cid, anchor)
            per_cid_segs: Dict[str, List[dict]] = {}
            for idx, m in enumerate(batch_meta):
                cid = m["cid"]
                ff = m["ff"] or float(np.min(batch_ctxs[idx]))
                pt = point[idx].tolist()
                q10 = quantiles[idx, :, C.Q10_IDX].tolist()
                q90 = quantiles[idx, :, C.Q90_IDX].tolist()
                predicted_regimes = series_to_regimes(pt, ff)

                hist_onsets = _same_weekday_onsets_excluding(
                    onsets_idx, m["rid"], C.CFG.held_out_dates
                )
                hdr = static_headers[cid]
                fusion = fuse(
                    verdict=hdr["verdicts"].get(m["rid"], "FREE_FLOW"),
                    confidence_label=(hdr["conf_by_rid"].get(m["rid"], {}) or {}).get("label", "MEDIUM"),
                    recurrence_label=(hdr["rec_by_rid"].get(m["rid"], {}) or {}).get("label", "NEVER"),
                    historical_onsets=hist_onsets,
                    predicted_regimes=predicted_regimes,
                    anchor_min=anchor_min,
                )

                per_cid_segs.setdefault(cid, []).append({
                    "segment_idx": m["segment_idx"],
                    "rid": m["rid"],
                    "ff_tt": ff,
                    "point": [round(v, 2) for v in pt],
                    "q10": [round(v, 2) for v in q10],
                    "q90": [round(v, 2) for v in q90],
                    "predicted_regimes": predicted_regimes,
                    "fusion": fusion.to_dict(),
                })

            for cid, seg_list in per_cid_segs.items():
                results[f"{cid}_{date_str}"]["forecasts_by_anchor"][anchor_min] = {
                    "anchor_min": anchor_min,
                    "segments": seg_list,
                }

            if total_calls % 5 == 0 or dt > 5.0:
                elapsed = time.time() - t_start
                total_anchors = len(C.CFG.held_out_dates) * len(anchor_ticks)
                print(f"[precompute] date={date_str} anchor={anchor_min} "
                      f"({len(batch_ctxs)} series) {dt:.1f}s "
                      f"| {total_calls}/{total_anchors} calls, {elapsed:.1f}s elapsed",
                      flush=True)

    print(f"[precompute] done: {total_calls} forecast calls in {time.time() - t_start:.1f}s",
          flush=True)
    return results


def main(prefer_timesfm: bool = True) -> None:
    corridors = load_corridors()
    profiles = load_profiles()
    onsets = load_onsets()
    onsets_idx = onsets_by_rid_date(onsets)
    diagnosis = load_diagnosis()

    held_out_data = json.loads(C.HELD_OUT_PATH.read_text())

    print(f"[precompute] loading forecaster...", flush=True)
    t0 = time.time()
    forecaster = load_forecaster(prefer_timesfm=prefer_timesfm)
    print(f"[precompute] forecaster {forecaster.name} ready in {time.time() - t0:.1f}s", flush=True)

    C.FORECASTS_DIR.mkdir(parents=True, exist_ok=True)
    anchor_ticks = C.anchor_ticks_min()

    results = precompute_all(
        forecaster=forecaster,
        corridors=corridors,
        profiles=profiles,
        held_out_data=held_out_data,
        diagnosis=diagnosis,
        onsets_idx=onsets_idx,
        anchor_ticks=anchor_ticks,
    )

    for key, result in results.items():
        out_path = C.FORECASTS_DIR / f"{key}.json"
        out_path.write_text(json.dumps(result))
    print(f"[precompute] wrote {len(results)} forecast JSONs", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true",
                    help="Force statistical baseline (skip TimesFM even if installed)")
    args = ap.parse_args()
    main(prefer_timesfm=not args.baseline)
