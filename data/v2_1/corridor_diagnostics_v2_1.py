#!/usr/bin/env python3
"""
TraffiCure — Corridor Diagnostic Pipeline v2.1 (refinements layer on top of v2)

What v2.1 adds on top of v2, with traffic-engineering justification:

  R1. LENGTH-WEIGHTED PRIMARY WINDOW (Stage 2b)
      The old "≥25% of segments congested" rule treats all segments equally.
      A corridor with 3 short (100m) + 2 long (2km) segments has 60% of its
      length in just 2 segments — if those fire, that is a corridor-level
      event, even though it is only 40% of the segment count. v2.1 replaces
      segment-count fraction with length-weighted fraction:
          hot(b) = sum(length_m over CONG/SEVR segs at b) / total_length ≥ 0.25

  R3. HEAD-SEGMENT BOTTLENECK (Stage 3)
      The classical three-point Bertini test requires an upstream segment.
      On a finite corridor, S01 can never fire because there is no S00.
      But in reality the first segment of a recorded corridor is often
      the junction where the queue starts — i.e. it IS the bottleneck.
      v2.1 introduces a two-point relaxation for S01:
          S01 is HEAD_BOTTLENECK iff current CONG/SEVR and downstream FREE/APPR
      emitted as a SECOND activation type alongside standard Bertini.
      Terminus (S_N) is still skipped — we have no downstream to validate.

  R5. CONTIGUITY-BASED SYSTEMIC (Stage 5)
      The old 80% simultaneous rule fires only when almost every segment
      jams at once. But a corridor where 7 of 10 adjacent segments jam
      simultaneously is operationally systemic (you cannot "fix S04" — the
      whole 70% of the corridor is failing together), while 7 of 10 segments
      jammed in 3 disconnected pockets is point-bottleneck behaviour.
      v2.1 adds a contiguity rule:
          systemic iff at some bucket the maximum contiguous run of CONG/SEVR
          segments accounts for ≥ 60% of the corridor length.
      Both the old (80% simultaneous) AND the new (60% contiguous length) are
      reported; either triggers SYSTEMIC.

  R7. CONFIDENCE INDEX (new; added to each Stage 3 verdict)
      A per-segment 0–1 confidence score derived from four independent
      signals, each a standard QA metric with a clear interpretation:
          A. ff_tightness — how consistent the quiet-window sample is
          B. primary_overlap — does the Bertini fire inside a primary window
          C. onset_support — number of day-level onset observations (≥5)
          D. shockwave_support — does the flanking pair pass Stage 4
      Aggregated with fixed weights and mapped to a label:
          ≥ 0.75 → HIGH, ≥ 0.50 → MEDIUM, < 0.50 → LOW

  R8. BASELINE-SATURATED SANITY CHECK (Stage 1 warning)
      If a segment's discovered free-flow speed is >2× slower than the
      median free-flow speed on the same corridor AND its quietest-window
      median tt / busiest-window median tt > 0.70 (i.e. the segment never
      got noticeably quieter), it is likely a perpetually-saturated link
      whose "free flow" is really just "less bad congestion". We do NOT
      change the ff_tt (we still clamp to 80 kmph to keep the pipeline
      coherent), but we raise a `baseline_saturated` warning so the operator
      knows the regime bar is on a soft foundation.

Recommendations deliberately deferred to a later phase:
  R2  Road-class ff clamp   — we don't have reliable road_class labels yet
  R4  Mandatory per-day onsets — we still keep the fallback for safety
  R6  Signal-cycle-aware Bertini duration — we don't know signal cycles

This module does NOT modify the v2 file. It imports the v2 building blocks
and wraps them with v2.1 logic. The API surface is diagnose_v21() which
returns a CorridorDiagnosisV21 object and render_v21() which produces the
report text.
"""
from __future__ import annotations
import sys, os, json
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from statistics import median
from typing import Optional

