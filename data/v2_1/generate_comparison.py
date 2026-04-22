#!/usr/bin/env python3
"""
Weekday vs weekend comparison HTMLs — one per corridor.

Reads:
  runs/v2_1/v2_1_validation_structured.json          (weekday)
  runs/v2_1/v2_1_validation_weekend_structured.json  (weekend)
  data/v2_1/validation_corridors.json                (chains + names)

Writes:
  docs/dry_runs/{cid}_compare.html

Pure local. No DB, no profile/onset reads. The per-slice dry-run HTMLs
already cover heatstrips / Stage 1 / etc; this view is a focused delta.

Per-corridor HTML surfaces:
  - hero: final verdict per slice + DIFFERS/IDENTICAL badge
  - corridor-at-a-glance: stacked weekday / weekend bars, Δ markers where
    per-segment verdict differs
  - per-segment verdict diff table (priority signal)
  - Stage 2b primary windows — two columns
  - Stage 3 Bertini + R3 head — two columns
  - Stage 4 shockwave pass rate — row
  - Stage 5 systemic rule comparison
  - Stage 6 recurrence band per bottleneck segment — side by side
"""
from __future__ import annotations
import argparse, json, os, sys

HERE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
DATA_DIR     = os.path.abspath(os.path.join(PROJECT_ROOT, "data"))
OUT_DIR      = os.path.join(PROJECT_ROOT, "docs", "dry_runs")

sys.path.insert(0, DATA_DIR)
sys.path.insert(0, HERE)
import corridor_diagnostics_v2 as v2  # noqa: E402
from generate_dry_runs import (  # noqa: E402
    CSS, VERDICT_BADGE_CLASS, VERDICT_SVG_FILL,
    esc, clock, bucket_range, duration_min,
)

WD_PATH  = os.path.join(PROJECT_ROOT, "runs", "v2_1", "v2_1_validation_structured.json")
WE_PATH  = os.path.join(PROJECT_ROOT, "runs", "v2_1", "v2_1_validation_weekend_structured.json")
COR_PATH = os.path.join(HERE, "validation_corridors.json")

BAND_ORDER = {"NEVER": 0, "RARE": 1, "OCCASIONAL": 2, "FREQUENT": 3, "RECURRING": 4}


def is_systemic(d: dict) -> bool:
    sv2  = (d.get("systemic_v2") or {}).get("max_fraction", 0) or 0
    sv21 = (d.get("systemic_v21") or {}).get("systemic_by_contig", False)
    return sv2 >= v2.SYSTEMIC_ALL_FRACTION or bool(sv21)


def verdict_of(d: dict) -> str:
    return "SYSTEMIC" if is_systemic(d) else "POINT"


