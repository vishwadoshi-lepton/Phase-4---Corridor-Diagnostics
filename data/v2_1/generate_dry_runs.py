#!/usr/bin/env python3
"""
Regenerate HTML dry-run docs for every corridor in the v2.1 validation set.

Pure data pipeline:
  inputs  = validation_corridors.json  (chain + names + lengths)
            profiles/all_profiles.json (2-min weekday-median travel times)
            runs/v2_1/v2_1_validation_structured.json (full pipeline output)
  outputs = docs/dry_runs/{corridor_id}_dry_run.html  (one per corridor)

No AI, no per-corridor hand-written prose. Static educational callouts ("why
three points and not just one", "why we don't trust vendor freeflow") are
identical across every corridor. Corridor-specific observations (hand-off
moments, one-paragraph summary, Stage 4 lag story) are computed from the
structured output at render time.
"""
from __future__ import annotations
import argparse, json, os, sys, html as _html

HERE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
DATA_DIR     = os.path.abspath(os.path.join(PROJECT_ROOT, "data"))
OUT_DIR      = os.path.join(PROJECT_ROOT, "docs", "dry_runs")
CORRIDORS_PATH  = os.path.join(HERE, "validation_corridors.json")

sys.path.insert(0, DATA_DIR)
import corridor_diagnostics_v2 as v2  # noqa: E402


def resolve_slice_paths(slice_: str) -> tuple[str, str]:
    """Return (structured_path, profiles_path) for this slice, with legacy fallback."""
    structured_suffixed = os.path.join(PROJECT_ROOT, "runs", "v2_1", f"v2_1_validation_{slice_}_structured.json")
    structured_legacy   = os.path.join(PROJECT_ROOT, "runs", "v2_1", "v2_1_validation_structured.json")
    profiles_suffixed   = os.path.join(HERE, "profiles", f"all_profiles_{slice_}.json")
    profiles_legacy     = os.path.join(HERE, "profiles", "all_profiles.json")
    structured = structured_suffixed if os.path.isfile(structured_suffixed) else (
        structured_legacy if slice_ == "weekday" and os.path.isfile(structured_legacy) else None)
    profiles = profiles_suffixed if os.path.isfile(profiles_suffixed) else (
        profiles_legacy if slice_ == "weekday" and os.path.isfile(profiles_legacy) else None)
    if not structured or not profiles:
        raise FileNotFoundError(f"missing input files for slice={slice_}: "
                                f"structured={structured_suffixed}, profiles={profiles_suffixed}")
    return structured, profiles

# ---- constants ----
REG_CHAR = {"FREE": "F", "APPROACHING": "A", "CONGESTED": "C", "SEVERE": "S"}
VERDICT_BADGE_CLASS = {
    "FREE_FLOW":         "verdict-free_flow",
    "SLOW_LINK":         "verdict-slow_link",
    "QUEUE_VICTIM":      "verdict-queue_victim",
    "ACTIVE_BOTTLENECK": "verdict-active_bottleneck",
    "HEAD_BOTTLENECK":   "verdict-head_bottleneck",
}
VERDICT_SVG_FILL = {
    "FREE_FLOW":         ("#10b981", 0.22),
    "SLOW_LINK":         ("#eab308", 0.25),
    "QUEUE_VICTIM":      ("#f97316", 0.28),
    "ACTIVE_BOTTLENECK": ("#dc2626", 0.30),
    "HEAD_BOTTLENECK":   ("#db2777", 0.30),
}
CONF_LABEL_CLASS = {"HIGH": "label-high", "MEDIUM": "label-medium", "LOW": "label-low"}

# ---- helpers ----
def esc(s): return _html.escape(str(s), quote=True)

def clock(bucket: int) -> str:
    m = int(bucket) * 2
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"

def bucket_range(a: int, b: int) -> str:
    return f"{clock(a)} – {clock(b)}"

def duration_min(a: int, b: int) -> int:
    return (b - a + 1) * 2

def regimes_for_seg(profile: dict, ff_tt: float) -> tuple[str, list]:
    tts = [0] * v2.BUCKETS_PER_DAY
    for k, tt in profile.items():
        b = int(k) // 2
        if 0 <= b < v2.BUCKETS_PER_DAY:
            tts[b] = tt
    regs = v2.classify_regimes(tts, ff_tt)
    return "".join(REG_CHAR.get(r, ".") for r in regs), tts

# ---- per-section renderers ----
def render_corridor_svg(chain: list, verdicts: dict, freeflow: dict) -> str:
    total = sum(c["length_m"] for c in chain) or 1
    W, H = 1000.0, 180.0
    x0, x1 = 40.0, 960.0
    track = x1 - x0
    parts = [f'<svg class="corridor" viewBox="0 0 {int(W)} {int(H)}" xmlns="http://www.w3.org/2000/svg">',
             f'<line x1="{x0}" y1="90" x2="{x1}" y2="90" stroke="#cbd5e1" stroke-width="2"/>']
    xc = x0
    for i, seg in enumerate(chain):
        w = track * seg["length_m"] / total
        v = verdicts.get(seg["road_id"], "FREE_FLOW")
        fill, op = VERDICT_SVG_FILL.get(v, ("#3b82f6", 0.22))
        cx = xc + w / 2
        ff = freeflow.get(seg["road_id"], {})
        ff_spd = ff.get("ff_speed_kmph", 0)
        ff_tt  = ff.get("ff_tt", 0)
        parts.append(
            f'<rect x="{xc:.2f}" y="76" width="{w:.2f}" height="28" rx="4" '
            f'fill="{fill}" fill-opacity="{op}" stroke="{fill}" stroke-width="1.5"/>'
        )
        parts.append(f'<text x="{cx:.2f}" y="95" text-anchor="middle" font-size="13" font-weight="600" fill="#0f172a">S{i+1:02d}</text>')
        parts.append(f'<text x="{cx:.2f}" y="60" text-anchor="middle" font-size="11" fill="#475569">{seg["length_m"]} m</text>')
        parts.append(f'<text x="{cx:.2f}" y="124" text-anchor="middle" font-size="10" fill="#64748b">{ff_spd:.1f} km/h</text>')
        parts.append(f'<text x="{cx:.2f}" y="138" text-anchor="middle" font-size="10" fill="#94a3b8">ff_tt {ff_tt:.0f}s</text>')
        xc += w
    upstream_label   = esc(chain[0]["road_name"].split(" To ")[0].split("/")[-1])
    downstream_label = esc(chain[-1]["road_name"].split(" To ")[-1].split("/")[-1])
    parts.append(f'<text x="{x0}" y="30" font-size="12" fill="#1e293b">⬅ upstream ({upstream_label})</text>')
    parts.append(f'<text x="{x1}" y="30" text-anchor="end" font-size="12" fill="#1e293b">downstream ({downstream_label}) ➡</text>')
    parts.append(f'<text x="{(x0+x1)/2:.1f}" y="170" text-anchor="middle" font-size="11" fill="#64748b" font-style="italic">segments drawn to scale; total corridor length {int(total)} m</text>')
    parts.append('</svg>')
    return "\n".join(parts)

