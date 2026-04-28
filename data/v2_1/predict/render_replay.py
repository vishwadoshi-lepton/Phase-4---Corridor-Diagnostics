"""Render a single-page HTML replay for each (corridor, held-out-day) combo.

Each HTML file is self-contained: it embeds the corresponding forecast JSON
(from precompute.py) and contains all JS/CSS/SVG needed to drive the slider.

Usage:
    python3 -m data.v2_1.predict.render_replay

Writes to docs/replay/<CORRIDOR>_<DATE>.html
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C


# ---------- HTML template ----------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg:#0b1220; --panel:#111a2e; --panel-2:#1a2440; --ink:#e7ecf3;
    --muted:#8a96ac; --accent:#38bdf8; --anchor:#f59e0b;
    --free:#22c55e; --appr:#fbbf24; --cong:#f97316; --sevr:#dc2626;
    --stroke:#2a3655;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin:0; padding:0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh;
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px 24px; }}
  h1 {{ font-size: 22px; margin: 0 0 6px; letter-spacing: -0.01em; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 4px; }}
  .meta-row {{ display: flex; gap: 14px; flex-wrap: wrap; margin-top: 8px; font-size: 12px; }}
  .tag {{
    background: var(--panel-2); border: 1px solid var(--stroke);
    padding: 3px 10px; border-radius: 999px; color: var(--muted);
  }}
  .tag.warn {{ background: #422006; border-color: #b45309; color: #fcd34d; }}
  .tag.ok {{ background: #022c22; border-color: #10b981; color: #6ee7b7; }}

  .panel {{ background: var(--panel); border: 1px solid var(--stroke);
           border-radius: 12px; padding: 22px; margin-top: 20px; }}

  .corridor-header {{ display: flex; justify-content: space-between; align-items: baseline;
                     margin-bottom: 12px; }}
  .playstate-chip {{
    font-size: 11px; padding: 4px 12px; border-radius: 999px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.06em;
  }}
  .playstate-chip.actual   {{ background: #022c2233; color: #6ee7b7; border: 1px solid #10b98166; }}
  .playstate-chip.forecast {{ background: #3b0a7b33; color: #c4b5fd; border: 1px solid #8b5cf666; }}
  .playstate-chip.future-actual {{ background: #0c2441; color: #7dd3fc; border: 1px solid #38bdf866; }}

  svg.corridor {{ width: 100%; height: 220px; display: block; }}

  .slider-outer {{ margin-top: 26px; padding: 12px 20px 38px; background: var(--panel-2);
                   border-radius: 8px; position: relative; }}
  .slider-track {{ position: relative; height: 52px; margin-top: 4px; }}
  .slider-rail {{ position: absolute; top: 22px; left: 0; right: 0; height: 8px;
                  background: #0b1220; border-radius: 4px; }}
  .fill-past {{ position: absolute; top: 22px; height: 8px;
                background: linear-gradient(90deg, #0f766e22, #10b98155); border-radius: 4px 0 0 4px; }}
  .fill-forecast {{ position: absolute; top: 22px; height: 8px;
                background: repeating-linear-gradient(45deg, #8b5cf666 0 6px, #8b5cf622 6px 12px);
                border-top: 1px solid #8b5cf688; border-bottom: 1px solid #8b5cf688; }}
  .fill-future-actual {{ position: absolute; top: 22px; height: 8px;
                background: linear-gradient(90deg, #0c244155, #38bdf844); border-radius: 0 4px 4px 0; }}

  .marker {{ position: absolute; cursor: grab; user-select: none; }}
  .marker .stem {{ position: absolute; left: 50%; transform: translateX(-50%); width: 2px;
                  height: 52px; top: 0; }}
  .marker.anchor .stem {{ background: var(--anchor); }}
  .marker.anchor .handle {{ position: absolute; left: 50%; transform: translateX(-50%);
                  top: 16px; width: 20px; height: 20px; border-radius: 50%;
                  background: var(--anchor); border: 2px solid var(--panel-2); }}
  .marker.anchor .label {{ position: absolute; left: 50%; transform: translateX(-50%);
                  top: -4px; font-size: 10px; color: var(--anchor); font-weight: 700;
                  white-space: nowrap; }}

  .marker.playhead .stem {{ background: var(--accent); width: 3px; }}
  .marker.playhead .handle {{ position: absolute; left: 50%; transform: translateX(-50%);
                  top: 16px; width: 18px; height: 18px; background: var(--accent);
                  transform: translateX(-50%) rotate(45deg); border: 2px solid var(--panel-2); }}
  .marker.playhead .label {{ position: absolute; left: 50%; transform: translateX(-50%);
                  bottom: -22px; font-size: 11px; color: var(--accent); font-weight: 700;
                  white-space: nowrap; }}

  .time-axis {{ display: flex; justify-content: space-between; font-size: 10px;
                color: var(--muted); margin-top: 10px; }}

  .controls {{ display: flex; gap: 10px; align-items: center; margin-top: 18px;
               padding-top: 16px; border-top: 1px solid var(--stroke); flex-wrap: wrap; }}
  button, select {{
    background: var(--panel-2); color: var(--ink); border: 1px solid var(--stroke);
    padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer;
    font-weight: 500;
  }}
  button:hover, select:hover {{ background: #24324f; }}
  button.primary {{ background: #2563eb; border-color: #3b82f6; }}
  button.primary:hover {{ background: #1d4ed8; }}
  .ctrl-label {{ font-size: 11px; color: var(--muted); }}

  .legend {{ display: flex; gap: 18px; font-size: 11px; color: var(--ink);
             flex-wrap: wrap; margin-top: 18px; }}
  .sw {{ width: 14px; height: 14px; border-radius: 3px; display: inline-block;
         vertical-align: middle; margin-right: 6px; }}

  .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                 gap: 12px; margin-top: 14px; }}
  .detail-card {{ background: var(--panel-2); border: 1px solid var(--stroke);
                  border-radius: 8px; padding: 10px 12px; font-size: 12px; }}
  .detail-card h4 {{ margin: 0 0 6px; font-size: 13px; color: var(--ink); }}
  .detail-card .row {{ display: flex; justify-content: space-between;
                        margin-bottom: 3px; color: var(--muted); }}
  .detail-card .row b {{ color: var(--ink); font-weight: 600; }}
  .agree-AGREE {{ color: #6ee7b7; }}
  .agree-EARLIER_THAN_USUAL {{ color: #fcd34d; }}
  .agree-LATER_THAN_USUAL {{ color: #7dd3fc; }}
  .agree-NO_PREDICTED {{ color: #f87171; }}
  .agree-NO_HISTORICAL {{ color: var(--muted); }}

  .verdict {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700;
              letter-spacing: 0.03em; }}
  .verdict.HEAD_BOTTLENECK {{ background: #7f1d1d; color: #fecaca; }}
  .verdict.ACTIVE_BOTTLENECK {{ background: #991b1b; color: #fecaca; }}
  .verdict.SLOW_LINK {{ background: #92400e; color: #fed7aa; }}
  .verdict.QUEUE_VICTIM {{ background: #713f12; color: #fde68a; }}
  .verdict.FREE_FLOW {{ background: #064e3b; color: #6ee7b7; }}

  .playstate-box {{ margin-top: 14px; font-size: 12px; color: var(--muted);
                    background: var(--panel-2); border-radius: 6px; padding: 10px 14px;
                    border-left: 3px solid var(--accent); }}
</style>
</head>
<body>
<div class="wrap">

  <h1>{corridor_id} · {corridor_name}</h1>
  <div class="sub">{city} · replay mode · held-out date <b>{date}</b></div>
  <div class="meta-row">
    <span class="tag">data source: <b>{source}</b></span>
    <span class="tag">forecaster: <b>{forecaster_name}</b></span>
    <span class="tag">horizon: <b>{horizon_min} min</b></span>
    <span class="tag">anchor step: <b>{anchor_step_min} min</b></span>
    <span class="tag ok">v2.1 prior active</span>
  </div>

  <div class="panel">
    <div class="corridor-header">
      <div>
        <h3 style="margin:0; font-size:14px;">Corridor view · segments scaled by length, coloured by regime at playhead</h3>
        <div style="font-size:11px; color:var(--muted); margin-top:4px;">
          Bottleneck icons are v2.1 verdicts (static). Fill colours are the live regime at the currently-displayed time.
        </div>
      </div>
      <span id="playstate-chip" class="playstate-chip actual">past · actual</span>
    </div>

    <svg class="corridor" viewBox="0 0 1200 220" preserveAspectRatio="xMinYMid meet" xmlns="http://www.w3.org/2000/svg">
      <!-- baseline -->
      <line x1="40" y1="110" x2="1160" y2="110" stroke="var(--stroke)" stroke-width="2"/>
      <g id="segments"></g>
    </svg>

    <div class="slider-outer">
      <div class="slider-track" id="slider-track">
        <div class="slider-rail"></div>
        <div class="fill-past" id="fill-past"></div>
        <div class="fill-forecast" id="fill-forecast"></div>
        <div class="fill-future-actual" id="fill-future-actual"></div>
        <div class="marker anchor" id="anchor-marker">
          <div class="stem"></div><div class="handle"></div>
          <div class="label">anchor · <span id="anchor-time">14:00</span></div>
        </div>
        <div class="marker playhead" id="playhead-marker">
          <div class="stem"></div><div class="handle"></div>
          <div class="label">playhead · <span id="playhead-time">14:30</span></div>
        </div>
      </div>
      <div class="time-axis">
        <span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span>
        <span>16:00</span><span>20:00</span><span>24:00</span>
      </div>
    </div>

    <div class="controls">
      <button class="primary" id="play-btn">▶ Play</button>
      <button id="reset-btn">↺ Reset</button>
      <span class="ctrl-label">speed</span>
      <select id="speed-select">
        <option value="10">10×</option>
        <option value="20" selected>20×</option>
        <option value="60">60×</option>
        <option value="120">120×</option>
      </select>
      <span class="ctrl-label" style="margin-left:18px;">anchor</span>
      <select id="anchor-select"></select>
    </div>

    <div class="legend">
      <span><span class="sw" style="background:var(--free);"></span>FREE</span>
      <span><span class="sw" style="background:var(--appr);"></span>APPROACHING</span>
      <span><span class="sw" style="background:var(--cong);"></span>CONGESTED</span>
      <span><span class="sw" style="background:var(--sevr);"></span>SEVERE</span>
      <span style="margin-left:24px;"><span class="sw" style="background:var(--anchor); border-radius:50%;"></span>anchor · model's "now"</span>
      <span><span class="sw" style="background:var(--accent); transform:rotate(45deg);"></span>playhead · what's shown</span>
    </div>

    <div class="playstate-box" id="playstate-detail">
      Playhead is before the anchor — showing <b>actual observed</b> regime at this time.
    </div>

    <div class="detail-grid" id="detail-grid"></div>
  </div>

  <div class="panel" style="margin-top:22px; font-size:12px; color:var(--muted);">
    <h3 style="margin:0 0 8px; color:var(--ink); font-size:13px;">How to read this</h3>
    <ul style="margin:0; padding-left:20px; line-height:1.7;">
      <li><b>Anchor</b> (orange dot) = the moment the forecaster is called. Drag it or pick from the dropdown; all 45 forecast steps for that anchor are pre-computed.</li>
      <li><b>Playhead</b> (blue diamond) = the time displayed on the corridor. Three zones:
        <ul>
          <li>Past of anchor → <b>actual</b> observed regime (green-tinted rail)</li>
          <li>Anchor → anchor+{horizon_min}min → <b>predicted</b> regime (violet-hatched rail)</li>
          <li>After anchor+{horizon_min}min → actual again (useful for scrubbing the rest of the day)</li>
        </ul>
      </li>
      <li><b>Detail cards</b> below the corridor show per-segment predicted vs. typical onset and v2.1 fusion agreement.</li>
    </ul>
  </div>

</div>

<script>
// ============ embedded forecast data ============
const DATA = {embedded_json};

// ============ constants ============
const BUCKET_MIN = DATA.bucket_min;
const BUCKETS_PER_DAY = 720;
const HORIZON_MIN = DATA.horizon_min;
const HORIZON_STEPS = HORIZON_MIN / BUCKET_MIN;
const DAY_MIN = 24 * 60;
const REGIME_COLOR = {{
  FREE: "#22c55e", APPROACHING: "#fbbf24",
  CONGESTED: "#f97316", SEVERE: "#dc2626",
}};

// ============ state ============
let anchorMin = DATA.anchor_ticks[Math.floor(DATA.anchor_ticks.length / 2)];
let playheadMin = anchorMin + 30;  // default: peek 30 min ahead
let playing = false;
let playTimer = null;
let playSpeed = 20;

// ============ anchor dropdown ============
const anchorSelect = document.getElementById('anchor-select');
for (const a of DATA.anchor_ticks) {{
  const opt = document.createElement('option');
  opt.value = a;
  opt.textContent = minToClock(a);
  if (a === anchorMin) opt.selected = true;
  anchorSelect.appendChild(opt);
}}
anchorSelect.addEventListener('change', () => {{
  anchorMin = parseInt(anchorSelect.value, 10);
  if (playheadMin < anchorMin) playheadMin = anchorMin;
  render();
}});

// ============ utility ============
function minToClock(m) {{
  const h = Math.floor(m / 60);
  const mi = m % 60;
  return String(h).padStart(2, '0') + ':' + String(mi).padStart(2, '0');
}}
function snapToAnchor(m) {{
  // find nearest anchor tick to m
  let best = DATA.anchor_ticks[0];
  let bestD = Math.abs(m - best);
  for (const a of DATA.anchor_ticks) {{
    const d = Math.abs(m - a);
    if (d < bestD) {{ bestD = d; best = a; }}
  }}
  return best;
}}

// ============ playstate logic ============
function getPlaystate() {{
  if (playheadMin < anchorMin) return 'past';
  if (playheadMin <= anchorMin + HORIZON_MIN) return 'forecast';
  return 'future-actual';
}}

// ============ regime lookup ============
function regimeAt(segIdx, displayMin, state) {{
  // state: 'past' | 'future-actual' → use DATA.actual_day
  //        'forecast' → use DATA.forecasts_by_anchor[anchorMin]
  if (state === 'forecast') {{
    const anc = DATA.forecasts_by_anchor[anchorMin];
    if (!anc) return 'FREE';
    const seg = anc.segments[segIdx];
    const k = Math.floor((displayMin - anchorMin) / BUCKET_MIN) - 1;
    if (k < 0 || k >= seg.predicted_regimes.length) return 'FREE';
    return seg.predicted_regimes[k];
  }} else {{
    const bk = Math.floor(displayMin / BUCKET_MIN);
    const idx = Math.max(0, Math.min(BUCKETS_PER_DAY - 1, bk));
    return DATA.actual_day[segIdx].regimes[idx];
  }}
}}

// ============ rendering ============
const segGroup = document.getElementById('segments');

function renderSegments(state, displayMin) {{
  segGroup.innerHTML = '';
  const totalLen = DATA.chain.reduce((a, s) => a + s.length_m, 0);
  const xStart = 60, xEnd = 1140, barY = 92;
  const barH = 36;
  const plotW = xEnd - xStart;
  let xCursor = xStart;

  for (let i = 0; i < DATA.chain.length; i++) {{
    const seg = DATA.chain[i];
    const w = (seg.length_m / totalLen) * plotW;
    const reg = regimeAt(i, displayMin, state);
    const fill = REGIME_COLOR[reg] || REGIME_COLOR.FREE;

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

    // segment rect
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', xCursor);
    rect.setAttribute('y', barY);
    rect.setAttribute('width', w);
    rect.setAttribute('height', barH);
    rect.setAttribute('fill', fill);
    rect.setAttribute('stroke', '#0b1220');
    rect.setAttribute('stroke-width', '1.5');
    rect.setAttribute('rx', 2);
    if (state === 'forecast') {{
      // overlay a diagonal hatch to signal "predicted"
      rect.setAttribute('stroke-dasharray', '4 2');
      rect.setAttribute('stroke', '#8b5cf6');
    }}
    g.appendChild(rect);

    // dynamic bottleneck icon (changes with data) — above segment, appears ONLY
    //   when the live regime at the playhead is CONG or SEVR
    if (reg === 'CONGESTED' || reg === 'SEVERE') {{
      const cx = xCursor + w / 2;
      const iy = 68;
      const tri = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      tri.setAttribute('d', `M ${{cx}} ${{iy}} L ${{cx + 10}} ${{iy + 17}} L ${{cx - 10}} ${{iy + 17}} Z`);
      tri.setAttribute('fill', reg === 'SEVERE' ? '#dc2626' : '#f97316');
      tri.setAttribute('stroke', '#0b1220');
      tri.setAttribute('stroke-width', '1.2');
      if (state === 'forecast') {{
        tri.setAttribute('stroke-dasharray', '3 2');
        tri.setAttribute('stroke', '#8b5cf6');
      }}
      g.appendChild(tri);
      const itxt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      itxt.setAttribute('x', cx);
      itxt.setAttribute('y', iy + 14);
      itxt.setAttribute('text-anchor', 'middle');
      itxt.setAttribute('font-size', '11');
      itxt.setAttribute('font-weight', '700');
      itxt.setAttribute('fill', '#fff');
      itxt.textContent = reg === 'SEVERE' ? '⚠' : '!';
      g.appendChild(itxt);
    }}

    // label
    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', xCursor + w / 2);
    label.setAttribute('y', barY + barH + 16);
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('font-size', '11');
    label.setAttribute('fill', '#cbd5e1');
    label.textContent = seg.segment_idx;
    g.appendChild(label);

    const sub = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    sub.setAttribute('x', xCursor + w / 2);
    sub.setAttribute('y', barY + barH + 30);
    sub.setAttribute('text-anchor', 'middle');
    sub.setAttribute('font-size', '9');
    sub.setAttribute('fill', '#8a96ac');
    sub.textContent = `${{seg.length_m}}m · ${{reg.toLowerCase()}}`;
    g.appendChild(sub);

    segGroup.appendChild(g);
    xCursor += w;
  }}
}}

// ============ slider rendering ============
function minToPct(m) {{ return (m / DAY_MIN) * 100; }}

function renderSlider() {{
  document.getElementById('fill-past').style.left = '0%';
  document.getElementById('fill-past').style.width = minToPct(anchorMin) + '%';
  document.getElementById('fill-forecast').style.left = minToPct(anchorMin) + '%';
  document.getElementById('fill-forecast').style.width =
    minToPct(HORIZON_MIN) + '%';
  const fueStart = anchorMin + HORIZON_MIN;
  document.getElementById('fill-future-actual').style.left = minToPct(fueStart) + '%';
  document.getElementById('fill-future-actual').style.width =
    (100 - minToPct(fueStart)) + '%';

  document.getElementById('anchor-marker').style.left = minToPct(anchorMin) + '%';
  document.getElementById('playhead-marker').style.left = minToPct(playheadMin) + '%';
  document.getElementById('anchor-time').textContent = minToClock(anchorMin);
  document.getElementById('playhead-time').textContent = minToClock(playheadMin);
}}

// ============ detail cards ============
function renderDetailCards(state) {{
  const grid = document.getElementById('detail-grid');
  grid.innerHTML = '';
  const anc = DATA.forecasts_by_anchor[anchorMin];
  if (!anc) return;
  for (let i = 0; i < DATA.chain.length; i++) {{
    const seg = DATA.chain[i];
    const fc = anc.segments[i];
    const fus = fc.fusion;
    const card = document.createElement('div');
    card.className = 'detail-card';

    const predictedOnset = fus.congestion_onset_predicted_min;
    const typicalOnset = fus.congestion_onset_typical_min;

    card.innerHTML = `
      <h4>${{seg.segment_idx}} <span class="verdict ${{seg.verdict}}">${{seg.verdict.replace('_',' ')}}</span></h4>
      <div class="row"><span>recurrence</span><b>${{seg.recurrence_label}}
        (${{(seg.recurrence_frac * 100).toFixed(0)}}%)</b></div>
      <div class="row"><span>predicted onset</span><b>${{predictedOnset !== null ?
        minToClockJs(predictedOnset) : '—'}}</b></div>
      <div class="row"><span>typical onset</span><b>${{typicalOnset !== null ?
        minToClockJs(typicalOnset) : '—'}}</b></div>
      <div class="row"><span>agreement</span>
        <b class="agree-${{fus.agreement}}">${{fus.agreement.replace(/_/g,' ')}}</b></div>
      <div style="font-size:11px; color:var(--muted); margin-top:8px; line-height:1.5;">
        ${{fus.skipped ? '<i>gated by v2.1 prior — ' + (fus.skip_reason||'') + '</i>' : fus.fusion_note}}
      </div>
    `;
    grid.appendChild(card);
  }}
}}
function minToClockJs(m) {{
  const h = Math.floor(m / 60);
  const mi = m % 60;
  return String(h).padStart(2, '0') + ':' + String(mi).padStart(2, '0');
}}

function renderPlaystate(state) {{
  const chip = document.getElementById('playstate-chip');
  const detail = document.getElementById('playstate-detail');
  chip.classList.remove('actual', 'forecast', 'future-actual');
  if (state === 'past') {{
    chip.classList.add('actual');
    chip.textContent = 'past of anchor · actual';
    detail.innerHTML = `Playhead at <b>${{minToClockJs(playheadMin)}}</b> is ` +
      `before anchor <b>${{minToClockJs(anchorMin)}}</b> — showing <b>actual observed</b> regime.`;
  }} else if (state === 'forecast') {{
    chip.classList.add('forecast');
    chip.textContent = 'inside forecast window · predicted';
    const stepsAhead = (playheadMin - anchorMin);
    detail.innerHTML = `Playhead is <b>${{stepsAhead}} min</b> ahead of anchor — ` +
      `showing <b>TimesFM/baseline prediction</b> (from anchor ${{minToClockJs(anchorMin)}}).`;
  }} else {{
    chip.classList.add('future-actual');
    chip.textContent = 'past horizon · actual (future of anchor)';
    detail.innerHTML = `Playhead is more than ${{HORIZON_MIN}} min past anchor — ` +
      `back to <b>actual observed</b> (the rest of the day's ground truth).`;
  }}
}}

function render() {{
  const state = getPlaystate();
  renderSegments(state, playheadMin);
  renderSlider();
  renderPlaystate(state);
  renderDetailCards(state);
}}

// ============ interactions ============
function pxToMin(clientX, trackEl) {{
  const rect = trackEl.getBoundingClientRect();
  const pct = (clientX - rect.left) / rect.width;
  return Math.max(0, Math.min(DAY_MIN - 1, Math.round(pct * DAY_MIN)));
}}

function makeDraggable(markerId, onChange, snap = false) {{
  const marker = document.getElementById(markerId);
  const track = document.getElementById('slider-track');
  let dragging = false;
  marker.addEventListener('mousedown', e => {{
    dragging = true; e.preventDefault();
    marker.style.cursor = 'grabbing';
  }});
  document.addEventListener('mousemove', e => {{
    if (!dragging) return;
    let m = pxToMin(e.clientX, track);
    if (snap) m = snapToAnchor(m);
    onChange(m);
  }});
  document.addEventListener('mouseup', () => {{
    dragging = false;
    marker.style.cursor = 'grab';
  }});
}}
makeDraggable('anchor-marker', m => {{
  // anchor can only move to snapped anchor-ticks
  anchorMin = snapToAnchor(m);
  anchorSelect.value = anchorMin;
  if (playheadMin < anchorMin - 60 || playheadMin > anchorMin + HORIZON_MIN + 60) {{
    playheadMin = anchorMin + 30;
  }}
  render();
}}, true);
makeDraggable('playhead-marker', m => {{
  playheadMin = m;
  render();
}}, false);

// click on rail to set playhead
document.getElementById('slider-track').addEventListener('click', e => {{
  // ignore clicks on the markers themselves
  if (e.target.closest('.marker')) return;
  playheadMin = pxToMin(e.clientX, e.currentTarget);
  render();
}});

// play/pause
const playBtn = document.getElementById('play-btn');
playBtn.addEventListener('click', () => {{
  if (playing) {{
    playing = false;
    clearInterval(playTimer);
    playBtn.textContent = '▶ Play';
  }} else {{
    playing = true;
    playBtn.textContent = '⏸ Pause';
    playTimer = setInterval(() => {{
      playheadMin += 2;  // advance 2 min per tick (1 bucket)
      if (playheadMin >= DAY_MIN) playheadMin = 0;
      render();
    }}, 2000 / playSpeed * 60);  // 2 min / speed ticks/sec
  }}
}});
document.getElementById('speed-select').addEventListener('change', e => {{
  playSpeed = parseInt(e.target.value, 10);
  if (playing) {{
    clearInterval(playTimer);
    playTimer = setInterval(() => {{
      playheadMin += 2;
      if (playheadMin >= DAY_MIN) playheadMin = 0;
      render();
    }}, 2000 / playSpeed * 60);
  }}
}});
document.getElementById('reset-btn').addEventListener('click', () => {{
  anchorMin = DATA.anchor_ticks[Math.floor(DATA.anchor_ticks.length / 2)];
  playheadMin = anchorMin + 30;
  anchorSelect.value = anchorMin;
  render();
}});

// initial render
render();
</script>
</body>
</html>
"""