# bring v2 into scope — parent data/ dir, resolved relative to this file
V2_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, V2_PATH)
import corridor_diagnostics_v2 as v2  # noqa: E402

# reuse v2 constants directly so our tunables table stays in one place
STEP_MIN          = v2.STEP_MIN
BUCKETS_PER_DAY   = v2.BUCKETS_PER_DAY
_mm               = v2._mm
_as_ordered_tts   = v2._as_ordered_tts

# ---- v2.1 tunables (all have traffic-engineering or QA justifications) ---- #
IMPACT_MIN_FRAC               = 0.25    # length-weighted primary window (same 25%)
SYSTEMIC_CONTIG_MIN_FRAC      = 0.60    # contiguous-length systemic rule
BASELINE_PEER_RATIO           = 2.0     # 2x slower than corridor median ff_spd
BASELINE_QUIET_BUSY_RATIO     = 0.70    # quiet/busy tt ratio > 0.70 means flat day
HEAD_BOTTLENECK_MIN_BUCKETS   = v2.BERTINI_MIN_BUCKETS   # reuse 10-min sustain
CONFIDENCE_WEIGHTS            = {"ff_tight": 0.25,
                                 "primary_overlap": 0.25,
                                 "onset_support": 0.25,
                                 "shockwave_support": 0.25}

# --------------------------------------------------------------------------- #
# R1 — length-weighted primary window
# --------------------------------------------------------------------------- #
def detect_primary_windows_lenweighted(regimes_by_idx, lengths_m):
    """
    Replace v2's segment-count rule with a length-weighted rule. A bucket is
    'hot' iff the sum of lengths of segments in CONG/SEVR at that bucket is
    at least IMPACT_MIN_FRAC of the total corridor length.
    """
    n_seg = len(regimes_by_idx)
    if n_seg == 0:
        return []
    total_len = sum(lengths_m)
    min_len = IMPACT_MIN_FRAC * total_len
    hot = [False] * BUCKETS_PER_DAY
    for b in range(BUCKETS_PER_DAY):
        acc = 0.0
        for i in range(n_seg):
            if regimes_by_idx[i][b] in ("CONGESTED", "SEVERE"):
                acc += lengths_m[i]
        hot[b] = acc >= min_len

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

    merged = [list(runs[0])]
    gap_buckets = v2.PRIMARY_WINDOW_GAP_MERGE // STEP_MIN
    for s, e in runs[1:]:
        if s - merged[-1][1] <= gap_buckets:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    if (len(merged) >= 2
            and merged[-1][1] >= BUCKETS_PER_DAY - 1
            and merged[0][0] == 0):
        head = merged.pop(-1)
        tail = merged.pop(0)
        merged.append([head[0], BUCKETS_PER_DAY + tail[1]])

    min_buckets = v2.PRIMARY_WINDOW_MIN_MIN // STEP_MIN
    final = [(s, e) for s, e in merged if (e - s + 1) >= min_buckets]
    return final


# --------------------------------------------------------------------------- #
# R3 — head-segment bottleneck test (S01 relaxation)
# --------------------------------------------------------------------------- #
def head_bottleneck_intervals(regimes_by_idx, primary_windows):
    """
    For the head segment S01 (and only S01), apply a two-point test:
    self is CONG/SEVR AND downstream is FREE/APPR, sustained ≥10 min.
    Only kept if the interval overlaps a primary window (same filter as v2).
    Returns list[(s_b, e_b)] — empty if head doesn't pass.
    """
    if len(regimes_by_idx) < 2:
        return []
    cur = regimes_by_idx[0]
    dn  = regimes_by_idx[1]
    flags = []
    for b in range(BUCKETS_PER_DAY):
        ok = (cur[b] in v2.BERTINI_CURRENT_REQ
              and dn[b] in v2.BERTINI_DOWNSTREAM_REQ)
        flags.append(ok)

    runs = []
    run_s = None
    for b, f in enumerate(flags):
        if f and run_s is None:
            run_s = b
        elif not f and run_s is not None:
            if b - run_s >= HEAD_BOTTLENECK_MIN_BUCKETS:
                runs.append((run_s, b - 1))
            run_s = None
    if run_s is not None and BUCKETS_PER_DAY - run_s >= HEAD_BOTTLENECK_MIN_BUCKETS:
        runs.append((run_s, BUCKETS_PER_DAY - 1))

    if primary_windows:
        mask = v2.primary_window_mask(primary_windows)
        runs = [(rs, re_) for rs, re_ in runs
                if any(mask[b] for b in range(rs, re_ + 1))]
    return runs


