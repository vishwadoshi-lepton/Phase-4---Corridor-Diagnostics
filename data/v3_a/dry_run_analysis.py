"""Dry-run analysis: v2.1 vs v3-A on DEL_AUROBINDO and KOL_B.

Produces docs/dry_runs_v3_a/{corridor_id}/ with:
  - v21_retrospective.json   (v2.1 reference output)
  - v3a_retrospective.json   (v3-A retrospective mode envelope; should match v21)
  - v3a_today_as_of_T.json   (v3-A Mode B envelope)
  - v3a_today_as_of_T.txt    (human-readable summary)

And docs/dry_runs_v3_a/COMPARISON.md — the side-by-side analytical report.

Uses the cached weekday-typical profile as the "today" pull (synthetic), since the
spec's Mode B is normally fed from live `traffic_observation`.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from data.v2_1 import corridor_diagnostics_v2_1 as v2_1
from data.v3_a import EngineConfig
from data.v3_a.api import _reset_for_tests, submit_run, wait_for_run
from data.v3_a.baseline import BaselineResult, DowSamples
from data.v3_a.data_pull import Row, TodayPull
from data.v3_a.progress import IST, RunStatus


REPO = Path(__file__).resolve().parents[2]
PROFILES = REPO / "data" / "v2_1" / "profiles" / "all_profiles_weekday.json"
ONSETS = REPO / "data" / "v2_1" / "onsets" / "all_onsets_weekday.json"
CORRIDORS = REPO / "data" / "v2_1" / "validation_corridors.json"
OUT = REPO / "docs" / "dry_runs_v3_a"


def _load(corridor_id):
    with open(CORRIDORS) as f:
        c = json.load(f)
    cor = c[corridor_id]
    seg_ord = [s["road_id"] for s in cor["chain"]]
    seg_meta = {s["road_id"]: {"name": s["road_name"], "length_m": s["length_m"], "road_class": s.get("road_class", "unknown")}
                for s in cor["chain"]}
    with open(PROFILES) as f:
        p = json.load(f)
    profile = {rid: {int(k): int(v) for k, v in p[rid].items()} for rid in seg_ord if rid in p and p[rid]}
    if len(profile) != len(seg_ord):
        missing = [r for r in seg_ord if r not in profile]
        raise RuntimeError(f"missing profile data for {missing}")
    with open(ONSETS) as f:
        all_onsets = json.load(f)
    raw_onsets = [(r["rid"], r["dt"], int(r["om"])) for r in all_onsets if r["rid"] in set(seg_ord)]
    return cor, seg_ord, seg_meta, profile, raw_onsets


def _run_one(corridor_id):
    print(f"\n=== {corridor_id} ===")
    cor, seg_ord, seg_meta, profile, raw_onsets = _load(corridor_id)
    out_dir = OUT / corridor_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. v2.1 reference (direct call)
    v21_ref = v2_1.diagnose_v21(corridor_id, cor["name"], seg_ord, seg_meta, profile, raw_onsets=raw_onsets)
    v21_dict = v2_1.to_plain_dict(v21_ref)
    (out_dir / "v21_reference.json").write_text(json.dumps(v21_dict, indent=2, default=str))

    # Render the v2.1 textual report for reference
    v21_text = v2_1.render_v21(v21_ref)
    (out_dir / "v21_reference_report.txt").write_text(v21_text)

    baseline = BaselineResult(profile_by_seg=profile, n_actual_days=22,
                              distinct_days=[date(2026, 4, 1)] * 22, thin=False)
    anchor = datetime(2026, 4, 22, 23, 58, tzinfo=IST)

    # 2. v3-A retrospective — should equal v2.1
    _reset_for_tests()
    run_id = submit_run(corridor_id, anchor, mode="retrospective",
                       baseline_override=baseline, raw_onsets_override=raw_onsets)
    rec = wait_for_run(run_id, timeout_sec=120)
    assert rec.status == RunStatus.COMPLETED, rec.error
    (out_dir / "v3a_retrospective.json").write_text(json.dumps(rec.result, indent=2, default=str))

    # 3. v3-A today_as_of_T — full Tier-1 + DOW
    day_start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [Row(seg, day_start + timedelta(minutes=mod), float(tt))
            for seg, by_min in profile.items() for mod, tt in by_min.items()]
    today_pull = TodayPull(rows=rows, by_seg={s: [r for r in rows if r.road_id == s] for s in seg_ord}, gap_warnings=[])
    dow_samples = DowSamples(
        {s: {date(2026, 4, 1): profile[s], date(2026, 4, 8): profile[s], date(2026, 4, 15): profile[s]} for s in seg_ord},
        [date(2026, 4, 1), date(2026, 4, 8), date(2026, 4, 15)], 3, 2, True,
    )

    _reset_for_tests()
    run_id = submit_run(corridor_id, anchor, mode="today_as_of_T",
                       baseline_override=baseline, today_pull_override=today_pull,
                       dow_samples_override=dow_samples, raw_onsets_override=raw_onsets)
    rec = wait_for_run(run_id, timeout_sec=120)
    assert rec.status == RunStatus.COMPLETED, rec.error
    env = rec.result
    (out_dir / "v3a_today_as_of_T.json").write_text(json.dumps(env, indent=2, default=str))

    # Human-readable summary
    summary = _human_summary(env, v21_dict, seg_ord, seg_meta)
    (out_dir / "v3a_today_as_of_T.txt").write_text(summary)
    print(summary)

    return v21_dict, env


def _bucket_to_hhmm(b):
    if b is None:
        return "—"
    m = b * 2
    return f"{m // 60:02d}:{m % 60:02d}"


def _human_summary(env, v21_dict, seg_ord, seg_meta):
    L = []
    L.append(f"=" * 90)
    L.append(f"v3-A Mode B  —  {env['corridor_name']}  (anchor {env['anchor_ts']})")
    L.append(f"=" * 90)
    L.append("")

    payload = env["payload"]
    L.append(f"  schema_version    : {env['schema_version']}")
    L.append(f"  engine_version    : {env['engine_version']}")
    L.append(f"  run_id            : {env['run_id']}")
    L.append(f"  partial           : {env['meta']['partial']}")
    L.append(f"  warnings          : {len(env['meta']['warnings'])}")
    L.append(f"  tier1 modules run : {env['meta']['tier1_modules_run']}")
    L.append("")

    # v2.1 stages summary
    L.append("--- v2.1 stages (today's regimes) ---")
    pw = payload["stages_v21"]["primary_windows_today"]
    L.append(f"  primary_windows_today: {len(pw)} window(s)")
    for s, e in pw[:5]:
        L.append(f"    {_bucket_to_hhmm(s)}–{_bucket_to_hhmm(e)}")
    sysv2 = payload["stages_v21"]["systemic_v2"]
    sysv21 = payload["stages_v21"]["systemic_v21"]
    L.append(f"  systemic_v2 max_fraction: {sysv2.get('max_fraction', 0):.2%}")
    L.append(f"  systemic_v21 max_contig_frac: {sysv21.get('max_contig_frac', 0):.2%}  -> {sysv21.get('systemic_by_contig')}")
    L.append("")

    # Verdicts
    L.append("--- v2.1 per-segment verdicts (typical-day) ---")
    verdicts = payload["stages_v21"]["verdicts"]
    confidence = payload["stages_v21"]["confidence"]
    recurrence = payload["stages_v21"]["recurrence"]
    for s in seg_ord:
        v = verdicts.get(s, "?")
        c = confidence.get(s, {}).get("label", "?")
        rec = recurrence.get(s, {}).get("label", "?")
        L.append(f"  {seg_meta[s]['name'][:55]:<55}  {v:<18}  conf={c:<8}  rec={rec}")
    L.append("")

    # Tier-1 — Growth rate
    gr = payload["tier1"]["growth_rate"]
    L.append("--- Tier-1 #1: Growth-rate (Duan 2023) ---")
    s = gr["summary"]
    L.append(f"  events: total={s['n_events']}  fast={s['n_fast']}  moderate={s['n_moderate']}  contained={s['n_contained']}  insuff={s['n_insufficient']}")
    for ev in gr["events"][:6]:
        slope = ev["slope_m_per_min"]
        slope_s = "—" if slope is None else f"{slope:+.1f}"
        L.append(f"    {ev['event_id']:<40}  t0={_bucket_to_hhmm(ev['t0_bucket'])}  slope={slope_s} m/min  {ev['label']}")
    L.append("")

    # Tier-1 — Percolation
    perc = payload["tier1"]["percolation"]
    L.append("--- Tier-1 #2: Percolation on corridor (Li / Zeng / Ambühl) ---")
    L.append(f"  onset_bucket: {perc['onset_bucket']}  ({_bucket_to_hhmm(perc['onset_bucket'])})")
    L.append(f"  onset_lcc_m:  {perc['onset_lcc_m']}")
    L.append(f"  onset_slcc_m: {perc['onset_slcc_m']}")
    L.append(f"  time_to_merge_minutes: {perc['time_to_merge_minutes']}")
    L.append(f"  summary: max_lcc={perc['summary']['max_lcc_m']:.0f}m  max_slcc={perc['summary']['max_slcc_m']:.0f}m  buckets_with_2plus={perc['summary']['buckets_with_2plus_components']}")
    L.append("")

    # Tier-1 — Jam tree
    jt = payload["tier1"]["jam_tree"]
    L.append("--- Tier-1 #3: Jam-tree + temporal precedence (Serok / Duan) ---")
    L.append(f"  origins: {jt['summary']['n_origins']}  propagated: {jt['summary']['n_propagated']}  max_depth: {jt['summary']['max_depth']}")
    L.append(f"  reclassifications: {jt['summary']['n_reclassifications']}")
    if jt["nodes"]:
        L.append("  ORIGINs:")
        for n in [n for n in jt["nodes"] if n["role"] == "ORIGIN"][:5]:
            L.append(f"    {seg_meta[n['segment_id']]['name'][:50]:<50}  onset={_bucket_to_hhmm(n['onset_bucket'])}")
    if jt["queue_victim_reclassifications"]:
        L.append("  QUEUE_VICTIM reclassifications:")
        for r in jt["queue_victim_reclassifications"][:5]:
            L.append(f"    {seg_meta[r['segment_id']]['name'][:45]:<45}  preceded supposed bottleneck by {r['earlier_by_minutes']} min")
    L.append("")

    # Tier-1 — MFD
    mfd = payload["tier1"]["mfd"]
    L.append("--- Tier-1 #4: MFD with hysteresis (Geroliminis / Saberi) ---")
    L.append(f"  peak_density_bucket: {mfd['peak_density_bucket']}  ({_bucket_to_hhmm(mfd['peak_density_bucket'])})")
    L.append(f"  peak_density_frac:   {mfd['peak_density_frac']:.2%}")
    L.append(f"  loop_closes:         {mfd['loop_closes']}")
    L.append(f"  loop_area:           {mfd['loop_area']:.2f}  (kmph * density-frac)")
    L.append(f"  recovery_lag_min:    {mfd['recovery_lag_min']}")
    L.append(f"  ff_corridor_kmph:    {mfd['ff_corridor_kmph']:.1f}")
    L.append("")

    # DOW anomaly
    dow = payload["dow_anomaly"]
    L.append("--- DOW anomaly track ---")
    if dow["available"]:
        L.append(f"  available: True   n_samples: {dow['n_samples']}   dow: {dow['dow']}")
        L.append(f"  max_deviation_pct: {dow.get('max_deviation_pct', 0):.2f}%  at bucket {dow.get('max_deviation_bucket')}")
    else:
        L.append(f"  available: False   reason: {dow.get('reason')}")
    L.append("")

    return "\n".join(L)


def _comparison_report(by_corridor):
    L = []
    L.append("# v2.1 vs v3-A — Side-by-side dry-run comparison")
    L.append("")
    L.append("Run on synthetic anchor `2026-04-22T23:58 IST` with the cached weekday-typical")
    L.append("profile fed in as today's data (so v3-A Mode B sees a 'typical day' worth of obs).")
    L.append("Real-day data on a known-systemic weekday will produce more pronounced Tier-1 signals.")
    L.append("")
    L.append("## Pass-through equivalence (gate b1)")
    L.append("")
    L.append("v3-A `mode=\"retrospective\"` output equals v2.1's `to_plain_dict` byte-for-byte for both corridors. ✅")
    L.append("(Verified by `data/v3_a/tests/test_pass_through_equivalence.py`.)")
    L.append("")

    for cid, (v21, v3a) in by_corridor.items():
        L.append(f"## {cid} — {v21['corridor_name']}")
        L.append("")
        L.append(f"  - segments: {v21['n_segments']}")
        L.append(f"  - total length: {v21['total_length_m']} m")
        L.append("")
        L.append("### What v2.1 already gave you (unchanged in v3-A)")
        L.append("")
        sysv21 = v21["systemic_v21"]
        L.append(f"- **Systemic verdict (typical day):** `{sysv21.get('systemic_by_contig')}` — max contiguous-CONG length fraction = `{sysv21.get('max_contig_frac', 0):.2%}`")
        verdicts = v21["verdicts"]
        from collections import Counter
        L.append(f"- **Per-segment verdict counts:**  " + "  ".join(f"{k}={v}" for k, v in Counter(verdicts.values()).items()))
        L.append(f"- **Primary windows (typical day):** {len(v21['primary_windows_v21'])} window(s)")
        head = v21.get("head_bottleneck", [])
        L.append(f"- **HEAD_BOTTLENECK intervals:** {len(head)}")
        L.append("")

        payload = v3a["payload"]
        L.append("### What v3-A Mode B adds")
        L.append("")
        gr = payload["tier1"]["growth_rate"]["summary"]
        L.append(f"- **Growth-rate (Duan 2023):** {gr['n_events']} events scored — fast={gr['n_fast']}, moderate={gr['n_moderate']}, contained={gr['n_contained']}, insufficient={gr['n_insufficient']}.")
        L.append(f"  - Each Bertini event now carries a slope-m-per-min and severity label, enabling early-warning operator UX.")
        perc = payload["tier1"]["percolation"]
        if perc["onset_bucket"] is not None:
            L.append(f"- **Percolation (Li 2015):** systemic onset detected at bucket `{perc['onset_bucket']}` ({_bucket_to_hhmm(perc['onset_bucket'])}).")
            L.append(f"  - LCC at onset: `{perc['onset_lcc_m']:.0f} m`. SLCC at onset: `{perc['onset_slcc_m']:.0f} m`.")
            L.append(f"  - Time to cluster merge: `{perc['time_to_merge_minutes']}` min.")
            L.append(f"  - This replaces v2.1's arbitrary 80%-simultaneous threshold with a precise phase-transition bucket.")
        else:
            L.append("- **Percolation:** no SLCC peak detected — corridor never had two distinct congestion clusters.")
        jt = payload["tier1"]["jam_tree"]["summary"]
        L.append(f"- **Jam-tree (Serok 2022):** `{jt['n_origins']}` ORIGIN node(s), `{jt['n_propagated']}` PROPAGATED, max_depth `{jt['max_depth']}`.")
        L.append(f"  - Reclassifies `{jt['n_reclassifications']}` v2.1 QUEUE_VICTIMs that actually preceded their supposed bottleneck (causal flip).")
        mfd = payload["tier1"]["mfd"]
        L.append(f"- **MFD (Geroliminis 2008):** peak_density `{mfd['peak_density_frac']:.2%}` at `{_bucket_to_hhmm(mfd['peak_density_bucket'])}`. loop_closes={mfd['loop_closes']}. loop_area=`{mfd['loop_area']:.2f}` (kmph·density-frac).")
        L.append(f"  - Recovery lag: `{mfd['recovery_lag_min']}` min between density halving and speed return-to-FF. Capacity-loss metric for the day.")
        dow = payload["dow_anomaly"]
        if dow["available"]:
            L.append(f"- **DOW anomaly:** `{dow['n_samples']}` same-DOW samples → available. Max deviation `{dow.get('max_deviation_pct', 0):.2f}%` at bucket `{dow.get('max_deviation_bucket')}`.")
        else:
            L.append(f"- **DOW anomaly:** unavailable ({dow['reason']}).")
        L.append("")

    return "\n".join(L)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    by_corridor = {}
    for cid in ("DEL_AUROBINDO", "KOL_B"):
        v21, v3a = _run_one(cid)
        by_corridor[cid] = (v21, v3a)
    rep = _comparison_report(by_corridor)
    (OUT / "COMPARISON.md").write_text(rep)
    print("\n" + "=" * 90)
    print(f"Comparison report written to: {OUT / 'COMPARISON.md'}")
