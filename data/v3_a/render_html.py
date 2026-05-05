"""Render a v3-A Mode B envelope as a self-contained HTML report.

Implements Layout B from brainstorm Q9:
    Header (mode toggle + anchor) → Two-column body:
        Left (centerpiece): compact corridor strip + per-segment regime ribbon (720 buckets)
        Right (sidebar):    Tier-1 panel (growth-rate / percolation / jam-tree / MFD) + verdicts + meta

No external libs. Pure HTML + inline CSS + a tiny SVG for the MFD loop.
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path


# --------------------------------------------------------------------------- #
# Visual primitives                                                           #
# --------------------------------------------------------------------------- #


REGIME_COLOR = {
    "FREE": "#2e7d32",
    "APPROACHING": "#fbc02d",
    "CONGESTED": "#ef6c00",
    "SEVERE": "#c62828",
    None: "#444",
    "": "#444",
}

VERDICT_COLOR = {
    "ACTIVE_BOTTLENECK": "#c62828",
    "HEAD_BOTTLENECK": "#b71c1c",
    "SLOW_LINK": "#ef6c00",
    "QUEUE_VICTIM": "#fbc02d",
    "FREE_FLOW": "#2e7d32",
}

CONFIDENCE_COLOR = {"HIGH": "#2e7d32", "MEDIUM": "#fbc02d", "LOW": "#c62828"}


def bucket_to_hhmm(b):
    if b is None:
        return "—"
    m = b * 2
    return f"{m // 60:02d}:{m % 60:02d}"


# --------------------------------------------------------------------------- #
# Segment ribbon — 720-bucket per-segment heatmap                              #
# --------------------------------------------------------------------------- #


def render_ribbon(regimes_today_by_seg, segment_order, segment_meta_by_seg, anchor_bucket,
                  bertini_today_by_seg, head_today, primary_windows, percolation_onset_b):
    """One row per segment, each row is 720 colored cells (1 px wide each → 720 px wide)."""
    rows = []
    for s in segment_order:
        regimes = regimes_today_by_seg.get(s, [])
        cells = []
        for b in range(min(720, len(regimes))):
            color = REGIME_COLOR.get(regimes[b], "#444")
            after_anchor = b > anchor_bucket
            opacity = 0.3 if after_anchor else 1.0
            cells.append(
                f'<span class="cell" style="background:{color};opacity:{opacity}"></span>'
            )
        # Bertini event flags overlaid on this row
        flags = []
        for t0, t1 in bertini_today_by_seg.get(s, []) or []:
            left_pct = (t0 / 720.0) * 100
            width_pct = max(0.4, ((t1 - t0 + 1) / 720.0) * 100)
            flags.append(
                f'<span class="flag" title="Bertini {bucket_to_hhmm(t0)}–{bucket_to_hhmm(t1)}" '
                f'style="left:{left_pct:.2f}%;width:{width_pct:.2f}%;"></span>'
            )
        meta = segment_meta_by_seg.get(s, {})
        seg_label = escape(meta.get("name", s)[:48])
        rows.append(
            f'''
            <div class="ribbon-row">
              <div class="ribbon-label" title="{escape(s)}">{seg_label}</div>
              <div class="ribbon-track">
                {"".join(cells)}
                {"".join(flags)}
              </div>
            </div>
            '''
        )

    # Primary window strips and percolation marker on a top axis bar
    pw_marks = []
    for s, e in primary_windows or []:
        left = (s / 720.0) * 100
        width = max(0.2, ((e - s + 1) / 720.0) * 100)
        pw_marks.append(
            f'<span class="primary-window" title="primary window {bucket_to_hhmm(s)}–{bucket_to_hhmm(e)}" '
            f'style="left:{left:.2f}%;width:{width:.2f}%;"></span>'
        )
    perc_marker = ""
    if percolation_onset_b is not None:
        left = (percolation_onset_b / 720.0) * 100
        perc_marker = (
            f'<span class="perc-marker" title="percolation onset {bucket_to_hhmm(percolation_onset_b)}" '
            f'style="left:{left:.2f}%;"></span>'
        )
    anchor_marker = ""
    if anchor_bucket is not None:
        left = (anchor_bucket / 720.0) * 100
        anchor_marker = (
            f'<span class="anchor-marker" title="anchor T = {bucket_to_hhmm(anchor_bucket)}" '
            f'style="left:{left:.2f}%;"></span>'
        )

    # Hour ticks every 2 hours
    ticks = []
    for hr in range(0, 25, 2):
        left = (hr * 30 / 720.0) * 100
        ticks.append(f'<span class="tick" style="left:{left:.2f}%">{hr:02d}</span>')

    axis = (
        f'<div class="ribbon-axis"><div class="ribbon-label"></div>'
        f'<div class="ribbon-track">{"".join(ticks)}{"".join(pw_marks)}{perc_marker}{anchor_marker}</div></div>'
    )

    return f'<div class="ribbon">{axis}{"".join(rows)}</div>'


# --------------------------------------------------------------------------- #
# Sidebar widgets                                                              #
# --------------------------------------------------------------------------- #


def render_growth_rate(payload):
    gr = payload["tier1"].get("growth_rate") or {}
    s = gr.get("summary", {})
    rows = []
    for ev in (gr.get("events") or [])[:8]:
        slope = ev.get("slope_m_per_min")
        slope_s = "—" if slope is None else f"{slope:+.1f}"
        label = ev.get("label", "")
        chip_color = {"FAST_GROWTH": "#c62828", "MODERATE": "#fbc02d", "CONTAINED": "#2e7d32",
                      "INSUFFICIENT_DATA": "#666"}.get(label, "#666")
        rows.append(
            f'''<tr>
                <td>{bucket_to_hhmm(ev.get("t0_bucket"))}</td>
                <td><span class="chip" style="background:{chip_color}">{escape(label)}</span></td>
                <td style="text-align:right">{escape(slope_s)}</td>
                <td style="text-align:right">{int(ev.get("cluster_length_m_at_tend") or 0)}m</td>
            </tr>'''
        )
    return f'''
    <div class="card">
      <div class="card-title">Growth-rate <span class="paper-tag">Duan 2023</span></div>
      <div class="kvs">
        <div><b>{s.get("n_events", 0)}</b> events</div>
        <div>fast: <b>{s.get("n_fast", 0)}</b></div>
        <div>moderate: <b>{s.get("n_moderate", 0)}</b></div>
        <div>contained: <b>{s.get("n_contained", 0)}</b></div>
      </div>
      <table class="mini">
        <thead><tr><th>t0</th><th>label</th><th>slope</th><th>cluster</th></tr></thead>
        <tbody>{"".join(rows) or '<tr><td colspan="4" style="opacity:.5">no events</td></tr>'}</tbody>
      </table>
    </div>
    '''


def render_percolation(payload):
    p = payload["tier1"].get("percolation") or {}
    onset = p.get("onset_bucket")
    rows = [
        ("onset bucket", f'{onset} ({bucket_to_hhmm(onset)})'),
        ("LCC at onset", f'{int(p.get("onset_lcc_m") or 0)} m'),
        ("SLCC at onset", f'{int(p.get("onset_slcc_m") or 0)} m'),
        ("time to merge", f'{p.get("time_to_merge_minutes")} min'),
        ("max LCC", f'{int(p.get("summary", {}).get("max_lcc_m") or 0)} m'),
        ("max SLCC", f'{int(p.get("summary", {}).get("max_slcc_m") or 0)} m'),
        ("buckets w/ 2+ clusters", str(p.get("summary", {}).get("buckets_with_2plus_components", 0))),
    ]
    # Tiny LCC/SLCC sparkline — just the relative magnitudes
    lcc = p.get("lcc_trace_m") or []
    slcc = p.get("slcc_trace_m") or []
    spark_html = render_lcc_spark(lcc, slcc, onset) if lcc else ""
    return f'''
    <div class="card">
      <div class="card-title">Percolation <span class="paper-tag">Li 2015 / Zeng 2019 / Ambühl 2023</span></div>
      <table class="mini">
        {"".join(f"<tr><td>{escape(k)}</td><td style='text-align:right'><b>{escape(v)}</b></td></tr>" for k, v in rows)}
      </table>
      {spark_html}
    </div>
    '''


def render_lcc_spark(lcc, slcc, onset_bucket):
    if not lcc:
        return ""
    width, height = 280, 70
    n = len(lcc)
    max_v = max(max(lcc), max(slcc)) if slcc else max(lcc)
    if max_v <= 0:
        max_v = 1
    def pts(arr):
        return " ".join(f"{i*width/(n-1):.1f},{height - (v / max_v) * (height - 2):.1f}"
                        for i, v in enumerate(arr))
    onset_x = (onset_bucket * width / (n - 1)) if onset_bucket is not None else None
    onset_line = (
        f'<line x1="{onset_x:.1f}" y1="0" x2="{onset_x:.1f}" y2="{height}" stroke="#fff" stroke-dasharray="2,2" stroke-width="0.6"/>'
        if onset_x is not None else ""
    )
    return f'''
    <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" style="width:100%;height:80px;background:#111;border-radius:4px;margin-top:6px">
      <polyline fill="none" stroke="#ffa726" stroke-width="1" points="{pts(lcc)}"/>
      <polyline fill="none" stroke="#42a5f5" stroke-width="1" points="{pts(slcc)}"/>
      {onset_line}
    </svg>
    <div class="legend"><span style="color:#ffa726">— LCC</span> &nbsp; <span style="color:#42a5f5">— SLCC</span></div>
    '''


def render_jam_tree(payload, segment_meta_by_seg):
    jt = payload["tier1"].get("jam_tree") or {}
    s = jt.get("summary", {})
    nodes = jt.get("nodes") or []
    origins_html = []
    for n in [x for x in nodes if x.get("role") == "ORIGIN"][:6]:
        nm = escape(segment_meta_by_seg.get(n["segment_id"], {}).get("name", n["segment_id"])[:36])
        origins_html.append(
            f'<li><span class="dot dot-origin"></span> {nm} '
            f'<span style="opacity:.6">@ {bucket_to_hhmm(n.get("onset_bucket"))}</span></li>'
        )
    return f'''
    <div class="card">
      <div class="card-title">Jam-tree <span class="paper-tag">Serok 2022 / Duan 2023</span></div>
      <div class="kvs">
        <div>origins: <b>{s.get("n_origins", 0)}</b></div>
        <div>propagated: <b>{s.get("n_propagated", 0)}</b></div>
        <div>max depth: <b>{s.get("max_depth", 0)}</b></div>
        <div>reclassifications: <b>{s.get("n_reclassifications", 0)}</b></div>
      </div>
      <ul class="origin-list">{"".join(origins_html) or '<li style="opacity:.5">no origins</li>'}</ul>
    </div>
    '''


def render_mfd(payload):
    m = payload["tier1"].get("mfd") or {}
    speed = m.get("speed_trace_kmph") or []
    density = m.get("density_trace_frac") or []
    svg = render_mfd_svg(density, speed, m.get("ff_corridor_kmph") or 0)
    rows = [
        ("peak density bucket", f'{m.get("peak_density_bucket")} ({bucket_to_hhmm(m.get("peak_density_bucket"))})'),
        ("peak density", f'{(m.get("peak_density_frac") or 0) * 100:.1f}%'),
        ("loop closes", str(m.get("loop_closes"))),
        ("loop area", f'{m.get("loop_area") or 0:.2f} kmph·dens'),
        ("recovery lag", f'{m.get("recovery_lag_min")} min'),
        ("ff corridor", f'{m.get("ff_corridor_kmph") or 0:.1f} km/h'),
    ]
    return f'''
    <div class="card">
      <div class="card-title">MFD hysteresis <span class="paper-tag">Geroliminis 2008 / Saberi 2013</span></div>
      {svg}
      <table class="mini">
        {"".join(f"<tr><td>{escape(k)}</td><td style='text-align:right'><b>{escape(v)}</b></td></tr>" for k, v in rows)}
      </table>
    </div>
    '''


def render_mfd_svg(density, speed, ff_kmph):
    if not density or not speed:
        return ""
    pairs = [(d, s) for d, s in zip(density, speed) if s is not None and not (isinstance(s, float) and s != s)]
    if len(pairs) < 4:
        return '<div style="opacity:.5;font-size:11px">MFD trace too thin</div>'
    width, height = 280, 200
    pad = 18
    max_d = max(d for d, _ in pairs) or 1.0
    max_s = max(max(s for _, s in pairs), ff_kmph) or 1.0
    def to_xy(d, s):
        x = pad + (d / max_d) * (width - 2 * pad)
        y = (height - pad) - (s / max_s) * (height - 2 * pad)
        return x, y
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (to_xy(d, s) for d, s in pairs))
    return f'''
    <svg viewBox="0 0 {width} {height}" style="width:100%;height:200px;background:#111;border-radius:4px">
      <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#444"/>
      <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#444"/>
      <text x="{width/2}" y="{height-2}" fill="#888" font-size="9" text-anchor="middle">density (CONG length-frac)</text>
      <text x="6" y="{height/2}" fill="#888" font-size="9" transform="rotate(-90 6 {height/2})" text-anchor="middle">speed (km/h)</text>
      <polyline fill="none" stroke="#42a5f5" stroke-width="0.8" points="{pts}"/>
    </svg>
    '''


def render_dow(payload):
    dow = payload.get("dow_anomaly") or {}
    if not dow.get("available"):
        return f'''
        <div class="card">
          <div class="card-title">DOW anomaly <span class="paper-tag">v3-A native</span></div>
          <div style="opacity:.6">unavailable — {escape(str(dow.get('reason', '')))}</div>
        </div>
        '''
    return f'''
    <div class="card">
      <div class="card-title">DOW anomaly <span class="paper-tag">v3-A native</span></div>
      <div class="kvs">
        <div>day: <b>{escape(str(dow.get("dow")))}</b></div>
        <div>samples: <b>{dow.get("n_samples")}</b></div>
        <div>max dev: <b>{(dow.get("max_deviation_pct") or 0):+.2f}%</b></div>
        <div>at: <b>{bucket_to_hhmm(dow.get("max_deviation_bucket"))}</b></div>
      </div>
    </div>
    '''


def render_verdicts(payload, segment_meta_by_seg, segment_order):
    verdicts = payload["stages_v21"]["verdicts"]
    confidence = payload["stages_v21"]["confidence"]
    recurrence = payload["stages_v21"]["recurrence"]
    rows = []
    for s in segment_order:
        v = verdicts.get(s, "?")
        c = confidence.get(s, {}).get("label", "?")
        rec = recurrence.get(s, {}).get("label", "?") if recurrence else "—"
        nm = escape(segment_meta_by_seg.get(s, {}).get("name", s)[:32])
        rows.append(f'''
            <tr>
              <td>{nm}</td>
              <td><span class="chip" style="background:{VERDICT_COLOR.get(v, "#666")}">{escape(v)}</span></td>
              <td><span class="chip-sm" style="background:{CONFIDENCE_COLOR.get(c, "#666")}">{escape(c)}</span></td>
              <td style="opacity:.7">{escape(rec)}</td>
            </tr>
        ''')
    return f'''
    <div class="card">
      <div class="card-title">Per-segment verdicts <span class="paper-tag">v2.1</span></div>
      <table class="mini">
        <thead><tr><th>segment</th><th>verdict</th><th>conf</th><th>rec</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    '''


def render_meta(env):
    meta = env["meta"]
    bw = meta["baseline_window"]["primary"]
    dw = meta["baseline_window"]["dow_anomaly"]
    rows = [
        ("schema", env["schema_version"]),
        ("engine", env["engine_version"]),
        ("mode", env["mode"]),
        ("anchor", env["anchor_ts"]),
        ("anchor bucket", str(meta["anchor_bucket"])),
        ("baseline days", f'{bw["n_actual_days"]} of {bw["n_target_days"]}'),
        ("DOW samples", f'{dw["n_samples"]} (avail={dw["available"]})'),
        ("partial", str(meta["partial"])),
        ("warnings", str(len(meta["warnings"]))),
        ("config", meta["config_signature"]),
    ]
    return f'''
    <div class="card meta-card">
      <div class="card-title">Run meta</div>
      <table class="mini">
        {"".join(f"<tr><td>{escape(k)}</td><td style='text-align:right'>{escape(v)}</td></tr>" for k, v in rows)}
      </table>
    </div>
    '''


# --------------------------------------------------------------------------- #
# Page                                                                         #
# --------------------------------------------------------------------------- #


HEAD = """<!doctype html><html><head><meta charset="utf-8">
<title>v3-A Mode B — {title}</title>
<style>
  body { background: #0c0d12; color: #e0e0e8; font: 13px/1.4 -apple-system, system-ui, sans-serif; margin: 0; padding: 20px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .subtitle { opacity: .65; margin: 0 0 18px; font-size: 12px; }
  .header-strip { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 12px 14px; background: #15161d; border-radius: 8px; border: 1px solid #232431; margin-bottom: 16px; }
  .mode-toggle { display: inline-flex; background: #0c0d12; border: 1px solid #232431; border-radius: 6px; overflow: hidden; }
  .mode-toggle span { padding: 5px 10px; font-size: 11px; cursor: default; }
  .mode-toggle .on { background: #283ad9; color: #fff; font-weight: 600; }
  .pill { padding: 3px 9px; background: #1c1f30; border-radius: 11px; font-size: 11px; font-family: ui-monospace, Menlo, monospace; }
  .layout { display: grid; grid-template-columns: 1fr 360px; gap: 16px; }
  .center { background: #15161d; border: 1px solid #232431; border-radius: 8px; padding: 14px; }
  .sidebar { display: flex; flex-direction: column; gap: 12px; }
  .card { background: #15161d; border: 1px solid #232431; border-radius: 8px; padding: 12px; }
  .card-title { font-weight: 600; font-size: 12px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
  .paper-tag { background: #1c1f30; padding: 2px 6px; border-radius: 4px; font-size: 9px; font-weight: 400; opacity: .7; font-family: ui-monospace, Menlo, monospace; }
  .kvs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; font-size: 11px; opacity: .85; margin-bottom: 6px; }
  table.mini { width: 100%; border-collapse: collapse; font-size: 11px; }
  table.mini td, table.mini th { padding: 3px 6px; border-top: 1px solid #232431; }
  table.mini th { text-align: left; opacity: .55; font-weight: 500; font-size: 10px; text-transform: uppercase; }
  .chip { display: inline-block; padding: 2px 6px; border-radius: 3px; color: #fff; font-size: 10px; }
  .chip-sm { display: inline-block; padding: 1px 5px; border-radius: 3px; color: #000; font-size: 10px; }
  .legend { font-size: 10px; opacity: .7; margin-top: 4px; }
  .ribbon { font-family: ui-monospace, Menlo, monospace; }
  .ribbon-axis, .ribbon-row { display: flex; align-items: center; height: 22px; }
  .ribbon-label { width: 200px; font-size: 11px; padding-right: 8px; text-align: right; opacity: .85; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ribbon-track { flex: 1; height: 16px; background: #0c0d12; position: relative; border: 1px solid #232431; border-radius: 2px; display: flex; }
  .cell { flex: 1; height: 100%; }
  .flag { position: absolute; top: -2px; height: 20px; background: rgba(255,255,255,0.18); border: 1px solid #fff; border-radius: 1px; pointer-events: none; }
  .primary-window { position: absolute; top: -3px; height: 22px; background: rgba(66, 165, 245, 0.10); border-left: 1px dashed #42a5f5; border-right: 1px dashed #42a5f5; pointer-events: none; }
  .perc-marker { position: absolute; top: -3px; height: 22px; width: 2px; background: #ffa726; pointer-events: none; }
  .anchor-marker { position: absolute; top: -3px; height: 22px; width: 2px; background: #fff; pointer-events: none; }
  .ribbon-axis .ribbon-track { height: 16px; background: transparent; border: none; }
  .ribbon-axis .tick { position: absolute; top: 0; font-size: 9px; opacity: .55; transform: translateX(-50%); }
  .legend-strip { display: flex; gap: 12px; font-size: 11px; opacity: .8; margin-top: 8px; }
  .legend-strip .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; vertical-align: middle; margin-right: 4px; }
  .origin-list { list-style: none; padding-left: 0; margin: 6px 0 0 0; font-size: 11px; }
  .origin-list li { padding: 2px 0; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
  .dot-origin { background: #ffa726; }
  .meta-card { font-size: 11px; }
  .footer { margin-top: 24px; opacity: .5; font-size: 11px; }
</style></head><body>
"""

FOOT = "<div class='footer'>v3-A Mode B mockup — Layout B (timeline-first centerpiece + sidebar). Spec: docs/superpowers/specs/2026-05-04-corridor-diagnostics-v3a-design.md</div></body></html>"


def render_page(env, regimes_today_by_seg, segment_meta_by_seg, segment_order, bertini_today_by_seg):
    payload = env["payload"]
    title = f'{env["corridor_id"]} — {env["corridor_name"]}'
    perc_onset = (payload["tier1"].get("percolation") or {}).get("onset_bucket")

    head = HEAD.replace("{title}", escape(title))
    header = f'''
      <h1>{escape(env["corridor_name"])}</h1>
      <div class="subtitle">{escape(env["corridor_id"])} · {len(segment_order)} segments · run_id {escape(env["run_id"])}</div>
      <div class="header-strip">
        <div class="mode-toggle">
          <span>Retrospective</span><span class="on">Today</span><span>Replay</span>
        </div>
        <div class="pill">anchor T = {escape(env["anchor_ts"])}</div>
        <div class="pill">bucket {env["meta"]["anchor_bucket"]}</div>
        <div class="pill" style="background:#283ad9">{escape(env["mode"])}</div>
        <div class="pill">partial = {str(env["meta"]["partial"]).lower()}</div>
      </div>
    '''
    ribbon = render_ribbon(
        regimes_today_by_seg, segment_order, segment_meta_by_seg,
        env["meta"]["anchor_bucket"], bertini_today_by_seg,
        payload["stages_v21"]["head_bottleneck"],
        payload["stages_v21"]["primary_windows_today"],
        perc_onset,
    )
    legend = '''
    <div class="legend-strip">
      <div><span class="swatch" style="background:#2e7d32"></span>FREE</div>
      <div><span class="swatch" style="background:#fbc02d"></span>APPROACHING</div>
      <div><span class="swatch" style="background:#ef6c00"></span>CONGESTED</div>
      <div><span class="swatch" style="background:#c62828"></span>SEVERE</div>
      <div style="opacity:.6">|</div>
      <div><span class="swatch" style="background:rgba(66,165,245,.3);border:1px dashed #42a5f5"></span>primary window</div>
      <div><span class="swatch" style="background:#ffa726"></span>percolation onset</div>
      <div><span class="swatch" style="background:#fff"></span>anchor T</div>
      <div><span class="swatch" style="background:rgba(255,255,255,.18);border:1px solid #fff"></span>Bertini event</div>
    </div>
    '''
    center = f'''
    <div class="center">
      <div style="font-weight:600;font-size:12px;margin-bottom:8px">Per-segment regime ribbon  <span style="opacity:.5;font-weight:400">— 720 buckets · 2 min each · upstream → downstream</span></div>
      {ribbon}
      {legend}
    </div>
    '''
    sidebar = f'''
    <div class="sidebar">
      {render_growth_rate(payload)}
      {render_percolation(payload)}
      {render_jam_tree(payload, segment_meta_by_seg)}
      {render_mfd(payload)}
      {render_dow(payload)}
      {render_verdicts(payload, segment_meta_by_seg, segment_order)}
      {render_meta(env)}
    </div>
    '''
    return head + header + f'<div class="layout">{center}{sidebar}</div>' + FOOT


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #


def main(corridor_id: str, out_path: Path):
    """Re-run Mode B on corridor + render to HTML.

    For convenience, we re-run the dry-run setup so segment_meta and regimes_today
    are available without round-tripping them through the envelope JSON.
    """
    from datetime import date, datetime, timedelta
    from data.v3_a.api import _reset_for_tests, submit_run, wait_for_run
    from data.v3_a.baseline import BaselineResult, DowSamples
    from data.v3_a.data_pull import Row, TodayPull
    from data.v3_a.progress import IST, RunStatus
    from data.v3_a.stages_v21 import run_v21_stages

    repo = Path(__file__).resolve().parents[2]
    with open(repo / "data/v2_1/profiles/all_profiles_weekday.json") as f:
        all_p = json.load(f)
    with open(repo / "data/v2_1/onsets/all_onsets_weekday.json") as f:
        all_o = json.load(f)
    with open(repo / "data/v2_1/validation_corridors.json") as f:
        c = json.load(f)[corridor_id]

    seg_ord = [s["road_id"] for s in c["chain"]]
    seg_meta = {s["road_id"]: {"name": s["road_name"], "length_m": s["length_m"], "road_class": s.get("road_class", "unknown")} for s in c["chain"]}
    profile = {rid: {int(k): int(v) for k, v in all_p[rid].items()} for rid in seg_ord}
    raw_onsets = [(r["rid"], r["dt"], int(r["om"])) for r in all_o if r["rid"] in set(seg_ord)]
    baseline = BaselineResult(profile_by_seg=profile, n_actual_days=22, distinct_days=[date(2026, 4, 1)] * 22, thin=False)

    anchor = datetime(2026, 4, 22, 23, 58, tzinfo=IST)
    day_start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [Row(seg, day_start + timedelta(minutes=mod), float(tt))
            for seg, by_min in profile.items() for mod, tt in by_min.items()]
    today_pull = TodayPull(rows=rows, by_seg={s: [r for r in rows if r.road_id == s] for s in seg_ord}, gap_warnings=[])
    dow_samples = DowSamples(
        {s: {date(2026, 4, 1): profile[s], date(2026, 4, 8): profile[s], date(2026, 4, 15): profile[s]} for s in seg_ord},
        [date(2026, 4, 1), date(2026, 4, 8), date(2026, 4, 15)], 3, 2, True,
    )

    _reset_for_tests()
    rid = submit_run(corridor_id, anchor, mode="today_as_of_T",
                     baseline_override=baseline, today_pull_override=today_pull,
                     dow_samples_override=dow_samples, raw_onsets_override=raw_onsets)
    rec = wait_for_run(rid, timeout_sec=120)
    assert rec.status == RunStatus.COMPLETED, rec.error
    env = rec.result

    # Re-run stages_v21 to recover regimes_today and bertini_today (envelope holds the numbers, not the trace)
    stages = run_v21_stages(
        corridor_id=corridor_id, corridor_name=c["name"],
        segment_order=seg_ord, segment_meta=seg_meta,
        baseline=baseline, raw_onsets=raw_onsets, today_pull=today_pull,
        anchor_ts=anchor, mode="today_as_of_T",
    )

    html = render_page(env, stages.regimes_today_by_seg, seg_meta, seg_ord, stages.bertini_today)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    out_dir = repo / "docs" / "dry_runs_v3_a"
    main("KOL_B", out_dir / "KOL_B" / "v3a_today_as_of_T.html")
    main("DEL_AUROBINDO", out_dir / "DEL_AUROBINDO" / "v3a_today_as_of_T.html")