# --------------------------------------------------------------------------- #
# R5 — contiguity-based systemic classification
# --------------------------------------------------------------------------- #
def systemic_contiguity(regimes_by_idx, lengths_m):
    """
    At each bucket, compute the longest contiguous run of CONG/SEVR segments
    (in segment-length terms). The systemic verdict fires if the max ever
    reaches SYSTEMIC_CONTIG_MIN_FRAC of the total corridor length.
    """
    n = len(regimes_by_idx)
    if n == 0:
        return {"max_contig_frac": 0.0, "systemic_by_contig": False,
                "peak_bucket": None, "peak_segs": []}
    total_len = sum(lengths_m)
    best_frac = 0.0
    best_bucket = None
    best_segs = []
    for b in range(BUCKETS_PER_DAY):
        # scan contiguous CONG/SEVR run
        cur_len = 0.0
        cur_segs = []
        run_len = 0.0
        run_segs = []
        for i in range(n):
            if regimes_by_idx[i][b] in ("CONGESTED", "SEVERE"):
                cur_len += lengths_m[i]
                cur_segs.append(i)
                if cur_len > run_len:
                    run_len = cur_len
                    run_segs = list(cur_segs)
            else:
                cur_len = 0.0
                cur_segs = []
        frac = run_len / total_len if total_len else 0.0
        if frac > best_frac:
            best_frac = frac
            best_bucket = b
            best_segs = run_segs
    return {
        "max_contig_frac": round(best_frac, 3),
        "systemic_by_contig": bool(best_frac >= SYSTEMIC_CONTIG_MIN_FRAC),
        "peak_bucket": best_bucket,
        "peak_segs": best_segs,
    }


# --------------------------------------------------------------------------- #
# R8 — baseline saturated sanity check
# --------------------------------------------------------------------------- #
def flag_saturated_baselines(ff_meta_by_seg, profile_by_seg, segment_order, lengths_m):
    """
    A segment is flagged baseline_saturated if:
      (a) its discovered ff_speed is more than BASELINE_PEER_RATIO× slower
          than the median ff_speed on this corridor, AND
      (b) its quietest-30-min median tt / busiest-30-min median tt > 0.70
          (i.e. the tt did not meaningfully drop during off-peak hours)
    """
    speeds = [ff_meta_by_seg[s]["ff_speed_kmph"] for s in segment_order]
    med_spd = median(speeds)
    flags = {}
    win = v2.FF_WINDOW_MIN // STEP_MIN
    for s in segment_order:
        tts = _as_ordered_tts(profile_by_seg[s])
        meds = []
        for start in range(BUCKETS_PER_DAY - win + 1):
            meds.append(median(tts[start:start + win]))
        quiet = min(meds) if meds else 0
        busy = max(meds) if meds else 1
        qb = (quiet / busy) if busy > 0 else 1.0
        spd = ff_meta_by_seg[s]["ff_speed_kmph"]
        peer = (med_spd / spd) if spd > 0 else 99
        saturated = (peer >= BASELINE_PEER_RATIO) and (qb >= BASELINE_QUIET_BUSY_RATIO)
        flags[s] = {
            "ff_speed_kmph": spd,
            "corridor_median_speed": round(med_spd, 1),
            "peer_ratio": round(peer, 2),
            "quiet_busy_ratio": round(qb, 3),
            "baseline_saturated": saturated,
        }
    return flags


