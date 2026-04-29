# Signal-density overlay on TraffiCure `/corridor-diagnostics` (v1) — design

## Goal

Surface OSM signal/crossing/junction structure on the live TraffiCure
frontend at `/corridor-diagnostics` so that an engineer reading a verdict
on the map can see whether a slow segment is *signal-dominated* or
*capacity-limited*.

No new physics yet — just structural context, rendered as a deck.gl layer
on the same map that already shows the corridor's verdict-coloured paths,
plus per-segment + corridor-level annotation in the right panel.

This is **step A + B + C** of the broader signal-aware diagnostics roadmap
(brainstormed 2026-04-29). Free-flow sanity check, Bertini disambiguation,
LWR band conditioning, junction-anchored splitting, and probe-derived
cycle-length estimation are out of scope; each is its own future round.

## Two repos, one feature

This feature spans both repos:

- **Phase 4 / Corridor Diagnostics** (`/Users/lepton/Documents/Phase 4 - Corridor Diagnostics`):
  no production-code changes. The OSM data already lands in
  `raw.osm_overpass_node` + `raw.road_signal_density` on dev DB
  `192.168.2.97`. This spec lives here for documentation continuity (this
  is the algorithm/data home of the diagnostic).
- **TraffiCure frontend** (`/Users/lepton/Desktop/trafficure`): all
  implementation lands here — one new API route, one data hook, one
  deck.gl layer, a toggle in the existing map legend, and right-panel
  annotation.

## Data situation (verified against dev DB `192.168.2.97`, schema `raw`)

- `raw.osm_overpass_node` — `lat`, `lon`, `node_type ∈ {traffic_signal,
  junction, crossing}`, `tags jsonb`, PostGIS `geom`. Loaded for Pune
  (539 nodes), Delhi (1529), Kolkata (81), Hyderabad (277), and a few
  smaller cities. Two dump generations exist; consume the latest by
  `osm_overpass_dump.id` per `city_id`.
- `raw.road_signal_density` — pre-aggregated per `road_id`: `signal_count`,
  `junction_count`, `crossing_count`, `total_node_count`,
  `signal_density_per_km`, `buffer_meters` (50 m). Already populated for
  all 89 v2.1 validation segments (verified 89/89 join coverage).

Coverage signature on the 7 validation corridors:

| Corridor | Σsignals | Σcrossings | Notes |
|---|---|---|---|
| PUNE_A | 0 | 0 | quiet peri-urban (correct) |
| PUNE_B | 11 | 0 | clusters on urban middle (S04–S07) |
| PUNE_C | 3 | 0 | only S08 has any |
| KOL_A | 0 | 0 | suspected OSM gap, not real "no signals" |
| **KOL_B** | **70** | **36** | **densest in fleet — primary demo** |
| KOL_C | 0 | 0 | half-correct: EM Bypass = expressway OK; Manicktala stretch suspicious |
| DEL_AUROBINDO | 26 | 8 | per-segment density unreliable: many segments < 50 m |

## Three brittleness facts the design must respect

1. **`signal_density_per_km` is unreliable when `length_m < buffer_meters × 2 (= 100 m)`.**
   A single signal on a 9 m segment shows 220 sig/km. Per-segment density
   must be *guarded* (suppressed below 100 m) and corridor-level density
   must be computed as Σsignals / Σlength_km, not as a mean of per-segment
   densities.
2. **`junction_count` is effectively noise** — OSM tag `junction=*` is
   sparsely applied in Indian data. Treat **traffic_signal + crossing**
   as the real intersection-presence signal; show `junction_count` for
   completeness only.
3. **A node within the 50 m buffer of two adjacent segments will
   double-count** under `road_signal_density`'s rollup, but visually it
   should render once, on the segment whose polyline is *nearest*. The
   API computes nearest-segment assignment; the rollup table itself is
   not changed by this spec.

## Architecture

The frontend already has the pattern we need: `CorridorDiagnosticsMapLayer`
fetches segment geometry, emits a payload to `CorridorDiagnosticsOverlayLayer`
via `rio.events`, which renders deck.gl `MapLayer` (paths) + `IconLayer`
(verdict badges). The signal overlay copies this pattern.