def render_one(forecast_json_path: Path, out_dir: Path) -> Path:
    data = json.loads(forecast_json_path.read_text())
    cid = data["corridor_id"]
    date_str = data["date"]
    title = f"{cid} · {date_str} · replay"

    # inline JSON (safely: no trailing </script> or -->) — for our own JSON this is safe
    embedded = json.dumps(data, separators=(",", ":"))

    html = HTML_TEMPLATE.format(
        title=title,
        corridor_id=cid,
        corridor_name=data["corridor_name"],
        city=data["city"],
        date=date_str,
        source=data["source"],
        forecaster_name=data["forecaster_name"],
        horizon_min=data["horizon_min"],
        anchor_step_min=data["anchor_step_min"],
        embedded_json=embedded,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{cid}_{date_str}_replay.html"
    out_path.write_text(html)
    return out_path


def main() -> None:
    out_dir = C.REPLAY_HTML_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(C.FORECASTS_DIR.glob("*.json"))
    for f in files:
        out = render_one(f, out_dir)
        print(f"[render] {f.name} → {out.relative_to(C.REPO_ROOT)}")
    # Index page listing all replays
    idx = out_dir / "index.html"
    links = "\n".join(
        f'    <li><a href="{f.name}">{f.name.replace("_replay.html","")}</a></li>'
        for f in sorted(out_dir.glob("*_replay.html"))
    )
    idx.write_text(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Replay index</title>
<style>
body{{background:#0b1220;color:#e7ecf3;font-family:-apple-system,sans-serif;padding:28px;}}
a{{color:#38bdf8;text-decoration:none}}a:hover{{text-decoration:underline}}
li{{margin:4px 0;font-size:14px}}
</style></head>
<body><h1>v2.1 prediction replays</h1>
<p style="color:#8a96ac;font-size:12px;">One HTML per (corridor, held-out-day).
Click any link to open the replay UI.</p>
<ul>
{links}
</ul></body></html>
""")
    print(f"[render] index → {idx.relative_to(C.REPO_ROOT)}")


if __name__ == "__main__":
    main()