# --------------------------------------------------------------------------- #
# R7 — confidence index
# --------------------------------------------------------------------------- #
def confidence_for_segment(
    idx, seg, diag, head_runs, shockwave_pairs, onsets_by_seg, profile_by_seg,
):
    """
    Produce a 0..1 confidence score and component breakdown for a single
    segment's Stage 3 verdict. Higher = more defensible.
    """
    # A. ff_tightness: stdev of quiet-window medians / raw_ff_sec (lower is better)
    ffm = diag.ff_meta[seg]
    raw_ff = ffm["raw_ff_sec"]
    tts = _as_ordered_tts(profile_by_seg[seg])
    win = v2.FF_WINDOW_MIN // STEP_MIN
    quiet_meds = sorted(median(tts[s:s+win]) for s in range(BUCKETS_PER_DAY - win + 1))
    top_n = quiet_meds[:v2.FF_N_WINDOWS]
    if raw_ff and raw_ff > 0 and len(top_n) >= 2:
        spread = (top_n[-1] - top_n[0]) / raw_ff
        ff_tight = max(0.0, min(1.0, 1.0 - spread))
    else:
        ff_tight = 0.5

    # B. primary_overlap: does any Bertini or Head run overlap a primary window
    runs = list(diag.bertini.get(seg, []))
    if idx == 0:
        runs = runs + list(head_runs or [])
    mask = v2.primary_window_mask(diag.primary_windows) if diag.primary_windows else [False] * BUCKETS_PER_DAY
    total_run_len = 0
    inside_run_len = 0
    for s_b, e_b in runs:
        total_run_len += (e_b - s_b + 1)
        inside_run_len += sum(1 for b in range(s_b, e_b + 1) if mask[b])
    if runs and total_run_len > 0:
        primary_overlap = inside_run_len / total_run_len
    elif not runs and not diag.primary_windows:
        primary_overlap = 0.7   # no runs, no primary → neutral
    elif not runs:
        primary_overlap = 0.4   # corridor has a primary window but this seg doesn't fire
    else:
        primary_overlap = 0.0

    # C. onset_support: number of onset rows for this segment, saturated at 5
    n_onsets = len(onsets_by_seg.get(seg, []))
    onset_support = min(1.0, n_onsets / 5.0)

    # D. shockwave_support: did any flanking pair Stage-4-pass?
    flanking = [r for r in shockwave_pairs
                if isinstance(r.get("pair"), tuple) and
                (r["pair"][0] == idx or r["pair"][1] == idx) and
                "skipped" not in r]
    if not flanking:
        shockwave_support = 0.5  # no data is neutral
    else:
        n_pass = sum(1 for r in flanking if r.get("pass"))
        shockwave_support = n_pass / len(flanking)

    comps = {
        "ff_tight": round(ff_tight, 3),
        "primary_overlap": round(primary_overlap, 3),
        "onset_support": round(onset_support, 3),
        "shockwave_support": round(shockwave_support, 3),
    }
    score = sum(CONFIDENCE_WEIGHTS[k] * v for k, v in comps.items())
    label = "HIGH" if score >= 0.75 else ("MEDIUM" if score >= 0.50 else "LOW")
    return {"score": round(score, 3), "label": label, "components": comps}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass
class CorridorDiagnosisV21:
    corridor_id: str
    corridor_name: str
    segment_order: list
    segment_meta: dict
    v2: object = None                     # underlying v2 result
    primary_windows_v21: list = field(default_factory=list)
    head_bottleneck: list = field(default_factory=list)
    systemic_v21: dict = field(default_factory=dict)
    baseline_flags: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    verdicts: dict = field(default_factory=dict)   # seg -> one of ACTIVE_BOTTLENECK / HEAD_BOTTLENECK / SLOW_LINK / QUEUE_VICTIM / FREE_FLOW