```
Backend (Postgres, schema raw)
  raw.osm_overpass_node, raw.osm_overpass_dump,
  raw.road_signal_density, public.road_segment
                │
                ▼
NEW  src/routes/api/corridor-diagnostics/signals.tsx
     GET /api/corridor-diagnostics/signals?ids=<csv road_ids>
     - per road_id: counts + length + signals_per_km_guarded
     - per node within 50m: lat, lon, node_type, nearest road_id, offset_ratio
                │
                ▼
NEW  src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.ts
     useCorridorSignals(segmentIds) — TanStack Query hook
                │
                ▼
NEW  src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer.tsx
     - reads enabled flag from useCorridorUrlState
     - emits "corridor-diagnostics.signals.update" / ".clear" via rio.events
                │
                ▼
NEW  Renderer extension inside corridor-diagnostics-overlay-layer.tsx
     - subscribes to the new event
     - renders deck.gl IconLayer (red ▲ signal, blue ◆ crossing,
       amber ● junction), order=720 (above verdict badges)

UI hooks (existing files, edits only):
- map-overlay/legend.tsx — adds a "Signals (N)" toggle row
- right-panel/kpi-grid.tsx — adds corridor-level density chip
- right-panel/segment-chain.tsx — adds signals + density column
- right-panel/verdict-tab.tsx — adds density tag to verdict line
- data/use-corridor-url-state.ts — adds `signals` query-param state
```

## What ships in v1

### A. Map overlay — toggleable signals layer on the live map

- New deck.gl `IconLayer` mounted alongside the existing
  verdict-paths/badges, rendering at `order=720` (above the badges so a
  signal node co-located with a verdict badge is still visible at the
  edge of the badge).
- Three icons in a single icon atlas:
  - **Traffic signal** — red filled triangle, white halo
  - **Crossing** — blue filled diamond, white halo
  - **Junction** — amber filled circle (rare in real data; included for
    completeness)
- Halo flips to dark grey on light basemaps, mirroring the existing
  pattern in `corridor-diagnostics-overlay-layer.tsx`.
- Hover → tooltip with `osm_node_id` + `node_type` + tag string. Picking
  on the same `pickable: true` channel as existing layers.
- Default state: **off**. Toggle is OFF on first visit; persists per
  user via the same URL state pattern (`?signals=on`) as the slice +
  corridor selectors.

### B. Toggle UI in the existing legend

- Extend `map-overlay/legend.tsx` with a single new row inside the
  expanded legend panel: **"Signals (N)"** where N = the loaded
  corridor's `Σsignals + Σcrossings`. Checkbox left of the count.
- In the collapsed (pill) state, add a small icon-only toggle to the
  right of the verdict swatches — clicking it flips the layer without
  expanding the legend. Tooltip: "Show / hide signals & crossings".
- The toggle reads/writes the `signals` URL param via
  `use-corridor-url-state` so the state is shareable + bookmarkable
  alongside corridor + slice.

### C. Right-panel annotation (per-segment + corridor-level)

- **Corridor-level chip** in the right-panel KPI grid, immediately under
  the corridor name:
  ```
  Σ signals 70  ·  Σ crossings 36  ·  density 13.3 sig/km
  ```
  Density = Σsignal_count / (Σlength_m / 1000). Renders `—` when all
  segments are zero.
- **Per-segment column** in the segments tab / segment-chain:
  - new column `signals` — raw count, always honest
  - new column `density` — `signals_per_km_guarded` formatted as
    `12.3 sig/km`, or `—` when length_m < 100
- **Density tag in the verdict tab** for ACTIVE_BOTTLENECK / SLOW_LINK /
  HEAD_BOTTLENECK / QUEUE_VICTIM lines:
  ```
  S05  ACTIVE BOTTLENECK   PM peak   · 16 sig/km · signal-dominated
  S03  ACTIVE BOTTLENECK   AM peak   · 0 sig/km  · capacity-limited
  S07  SLOW LINK           all-day   · 2.1 sig/km
  ```
  Rule: `signal-dominated` if `signals_per_km_guarded ≥ 4`,
  `capacity-limited` if `signals_per_km_guarded ≤ 0.5`, density-only when
  in between, full omission when density is unguarded (short segment).

## API contract

`GET /api/corridor-diagnostics/signals?ids=<comma-separated road_ids>`

Response (200):

```json
{
  "rollups": {
    "<road_id>": {
      "road_id": "ccae34ae-…",
      "signal_count": 16,
      "crossing_count": 0,
      "junction_count": 0,
      "length_m": 734,
      "signals_per_km_guarded": 21.80
    }
  },
  "nodes": [
    {
      "osm_node_id": 249350111,
      "lat": 22.539,
      "lon": 88.345,
      "node_type": "traffic_signal",
      "nearest_road_id": "ccae34ae-…",
      "offset_ratio": 0.31,
      "tags": { "highway": "traffic_signals" }
    }
  ],
  "missing": []
}
```

Server SQL (single round-trip, two CTEs):

```sql
WITH seg AS (
  SELECT road_id::text, road_length_meters::int AS length_m, geometry
    FROM road_segment
   WHERE road_id::text = ANY($1::text[])
),
node AS (
  SELECT n.osm_node_id, n.lat, n.lon, n.node_type, n.tags, n.geom,
         s.road_id, s.length_m, s.geometry AS seg_geom,
         ST_Distance(n.geom::geography, s.geometry::geography) AS d_m
    FROM seg s
    JOIN raw.osm_overpass_node n
      ON ST_DWithin(n.geom::geography, s.geometry::geography, 50)
)
-- pick nearest segment per node, project to compute offset_ratio
SELECT *
  FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY osm_node_id ORDER BY d_m ASC) AS rn,
           ST_LineLocatePoint(seg_geom, ST_ClosestPoint(seg_geom, geom)) AS offset_ratio
      FROM node
  ) t
 WHERE rn = 1;
```

