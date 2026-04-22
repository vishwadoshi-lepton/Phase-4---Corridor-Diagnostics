#!/usr/bin/env python3
"""
TraffiCure  —  Corridor Diagnostic Pipeline v2  (traffic-engineering grounded)

Designed to be GLOBAL:
  * free-flow is DISCOVERED, not assumed (no 8-10am India-specific heuristic)
  * regimes are SPEED-RATIO based (not arbitrary tt/ff thresholds)
  * bottleneck test is the classical Bertini activation rule
    (upstream congested + current congested + downstream free-flowing)
  * shockwave validation uses LWR back-propagation speed (12-22 km/h globally)
  * no hard-coded direction, time-of-day, or corridor-specific rules

Input contract (per corridor call):
  corridor_id        : str
  corridor_name      : str
  segment_order      : list[str]        (physical upstream -> downstream)
  segment_meta       : dict[seg -> {'name', 'length_m'}]
  profile_by_seg     : dict[seg -> dict[minute_of_day -> avg_tt_sec]]  (720 buckets/day)
  (optional) onsets  : list[(seg, date, onset_min)]   (for Stage 6 recurrence)

Returns: (report_text, structured_results)

Stages:
  1. Discovered free-flow  (sliding-window scan + physical bounds)
  2. Regime classification (FREE / APPROACHING / CONGESTED / SEVERE by speed ratio)
  3. Bertini activation    (three-segment test; sustained >= 10 min)
  4. Shockwave validation  (backward propagation against distance/17 km/h)
  5. Systemic vs point     (corridor-wide simultaneous congestion)
  6. Recurrence typing     (if per-day onsets supplied; otherwise skipped)
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import comb
from statistics import median, quantiles
from typing import Optional

# --------------------------------------------------------------------------- #
# Tunables — all grounded in traffic-engineering literature, not heuristics.
# --------------------------------------------------------------------------- #
STEP_MIN        = 2          # profile bucket width (minutes)
BUCKETS_PER_DAY = 24 * 60 // STEP_MIN          # 720
FF_WINDOW_MIN   = 30         # free-flow search-window width (minutes)
FF_N_WINDOWS    = 3          # use the N quietest windows to build ff pool
FF_PCTILE       = 15         # p15 within the pooled quiet buckets
FF_SPEED_CAP_KMPH = 80       # urban physical ceiling — no segment > 80 km/h
FF_SPEED_MIN_KMPH = 8        # if discovered ff implies < 8 km/h, flag it

REGIME_FREE_RATIO        = 0.80       # speed >= 80% of FFS
REGIME_APPROACHING_RATIO = 0.50       # 50-80%
REGIME_CONGESTED_RATIO   = 0.30       # 30-50%  (severe below 30%)
REGIME_SMOOTH_BUCKETS    = 3          # 3x2=6-minute majority smoothing

BERTINI_MIN_BUCKETS    = 5            # 5x2=10 minutes sustained
BERTINI_UPSTREAM_REQ   = {"CONGESTED", "SEVERE"}
BERTINI_CURRENT_REQ    = {"CONGESTED", "SEVERE"}
BERTINI_DOWNSTREAM_REQ = {"FREE", "APPROACHING"}

SHOCKWAVE_LOW_KMPH   = 12    # LWR backward propagation lower bound
SHOCKWAVE_HIGH_KMPH  = 22    # upper bound
SHOCKWAVE_TOL_MIN    = 3     # ±3 min tolerance around expected lag

SYSTEMIC_ALL_FRACTION    = 0.80   # >=80% segments congested simultaneously
SYSTEMIC_WINDOW_BUCKETS  = 5      # within a 10-min window

# primary congestion window: sustained ≥N segments CONG/SEVR for ≥M minutes
PRIMARY_WINDOW_MIN_FRAC  = 0.25   # at least 25% of segments congested simultaneously
PRIMARY_WINDOW_MIN_MIN   = 30     # for at least 30 minutes
PRIMARY_WINDOW_GAP_MERGE = 30     # merge windows separated by <30 min

RECURRENCE_BANDS = [
    (0.75, "RECURRING"),
    (0.50, "FREQUENT"),
    (0.25, "OCCASIONAL"),
    (0.01, "RARE"),
]

REGIMES = ("FREE", "APPROACHING", "CONGESTED", "SEVERE")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _mm(t_min: int) -> str:
    t = int(t_min)
    if t >= 1440:
        h = (t // 60) % 24
        return f"{h:02d}:{t%60:02d}+1"
    return f"{t//60:02d}:{t%60:02d}"


def _as_ordered_tts(profile: dict[int, int]) -> list[int]:
    """Return a 720-long list of tt values (fill gaps from neighbours)."""
    out = [None] * BUCKETS_PER_DAY
    for m, tt in profile.items():
        idx = (m // STEP_MIN) % BUCKETS_PER_DAY
        out[idx] = tt
    last_known = next((v for v in out if v is not None), 0)
    for i in range(BUCKETS_PER_DAY):
        if out[i] is None:
            out[i] = last_known
        else:
            last_known = out[i]
    return out


def _pctile(values, pct: float):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _binom_tail(k: int, n: int, p: float) -> float:
    if n == 0:
        return 1.0
    return sum(comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k, n + 1))


# --------------------------------------------------------------------------- #
# STAGE 1 — discovered free-flow
# --------------------------------------------------------------------------- #
def discover_freeflow(tts: list[int], length_m: int) -> tuple[float, dict]:
    """
    Scan all 30-min sliding windows, pick the N quietest by median TT,
    take the p15 of their pooled buckets as the free-flow tt.
    Then clamp against physical limits.
    """
    win = FF_WINDOW_MIN // STEP_MIN          # 15 buckets per window
    medians = []
    for start in range(BUCKETS_PER_DAY - win + 1):
        w = tts[start:start + win]
        medians.append((median(w), start))
    medians.sort()
    best = medians[:FF_N_WINDOWS]
    pooled = []
    for _, start in best:
        pooled.extend(tts[start:start + win])
    raw_ff = _pctile(pooled, FF_PCTILE)

    # physical floor: no faster than FF_SPEED_CAP_KMPH
    min_tt_physical = length_m / (FF_SPEED_CAP_KMPH / 3.6)
    clamped = max(raw_ff, min_tt_physical)
    speed_kmph = length_m / clamped * 3.6

    # warnings
    warnings = []
    if raw_ff < min_tt_physical:
        warnings.append(
            f"raw ff={raw_ff:.1f}s implies {length_m/raw_ff*3.6:.1f} km/h "
            f"(>{FF_SPEED_CAP_KMPH}); clamped to {clamped:.1f}s"
        )
    if speed_kmph < FF_SPEED_MIN_KMPH:
        warnings.append(
            f"ff speed {speed_kmph:.1f} km/h < {FF_SPEED_MIN_KMPH} — "
            f"segment may never reach true free flow"
        )

    meta = {
        "raw_ff_sec": raw_ff,
        "clamped_ff_sec": clamped,
        "ff_speed_kmph": round(speed_kmph, 1),
        "quiet_windows": [(_mm(s * STEP_MIN), _mm((s + win) * STEP_MIN)) for _, s in best],
        "warnings": warnings,
    }
    return clamped, meta


# --------------------------------------------------------------------------- #
# STAGE 2 — regime classification
# --------------------------------------------------------------------------- #
def classify_regimes(tts: list[int], ff_tt: float) -> list[str]:
    """speed_ratio = ff_tt / current_tt ; partition into 4 regimes."""
    raw = []
    for tt in tts:
        r = ff_tt / max(tt, 1)
        if r >= REGIME_FREE_RATIO:
            raw.append("FREE")
        elif r >= REGIME_APPROACHING_RATIO:
            raw.append("APPROACHING")
        elif r >= REGIME_CONGESTED_RATIO:
            raw.append("CONGESTED")
        else:
            raw.append("SEVERE")

    # rolling majority smooth
    half = REGIME_SMOOTH_BUCKETS
    smoothed = []
    for i in range(len(raw)):
        lo, hi = max(0, i - half), min(len(raw), i + half + 1)
        counts = Counter(raw[lo:hi])
        smoothed.append(counts.most_common(1)[0][0])
    return smoothed


# --------------------------------------------------------------------------- #
# STAGE 2b — Primary congestion window detection
# --------------------------------------------------------------------------- #
def primary_window_mask(windows: list[tuple[int, int]]) -> list[bool]:
    """Return a BUCKETS_PER_DAY bool mask of which buckets are inside any
    (possibly wrapped, end_bucket may exceed BUCKETS_PER_DAY-1) primary window."""
    mask = [False] * BUCKETS_PER_DAY
    for s, e in windows:
        for b in range(s, e + 1):
            mask[b % BUCKETS_PER_DAY] = True
    return mask


def detect_primary_windows(regimes_by_idx: list[list[str]]) -> list[tuple[int, int]]:
    """
    Find the contiguous bucket windows where at least PRIMARY_WINDOW_MIN_FRAC
    of segments are simultaneously CONGESTED or SEVERE, lasting at least
    PRIMARY_WINDOW_MIN_MIN. Nearby windows within PRIMARY_WINDOW_GAP_MERGE
    minutes are merged into one, and windows that wrap past midnight are
    stitched together (end_bucket can exceed BUCKETS_PER_DAY-1).
    """
    n_seg = len(regimes_by_idx)
    if n_seg == 0:
        return []
    min_segs = max(1, int(PRIMARY_WINDOW_MIN_FRAC * n_seg + 0.999))
    hot = [
        sum(1 for i in range(n_seg) if regimes_by_idx[i][b] in ("CONGESTED", "SEVERE"))
        >= min_segs
        for b in range(BUCKETS_PER_DAY)
    ]

    runs = []
    run_s = None
    for b in range(BUCKETS_PER_DAY):
        if hot[b] and run_s is None:
            run_s = b
        elif not hot[b] and run_s is not None:
            runs.append((run_s, b - 1))
            run_s = None
    if run_s is not None:
        runs.append((run_s, BUCKETS_PER_DAY - 1))

    if not runs:
        return []

    # merge nearby
    merged = [list(runs[0])]
    gap_buckets = PRIMARY_WINDOW_GAP_MERGE // STEP_MIN
    for s, e in runs[1:]:
        if s - merged[-1][1] <= gap_buckets:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    # wrap-merge: if a window ends at the last bucket and another starts at 0,
    # stitch them into a single wrap window (end_bucket encoded as >= BUCKETS_PER_DAY).
    if (len(merged) >= 2
            and merged[-1][1] >= BUCKETS_PER_DAY - 1
            and merged[0][0] == 0):
        head = merged.pop(-1)          # [head_start, BUCKETS-1]
        tail = merged.pop(0)           # [0, tail_end]
        merged.append([head[0], BUCKETS_PER_DAY + tail[1]])

    # drop too-short
    min_buckets = PRIMARY_WINDOW_MIN_MIN // STEP_MIN
    final = [(s, e) for s, e in merged if (e - s + 1) >= min_buckets]
    return final


# --------------------------------------------------------------------------- #
# STAGE 3 — Bertini activation (three-segment test)
# --------------------------------------------------------------------------- #
def bertini_activations(
    regimes_by_idx: list[list[str]],
    primary_windows: Optional[list[tuple[int, int]]] = None,
) -> list[list[tuple[int, int]]]:
    """
    For each segment index, list time intervals (bucket_start, bucket_end_inclusive)
    where the Bertini rule fires for >= BERTINI_MIN_BUCKETS.
    Endpoints: if only one neighbour exists, require only that neighbour + current.
    If `primary_windows` is provided, activations are only retained if they
    overlap at least one primary congestion window (this removes midnight-wrap
    noise and floor-effect flicker during quiet hours).
    """
    n_seg = len(regimes_by_idx)
    out = [[] for _ in range(n_seg)]
    for i in range(n_seg):
        cur = regimes_by_idx[i]
        up  = regimes_by_idx[i - 1] if i > 0 else None
        dn  = regimes_by_idx[i + 1] if i < n_seg - 1 else None
        flags = []
        for b in range(BUCKETS_PER_DAY):
            if cur[b] not in BERTINI_CURRENT_REQ:
                flags.append(False); continue
            if up is not None and up[b] not in BERTINI_UPSTREAM_REQ:
                # standard Bertini requires upstream also congested (spillback)
                flags.append(False); continue
            if dn is not None and dn[b] not in BERTINI_DOWNSTREAM_REQ:
                flags.append(False); continue
            flags.append(True)

        # compact runs
        runs = []
        run_s = None
        for b, f in enumerate(flags):
            if f and run_s is None:
                run_s = b
            elif not f and run_s is not None:
                if b - run_s >= BERTINI_MIN_BUCKETS:
                    runs.append((run_s, b - 1))
                run_s = None
        if run_s is not None and BUCKETS_PER_DAY - run_s >= BERTINI_MIN_BUCKETS:
            runs.append((run_s, BUCKETS_PER_DAY - 1))

        # optionally filter to primary windows (using wrap-safe mask)
        if primary_windows:
            mask = primary_window_mask(primary_windows)
            filtered = []
            for rs, re_ in runs:
                if any(mask[b] for b in range(rs, re_ + 1)):
                    filtered.append((rs, re_))
            runs = filtered
        out[i] = runs
    return out


# --------------------------------------------------------------------------- #
# STAGE 4 — Shockwave validation
# --------------------------------------------------------------------------- #
def shockwave_validation_from_onsets(
    onsets_by_day_by_seg: dict,
    segment_order: list[str],
    segment_meta: dict,
) -> dict:
    """
    Preferred shockwave validation: uses per-day onsets (bucket_minute_of_day
    when each segment first crossed threshold on each weekday). For each
    adjacent (A upstream, B downstream) pair we compute the median observed
    lag (t_A - t_B in minutes) across days where BOTH fired, then compare to
    the LWR expected range dist/(12..22 km/h).
    """
    # Collect ALL onsets per (seg, date), not just the earliest — a segment
    # can have separate AM and PM peaks on the same day and we need both.
    by_date_seg = defaultdict(lambda: defaultdict(list))
    for seg, date, onset in onsets_by_day_by_seg:
        by_date_seg[date][seg].append(onset)
    results = []
    SAME_EVENT_MAX_LAG_MIN = 60   # only count pairs that are temporally close
    for i in range(len(segment_order) - 1):
        a, b = segment_order[i], segment_order[i + 1]
        deltas = []
        for date, segs in by_date_seg.items():
            if a not in segs or b not in segs: continue
            # pair each B onset with the closest A onset within ±60 min
            for tb in segs[b]:
                candidates = [ta for ta in segs[a]
                              if abs(ta - tb) <= SAME_EVENT_MAX_LAG_MIN]
                if not candidates:
                    continue
                ta = min(candidates, key=lambda x: abs(x - tb))
                deltas.append(ta - tb)
        if not deltas:
            results.append({"pair": (i, i + 1), "skipped": "no paired onsets"})
            continue
        observed = median(deltas)
        dist_m = 0.5 * segment_meta[a]["length_m"] + 0.5 * segment_meta[b]["length_m"]
        low_lag  = dist_m / (SHOCKWAVE_HIGH_KMPH / 3.6) / 60.0
        high_lag = dist_m / (SHOCKWAVE_LOW_KMPH  / 3.6) / 60.0
        ok = (low_lag - SHOCKWAVE_TOL_MIN) <= observed <= (high_lag + SHOCKWAVE_TOL_MIN)
        results.append({
            "pair": (i, i + 1),
            "n_days": len(deltas),
            "observed_lag_min": round(observed, 1),
            "expected_lag_range_min": (round(low_lag, 1), round(high_lag, 1)),
            "pass": bool(ok),
            "dist_m": round(dist_m, 0),
        })
    with_data = [r for r in results if "skipped" not in r]
    pass_rate = (sum(1 for r in with_data if r["pass"]) / len(with_data)
                 if with_data else None)
    return {"pairs": results, "pass_rate": pass_rate, "mode": "per-day onsets"}


def shockwave_validation(
    regimes_by_idx: list[list[str]],
    segment_order: list[str],
    segment_meta: dict,
    primary_windows: Optional[list[tuple[int, int]]] = None,
) -> dict:
    """
    Fallback shockwave validation that works from median profiles alone.
    Because median profiles compress many days, `first onset` is ambiguous —
    we instead look at the centroid of congestion (weighted by TT ratio
    above 1.5) within the primary window for each segment, and compute
    pairwise lag between centroids. Under LWR, A_centroid should trail
    B_centroid by dist_AB / shockwave_speed.
    """
    if not primary_windows:
        return {"pairs": [], "pass_rate": None, "mode": "no primary windows"}

    mask = primary_window_mask(primary_windows)

    def centroid(regimes, tts, ff_tt):
        w_num = 0.0
        w_den = 0.0
        for b in range(BUCKETS_PER_DAY):
            if not mask[b]: continue
            if regimes[b] not in ("CONGESTED", "SEVERE"): continue
            ratio = max(0.0, (tts[b] / ff_tt) - 1.5)
            w_num += ratio * b
            w_den += ratio
        return (w_num / w_den) if w_den > 0 else None

    # recompute tts & ff from regimes_by_idx context — caller must supply
    # NOTE: this fallback centroid needs tts + ff_tt per segment; the wrapper
    # in diagnose() passes them via the regimes argument augmentation.
    # Here we degrade gracefully: if regimes_by_idx contains ('regime', tts, ff)
    # tuples we extract; otherwise we skip.
    if not (regimes_by_idx and isinstance(regimes_by_idx[0], dict)):
        return {"pairs": [], "pass_rate": None,
                "mode": "median-profile fallback requires tts+ff bundle"}

    results = []
    for i in range(len(segment_order) - 1):
        a = segment_order[i]; b = segment_order[i + 1]
        ca = centroid(regimes_by_idx[i]["regimes"],
                      regimes_by_idx[i]["tts"], regimes_by_idx[i]["ff"])
        cb = centroid(regimes_by_idx[i + 1]["regimes"],
                      regimes_by_idx[i + 1]["tts"], regimes_by_idx[i + 1]["ff"])
        if ca is None or cb is None:
            results.append({"pair": (i, i + 1), "skipped": "no centroid"})
            continue
        observed_lag_min = (ca - cb) * STEP_MIN
        dist_m = 0.5 * segment_meta[a]["length_m"] + 0.5 * segment_meta[b]["length_m"]
        low_lag  = dist_m / (SHOCKWAVE_HIGH_KMPH / 3.6) / 60.0
        high_lag = dist_m / (SHOCKWAVE_LOW_KMPH  / 3.6) / 60.0
        ok = (low_lag - SHOCKWAVE_TOL_MIN) <= observed_lag_min <= (high_lag + SHOCKWAVE_TOL_MIN)
        results.append({
            "pair": (i, i + 1),
            "observed_lag_min": round(observed_lag_min, 1),
            "expected_lag_range_min": (round(low_lag, 1), round(high_lag, 1)),
            "pass": bool(ok),
            "dist_m": round(dist_m, 0),
        })
    with_data = [r for r in results if "skipped" not in r]
    pass_rate = (sum(1 for r in with_data if r["pass"]) / len(with_data)
                 if with_data else None)
    return {"pairs": results, "pass_rate": pass_rate, "mode": "median centroid"}


# --------------------------------------------------------------------------- #
# STAGE 5 — Systemic vs point
# --------------------------------------------------------------------------- #
def systemic_analysis(regimes_by_idx: list[list[str]]) -> dict:
    n_seg = len(regimes_by_idx)
    if n_seg == 0:
        return {"systemic_windows": [], "max_simultaneous": 0, "max_fraction": 0.0}
    threshold = int(SYSTEMIC_ALL_FRACTION * n_seg + 0.999)
    simultaneous = []
    for b in range(BUCKETS_PER_DAY):
        c = sum(1 for i in range(n_seg) if regimes_by_idx[i][b] in ("CONGESTED", "SEVERE"))
        simultaneous.append(c)

    # find windows of at least SYSTEMIC_WINDOW_BUCKETS where count >= threshold
    runs = []
    run_s = None
    for b in range(BUCKETS_PER_DAY):
        if simultaneous[b] >= threshold:
            if run_s is None: run_s = b
        else:
            if run_s is not None:
                if b - run_s >= SYSTEMIC_WINDOW_BUCKETS:
                    runs.append((run_s * STEP_MIN, (b - 1) * STEP_MIN))
                run_s = None
    if run_s is not None and BUCKETS_PER_DAY - run_s >= SYSTEMIC_WINDOW_BUCKETS:
        runs.append((run_s * STEP_MIN, (BUCKETS_PER_DAY - 1) * STEP_MIN))
    return {
        "systemic_windows": runs,
        "max_simultaneous": max(simultaneous),
        "max_fraction": round(max(simultaneous) / n_seg, 2),
        "threshold_segments": threshold,
    }


# --------------------------------------------------------------------------- #
# STAGE 6 — Recurrence typing (requires raw per-day onsets)
# --------------------------------------------------------------------------- #
def classify_recurrence(onsets_by_day_by_seg: dict[str, dict[str, int]],
                        segment_order: list[str]) -> dict:
    total_days = len(onsets_by_day_by_seg)
    seg_days = defaultdict(int)
    for d, segs in onsets_by_day_by_seg.items():
        for s in segs:
            seg_days[s] += 1
    out = {}
    for s in segment_order:
        frac = seg_days[s] / total_days if total_days else 0.0
        label = "NEVER"
        for thresh, name in RECURRENCE_BANDS:
            if frac >= thresh:
                label = name
                break
        out[s] = {"n_days": seg_days[s], "total_days": total_days, "frac": round(frac, 2), "label": label}
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass
class CorridorDiagnosis:
    corridor_id: str
    corridor_name: str
    segment_order: list
    segment_meta: dict
    freeflow: dict = field(default_factory=dict)
    ff_meta: dict = field(default_factory=dict)
    regimes: dict = field(default_factory=dict)        # seg -> list[720]
    primary_windows: list = field(default_factory=list)  # list[(s_bucket, e_bucket)]
    bertini: dict = field(default_factory=dict)        # seg -> list[(s_b, e_b)]
    shockwave: dict = field(default_factory=dict)
    systemic: dict = field(default_factory=dict)
    recurrence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def diagnose(corridor_id, corridor_name, segment_order, segment_meta,
             profile_by_seg,
             onsets_by_day_by_seg: Optional[dict] = None,
             raw_onsets: Optional[list] = None,
             ) -> CorridorDiagnosis:
    """
    raw_onsets is an optional list of (seg, date, onset_min_of_day) used by
    Stage 4 shockwave validation (preferred path). If absent, Stage 4 falls
    back to the median-profile centroid method.
    """
    diag = CorridorDiagnosis(corridor_id, corridor_name, segment_order, segment_meta)

    # Stage 1 + 2 per segment
    regimes_by_idx = []
    bundle_for_fallback = []
    for s in segment_order:
        tts = _as_ordered_tts(profile_by_seg[s])
        ff, ff_meta = discover_freeflow(tts, segment_meta[s]["length_m"])
        diag.freeflow[s] = ff
        diag.ff_meta[s] = ff_meta
        if ff_meta["warnings"]:
            diag.warnings.extend([f"{s[:8]} ({segment_meta[s]['name']}): {w}"
                                  for w in ff_meta["warnings"]])
        regimes = classify_regimes(tts, ff)
        diag.regimes[s] = regimes
        regimes_by_idx.append(regimes)
        bundle_for_fallback.append({"regimes": regimes, "tts": tts, "ff": ff})

    # Stage 2b — primary congestion window
    diag.primary_windows = detect_primary_windows(regimes_by_idx)

    # Stage 3 — Bertini, filtered to primary windows
    bertini = bertini_activations(regimes_by_idx, diag.primary_windows)
    for i, s in enumerate(segment_order):
        diag.bertini[s] = bertini[i]

    # Stage 4 — Shockwave
    if raw_onsets:
        diag.shockwave = shockwave_validation_from_onsets(
            raw_onsets, segment_order, segment_meta
        )
    else:
        diag.shockwave = shockwave_validation(
            bundle_for_fallback, segment_order, segment_meta, diag.primary_windows
        )

    # Stage 5
    diag.systemic = systemic_analysis(regimes_by_idx)

    # Stage 6
    if onsets_by_day_by_seg:
        diag.recurrence = classify_recurrence(onsets_by_day_by_seg, segment_order)

    return diag


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def render(diag: CorridorDiagnosis) -> str:
    L = []
    L.append("=" * 90)
    L.append(f"TRAFFICURE CORRIDOR DIAGNOSTIC v2  —  {diag.corridor_name}")
    L.append(f"id: {diag.corridor_id}")
    L.append("=" * 90)
    total_km = sum(diag.segment_meta[s]["length_m"] for s in diag.segment_order) / 1000.0
    L.append(f"Segments: {len(diag.segment_order)}    Corridor length: {total_km:.2f} km")

    # Stage 1
    L.append("\n--- STAGE 1 — DISCOVERED FREE FLOW (quietest 30-min windows, p15, clamped) ---")
    L.append(f"{'seg':<5} {'length':>8}  {'ff_tt':>7}  {'ff_spd':>9}   quiet windows used")
    for i, s in enumerate(diag.segment_order):
        meta = diag.segment_meta[s]
        ff = diag.freeflow[s]
        fm = diag.ff_meta[s]
        qw = ", ".join(f"{a}–{b}" for a, b in fm["quiet_windows"])
        L.append(f"S{i+1:02d}   {meta['length_m']:>6}m  {ff:>5.0f}s   "
                 f"{fm['ff_speed_kmph']:>5.1f} kmph   {qw}")

    # Stage 2 — regime histogram per segment
    L.append("\n--- STAGE 2 — REGIME DISTRIBUTION (speed-ratio classification) ---")
    L.append(f"{'seg':<5}  {'FREE':>6}  {'APPR':>6}  {'CONG':>6}  {'SEVR':>6}   name")
    for i, s in enumerate(diag.segment_order):
        c = Counter(diag.regimes[s])
        tot = sum(c.values())
        pct = lambda k: 100 * c.get(k, 0) / tot
        L.append(f"S{i+1:02d}  "
                 f"{pct('FREE'):>5.1f}%  {pct('APPROACHING'):>5.1f}%  "
                 f"{pct('CONGESTED'):>5.1f}%  {pct('SEVERE'):>5.1f}%   "
                 f"{diag.segment_meta[s]['name']}")

    # Stage 2b — primary congestion windows
    L.append("\n--- STAGE 2b — PRIMARY CONGESTION WINDOW(S) ---")
    L.append(f"  rule: ≥{PRIMARY_WINDOW_MIN_FRAC*100:.0f}% of segments congested "
             f"simultaneously for ≥{PRIMARY_WINDOW_MIN_MIN} min")
    if not diag.primary_windows:
        L.append("  (no corridor-level congestion window — quiet or fragmented)")
    else:
        for ws, we in diag.primary_windows:
            dur = (we - ws + 1) * STEP_MIN
            L.append(f"  {_mm(ws*STEP_MIN)} – {_mm((we+1)*STEP_MIN)}   (duration {dur} min)")

    # Stage 3 — Bertini activations
    L.append("\n--- STAGE 3 — BERTINI ACTIVATION INTERVALS (active bottleneck evidence) ---")
    L.append("rule: upstream CONG/SEVR  AND  current CONG/SEVR  AND  downstream FREE/APPR")
    L.append("      sustained ≥ 10 min")
    any_hit = False
    for i, s in enumerate(diag.segment_order):
        runs = diag.bertini[s]
        if not runs:
            continue
        any_hit = True
        ivs = ", ".join(f"{_mm(a*STEP_MIN)}–{_mm((b+1)*STEP_MIN)}" for a, b in runs)
        L.append(f"  S{i+1:02d}  {ivs}   [{diag.segment_meta[s]['name']}]")
    if not any_hit:
        L.append("  (no segment satisfies the Bertini activation rule — "
                 "likely systemic or quiet corridor)")

    # Stage 4 — shockwave
    sw = diag.shockwave
    mode = sw.get("mode", "?")
    L.append(f"\n--- STAGE 4 — SHOCKWAVE VALIDATION (LWR 12–22 km/h back-prop; mode={mode}) ---")
    for r in sw.get("pairs", []):
        i, j = r["pair"]
        if "skipped" in r:
            L.append(f"  S{i+1:02d}→S{j+1:02d}   skipped ({r['skipped']})")
            continue
        tag = "OK " if r["pass"] else "!! "
        days = f"  (n={r['n_days']}d)" if "n_days" in r else ""
        L.append(f"  {tag}S{i+1:02d}→S{j+1:02d}   observed_lag={r['observed_lag_min']:+.1f}m  "
                 f"expected={r['expected_lag_range_min'][0]:.1f}-{r['expected_lag_range_min'][1]:.1f}m  "
                 f"dist={r['dist_m']:.0f}m{days}")
    if sw.get("pass_rate") is not None:
        L.append(f"  shockwave pass rate: {sw['pass_rate']*100:.0f}%")

    # Stage 5 — systemic
    L.append("\n--- STAGE 5 — SYSTEMIC vs POINT CONGESTION ---")
    sys_ = diag.systemic
    L.append(f"  max simultaneous congested segments: "
             f"{sys_['max_simultaneous']}/{len(diag.segment_order)} "
             f"({sys_['max_fraction']*100:.0f}%)")
    if sys_["systemic_windows"]:
        windows_txt = ", ".join(f"{_mm(a)}–{_mm(b)}" for a, b in sys_["systemic_windows"])
        L.append(f"  SYSTEMIC WINDOWS (≥{SYSTEMIC_ALL_FRACTION*100:.0f}% "
                 f"of segments simultaneously): {windows_txt}")
    else:
        n_bert = sum(1 for s in diag.segment_order if diag.bertini[s])
        L.append(f"  NOT systemic — point-bottleneck model fits "
                 f"({n_bert}/{len(diag.segment_order)} segments fire Bertini)")

    # Stage 6 — recurrence
    if diag.recurrence:
        L.append("\n--- STAGE 6 — RECURRENCE TYPING ---")
        for i, s in enumerate(diag.segment_order):
            r = diag.recurrence[s]
            L.append(f"  S{i+1:02d}  {r['n_days']:>2}/{r['total_days']}  "
                     f"{r['frac']*100:>4.0f}%  {r['label']}")

    if diag.warnings:
        L.append("\n--- WARNINGS ---")
        for w in diag.warnings:
            L.append(f"  • {w}")

    return "\n".join(L)


# Smoke test when run directly
if __name__ == "__main__":
    import sys, pathlib, json
    sys.path.insert(0, "/sessions/magical-gifted-meitner")
    from profiles import PROFILES
    corridors = json.load(open("/sessions/magical-gifted-meitner/corridor_segments.json"))
    raw = pathlib.Path("/sessions/magical-gifted-meitner/profiles_raw/onsets.json").read_text()
    onset_rows = json.loads(json.loads(raw)[0]["text"])
    all_onsets = [(r["road_id"], r["date"], r["onset_min_of_day"]) for r in onset_rows]

    for cid, cdata in corridors.items():
        seg_order = [s["road_id"] for s in cdata["segments"]]
        seg_meta = {s["road_id"]: {"name": s["road_name"], "length_m": s["length_m"]}
                    for s in cdata["segments"]}
        prof = {s: PROFILES[s] for s in seg_order if s in PROFILES}
        if len(prof) != len(seg_order):
            print(f"!! {cdata['name']}: missing {len(seg_order)-len(prof)} profiles, skipping")
            continue
        seg_set = set(seg_order)
        raw_onsets = [(s, d, o) for (s, d, o) in all_onsets if s in seg_set]
        diag = diagnose(cid, cdata["name"], seg_order, seg_meta, prof,
                        raw_onsets=raw_onsets)
        print(render(diag))
        print("\n\n")