def _verdict_for_segment(idx, seg, diag_v2, head_runs, confidence, primary_windows, regime):
    """Derive a per-segment operator-facing verdict label."""
    if idx == 0 and head_runs:
        return "HEAD_BOTTLENECK"
    bert = diag_v2.bertini.get(seg, [])
    if bert:
        return "ACTIVE_BOTTLENECK"
    # if the seg is mostly CONG/SEVR during a primary window but did not fire
    # Bertini, it's either a SLOW_LINK (no upstream queue) or a QUEUE_VICTIM
    if not primary_windows:
        return "FREE_FLOW"
    mask = v2.primary_window_mask(primary_windows)
    in_window = [regime[b] for b in range(BUCKETS_PER_DAY) if mask[b]]
    if not in_window:
        return "FREE_FLOW"
    cong_frac = sum(1 for r in in_window if r in ("CONGESTED", "SEVERE")) / len(in_window)
    if cong_frac < 0.20:
        return "FREE_FLOW"
    # victim vs slow-link: does the DOWNSTREAM segment also congest during the primary window?
    # if yes, we are a queue spillback (victim). if no, we're a slow link with no spillback.
    return "QUEUE_VICTIM"  # most common case when Bertini doesn't fire but congested


def _refine_slow_vs_victim(seg_order, regimes_by_idx, primary_windows, verdicts):
    """Second pass: distinguish SLOW_LINK (no downstream queue) from QUEUE_VICTIM."""
    if not primary_windows:
        return
    mask = v2.primary_window_mask(primary_windows)
    for i, s in enumerate(seg_order):
        if verdicts.get(s) != "QUEUE_VICTIM":
            continue
        if i == len(seg_order) - 1:
            verdicts[s] = "SLOW_LINK"  # terminus with no downstream → slow link
            continue
        dn = regimes_by_idx[i + 1]
        dn_in_window = [dn[b] for b in range(BUCKETS_PER_DAY) if mask[b]]
        dn_cong_frac = sum(1 for r in dn_in_window if r in ("CONGESTED", "SEVERE")) / max(1, len(dn_in_window))
        if dn_cong_frac < 0.20:
            verdicts[s] = "SLOW_LINK"


