# Signal-density overlay (v1) — design

## Goal

Surface OSM signal/crossing/junction structure on existing v2.1 diagnostic
artifacts (dry-run HTMLs, replay HTMLs, validation reports) so that an
engineer reading any verdict can see whether a slow segment is *signal-dominated*
or *capacity-limited*. No new physics yet — just structural context, snapshotted
into the run output.

This is **step A + B + C** of the broader signal-aware diagnostics roadmap
(brainstormed 2026-04-29). Free-flow sanity check, Bertini disambiguation,
LWR band conditioning, junction-anchored splitting, and probe-derived cycle
length estimation are **out of scope** for this spec; each is its own future
design round.

## Data situation (verified against dev DB `192.168.2.97`, schema `raw`)

- `raw.osm_overpass_node` — 138 + dump-2 nodes per city across 8 cities. Has
  `lat`, `lon`, `node_type ∈ {traffic_signal, junction, crossing}`, `tags`,
  PostGIS `geom`. Loaded for Pune (539), Delhi (1529), Kolkata (81), Hyderabad
  (277), and a few smaller cities. Two dump generations; we use the latest by
  `osm_overpass_dump.id`.
- `raw.road_signal_density` — pre-aggregated per `road_id`: `signal_count`,
  `junction_count`, `crossing_count`, `total_node_count`,
  `signal_density_per_km`, `buffer_meters` (50 m). Already populated for all
  89 v2.1 validation segments (verified 89/89 join coverage).

Coverage signature on our 7 validation corridors:

| Corridor | Σsignals | Σcrossings | Notes |
|---|---|---|---|
| PUNE_A | 0 | 0 | quiet peri-urban (correct) |
| PUNE_B | 11 | 0 | signals concentrate on urban middle (S04–S07) |
| PUNE_C | 3 | 0 | only S08 has any |
| KOL_A | 0 | 0 | suspected OSM gap (not real "no signals") |
| **KOL_B** | **70** | **36** | **densest in fleet: 16–22 sig/km on JL Nehru / SP Mukherjee** — primary demo case |
| KOL_C | 0 | 0 | half-correct: EM Bypass = expressway (OK), Manicktala stretch suspicious |
| DEL_AUROBINDO | 26 | 8 | per-segment density unreliable: many segments < 50 m |

## Three brittleness facts that the design must respect

1. **`signal_density_per_km` is unreliable when `road_length_meters < buffer_meters × 2 (= 100 m)`.** A
   single signal on a 9 m segment shows 220 sig/km. Per-segment density must be
   *guarded* (suppressed below 100 m) and corridor-level density must be
   computed as Σsignals / Σlength_km, not as a mean of per-segment densities.

2. **`junction_count` is effectively noise** — OSM tag `junction=*` is sparsely
   applied in Indian data. Treat **traffic_signal + crossing** as the real
   intersection-presence signal; show `junction_count` for completeness only.

3. **A node within the 50 m buffer of two adjacent segments will double-count**
   under the existing `road_signal_density` rollup, but visually it should
   render once, on the segment whose polyline it is *nearest* to. The marker
   layer therefore uses nearest-segment assignment, not buffer-set membership.
   (We do not change `road_signal_density` itself.)

## What ships in v1

### A. Strip overlay (the "toggle on the map")

**Constraint:** the existing dry-run / replay HTMLs do **not** have a
geographic map. They use the SVG corridor strip rendered by
`render_corridor_svg` in `generate_dry_runs.py` (a horizontal filmstrip of
segment bars drawn to scale). A real Leaflet/OSM map is a much larger lift and
is deferred to a follow-up spec if needed.

For v1, the "toggle on the map" is a **toggle on the SVG corridor strip**:

- Each signal node renders as a small red ▲ above its segment bar at the
  fractional position where the node falls along the segment polyline
  (offset ratio 0.0 = upstream end, 1.0 = downstream end).
- Each crossing renders as a blue ◆.
- Each junction (rare in real data) renders as an amber ●.
- All markers live in a single `<g class="signals-layer">` group.
- Above the strip, a checkbox `Show signals` toggles the group via inline JS
  that flips an attribute on the group (no external libs).
- Markers carry an SVG `<title>` tooltip showing osm_node_id and tag string.
- Default: **off**. Don't disturb the existing default visual.

The same overlay block is reused by the replay HTMLs (identical strip
component) and is rendered when the data is present, gracefully absent
otherwise.

### B. Per-segment annotation in structured output and dry-run tables

In `v2_1_validation_structured.json`, add a new top-level per-corridor block
keyed by `road_id`:

```json
"signals": {
  "<road_id>": {
    "signal_count": 16,
    "crossing_count": 0,
    "junction_count": 0,
    "length_m": 734,
    "signals_per_km_guarded": 21.80,   // null when length_m < 100
    "nodes": [
      {"osm_node_id": 249350111, "lat": 22.539, "lon": 88.345,
       "node_type": "traffic_signal", "offset_ratio": 0.31}
    ]
  }
}
```

In the dry-run HTML, the existing per-segment Stage 1 table gains two columns:

- `signals` — raw count (always honest)
- `density` — `signals_per_km_guarded` formatted as `12.3 sig/km`, or `—` when
  the segment is too short to trust.

In the verdict-line text in `v2_1_validation_report.txt` and the report
section of the dry-run HTML, append a tag to each ACTIVE_BOTTLENECK /
SLOW_LINK / QUEUE_VICTIM line:

```
S05  ACTIVE_BOTTLENECK  (PM peak)  · 16 signals/km · signal-dominated
S03  ACTIVE_BOTTLENECK  (AM peak)  · 0 signals/km  · capacity-limited
```

Tag rule: `signal-dominated` if `signals_per_km_guarded ≥ 4`,
`capacity-limited` if `signals_per_km_guarded ≤ 0.5`, omitted otherwise. Tag
omitted entirely when density is unguarded (short segment).

### C. Corridor-level density rollup

Single line printed at the top of every report (HTML + plain text), right
under the corridor name:

```
Σsignals=70  ·  Σcrossings=36  ·  Σjunctions=0  ·  corridor density = 13.3 sig/km
```

Corridor density = Σsignal_count / (Σlength_m / 1000). Honest cross-corridor
metric; immune to short-segment blow-up. Becomes the headline number for any
"how signal-heavy is this corridor" comparison.

## Architecture

User picked snapshot mode (option i): the v2.1 runner pulls signal data once
per run and embeds it into the structured JSON + HTML artifacts. No live DB
calls at HTML render time.

```
+----------------------+        +------------------------+
| validation_corridors |        | raw.road_signal_density|
| .json (89 segments)  |        | raw.osm_overpass_node  |
+----------+-----------+        +------------+-----------+
           |                                 |
           v                                 v
     +------------------------------------------+
     |  data/v2_1/pull_signals.py  (new)        |
     |  - per road_id: counts + length          |
     |  - per node within 50m buffer:           |
     |     lat, lon, type, nearest-seg ratio    |
     +------------------+-----------------------+
                        |
                        v
        data/v2_1/signals/all_signals.json
        (mirrors all_onsets.json shape)
                        |
                        v
+----------------------------------+
|  data/v2_1/run_validation.py     |
|  - loads all_signals.json        |
|  - attaches `signals` block to   |
|    each corridor's structured row|
+----+------------------------+----+
     |                        |
     v                        v
+-----------------+   +---------------------+
| validation      |   | generate_dry_runs.py|
| _structured.json|   | predict/replays     |
+-----------------+   +----------+----------+
                                 |
                                 v
                  per-corridor HTML with:
                   - corridor density header
                   - SVG strip + signals layer toggle
                   - per-segment density column
                   - density-tagged verdict lines
```

Drop-in points:

- **New script:** `data/v2_1/pull_signals.py` — mirrors `pull_onsets.py`
  semantics: `--corridor`, `--max-age`, idempotent, snapshots to
  `data/v2_1/signals/all_signals.json`.
- **`run_validation.py`:** load `all_signals.json`, attach `signals` block to
  the per-corridor structured object before writing `v2_1_validation_structured.json`.
- **`generate_dry_runs.py`:**
  - Extend `render_corridor_svg(chain, verdicts, freeflow, signals=None)` —
    when `signals` is present, append a toggleable `<g class="signals-layer">`
    group above the bars. Add the `Show signals` checkbox + 4-line inline JS
    above the SVG. No-op when `signals=None`.
  - Extend `render_stage1_table(...)` with two columns (signals, density).
  - Extend the verdict-summary section to append the density tag.
  - Add the corridor-density header line.
- **`predict/replay_*` generator:** same SVG-strip extension. Reuses
  `all_signals.json`.

## Edge cases

- **Segment not in `road_signal_density`:** treated as zeros; warn count at
  run start (expected to be 0).
- **Segment shorter than 2× buffer (i.e., < 100 m):** `signals_per_km_guarded = null`,
  density column shows `—`, tag omitted, but markers still render in the
  strip overlay.
- **Node within buffer of two adjacent segments:** assigned to the segment
  whose polyline is *nearest*. Computed in `pull_signals.py` via PostGIS
  `ST_Distance(geom, segment_geom)`.
- **No node-level lat/lon for some segments:** strip overlay simply has no
  markers for that segment; counts and density still render from the
  pre-aggregated table.
- **Stale OSM dump:** `osm_overpass_dump` has multiple generations. Use the
  latest `id` per city. Future-proof by surfacing dump-id in the
  `all_signals.json` provenance block.

## Out of scope (future spec rounds)

- Free-flow sanity check (Stage 1 warning when discovered FF is implausible
  given signal density).
- Bertini disambiguation (does the bottleneck side of a fired triple sit on a
  signal-cluster?).
- LWR backward-shockwave band conditioning on signal density.
- Junction-anchored re-segmentation of long multi-signal segments.
- Probe-derived cycle length estimation per segment.
- A real geographic Leaflet/OSM map panel in the HTMLs (vs SVG strip overlay).
- Cross-city density-normalised comparisons in a fleet-wide report.

## Acceptance

- `data/v2_1/signals/all_signals.json` exists, contains `signals` and per-node
  `nodes` arrays for all 89 v2.1 segments with provenance `dump_id` per city.
- Re-running the v2.1 validation pipeline produces an updated
  `v2_1_validation_structured.json` with the new `signals` block per corridor.
- The 7 weekday and 7 weekend dry-run HTMLs render without errors and show:
  - corridor-density header line
  - working `Show signals` checkbox on the SVG strip
  - signals + density columns in the Stage 1 table
  - density-tagged verdict lines
- KOL_B's strip visibly shows clustered signal markers on S01/S02/S05/S06.
- DEL_AUROBINDO's per-segment density column shows `—` for sub-100m segments
  but corridor-level density renders cleanly.
- Existing tests (if any) still pass; if none, manual visual verification on
  KOL_B and DEL_AUROBINDO is the acceptance bar.