Rollups come from the same set of nodes (group + count by `road_id`,
`node_type`); we deliberately don't read `raw.road_signal_density`
because its 50 m buffer membership is set-membership not nearest-segment,
which would over-count border nodes by ~5–10%.

`signals_per_km_guarded`: `null` if `length_m < 100`, else
`signal_count * 1000.0 / length_m`.

## URL state

Extend `use-corridor-url-state.ts` to read/write a `signals` query param:
`?signals=on` (default off). Persists across refresh + sharing. Implemented
with the same `useSearchParams` pattern as `corridor` and `slice`.

## Edge cases

- **Segment not loaded yet:** layer renders nothing for that segment; no
  errors. Hook stays in `enabled: ids.length > 0` mode.
- **Segment shorter than 2× buffer (< 100 m):** `signals_per_km_guarded`
  is `null`; right-panel density column shows `—`; verdict-tag is
  omitted; markers still render on the map.
- **Node within 50 m of two adjacent segments:** assigned to the segment
  whose polyline is nearest via `ST_Distance` + `ROW_NUMBER()`. Ties
  resolve to the segment with the lower `osm_node_id %` of road_id —
  deterministic, but ties are vanishingly rare given float precision.
- **No signals for the whole corridor:** legend toggle still renders
  showing "Signals (0)"; clicking it is a no-op visually but persists
  the URL param. Right-panel chip shows `Σ signals 0  · density —`.
- **Stale OSM dump:** the API joins the latest `osm_overpass_dump`
  generation per city implicitly (since `osm_overpass_node.dump_id`
  points at it); a future spec can add a "data as of {date}" caption
  if needed. Out of scope here.
- **Performance:** corridors are ≤41 segments × ≤1500 nodes/city; the
  CTE finishes in well under 200 ms even on the densest Delhi join. No
  pagination, no caching beyond TanStack Query's default `staleTime`.

## File list (TraffiCure frontend)

**New:**

- `src/routes/api/corridor-diagnostics/signals.tsx`
- `src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.ts`
- `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer.tsx`
- `src/modules/trafficure.corridor-diagnostics/data/api.ts` — add
  `fetchCorridorSignals(ids)`
- `src/modules/trafficure.corridor-diagnostics/types/api.ts` — add
  `CorridorSignalsResponse`, `SignalNode`, `SignalRollup`

**Edited:**

- `src/routes/(app)/(dashboard)/corridor-diagnostics/layout.tsx` — mount
  `<CorridorDiagnosticsSignalsLayer mapId="main" />` next to the existing
  `<CorridorDiagnosticsMapLayer />`
- `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx`
  — subscribe to the new event + render the new IconLayer
- `src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx`
  — add toggle row + collapsed-pill toggle
- `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts`
  — add `signals` param
- `src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx`
  — corridor-level density chip
- `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`
  (or the `segments-tab.tsx`) — per-segment signals + density columns
- `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx`
  — density tag on verdict lines

## Out of scope (future spec rounds)

- Free-flow sanity check (Stage 1 warning when discovered FF is
  implausible given signal density)
- Bertini disambiguation (does the bottleneck side of a fired triple sit
  on a signal-cluster?)
- LWR backward-shockwave band conditioning on signal density
- Junction-anchored re-segmentation of long multi-signal segments
- Probe-derived cycle-length estimation per segment
- Pulling fresher OSM dumps / DAG-ifying ingestion
- Same overlay on the static dry-run / replay HTMLs (explicitly
  descoped — those don't have a real map)

## Acceptance

- Backend: `GET /api/corridor-diagnostics/signals?ids=<ids>` returns the
  documented shape; works on KOL_B (returns ≥70 signal nodes) and
  PUNE_A (returns 0 nodes, empty `nodes`, all-zero `rollups`).
- Map: the toggle in the legend turns the signal layer on/off; the URL
  param round-trips; on KOL_B the densest stretch shows ~16–22 visible
  red triangles per km along the path; on PUNE_A the layer is empty;
  hover tooltips show node_type + tags.
- Right panel: corridor density chip renders for all 7 validation
  corridors; per-segment density column shows `—` for any segment
  shorter than 100 m on DEL_AUROBINDO; density tag appears on
  ACTIVE_BOTTLENECK lines for KOL_B and is omitted on PUNE_A.
- Map fits + paths still render unchanged when the layer is off; no
  regression to existing verdict overlay behaviour.