def render_stacked_svg(chain: list, wd_verdicts: dict, we_verdicts: dict, total_len: int) -> str:
    W = 1000.0
    x0, x1 = 40.0, 960.0
    track = x1 - x0
    H = 240
    parts = [f'<svg class="corridor" viewBox="0 0 {int(W)} {H}" xmlns="http://www.w3.org/2000/svg">']
    # Row labels
    parts.append(f'<text x="{x0}" y="40" font-size="13" font-weight="700" fill="#1e293b">Weekday</text>')
    parts.append(f'<text x="{x0}" y="160" font-size="13" font-weight="700" fill="#1e293b">Weekend</text>')
    # Upstream / downstream anchors
    parts.append(f'<text x="{x0}" y="18" font-size="11" fill="#64748b">⬅ upstream</text>')
    parts.append(f'<text x="{x1}" y="18" text-anchor="end" font-size="11" fill="#64748b">downstream ➡</text>')

    def draw_row(y_rect: int, y_label: int, verdicts: dict, delta_row: bool):
        xc = x0
        for i, seg in enumerate(chain):
            w = track * seg["length_m"] / total_len
            v = verdicts.get(seg["road_id"], "FREE_FLOW")
            fill, op = VERDICT_SVG_FILL.get(v, ("#3b82f6", 0.22))
            parts.append(f'<rect x="{xc:.2f}" y="{y_rect}" width="{w:.2f}" height="30" rx="4" '
                         f'fill="{fill}" fill-opacity="{op}" stroke="{fill}" stroke-width="1.5"/>')
            parts.append(f'<text x="{xc + w/2:.2f}" y="{y_label}" text-anchor="middle" '
                         f'font-size="12" font-weight="700" fill="#0f172a">S{i+1:02d}</text>')
            if delta_row and wd_verdicts.get(seg["road_id"]) != we_verdicts.get(seg["road_id"]):
                parts.append(
                    f'<text x="{xc + w/2:.2f}" y="120" text-anchor="middle" '
                    f'font-size="18" font-weight="800" fill="#dc2626">Δ</text>'
                )
            xc += w

    # Weekday row (top), Weekend row (bottom). Δ markers anchored between them.
    draw_row(y_rect=50,  y_label=71,  verdicts=wd_verdicts, delta_row=False)
    draw_row(y_rect=170, y_label=191, verdicts=we_verdicts, delta_row=True)
    parts.append(f'<text x="{(x0+x1)/2:.0f}" y="218" text-anchor="middle" font-size="11" '
                 f'fill="#64748b" font-style="italic">segments drawn to scale; '
                 f'Δ markers flag segments whose verdict moves between slices</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def verdict_cell(v: str | None) -> str:
    if not v:
        return "<span class='verdict verdict-free_flow'>—</span>"
    return f"<span class='verdict {VERDICT_BADGE_CLASS.get(v, 'verdict-free_flow')}'>{v}</span>"


def render_verdict_diff_table(chain: list, wd: dict, we: dict) -> str:
    rows = []
    wd_verdicts = wd.get("verdicts") or {}
    we_verdicts = we.get("verdicts") or {}
    wd_conf = wd.get("confidence") or {}
    we_conf = we.get("confidence") or {}
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        wv = wd_verdicts.get(rid, "FREE_FLOW")
        ev = we_verdicts.get(rid, "FREE_FLOW")
        wc = wd_conf.get(rid, {}) or {}
        ec = we_conf.get(rid, {}) or {}
        same = wv == ev
        marker = "" if same else "<b style='color:#dc2626'>Δ</b>"
        row_style = "" if same else ' style="background:#fff1f2"'
        rows.append(
            f"<tr{row_style}>"
            f"<td><b>S{i+1:02d}</b></td>"
            f"<td style='max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;' "
            f"title=\"{esc(seg['road_name'])}\">{esc(seg['road_name'])}</td>"
            f"<td>{verdict_cell(wv)}</td>"
            f"<td>{wc.get('label', '—')} ({wc.get('score', 0):.2f})</td>"
            f"<td>{verdict_cell(ev)}</td>"
            f"<td>{ec.get('label', '—')} ({ec.get('score', 0):.2f})</td>"
            f"<td style='text-align:center;'>{marker}</td>"
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Seg</th><th>Road</th>"
        "<th>Weekday verdict</th><th>WD conf</th>"
        "<th>Weekend verdict</th><th>WE conf</th>"
        "<th>Δ</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_windows_cell(windows: list) -> str:
    if not windows:
        return "<i style='color:#64748b'>none</i>"
    items = [f"<li><code>{bucket_range(a, b)}</code> "
             f"<span style='color:#64748b'>({duration_min(a,b)} min)</span></li>"
             for a, b in windows]
    return "<ul style='margin:4px 0;padding-left:18px;'>" + "".join(items) + "</ul>"


def render_bertini_cell(chain: list, d: dict) -> str:
    verdicts = d.get("verdicts") or {}
    bertini = d.get("bertini") or {}
    head = d.get("head_bottleneck") or []
    lines = []
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        runs = bertini.get(rid, [])
        if not runs:
            continue
        iv = ", ".join(f"<code>{bucket_range(a,b)}</code>" for a, b in runs)
        lines.append(f"<li><b>S{i+1:02d}</b> ACTIVE — {iv}</li>")
    if head:
        iv = ", ".join(f"<code>{bucket_range(a,b)}</code>" for a, b in head)
        lines.append(f"<li><b>S01</b> HEAD — {iv}</li>")
    if not lines:
        return "<i style='color:#64748b'>no Stage 3 activations</i>"
    return "<ul style='margin:4px 0;padding-left:18px;'>" + "".join(lines) + "</ul>"


def render_systemic_table(wd: dict, we: dict) -> str:
    wd_sim  = (wd.get("systemic_v2") or {}).get("max_fraction", 0) or 0
    we_sim  = (we.get("systemic_v2") or {}).get("max_fraction", 0) or 0
    wd_con  = (wd.get("systemic_v21") or {}).get("max_contig_frac", 0) or 0
    we_con  = (we.get("systemic_v21") or {}).get("max_contig_frac", 0) or 0
    def row(rule, wv, ev, thresh, trigger_wd, trigger_we):
        return (
            f"<tr><td>{rule}</td>"
            f"<td>{wv*100:.0f}%</td>"
            f"<td>{ev*100:.0f}%</td>"
            f"<td>{thresh}</td>"
            f"<td>{'✅' if trigger_wd else '❌'}</td>"
            f"<td>{'✅' if trigger_we else '❌'}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Rule</th><th>WD peak</th><th>WE peak</th>"
        "<th>Threshold</th><th>WD fire?</th><th>WE fire?</th></tr></thead><tbody>"
        + row("v2 simultaneous CONG/SEVR", wd_sim, we_sim, "80%",
              wd_sim >= v2.SYSTEMIC_ALL_FRACTION, we_sim >= v2.SYSTEMIC_ALL_FRACTION)
        + row("v2.1 R5 contiguous length", wd_con, we_con, "60%",
              (wd.get("systemic_v21") or {}).get("systemic_by_contig", False),
              (we.get("systemic_v21") or {}).get("systemic_by_contig", False))
        + "</tbody></table>"
    )


def render_shockwave_row(wd: dict, we: dict) -> str:
    wd_pr = (wd.get("shockwave") or {}).get("pass_rate")
    we_pr = (we.get("shockwave") or {}).get("pass_rate")
    wd_mode = (wd.get("shockwave") or {}).get("mode", "?")
    we_mode = (we.get("shockwave") or {}).get("mode", "?")
    wd_txt = f"{wd_pr*100:.0f}%" if wd_pr is not None else "—"
    we_txt = f"{we_pr*100:.0f}%" if we_pr is not None else "—"
    return (
        "<table><thead><tr><th></th><th>Weekday</th><th>Weekend</th></tr></thead><tbody>"
        f"<tr><td>Pass rate</td><td>{wd_txt}</td><td>{we_txt}</td></tr>"
        f"<tr><td>Stage 4 mode</td><td><code>{esc(wd_mode)}</code></td>"
        f"<td><code>{esc(we_mode)}</code></td></tr>"
        "</tbody></table>"
    )


def render_recurrence_diff(chain: list, wd: dict, we: dict) -> str:
    wd_rec = wd.get("recurrence") or {}
    we_rec = we.get("recurrence") or {}
    wd_verdicts = wd.get("verdicts") or {}
    we_verdicts = we.get("verdicts") or {}
    rows = []
    for i, seg in enumerate(chain):
        rid = seg["road_id"]
        wv = wd_verdicts.get(rid, "FREE_FLOW")
        ev = we_verdicts.get(rid, "FREE_FLOW")
        if wv not in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK") \
           and ev not in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK"):
            continue
        wr = wd_rec.get(rid, {}) or {}
        er = we_rec.get(rid, {}) or {}
        wb = wr.get("label", "—")
        eb = er.get("label", "—")
        shift = ""
        if wb != eb and wb != "—" and eb != "—":
            delta = BAND_ORDER.get(eb, 0) - BAND_ORDER.get(wb, 0)
            if delta > 0:
                shift = f"<b style='color:#16a34a'>↑{delta} band(s)</b>"
            elif delta < 0:
                shift = f"<b style='color:#dc2626'>↓{-delta} band(s)</b>"
        rows.append(
            f"<tr>"
            f"<td><b>S{i+1:02d}</b></td>"
            f"<td>{verdict_cell(wv)}</td>"
            f"<td>{wb} ({wr.get('n_days', 0)}/{wr.get('total_days', 0)})</td>"
            f"<td>{verdict_cell(ev)}</td>"
            f"<td>{eb} ({er.get('n_days', 0)}/{er.get('total_days', 0)})</td>"
            f"<td>{shift}</td>"
            f"</tr>"
        )
    if not rows:
        return "<i style='color:#64748b'>no bottlenecks in either slice</i>"
    return (
        "<table><thead><tr>"
        "<th>Seg</th><th>WD verdict</th><th>WD band</th>"
        "<th>WE verdict</th><th>WE band</th><th>Shift</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_summary_paragraph(
    cid: str, name: str, chain: list, wd: dict, we: dict, total_len: int
) -> str:
    wd_v = verdict_of(wd)
    we_v = verdict_of(we)
    wd_bots = sum(1 for s in chain if (wd.get("verdicts") or {}).get(s["road_id"])
                  in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK"))
    we_bots = sum(1 for s in chain if (we.get("verdicts") or {}).get(s["road_id"])
                  in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK"))
    changed_segs = [f"S{i+1:02d}" for i, s in enumerate(chain)
                    if (wd.get("verdicts") or {}).get(s["road_id"]) !=
                       (we.get("verdicts") or {}).get(s["road_id"])]
    identical = wd_v == we_v and not changed_segs
    header = ("✅ <b>Verdicts identical across slices.</b> "
              "Same final verdict, same per-segment verdicts.") if identical else (
              "⚠️ <b>Verdicts differ between slices.</b>")
    body_bits = []
    if wd_v != we_v:
        body_bits.append(f"Corridor-level verdict shifted: <b>{wd_v}</b> on weekdays → "
                         f"<b>{we_v}</b> on weekends.")
    if wd_bots != we_bots:
        body_bits.append(f"Bottleneck count changed from {wd_bots} (weekday) to "
                         f"{we_bots} (weekend).")
    if changed_segs:
        body_bits.append(f"Segments with a different verdict: "
                         f"<b>{', '.join(changed_segs)}</b>.")
    return (f'<div class="story">{header} '
            + " ".join(body_bits) + '</div>')


def render_one(cid: str, cor_meta: dict, wd: dict, we: dict) -> str:
    chain = cor_meta["chain"]
    name  = cor_meta.get("name", cid)
    city  = cor_meta.get("city", "")
    total_len = sum(c["length_m"] for c in chain)

    wd_verdicts = wd.get("verdicts") or {}
    we_verdicts = we.get("verdicts") or {}
    wd_v = verdict_of(wd)
    we_v = verdict_of(we)
    differs = any(
        wd_verdicts.get(s["road_id"]) != we_verdicts.get(s["road_id"]) for s in chain
    ) or wd_v != we_v
    status_badge = "DIFFERS" if differs else "IDENTICAL"
    status_color = "#dc2626" if differs else "#16a34a"

    out = []
    out.append('<!DOCTYPE html>')
    out.append(f'<html lang="en"><head><meta charset="utf-8"/>'
               f'<title>{esc(cid)} — weekday vs weekend compare</title>'
               '<meta name="viewport" content="width=device-width,initial-scale=1"/>')
    out.append(CSS)
    out.append('</head><body>')
    out.append('<div class="wrap">')

    # Simple TOC — no sticky nav; single-column layout
    out.append('<nav class="toc"><h2>On this page</h2>'
               '<a href="#top">Overview</a>'
               '<a href="#seg">Per-segment verdict diff</a>'
               '<a href="#s2b">Stage 2b windows</a>'
               '<a href="#s3">Stage 3 activations</a>'
               '<a href="#s4">Stage 4 shockwave</a>'
               '<a href="#s5">Stage 5 systemic rules</a>'
               '<a href="#s6">Stage 6 recurrence</a>'
               '<a href="#links">Full per-slice HTMLs</a>'
               '</nav>')

    out.append('<main>')
    out.append('<a id="top"></a>')
    out.append('<header class="hero">')
    out.append(f'<h1>{esc(cid)} — weekday vs weekend</h1>')
    out.append(f'<div class="sub">{esc(name)} · {esc(city)} · {len(chain)} segments · {total_len} m</div>')
    out.append('<div class="meta">')
    out.append(f'<div><span>Weekday verdict</span><b>{wd_v}</b></div>')
    out.append(f'<div><span>Weekend verdict</span><b>{we_v}</b></div>')
    out.append(f'<div><span>Status</span><b style="background:{status_color};padding:2px 10px;'
               f'border-radius:99px;font-size:11px;">{status_badge}</b></div>')
    out.append('</div></header>')

    # Glance section with stacked SVG
    out.append('<section><h2>Overview</h2>'
               '<div class="stage-sub">Segments colored by final verdict. '
               'Weekday row on top, weekend below. Δ marker sits between rows where a segment\'s '
               'verdict moves between slices.</div>')
    out.append(render_stacked_svg(chain, wd_verdicts, we_verdicts, total_len))
    out.append(render_summary_paragraph(cid, name, chain, wd, we, total_len))
    out.append('</section>')

    # Per-segment verdict diff table
    out.append('<a id="seg"></a><section><h2>Per-segment verdict diff</h2>'
               '<div class="stage-sub">Rows highlighted in red indicate segments whose verdict '
               'moved between slices. Confidence label + score shown for both slices.</div>')
    out.append(render_verdict_diff_table(chain, wd, we))
    out.append('</section>')

    # Stage 2b
    out.append('<a id="s2b"></a><section><h2>Stage 2b · Primary windows</h2>'
               '<div class="stage-sub">Length-weighted R1 rule: ≥25% of corridor length '
               'simultaneously CONG/SEVR for ≥30 min. Listed per slice.</div>')
    wd_pw = wd.get("primary_windows_v21") or []
    we_pw = we.get("primary_windows_v21") or []
    out.append('<table><thead><tr><th style="width:50%">Weekday</th><th>Weekend</th></tr></thead>'
               '<tbody><tr>'
               f'<td style="vertical-align:top">{render_windows_cell(wd_pw)}</td>'
               f'<td style="vertical-align:top">{render_windows_cell(we_pw)}</td>'
               '</tr></tbody></table>')
    out.append('</section>')

    # Stage 3
    out.append('<a id="s3"></a><section><h2>Stage 3 · Bertini + R3 head</h2>'
               '<div class="stage-sub">Active bottlenecks that fire the three-point test, '
               'plus any S01 head bottleneck from R3\'s two-point relaxation.</div>')
    out.append('<table><thead><tr><th style="width:50%">Weekday</th><th>Weekend</th></tr></thead>'
               '<tbody><tr>'
               f'<td style="vertical-align:top">{render_bertini_cell(chain, wd)}</td>'
               f'<td style="vertical-align:top">{render_bertini_cell(chain, we)}</td>'
               '</tr></tbody></table>')
    out.append('</section>')

    # Stage 4
    out.append('<a id="s4"></a><section><h2>Stage 4 · Shockwave pass rate</h2>'
               '<div class="stage-sub">LWR backward-propagation check; mode indicates whether '
               'Stage 4 ran with per-day onsets or fallback midpoints.</div>')
    out.append(render_shockwave_row(wd, we))
    out.append('</section>')

    # Stage 5
    out.append('<a id="s5"></a><section><h2>Stage 5 · Systemic vs Point rules</h2>'
               '<div class="stage-sub">Both slices evaluated against the same two thresholds '
               '(v2 simultaneity 80%, v2.1 contiguous-length 60%).</div>')
    out.append(render_systemic_table(wd, we))
    out.append('</section>')

    # Stage 6
    out.append('<a id="s6"></a><section><h2>Stage 6 · Recurrence bands on bottleneck segments</h2>'
               '<div class="stage-sub">For every segment that fires as ACTIVE_BOTTLENECK or '
               'HEAD_BOTTLENECK in either slice, showing its recurrence band on each. '
               'Shift arrows indicate band movement (RARE → OCCASIONAL → FREQUENT → RECURRING).</div>')
    out.append(render_recurrence_diff(chain, wd, we))
    out.append('</section>')

    # Links to per-slice HTMLs
    out.append(f'<a id="links"></a><section><h2>Per-slice full dry-runs</h2>'
               f'<ul>'
               f'<li><a href="{esc(cid)}_dry_run.html">{esc(cid)}_dry_run.html</a> '
               '(weekday, with heatstrips, Stage 1/R7/R8 detail)</li>'
               f'<li><a href="{esc(cid)}_weekend_dry_run.html">{esc(cid)}_weekend_dry_run.html</a> '
               '(weekend, same shape)</li>'
               '</ul></section>')

    out.append(f'<footer style="font-size:12px; color:var(--muted); text-align:center; margin:30px 0 0;">'
               f'Generated from <code>runs/v2_1/v2_1_validation_structured.json</code> + '
               f'<code>runs/v2_1/v2_1_validation_weekend_structured.json</code>. '
               f'Pure local diff — no DB access.</footer>')
    out.append('</main></div></body></html>')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wd", default=WD_PATH, help="path to weekday structured JSON")
    ap.add_argument("--we", default=WE_PATH, help="path to weekend structured JSON")
    args = ap.parse_args()

    wd = json.load(open(args.wd))
    we = json.load(open(args.we))
    corridors = json.load(open(COR_PATH))

    os.makedirs(OUT_DIR, exist_ok=True)
    wrote = []
    for cid in wd:
        if cid not in we:
            print(f"skip {cid}: not in weekend structured")
            continue
        if cid not in corridors:
            print(f"skip {cid}: no chain in validation_corridors.json")
            continue
        html_out = render_one(cid, corridors[cid], wd[cid], we[cid])
        path = os.path.join(OUT_DIR, f"{cid}_compare.html")
        with open(path, "w") as f:
            f.write(html_out)
        wrote.append(path)

    print(f"Wrote {len(wrote)} comparison HTML(s):")
    for p in wrote:
        print(f"  {p}")


if __name__ == "__main__":
    main()