def diagnose_v21(corridor_id, corridor_name, segment_order, segment_meta,
                 profile_by_seg, raw_onsets=None):
    """Run v2 + v2.1 refinements. Returns CorridorDiagnosisV21."""
    # Build per-day onset dict for Stage 6 recurrence (earliest onset per seg per day).
    onsets_by_day_by_seg = None
    if raw_onsets:
        obd: dict[str, dict[str, int]] = {}
        for s, d, o in raw_onsets:
            day = obd.setdefault(str(d), {})
            if s not in day or o < day[s]:
                day[s] = o
        onsets_by_day_by_seg = obd

    # Run v2 as-is first
    diag_v2 = v2.diagnose(corridor_id, corridor_name, segment_order, segment_meta,
                          profile_by_seg, raw_onsets=raw_onsets,
                          onsets_by_day_by_seg=onsets_by_day_by_seg)
    out = CorridorDiagnosisV21(corridor_id, corridor_name, segment_order, segment_meta, v2=diag_v2)

    regimes_by_idx = [diag_v2.regimes[s] for s in segment_order]
    lengths_m = [segment_meta[s]["length_m"] for s in segment_order]

    # R1 length-weighted primary windows (replace v2's count-based)
    out.primary_windows_v21 = detect_primary_windows_lenweighted(regimes_by_idx, lengths_m)
    # Re-filter Bertini runs to the length-weighted windows
    refiltered = {}
    mask = v2.primary_window_mask(out.primary_windows_v21) if out.primary_windows_v21 else None
    for i, s in enumerate(segment_order):
        runs = diag_v2.bertini.get(s, [])
        if mask:
            runs = [(rs, re_) for rs, re_ in runs if any(mask[b] for b in range(rs, re_ + 1))]
        refiltered[s] = runs
    diag_v2.bertini = refiltered

    # R3 head-segment bottleneck
    # NB: v2's classical Bertini implementation already lets S01 fire whenever
    # upstream is None (it simply skips the upstream regime check). So all of
    # v2's S01 Bertini runs are already "head" firings by any other name.
    # v2.1 makes this EXPLICIT by (a) computing head runs without primary-window
    # filter so we also catch S01-only sustained congestion outside any
    # corridor-wide window, (b) REPLACING v2's S01 Bertini output with the head
    # runs (removes double-display), and (c) labelling the verdict HEAD_BOTTLENECK.
    out.head_bottleneck = head_bottleneck_intervals(regimes_by_idx, None)
    if out.segment_order:
        # Replace S01's Bertini with head runs so there is only one source of truth.
        diag_v2.bertini[out.segment_order[0]] = []
        # Per design intent (Stage 3 §edge segments): the terminus has no
        # downstream so we cannot apply the three-point test. v2 has a latent
        # behaviour of firing it whenever `dn is None`. v2.1 suppresses that.
        diag_v2.bertini[out.segment_order[-1]] = []

    # R5 contiguity-based systemic
    out.systemic_v21 = systemic_contiguity(regimes_by_idx, lengths_m)

    # R8 baseline saturated flags
    out.baseline_flags = flag_saturated_baselines(
        diag_v2.ff_meta, profile_by_seg, segment_order, lengths_m
    )

    # R7 confidence per segment
    onsets_by_seg = defaultdict(list)
    if raw_onsets:
        for s, d, o in raw_onsets:
            onsets_by_seg[s].append((d, o))
    sw_pairs = diag_v2.shockwave.get("pairs", [])
    for i, s in enumerate(segment_order):
        out.confidence[s] = confidence_for_segment(
            i, s, diag_v2, out.head_bottleneck, sw_pairs, onsets_by_seg, profile_by_seg,
        )

    # Verdict labels
    verdicts = {}
    for i, s in enumerate(segment_order):
        verdicts[s] = _verdict_for_segment(
            i, s, diag_v2, out.head_bottleneck, out.confidence[s],
            out.primary_windows_v21, diag_v2.regimes[s],
        )
    _refine_slow_vs_victim(segment_order, regimes_by_idx, out.primary_windows_v21, verdicts)
    out.verdicts = verdicts
    return out


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def render_v21(out: CorridorDiagnosisV21) -> str:
    diag = out.v2
    L = []
    L.append("=" * 90)
    L.append(f"TRAFFICURE CORRIDOR DIAGNOSTIC v2.1  —  {out.corridor_name}")
    L.append(f"id: {out.corridor_id}")
    L.append("=" * 90)
    total_km = sum(out.segment_meta[s]["length_m"] for s in out.segment_order) / 1000.0
    L.append(f"Segments: {len(out.segment_order)}    Corridor length: {total_km:.2f} km")

    # Stage 1 — ff
    L.append("\n--- STAGE 1 — DISCOVERED FREE FLOW ---")
    L.append(f"{'seg':<5} {'length':>8}  {'ff_tt':>7}  {'ff_spd':>9}  sat? peer qb   name")
    for i, s in enumerate(out.segment_order):
        meta = out.segment_meta[s]
        ff = diag.freeflow[s]
        fm = diag.ff_meta[s]
        bf = out.baseline_flags[s]
        flag = "!!" if bf["baseline_saturated"] else "  "
        L.append(f"S{i+1:02d}   {meta['length_m']:>6}m  {ff:>5.0f}s  "
                 f"{fm['ff_speed_kmph']:>5.1f} kmph  {flag} "
                 f"{bf['peer_ratio']:.1f}x {bf['quiet_busy_ratio']:.2f}  "
                 f"{meta['name'][:60]}")

    # Stage 2 — regime dist
    L.append("\n--- STAGE 2 — REGIME DISTRIBUTION ---")
    L.append(f"{'seg':<5}  {'FREE':>6}  {'APPR':>6}  {'CONG':>6}  {'SEVR':>6}   name")
    for i, s in enumerate(out.segment_order):
        c = Counter(diag.regimes[s])
        tot = sum(c.values()) or 1
        pct = lambda k: 100 * c.get(k, 0) / tot
        L.append(f"S{i+1:02d}  "
                 f"{pct('FREE'):>5.1f}%  {pct('APPROACHING'):>5.1f}%  "
                 f"{pct('CONGESTED'):>5.1f}%  {pct('SEVERE'):>5.1f}%   "
                 f"{out.segment_meta[s]['name'][:60]}")

    # Stage 2b — primary windows (length-weighted)
    L.append("\n--- STAGE 2b — PRIMARY CONGESTION WINDOW(S) (length-weighted, R1) ---")
    L.append(f"  rule: CONG/SEVR segments ≥ {IMPACT_MIN_FRAC*100:.0f}% of corridor LENGTH for ≥ {v2.PRIMARY_WINDOW_MIN_MIN} min")
    if not out.primary_windows_v21:
        L.append("  (no corridor-level congestion window — quiet or fragmented)")
    else:
        for ws, we in out.primary_windows_v21:
            dur = (we - ws + 1) * STEP_MIN
            L.append(f"  {_mm(ws*STEP_MIN)} – {_mm((we+1)*STEP_MIN)}   (duration {dur} min)")

    # Stage 3 — Bertini + head bottleneck
    L.append("\n--- STAGE 3 — BOTTLENECK ACTIVATION (Bertini + R3 head) ---")
    any_hit = False
    for i, s in enumerate(out.segment_order):
        runs = diag.bertini.get(s, [])
        if runs:
            any_hit = True
            ivs = ", ".join(f"{_mm(a*STEP_MIN)}–{_mm((b+1)*STEP_MIN)}" for a, b in runs)
            conf = out.confidence[s]
            L.append(f"  S{i+1:02d}  ACTIVE   {ivs}   conf={conf['label']}({conf['score']:.2f})   "
                     f"[{out.segment_meta[s]['name'][:50]}]")
    if out.head_bottleneck:
        any_hit = True
        s = out.segment_order[0]
        ivs = ", ".join(f"{_mm(a*STEP_MIN)}–{_mm((b+1)*STEP_MIN)}" for a, b in out.head_bottleneck)
        conf = out.confidence[s]
        L.append(f"  S01  HEAD     {ivs}   conf={conf['label']}({conf['score']:.2f})   "
                 f"[{out.segment_meta[s]['name'][:50]}]")
    if not any_hit:
        L.append("  (no Stage 3 activations — quiet corridor or fully systemic)")

    # Stage 4 — shockwave
    sw = diag.shockwave
    mode = sw.get("mode", "?")
    L.append(f"\n--- STAGE 4 — SHOCKWAVE VALIDATION (mode={mode}) ---")
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
    L.append("\n--- STAGE 5 — SYSTEMIC vs POINT ---")
    sys_ = diag.systemic
    L.append(f"  simultaneous (v2): {sys_['max_simultaneous']}/{len(out.segment_order)} "
             f"({sys_['max_fraction']*100:.0f}%)  threshold={v2.SYSTEMIC_ALL_FRACTION*100:.0f}%")
    sc = out.systemic_v21
    L.append(f"  contig-length (v2.1 R5): max={sc['max_contig_frac']*100:.0f}%  threshold={SYSTEMIC_CONTIG_MIN_FRAC*100:.0f}%")
    is_sys = (sys_["max_fraction"] >= v2.SYSTEMIC_ALL_FRACTION) or sc["systemic_by_contig"]
    L.append(f"  VERDICT: {'SYSTEMIC' if is_sys else 'POINT-BOTTLENECK'}")

    # Stage 6 — recurrence typing
    L.append("\n--- STAGE 6 — RECURRENCE TYPING ---")
    if not diag.recurrence:
        L.append("  (no per-day onsets supplied — recurrence not computed)")
    else:
        any_rec = next(iter(diag.recurrence.values()))
        L.append(f"  window: {any_rec['total_days']} analysed days with ≥1 onset")
        L.append(f"  bands: RECURRING≥75%, FREQUENT≥50%, OCCASIONAL≥25%, RARE≥1%, else NEVER")
        L.append(f"  {'seg':<5}  {'verdict':<18}  {'band':<11}  days  frac   name")
        for i, s in enumerate(out.segment_order):
            r = diag.recurrence.get(s, {})
            if not r:
                continue
            v_label = out.verdicts.get(s, "")
            bottleneck = v_label in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK")
            marker = "★" if bottleneck else " "
            L.append(f"  S{i+1:02d}{marker} {v_label:<18}  {r['label']:<11}  "
                     f"{r['n_days']:>2}/{r['total_days']:<2}  "
                     f"{r['frac']*100:>4.0f}%  "
                     f"{out.segment_meta[s]['name'][:55]}")
        # Explicit per-bottleneck summary (CONTEXT.md item #3: "Turn each
        # ACTIVE BOTTLENECK verdict into recurrent/frequent/episodic").
        bot = [(i, s) for i, s in enumerate(out.segment_order)
               if out.verdicts.get(s) in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK")]
        if bot:
            L.append("  ★ bottleneck recurrence summary:")
            for i, s in bot:
                r = diag.recurrence[s]
                L.append(f"      S{i+1:02d}  {out.verdicts[s]}  →  "
                         f"{r['label']} ({r['n_days']}/{r['total_days']} days, {r['frac']*100:.0f}%)")

    # Per-segment verdicts
    L.append("\n--- PER-SEGMENT VERDICTS (operator-facing) ---")
    for i, s in enumerate(out.segment_order):
        v_label = out.verdicts[s]
        c = out.confidence[s]
        L.append(f"  S{i+1:02d}  {v_label:<18}  conf={c['label']:<6} ({c['score']:.2f})  "
                 f"{out.segment_meta[s]['name'][:55]}")

    # warnings
    warns = list(diag.warnings)
    for s in out.segment_order:
        if out.baseline_flags[s]["baseline_saturated"]:
            warns.append(f"{s[:8]} baseline_saturated "
                         f"(peer {out.baseline_flags[s]['peer_ratio']:.1f}x slower, "
                         f"quiet/busy {out.baseline_flags[s]['quiet_busy_ratio']:.2f})")
    if warns:
        L.append("\n--- WARNINGS ---")
        for w in warns:
            L.append(f"  • {w}")

    return "\n".join(L)


# Serialisation helper
def to_plain_dict(out: CorridorDiagnosisV21) -> dict:
    diag = out.v2
    return {
        "corridor_id": out.corridor_id,
        "corridor_name": out.corridor_name,
        "n_segments": len(out.segment_order),
        "total_length_m": sum(out.segment_meta[s]["length_m"] for s in out.segment_order),
        "freeflow": {s: {"ff_tt": diag.freeflow[s], **diag.ff_meta[s]} for s in out.segment_order},
        "baseline_flags": out.baseline_flags,
        "primary_windows_v21": [(a, b) for a, b in out.primary_windows_v21],
        "bertini": {s: [(a, b) for a, b in diag.bertini.get(s, [])] for s in out.segment_order},
        "head_bottleneck": [(a, b) for a, b in out.head_bottleneck],
        "shockwave": diag.shockwave,
        "systemic_v2": diag.systemic,
        "systemic_v21": out.systemic_v21,
        "recurrence": diag.recurrence,
        "confidence": out.confidence,
        "verdicts": out.verdicts,
    }