def render_stage1_table(chain: list, freeflow: dict) -> str:
    rows = []
    for i, seg in enumerate(chain):
        ff = freeflow[seg["road_id"]]
        raw_ff = ff.get("raw_ff_sec")
        clamped_ff = ff.get("clamped_ff_sec", ff["ff_tt"])
        clamp = "yes" if raw_ff is not None and raw_ff != clamped_ff else "no"
        warns = ff.get("warnings") or []
        warn_txt = "; ".join(warns) if warns else "—"
        qws = ff.get("quiet_windows") or []
        if qws:
            a, b = qws[0]
            quiet_txt = f"{a}–{b}"
            if len(qws) > 1:
                quiet_txt += f" (+{len(qws)-1} more)"
        else:
            quiet_txt = "—"
        rows.append(
            "<tr>"
            f"<td><b>S{i+1:02d}</b></td>"
            f'<td style="max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{esc(seg["road_name"])}">{esc(seg["road_name"])}</td>'
            f"<td>{seg['length_m']}</td>"
            f"<td>{esc(seg.get('road_class', ''))}</td>"
            f"<td>{ff['ff_tt']:.0f} s</td>"
            f"<td><b>{ff['ff_speed_kmph']:.1f}</b></td>"
            f"<td><code>{quiet_txt}</code></td>"
            f"<td>{clamp}</td>"
            f"<td>{esc(warn_txt)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Seg</th><th>Road name</th><th>Length (m)</th>"
        "<th>Class</th><th>ff_tt (p15)</th><th>ff_spd (km/h)</th>"
        "<th>Quietest window (IST)</th><th>80 km/h clamp?</th><th>Warnings</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )

def render_primary_window_block(primary_windows: list, regimes_by_idx: list, chain: list) -> str:
    total_len = sum(c["length_m"] for c in chain)
    if primary_windows:
        rows = []
        for a, b in primary_windows:
            rows.append(f"<tr><td><code>[{a}, {b}]</code></td><td><b>{bucket_range(a, b)}</b></td><td>{b-a+1}</td><td>{duration_min(a, b)} min</td></tr>")
        table = "<table><thead><tr><th>Bucket interval</th><th>IST clock time</th><th># buckets</th><th>Duration</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        return f'<div class="callout"><b>{len(primary_windows)} primary window(s) fired</b> — ≥25% of corridor length simultaneously CONG/SEVR for ≥30 min.</div>{table}'
    # No windows — show the peak hot-fraction so readers see how close we got
    peak_frac, peak_b, peak_segs = 0.0, 0, []
    for b in range(v2.BUCKETS_PER_DAY):
        hot_len = 0.0
        hot_idxs = []
        for i, reg in enumerate(regimes_by_idx):
            if reg[b] in ("CONGESTED", "SEVERE"):
                hot_len += chain[i]["length_m"]
                hot_idxs.append(i)
        frac = hot_len / total_len if total_len else 0.0
        if frac > peak_frac:
            peak_frac, peak_b, peak_segs = frac, b, hot_idxs
    seg_list = " + ".join(f"S{i+1:02d} ({chain[i]['length_m']} m)" for i in peak_segs) or "none"
    hot_sum  = sum(chain[i]["length_m"] for i in peak_segs)
    math_block = (
        '<details><summary>The math, spelled out</summary>'
        f'<pre style="font-size:12px; background:#f1f5f9; padding:10px; border-radius:6px; overflow:auto;">'
        f"corridor_length = {total_len} m\n"
        f"At peak bucket ({peak_b}, i.e. {clock(peak_b)} IST):\n"
        f"  CONG/SEVR segments: {seg_list} = {hot_sum} m\n"
        f"  hot_fraction = {hot_sum} / {total_len} = {peak_frac:.3f} = {peak_frac*100:.1f}%\n"
        f"Threshold: 0.25 (25%) for ≥15 consecutive buckets (30 min)\n"
        f"Result: fraction never crosses 0.25 → no primary window fires"
        "</pre></details>"
    )
    return (
        f'<div class="callout"><b>No primary windows fired.</b> Peak corridor-level stress '
        f'was <b>{hot_sum} m / {total_len} m = {peak_frac*100:.1f}%</b> at {clock(peak_b)}, '
        f'below the 25% threshold. The corridor is never "under stress" as a whole — '
        f'downstream stages will treat it as a POINT problem.</div>{math_block}'
    )

def render_bertini_table(chain: list, bertini: dict) -> str:
    rows = []
    for i, seg in enumerate(chain):
        runs = bertini.get(seg["road_id"], [])
        if not runs:
            continue
        for a, b in runs:
            rows.append(
                f"<tr><td><b>S{i+1:02d}</b></td><td>{esc(seg['road_name'])}</td>"
                f"<td><code>[{a}, {b}]</code></td>"
                f"<td><b>{bucket_range(a, b)}</b></td>"
                f"<td>{b-a+1}</td><td>{duration_min(a, b)} min</td></tr>"
            )
    if not rows:
        return '<div class="callout">Bertini did not fire on any segment in a primary window.</div>'
    return (
        "<table><thead><tr><th>Seg</th><th>Road</th><th>Bucket</th>"
        "<th>IST clock</th><th># buckets</th><th>Duration</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )

def render_head_block(chain: list, head: list) -> str:
    if not head:
        return '<div class="callout">R3 head bottleneck did not fire — S01 was not sustained CONG/SEVR while S02 discharged freely.</div>'
    s01 = chain[0]
    rows = []
    for a, b in head:
        rows.append(
            f"<tr><td><code>[{a}, {b}]</code></td>"
            f"<td><b>{bucket_range(a, b)}</b></td>"
            f"<td>{b-a+1}</td><td>{duration_min(a, b)} min</td></tr>"
        )
    table = (
        f'<h3 style="margin-top:18px;font-size:15px;">S01 · {esc(s01["road_name"])} — head runs</h3>'
        '<table><thead><tr><th>Bucket interval</th><th>IST clock</th>'
        '<th># buckets</th><th>Duration</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table>"
    )
    return table

def render_shockwave_table(pairs: list) -> str:
    rows = []
    passes = 0
    total = 0
    for p in pairs:
        if "skipped" in p:
            i, j = p["pair"]
            rows.append(
                f"<tr><td>S{i+1:02d} → S{j+1:02d}</td>"
                f"<td colspan='5' style='color:#64748b;'>skipped ({esc(p['skipped'])})</td></tr>"
            )
            continue
        total += 1
        i, j = p["pair"]
        dist = p["dist_m"]
        exp_lo, exp_hi = p["expected_lag_range_min"]
        obs = p["observed_lag_min"]
        result = "PASS" if p["pass"] else "FAIL"
        cls = "pass" if p["pass"] else "fail"
        mark = "✅" if p["pass"] else "❌"
        if p["pass"]:
            passes += 1
        n_days = p.get("n_days", "—")
        rows.append(
            f"<tr><td>S{i+1:02d} → S{j+1:02d}</td><td>{dist:.0f} m</td>"
            f"<td>{exp_lo:.1f} – {exp_hi:.1f} min</td>"
            f"<td>{obs:+.1f} min</td><td>{n_days}</td>"
            f"<td class='{cls}'>{mark} {result}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Pair</th><th>Distance</th>"
        "<th>Expected lag (12–22 km/h)</th><th>Observed lag</th>"
        "<th># days</th><th>Result</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    ), passes, total

def render_confidence_table(chain: list, confidence: dict, verdicts: dict) -> str:
    def bar(val: float, color: str, name: str) -> str:
        w = max(0.0, min(1.0, float(val))) * 25.0
        return (f'<div class="sbar-seg" style="width:{w:.3f}%;background:{color}" '
                f'title="{name}={val:.2f}"></div>')
    rows = []
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        c = confidence[rid]
        br = c.get("breakdown", {})
        label = c.get("label", "LOW")
        cls   = CONF_LABEL_CLASS.get(label, "label-low")
        v     = verdicts.get(rid, "FREE_FLOW")
        badge = VERDICT_BADGE_CLASS.get(v, "verdict-free_flow")
        stacked = (
            '<div class="sbar">'
            + bar(br.get("ff_tight", 0),          "#3b82f6", "ff_tight")
            + bar(br.get("primary_overlap", 0),   "#8b5cf6", "primary_overlap")
            + bar(br.get("onset_support", 0),     "#14b8a6", "onset_support")
            + bar(br.get("shockwave_support", 0), "#f59e0b", "shockwave_support")
            + '</div>'
        )
        rows.append(
            f"<tr><td><b>S{i+1:02d}</b></td>"
            f"<td><span class='verdict {badge}'>{v}</span></td>"
            f"<td>{c['score']:.2f}</td>"
            f"<td><span class='{cls}'>{label}</span></td>"
            f"<td>{br.get('ff_tight', 0):.2f}</td>"
            f"<td>{br.get('primary_overlap', 0):.2f}</td>"
            f"<td>{br.get('onset_support', 0):.2f}</td>"
            f"<td>{br.get('shockwave_support', 0):.2f}</td>"
            f"<td class='bar-cell'>{stacked}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Seg</th><th>Verdict</th><th>Score</th><th>Label</th>"
        "<th>ff_tight</th><th>primary_overlap</th><th>onset_support</th>"
        "<th>shockwave_support</th><th>Breakdown</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )

def render_r8_table(chain: list, baseline_flags: dict) -> str:
    rows = []
    for i, seg in enumerate(chain):
        b = baseline_flags.get(seg["road_id"], {})
        flag = "🔴 FLAGGED" if b.get("baseline_saturated") else "🟢 clear"
        rows.append(
            f"<tr><td><b>S{i+1:02d}</b></td>"
            f"<td>{b.get('ff_speed_kmph', 0):.1f}</td>"
            f"<td>{b.get('corridor_median_speed', 0):.1f}</td>"
            f"<td>{b.get('peer_ratio', 0):.2f}</td>"
            f"<td>{b.get('quiet_busy_ratio', 0):.3f}</td>"
            f"<td>{flag}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Seg</th><th>ff_spd (km/h)</th><th>Corridor median</th>"
        "<th>Peer ratio</th><th>Quiet/busy ratio</th><th>Flag</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )

def render_recurrence_block(chain: list, recurrence: dict, verdicts: dict) -> str:
    if not recurrence:
        return '<div class="callout">No per-day onsets supplied — recurrence not computed.</div>'
    any_r = next(iter(recurrence.values()))
    total_days = any_r.get("total_days", 0)
    header = (
        f'<div class="callout"><b>{total_days} analysed days with ≥1 onset.</b> '
        'Bands: RECURRING ≥ 75%, FREQUENT ≥ 50%, OCCASIONAL ≥ 25%, RARE ≥ 1%, else NEVER. '
        'Per <code>CONTEXT.md</code> item #3, each ACTIVE_BOTTLENECK / HEAD_BOTTLENECK verdict gets tagged with its recurrence band.</div>'
    )
    rows = []
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        r = recurrence.get(rid, {})
        v = verdicts.get(rid, "FREE_FLOW")
        star = "★" if v in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK") else ""
        badge = VERDICT_BADGE_CLASS.get(v, "verdict-free_flow")
        rows.append(
            f"<tr><td><b>S{i+1:02d}</b> {star}</td>"
            f"<td><span class='verdict {badge}'>{v}</span></td>"
            f"<td><b>{r.get('label', '—')}</b></td>"
            f"<td>{r.get('n_days', 0)} / {r.get('total_days', 0)}</td>"
            f"<td>{r.get('frac', 0)*100:.0f}%</td>"
            f"<td>{esc(seg['road_name'])}</td></tr>"
        )
    table = (
        "<table><thead><tr><th>Seg</th><th>Verdict</th><th>Band</th>"
        "<th>Days</th><th>Frac</th><th>Road</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )
    bots = [(i, seg) for i, seg in enumerate(chain)
            if verdicts.get(seg["road_id"]) in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK")]
    summary = ""
    if bots:
        li = []
        for i, seg in bots:
            r = recurrence[seg["road_id"]]
            v = verdicts[seg["road_id"]]
            li.append(f"<li><b>S{i+1:02d}</b> ({v}) → <b>{r['label']}</b> ({r['n_days']}/{r['total_days']} days, {r['frac']*100:.0f}%)</li>")
        summary = f'<div class="story"><b>Bottleneck recurrence summary</b><ul>{"".join(li)}</ul></div>'
    return header + table + summary

def render_final_verdicts(chain: list, verdicts: dict, confidence: dict) -> str:
    rows = []
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        v = verdicts.get(rid, "FREE_FLOW")
        c = confidence.get(rid, {})
        badge = VERDICT_BADGE_CLASS.get(v, "verdict-free_flow")
        label = c.get("label", "LOW")
        cls   = CONF_LABEL_CLASS.get(label, "label-low")
        rows.append(
            f"<tr><td><b>S{i+1:02d}</b></td><td>{esc(seg['road_name'])}</td>"
            f"<td>{seg['length_m']} m</td>"
            f"<td><span class='verdict {badge}'>{v}</span></td>"
            f"<td><span class='{cls}'>{label}</span> ({c.get('score', 0):.2f})</td></tr>"
        )
    return (
        "<table><thead><tr><th>Seg</th><th>Road name</th><th>Length</th>"
        "<th>Verdict</th><th>Confidence</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )

def render_handoff_story(chain: list, bertini: dict, head: list) -> str:
    if not head or len(chain) < 2:
        return ""
    s02_runs = bertini.get(chain[1]["road_id"], [])
    if not s02_runs:
        return ""
    # Find the closest head-end → S02-Bertini-start pair with a small positive gap.
    best = None
    for _, he in head:
        for bs, _ in s02_runs:
            gap = bs - he
            if 0 <= gap <= 15 and (best is None or gap < best[0]):
                best = (gap, he, bs)
    if not best:
        return ""
    gap_buckets, he, bs = best
    return (
        f'<div class="story"><b>Hand-off moment</b> — an S01 head run ends at '
        f'<b>{clock(he)}</b>; the next S02 Bertini fire starts at '
        f'<b>{clock(bs)}</b>. A {gap_buckets*2}-min gap marks the transition '
        f'from S01-only congestion to S02 becoming the operative active bottleneck. '
        'This falls out of the regime definitions — the pipeline has no explicit rule for it.</div>'
    )

def render_one_paragraph_story(
    corridor_name: str, total_len_m: int, verdicts: dict, chain: list,
    systemic_v2: dict, systemic_v21: dict, sw_pass_rate: float | None,
    primary_windows: list
) -> str:
    n_seg = len(chain)
    v_counts = {k: 0 for k in ("FREE_FLOW", "SLOW_LINK", "QUEUE_VICTIM",
                                "ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK")}
    for s in chain:
        v_counts[verdicts.get(s["road_id"], "FREE_FLOW")] = v_counts.get(
            verdicts.get(s["road_id"], "FREE_FLOW"), 0) + 1
    is_sys = (systemic_v2.get("max_fraction", 0) >= v2.SYSTEMIC_ALL_FRACTION) \
             or bool(systemic_v21.get("systemic_by_contig"))
    verdict_word = "SYSTEMIC" if is_sys else "POINT bottleneck"
    bot_segs = [f"S{i+1:02d}" for i, seg in enumerate(chain)
                if verdicts.get(seg["road_id"]) in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK")]
    bot_text = ", ".join(bot_segs) if bot_segs else "none"
    pw_text = f"{len(primary_windows)} primary window(s)" if primary_windows else "no primary window"
    sw_text = (f"{sw_pass_rate*100:.0f}% shockwave pass rate"
               if sw_pass_rate is not None else "shockwave N/A")
    return (
        f'<div class="story"><b>One-paragraph story</b> — {esc(corridor_name)} is '
        f'a <b>{verdict_word}</b> corridor ({n_seg} segments, {total_len_m} m). '
        f'Stage 2b found {pw_text}. Stage 3 fired on {bot_text} '
        f'({v_counts["ACTIVE_BOTTLENECK"]} active + {v_counts["HEAD_BOTTLENECK"]} head); '
        f'{sw_text}. Stage 5 simultaneity peaked at '
        f'{systemic_v2.get("max_fraction", 0)*100:.0f}%; contiguous-length peaked at '
        f'{systemic_v21.get("max_contig_frac", 0)*100:.0f}%.</div>'
    )

def render_shockwave_narrative(passes: int, total: int, pairs: list, verdicts: dict, chain: list) -> str:
    if total == 0:
        return '<div class="callout">No valid shockwave pairs.</div>'
    pass_rate = passes / total
    neg = sum(1 for p in pairs if "observed_lag_min" in p and p.get("observed_lag_min", 0) < 0)
    n_active = sum(1 for s in chain if verdicts.get(s["road_id"]) == "ACTIVE_BOTTLENECK")
    sys_hint = ("A low SW pass rate on a POINT corridor is expected — negative lags "
                "mean the queue backs UP past segment boundaries rather than propagating "
                "as a forward shockwave.") if n_active <= 1 else (
                "Mixed-sign lags on a SYSTEMIC corridor reflect multiple active chokes "
                "whose shockwaves overlap and partially cancel.")
    return (f'<div class="callout"><b>Pass rate: {pass_rate*100:.0f}% ({passes} of {total})</b> — '
            f'{neg} pair(s) show negative observed lag (downstream onset before upstream). '
            f'{sys_hint}</div>')

# ---- master template ----
CSS = """<style>
  :root {
    --bg:#f8fafc; --card:#ffffff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0;
    --accent:#1d4ed8; --accent-soft:#dbeafe;
    --free:#16a34a; --appr:#eab308; --cong:#f97316; --sevr:#dc2626;
  }
  html,body { background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif; margin:0; padding:0; line-height:1.55; font-size:15px; }
  .wrap { display:grid; grid-template-columns: 220px 1fr; gap:32px; max-width:1200px; margin:0 auto; padding:32px; }
  nav.toc { position:sticky; top:24px; align-self:start; font-size:13px; }
  nav.toc h2 { font-size:12px; text-transform:uppercase; letter-spacing:0.1em; color:var(--muted); margin:0 0 8px; }
  nav.toc a { display:block; padding:4px 0; color:#334155; text-decoration:none; }
  nav.toc a:hover { color:var(--accent); }
  header.hero { background:linear-gradient(135deg,#1e40af,#1d4ed8); color:#fff; padding:32px; border-radius:14px; margin-bottom:28px; }
  header.hero h1 { margin:0 0 6px; font-size:28px; letter-spacing:-0.01em; }
  header.hero .sub { opacity:0.85; font-size:14px; }
  header.hero .meta { display:flex; gap:22px; margin-top:18px; flex-wrap:wrap; font-size:13px; }
  header.hero .meta div span { display:block; opacity:0.7; font-size:11px; text-transform:uppercase; letter-spacing:0.08em; }
  section { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:24px 28px; margin-bottom:22px; }
  section h2 { margin:0 0 4px; font-size:20px; letter-spacing:-0.01em; }
  section .stage-sub { color:var(--muted); font-size:13px; margin-bottom:14px; }
  .why { background:#fef9c3; border-left:4px solid #ca8a04; padding:12px 16px; border-radius:6px; margin:14px 0; font-size:14px; }
  .why b { color:#713f12; }
  .callout { background:#ede9fe; border-left:4px solid #7c3aed; padding:12px 16px; border-radius:6px; margin:14px 0; font-size:14px; }
  .callout b { color:#5b21b6; }
  .story { background:#ecfeff; border-left:4px solid #0891b2; padding:14px 18px; border-radius:6px; margin:16px 0; font-size:14px; }
  .story b { color:#155e75; }
  table { width:100%; border-collapse:collapse; font-size:13px; margin:10px 0; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { background:#f1f5f9; font-weight:600; color:#1e293b; }
  td code { background:#f1f5f9; padding:1px 6px; border-radius:4px; font-size:12px; }
  .pass { color:var(--free); font-weight:600; }
  .fail { color:var(--sevr); font-weight:600; }
  svg.corridor, svg.diagram { width:100%; height:auto; }
  .strip-row { display:grid; grid-template-columns: 60px 1fr 70px; gap:10px; align-items:center; margin:3px 0; }
  .strip-row .seg-label { font-weight:700; color:#1e293b; font-size:13px; }
  .strip { display:flex; width:100%; height:20px; border-radius:3px; overflow:hidden; box-shadow:inset 0 0 0 1px rgba(0,0,0,0.05); cursor:crosshair; }
  .strip .cell { flex:1 1 0; height:100%; }
  .strip-row .seg-stats { font-size:11px; color:var(--muted); text-align:right; font-variant-numeric:tabular-nums; }
  .ticks { display:grid; grid-template-columns: 60px 1fr 70px; gap:10px; margin-top:6px; margin-bottom:4px; }
  .ticks .axis { display:flex; justify-content:space-between; font-size:10px; color:var(--muted); }
  .legend { display:flex; gap:14px; font-size:12px; color:var(--muted); margin:10px 0 16px; }
  .legend span.sw { display:inline-block; width:14px; height:14px; border-radius:3px; vertical-align:middle; margin-right:5px; }
  #tip { position:fixed; pointer-events:none; background:#0f172a; color:#f8fafc; padding:8px 10px; border-radius:6px; font-size:12px; z-index:999; display:none; white-space:nowrap; box-shadow:0 6px 20px rgba(15,23,42,0.25); }
  #tip .tip-head { font-weight:700; font-size:11px; opacity:0.9; margin-bottom:3px; letter-spacing:0.04em; }
  .verdict { display:inline-block; padding:2px 10px; border-radius:99px; font-size:11px; font-weight:700; letter-spacing:0.04em; }
  .verdict-free_flow        { background:#dcfce7; color:#14532d; }
  .verdict-slow_link        { background:#fef3c7; color:#713f12; }
  .verdict-queue_victim     { background:#fed7aa; color:#7c2d12; }
  .verdict-active_bottleneck{ background:#fecaca; color:#7f1d1d; }
  .verdict-head_bottleneck  { background:#fbcfe8; color:#831843; }
  .label-high   { color:var(--free); font-weight:700; }
  .label-medium { color:#ca8a04; font-weight:700; }
  .label-low    { color:var(--sevr); font-weight:700; }
  .sbar { display:flex; width:100%; height:14px; border-radius:7px; overflow:hidden; background:#e2e8f0; }
  .sbar-seg { height:100%; }
  td.bar-cell { min-width:180px; }
  .kpis { display:grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin:12px 0 20px; }
  .kpi { background:#f8fafc; border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
  .kpi .k { font-size:11px; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin-bottom:4px; }
  .kpi .v { font-size:20px; font-weight:700; color:var(--ink); font-variant-numeric:tabular-nums; }
  .kpi .s { font-size:11px; color:var(--muted); margin-top:2px; }
  details { margin:10px 0; background:#f8fafc; border:1px solid var(--line); border-radius:6px; padding:10px 14px; }
  details summary { cursor:pointer; font-weight:600; color:#334155; font-size:13px; }
  details[open] summary { margin-bottom:10px; }
  @media (max-width: 900px) { .wrap { grid-template-columns:1fr; } nav.toc { position:static; } }
  @media print { nav.toc { display:none; } .wrap { grid-template-columns:1fr; padding:0; } }
</style>"""

WHY_STAGE1 = ('<div class="why"><b>Why we don\'t trust static speed limits or vendor "freeflow"</b> — '
              "Urban signs say 50 km/h but real geometry + signal density often caps you at 35. Vendor "
              "freeflow columns are heuristic blends of nighttime averages and road-class defaults; "
              "the DB's <code>freeflow_travel_time_sec</code> mirrors the 8–9 am commute median within "
              "±1 s on every Pune segment, which means using it would silently anchor regime classification "
              "to a <i>congested</i> baseline. Discovering free flow from each segment's own quietest "
              "30 min is the only defensible baseline.</div>")

WHY_STAGE2 = ('<div class="why"><b>Why 0.80 / 0.50 / 0.30 and not other numbers</b> — '
              "These breakpoints come from the Greenshields / Van Aerde family of speed–density models. "
              "A road at 80% of free-flow speed is physically near capacity (<i>stable dense flow</i>). "
              "At 50% you're past the critical speed (<i>LOS E</i>). At 30% you're in stop-and-go "
              "(<i>LOS F</i>). They are traffic-engineering numbers, not tuned knobs.</div>")

WHY_STAGE2B = ('<div class="why"><b>Why v2.1 switched from segment-count to length-weighted</b> — '
               'v2 used "≥ 25% of segments congested". That treats a 3,451 m highway segment and a 314 m '
               "arterial stub as equivalent votes, which gets the physics backwards. The length-weighted "
               "rule is what makes the POINT vs SYSTEMIC distinction robust against pathological corridor shapes.</div>")

WHY_STAGE3 = ('<div class="why"><b>Why three points and not just one</b> — '
              "A slow segment and a bottleneck look identical on a speed-only map (both are red). "
              "The difference is what's happening on either side. A bottleneck makes a <b>queue back up</b> "
              "upstream because demand outstrips capacity at the choke — and past the choke, traffic "
              "<b>discharges freely</b> because you're downstream of the restriction. Bertini &amp; Leal's "
              "2005 insight: use the three-point pattern as the <i>operational definition</i> of active "
              "bottleneck. Physically verifiable, no thresholds to tune.</div>")

WHY_STAGE3R3 = ('<div class="why"><b>Why R3 matters</b> — On a recorded corridor, the "first" segment is '
                "almost always the place where a junction queue starts. There's no S00 to act as the upstream "
                "anchor, so classical Bertini has a structural blind spot at S01. R3 adds a two-point relaxation: "
                "<b>if S01 is CONG/SEVR and S02 is FREE/APPR, that IS a head bottleneck</b>.</div>")

WHY_STAGE4 = ('<div class="why"><b>Why shockwave validation is a check, not a gate</b> — '
              "Bertini is already strong on its own. Shockwaves have a physical meaning: when a bottleneck "
              "forms, the congestion boundary <i>propagates backwards</i> at 12–22 km/h (LWR model). "
              "Low pass rate <b>doesn't</b> mean Bertini is wrong — it usually means the congestion is local "
              "(doesn't propagate far), or the onset signal is noisy.</div>")

WHY_STAGE5 = ('<div class="why"><b>Why two rules and not one</b> — '
              "v2's simultaneity rule (≥80% of segments CONG at the same bucket) catches the canonical "
              "corridor-wide jam. v2.1 adds a contiguity rule (≥60% of corridor <i>length</i> in one "
              "unbroken CONG run) to catch corridors where 7 of 10 adjacent segments jam in a connected "
              "spine — operationally systemic even if the full 80% never fires simultaneously.</div>")

WHY_STAGE6 = ('<div class="why"><b>Why recurrence typing matters</b> — '
              "A verdict of ACTIVE_BOTTLENECK only says \"the three-point test fires\"; it says nothing "
              "about <i>how often</i>. Operators prioritise by recurrence: a RECURRING bottleneck (≥75% of "
              "weekdays) is a standing issue; an OCCASIONAL one may be event-driven and not worth retuning "
              "for. Stage 6 counts per-day onsets directly — no heuristics.</div>")

WHY_R7 = ('<div class="why"><b>Why four separate signals instead of one score</b> — '
          "A single opaque \"confidence number\" tells an operator nothing. The four components tell them "
          "exactly <i>why</i> they should trust (or not trust) a verdict. Each signal is a standard QA "
          "metric that breaks out separately — operators know which failure mode hit.</div>")

WHY_R8 = ('<div class="why"><b>Why this doesn\'t change verdicts</b> — '
          "If a segment is perpetually saturated, its \"free flow\" is really \"less bad congestion\", "
          "which would make every regime classification wrong. We still compute ff_tt and clamp to 80 km/h "
          "so the pipeline stays coherent, but we raise a warning so the operator knows the regime bar "
          "is on a soft foundation. <i>Never</i> silently rewriting verdicts preserves the audit trail.</div>")

BERTINI_DIAGRAM = """<svg viewBox="0 0 720 220" xmlns="http://www.w3.org/2000/svg" class="diagram">
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L10,5 L0,10 z" fill="#475569"/>
    </marker>
  </defs>
  <rect x="40"  y="80" width="180" height="60" rx="6" fill="#fed7aa" stroke="#f97316" stroke-width="2"/>
  <text x="130" y="100" text-anchor="middle" font-size="13" font-weight="700" fill="#7c2d12">upstream</text>
  <text x="130" y="120" text-anchor="middle" font-size="11" fill="#7c2d12">CONG — queue backing up</text>
  <rect x="270" y="80" width="180" height="60" rx="6" fill="#fecaca" stroke="#dc2626" stroke-width="2"/>
  <text x="360" y="100" text-anchor="middle" font-size="13" font-weight="700" fill="#7f1d1d">mid = choke</text>
  <text x="360" y="120" text-anchor="middle" font-size="11" fill="#7f1d1d">CONG — the active bottleneck</text>
  <rect x="500" y="80" width="180" height="60" rx="6" fill="#bbf7d0" stroke="#16a34a" stroke-width="2"/>
  <text x="590" y="100" text-anchor="middle" font-size="13" font-weight="700" fill="#14532d">downstream</text>
  <text x="590" y="120" text-anchor="middle" font-size="11" fill="#14532d">FREE — traffic discharging</text>
  <line x1="220" y1="110" x2="270" y2="110" stroke="#475569" stroke-width="2" marker-end="url(#arr)"/>
  <line x1="450" y1="110" x2="500" y2="110" stroke="#475569" stroke-width="2" marker-end="url(#arr)"/>
  <text x="360" y="50"  text-anchor="middle" font-size="14" font-weight="700" fill="#0f172a">The Bertini &amp; Leal (2005) three-point test</text>
  <text x="360" y="70"  text-anchor="middle" font-size="12" fill="#475569">mid is CONG + up is CONG (queue) + dn is FREE (discharge) → active bottleneck</text>
  <text x="360" y="175" text-anchor="middle" font-size="11" fill="#64748b">Sustained for ≥ 10 min (5 consecutive 2-min buckets) → fires.</text>
</svg>"""

LEGEND = ('<div class="legend">'
          '<span><span class="sw" style="background:var(--free)"></span>FREE (≥ 0.80)</span>'
          '<span><span class="sw" style="background:var(--appr)"></span>APPROACHING (0.50 – 0.80)</span>'
          '<span><span class="sw" style="background:var(--cong)"></span>CONGESTED (0.30 – 0.50)</span>'
          '<span><span class="sw" style="background:var(--sevr)"></span>SEVERE (&lt; 0.30)</span>'
          '</div>')

STRIP_SCRIPT = """<script>
const COLOR = { "F":"var(--free)", "A":"var(--appr)", "C":"var(--cong)", "S":"var(--sevr)", ".":"#e2e8f0" };
const LABEL = { "F":"FREE", "A":"APPR", "C":"CONG", "S":"SEVR", ".":"n/a" };
const N = 720;
function minToClock(b) { const m = b*2; return String(Math.floor(m/60)).padStart(2,'0') + ':' + String(m%60).padStart(2,'0'); }
function renderStrips() {
  const root = document.getElementById("heatstrips");
  for (const seg of DATA.segments) {
    const row = document.createElement("div"); row.className = "strip-row";
    const lbl = document.createElement("div"); lbl.className = "seg-label"; lbl.textContent = seg.label; row.appendChild(lbl);
    const strip = document.createElement("div"); strip.className = "strip";
    let fF=0,fA=0,fC=0,fS=0;
    for (let i=0;i<N;i++) {
      const c = seg.regime[i];
      const cell = document.createElement("div"); cell.className = "cell";
      cell.style.background = COLOR[c] || "#e2e8f0";
      cell.dataset.i = i; cell.dataset.seg = seg.label;
      strip.appendChild(cell);
      if (c==="F") fF++; else if (c==="A") fA++; else if (c==="C") fC++; else if (c==="S") fS++;
    }
    row.appendChild(strip);
    const stats = document.createElement("div"); stats.className = "seg-stats";
    stats.innerHTML = `<b>${((fC+fS)/N*100).toFixed(0)}%</b> red`;
    row.appendChild(stats);
    root.appendChild(row);
  }
  const tip = document.getElementById("tip"); const tipHead = tip.querySelector(".tip-head"); const tipBody = tip.querySelector(".tip-body");
  document.getElementById("heatstrips").addEventListener("mousemove", (e) => {
    const t = e.target;
    if (!t.classList.contains("cell")) { tip.style.display = "none"; return; }
    const i = parseInt(t.dataset.i, 10);
    const seg = DATA.segments.find(s => s.label === t.dataset.seg);
    const tt = seg.tt[i]; const reg = seg.regime[i];
    const r = tt ? (seg.ff_tt / tt) : null;
    tipHead.textContent = seg.label + "   " + minToClock(i);
    tipBody.innerHTML = tt ? `tt = <b>${tt} s</b>   ·   ratio ${r.toFixed(2)}   ·   <b>${LABEL[reg]}</b>` : `<i>no data</i>`;
    tip.style.display = "block"; tip.style.left = (e.clientX+14)+"px"; tip.style.top = (e.clientY+14)+"px";
  });
  document.getElementById("heatstrips").addEventListener("mouseleave", () => document.getElementById("tip").style.display = "none");
}
renderStrips();
</script>"""

# ---- orchestrator ----
def render_one(cid: str, cor_meta: dict, structured_one: dict, profiles: dict) -> str:
    chain = cor_meta["chain"]
    city  = cor_meta.get("city", "")
    name  = cor_meta.get("name", cid)
    total_len = sum(c["length_m"] for c in chain)

    freeflow = structured_one["freeflow"]
    baseline_flags = structured_one["baseline_flags"]
    primary_windows = structured_one["primary_windows_v21"]
    bertini = structured_one["bertini"]
    head = structured_one["head_bottleneck"]
    shockwave = structured_one["shockwave"]
    systemic_v2  = structured_one["systemic_v2"]
    systemic_v21 = structured_one["systemic_v21"]
    recurrence = structured_one.get("recurrence", {}) or {}
    confidence = structured_one["confidence"]
    verdicts   = structured_one["verdicts"]

    # Build regime strings for JS heatstrips
    segs_data = []
    regimes_by_idx = []
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        ff_tt = freeflow[rid]["ff_tt"]
        reg_str, tts = regimes_for_seg(profiles[rid], ff_tt)
        regimes_by_idx.append([
            "FREE" if c=="F" else "APPROACHING" if c=="A" else "CONGESTED" if c=="C" else "SEVERE" if c=="S" else "FREE"
            for c in reg_str
        ])
        segs_data.append({
            "label": f"S{i+1:02d}",
            "name": seg["road_name"],
            "ff_tt": freeflow[rid]["ff_tt"],
            "ff_spd": freeflow[rid]["ff_speed_kmph"],
            "regime": reg_str,
            "tt": tts,
        })

    # Stage 4 / shockwave
    sw_pairs = shockwave.get("pairs", [])
    sw_rate  = shockwave.get("pass_rate")
    sw_mode  = shockwave.get("mode", "?")
    sw_table_html, passes, total_pairs = render_shockwave_table(sw_pairs)

    # Hero
    is_sys = (systemic_v2.get("max_fraction", 0) >= v2.SYSTEMIC_ALL_FRACTION) \
             or bool(systemic_v21.get("systemic_by_contig"))
    final_verdict = "SYSTEMIC" if is_sys else "POINT BOTTLENECK"
    active_segs = [f"S{i+1:02d}" for i, s in enumerate(chain)
                   if verdicts.get(s["road_id"]) == "ACTIVE_BOTTLENECK"]
    head_segs   = [f"S{i+1:02d}" for i, s in enumerate(chain)
                   if verdicts.get(s["road_id"]) == "HEAD_BOTTLENECK"]
    active_meta = ", ".join(active_segs) if active_segs else "—"
    head_meta   = ", ".join(head_segs) if head_segs else "—"
    sw_meta_txt = f"{sw_rate*100:.0f}% ({passes} of {total_pairs} pairs)" if sw_rate is not None else "—"

    # KPI cards (compute verdict composition)
    v_lengths = {"FREE_FLOW": 0, "SLOW_LINK": 0, "QUEUE_VICTIM": 0,
                 "ACTIVE_BOTTLENECK": 0, "HEAD_BOTTLENECK": 0}
    for s in chain:
        v_lengths[verdicts.get(s["road_id"], "FREE_FLOW")] += s["length_m"]
    bot_len = v_lengths["ACTIVE_BOTTLENECK"] + v_lengths["HEAD_BOTTLENECK"] + v_lengths["QUEUE_VICTIM"]
    free_len = v_lengths["FREE_FLOW"]

    kpis = (
        '<div class="kpis">'
        f'<div class="kpi"><div class="k">Total length</div><div class="v">{total_len} m</div><div class="s">{len(chain)} segments</div></div>'
        f'<div class="kpi"><div class="k">Free-flow length</div><div class="v">{free_len} m</div><div class="s">{free_len/total_len*100:.1f}% of corridor</div></div>'
        f'<div class="kpi"><div class="k">Bottleneck/victim length</div><div class="v">{bot_len} m</div><div class="s">{bot_len/total_len*100:.1f}% of corridor</div></div>'
        f'<div class="kpi"><div class="k">Verdict</div><div class="v">{"SYS" if is_sys else "POINT"}</div><div class="s">{"systemic" if is_sys else "not systemic"}</div></div>'
        '</div>'
    )

    # Assemble
    out = []
    out.append('<!DOCTYPE html>')
    out.append(f'<html lang="en"><head><meta charset="utf-8"/><title>{esc(cid)} — Corridor Diagnostics v2.1 — Dry Run</title>'
               '<meta name="viewport" content="width=device-width,initial-scale=1"/>')
    out.append(CSS)
    out.append('</head><body>')
    out.append('<div class="wrap">')
    out.append('<nav class="toc"><h2>On this page</h2>'
               f'<a href="#top">{esc(cid)} at a glance</a>'
               '<a href="#s1">Stage 1 · Free flow</a>'
               '<a href="#s2">Stage 2 · Regimes</a>'
               '<a href="#s2b">Stage 2b · Primary window</a>'
               '<a href="#s3">Stage 3 · Bertini</a>'
               '<a href="#s3r3">Stage 3 R3 · Head bottleneck</a>'
               '<a href="#s4">Stage 4 · Shockwave</a>'
               '<a href="#s5">Stage 5 · Systemic vs Point</a>'
               '<a href="#s6">Stage 6 · Recurrence</a>'
               '<a href="#r7">R7 · Confidence</a>'
               '<a href="#r8">R8 · Baseline sanity</a>'
               '<a href="#final">Final verdicts</a>'
               '</nav>')
    out.append('<main>')
    out.append('<a id="top"></a>')
    out.append('<header class="hero">')
    out.append(f'<h1>{esc(cid)} — Corridor Diagnostics v2.1, dry run</h1>')
    out.append(f'<div class="sub">{esc(name)} · {esc(city)} · {len(chain)} segments · {total_len} m</div>')
    out.append('<div class="meta">')
    out.append(f'<div><span>Final verdict</span><b>{final_verdict}</b></div>')
    out.append(f'<div><span>Active bottleneck</span>{active_meta}</div>')
    out.append(f'<div><span>Head bottleneck</span>{head_meta}</div>')
    out.append(f'<div><span>Shockwave pass rate</span>{sw_meta_txt}</div>')
    out.append(f'<div><span>Stage 4 mode</span>{esc(sw_mode)}</div>')
    out.append('</div></header>')

    # Section 0 · glance
    out.append('<section><h2>0 · Corridor at a glance</h2>'
               '<div class="stage-sub">Each box below is one monitored segment. Width ∝ physical length; '
               'colour shows the final verdict. Labels show free-flow speed and free-flow travel time.</div>')
    out.append(render_corridor_svg(chain, verdicts, freeflow))
    out.append(kpis)
    out.append(render_one_paragraph_story(name, total_len, verdicts, chain, systemic_v2, systemic_v21, sw_rate, primary_windows))
    out.append('</section>')

    # Stage 1
    out.append('<a id="s1"></a><section><h2>Stage 1 · Free-flow discovery</h2>'
               '<div class="stage-sub">For every segment, slide a 30-min window across weekdays of 2-min data, '
               'pick the 3 quietest windows, pool their raw travel times, take p15.</div>')
    out.append(WHY_STAGE1)
    out.append(render_stage1_table(chain, freeflow))
    out.append('</section>')

    # Stage 2
    out.append('<a id="s2"></a><section><h2>Stage 2 · Regime classification</h2>'
               '<div class="stage-sub">For every 2-min bucket compute <code>speed_ratio = ff_tt / current_tt</code>. '
               'Bucket into 4 regimes grounded in the fundamental diagram of traffic flow.</div>')
    out.append(WHY_STAGE2)
    out.append(LEGEND)
    out.append('<div class="ticks"><div></div><div class="axis">'
               '<span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span>'
               '<span>16:00</span><span>20:00</span><span>23:58</span>'
               '</div><div></div></div>')
    out.append('<div id="heatstrips"></div>')
    out.append('<details><summary>Hover any cell for the exact time / tt / regime</summary>'
               'Tooltip shows clock time, travel-time in seconds, and regime label.</details>')
    out.append('</section>')

    # Stage 2b
    out.append('<a id="s2b"></a><section><h2>Stage 2b · Primary congestion window (length-weighted, R1)</h2>'
               '<div class="stage-sub">Find intervals where ≥ 25% of <b>corridor length</b> is simultaneously '
               'CONG/SEVR for ≥ 30 min. Merge gaps &lt; 30 min.</div>')
    out.append(WHY_STAGE2B)
    out.append(render_primary_window_block(primary_windows, regimes_by_idx, chain))
    out.append('</section>')

    # Stage 3
    out.append('<a id="s3"></a><section><h2>Stage 3 · Bertini active-bottleneck test (core)</h2>'
               '<div class="stage-sub">The three-point test: look at each segment with its upstream and '
               'downstream neighbour. A real bottleneck has a queue upstream AND free discharge downstream.</div>')
    out.append(BERTINI_DIAGRAM)
    out.append(WHY_STAGE3)
    out.append(render_bertini_table(chain, bertini))
    out.append('</section>')

    # Stage 3 R3
    out.append('<a id="s3r3"></a><section><h2>Stage 3 R3 · Head-segment bottleneck (v2.1 addition)</h2>'
               '<div class="stage-sub">The classical Bertini test needs an upstream segment, so S01 can never '
               'fire. R3 is a two-point relaxation for S01 specifically.</div>')
    out.append(WHY_STAGE3R3)
    out.append(render_head_block(chain, head))
    out.append(render_handoff_story(chain, bertini, head))
    out.append('</section>')

    # Stage 4
    out.append('<a id="s4"></a><section><h2>Stage 4 · Shockwave cross-check (LWR)</h2>'
               f'<div class="stage-sub">Mode: <code>{esc(sw_mode)}</code>. For each adjacent pair, check whether '
               'the observed congestion onset lag matches the LWR prediction (backward propagation at 12–22 km/h).</div>')
    out.append(WHY_STAGE4)
    out.append(sw_table_html)
    out.append(render_shockwave_narrative(passes, total_pairs, sw_pairs, verdicts, chain))
    out.append('</section>')

    # Stage 5
    out.append('<a id="s5"></a><section><h2>Stage 5 · Systemic vs Point classification</h2>'
               '<div class="stage-sub">Two independent rules: v2\'s simultaneity (≥80%) and v2.1\'s '
               'contiguity (≥60% of length). Either triggers SYSTEMIC.</div>')
    out.append(WHY_STAGE5)
    out.append(
        '<table><thead><tr><th>Rule</th><th>Peak value</th><th>Threshold</th><th>Trigger?</th></tr></thead><tbody>'
        f'<tr><td>v2 · simultaneous CONG/SEVR</td><td>{systemic_v2.get("max_fraction", 0)*100:.0f}%</td>'
        f'<td>80%</td><td>{"✅ YES" if systemic_v2.get("max_fraction", 0) >= v2.SYSTEMIC_ALL_FRACTION else "❌ no"}</td></tr>'
        f'<tr><td>v2.1 R5 · contiguous length</td><td>{systemic_v21.get("max_contig_frac", 0)*100:.0f}%</td>'
        f'<td>60%</td><td>{"✅ YES" if systemic_v21.get("systemic_by_contig") else "❌ no"}</td></tr>'
        '</tbody></table>'
        f'<div class="callout"><b>Verdict: {"SYSTEMIC" if is_sys else "POINT"}</b></div>'
    )
    out.append('</section>')

    # Stage 6
    out.append('<a id="s6"></a><section><h2>Stage 6 · Recurrence typing</h2>'
               '<div class="stage-sub">How often does each segment show a congestion onset on an analysed weekday?</div>')
    out.append(WHY_STAGE6)
    out.append(render_recurrence_block(chain, recurrence, verdicts))
    out.append('</section>')

    # R7
    out.append('<a id="r7"></a><section><h2>R7 · Per-segment confidence (v2.1 addition)</h2>'
               '<div class="stage-sub">Four independent 0–1 signals, each weighted 0.25. Sum → confidence score. '
               'Label: HIGH ≥ 0.75, MEDIUM ≥ 0.50, LOW &lt; 0.50.</div>')
    out.append(WHY_R7)
    out.append(render_confidence_table(chain, confidence, verdicts))
    out.append('</section>')

    # R8
    out.append('<a id="r8"></a><section><h2>R8 · Baseline-saturated sanity check (informational only)</h2>'
               '<div class="stage-sub">Flag any segment whose discovered free flow is &gt; 2× slower than the '
               'corridor median AND whose quietest window is still &gt; 70% of the busiest window.</div>')
    out.append(WHY_R8)
    out.append(render_r8_table(chain, baseline_flags))
    out.append('</section>')

    # Final
    out.append('<a id="final"></a><section><h2>Final per-segment verdicts</h2>')
    out.append(render_final_verdicts(chain, verdicts, confidence))
    out.append('</section>')

    out.append(f'<footer style="font-size:12px; color:var(--muted); text-align:center; margin:30px 0 0;">'
               f'Generated from <code>data/v2_1/profiles/all_profiles.json</code> + '
               f'<code>runs/v2_1/v2_1_validation_structured.json</code>.<br/>'
               f'Corridor: {esc(cid)} · 2-min median profiles · v2.1 pipeline output, unmodified.'
               f'</footer>')
    out.append('</main></div>')
    out.append('<div id="tip"><div class="tip-head"></div><div class="tip-body"></div></div>')
    out.append(f'<script>const DATA = {{"segments": {json.dumps(segs_data)}}};</script>')
    out.append(STRIP_SCRIPT)
    out.append('</body></html>')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", default="weekday", choices=["weekday", "weekend"])
    ap.add_argument("--legacy-names", action="store_true",
                    help="for slice=weekday, write un-suffixed output filenames")
    args = ap.parse_args()

    structured_path, profiles_path = resolve_slice_paths(args.slice)
    structured = json.load(open(structured_path))
    corridors  = json.load(open(CORRIDORS_PATH))
    profiles_raw = json.load(open(profiles_path))
    profiles   = {rid: {int(k): v for k, v in prof.items()} for rid, prof in profiles_raw.items()}

    print(f"slice={args.slice}")
    print(f"  structured: {structured_path}")
    print(f"  profiles:   {profiles_path}")

    os.makedirs(OUT_DIR, exist_ok=True)
    wrote = []
    for cid in structured:
        if cid not in corridors:
            print(f"skip {cid}: no chain in validation_corridors.json")
            continue
        html_out = render_one(cid, corridors[cid], structured[cid], profiles)
        if args.legacy_names and args.slice == "weekday":
            filename = f"{cid}_dry_run.html"
        else:
            filename = f"{cid}_{args.slice}_dry_run.html"
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w") as f:
            f.write(html_out)
        wrote.append(path)

    print(f"Wrote {len(wrote)} dry-run HTML(s):")
    for p in wrote:
        print(f"  {p}")


if __name__ == "__main__":
    main()
