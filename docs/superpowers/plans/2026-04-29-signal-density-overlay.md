# Signal-density overlay on TraffiCure `/corridor-diagnostics` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable signals/crossings/junctions overlay to TraffiCure's `/corridor-diagnostics` map, plus per-segment + corridor-level signal-density annotation in the right panel, sourced from `raw.osm_overpass_node` on the diagnostics Postgres.

**Architecture:** New server route that runs a single PostGIS CTE to attach the nearest road segment to each node within 50 m. A TanStack Query hook fetches the result. A new `CorridorDiagnosticsSignalsLayer` component subscribes to URL state and emits a payload via `rio.events`; the existing `CorridorDiagnosticsOverlayLayer` renders three icons through a deck.gl `IconLayer`. Legend toggle drives URL state. Right-panel components consume the rollups for inline annotation.

**Tech Stack:** TypeScript, React, react-router (`useSearchParams`), TanStack Query, vinxi/SolidStart server routes, `pg` Pool (`diagnosticsDB`), deck.gl `IconLayer` via `@rio.js/maps-ui`, `rio.events` event bus, Tailwind CSS, vitest for unit tests.

**Repo target:** `/Users/lepton/Desktop/trafficure` (TraffiCure frontend). The diagnostics Postgres at `192.168.2.97` already holds the data — no Phase 4 code changes.

**Spec:** `docs/superpowers/specs/2026-04-29-signal-density-overlay-design.md`

---

## File structure

**New files (TraffiCure):**

- `src/routes/api/corridor-diagnostics/signals.tsx` — GET endpoint
- `src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.ts` — React Query hook
- `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer.tsx` — payload emitter
- `src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.test.ts` — hook tests are *not* added (would require a fake fetch / RQ wrapper); URL-state tests cover the toggle path
- Alongside each above where useful

**Edited files (TraffiCure):**

- `src/modules/trafficure.corridor-diagnostics/types/api.ts` — add types
- `src/modules/trafficure.corridor-diagnostics/data/api.ts` — add `fetchCorridorSignals`
- `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts` — add `signals` boolean
- `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts` — extend tests
- `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx` — render IconLayer for signals
- `src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx` — toggle UI
- `src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx` — accept signal rollup props
- `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx` — signals/density columns
- `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx` — wire signal data
- `src/routes/(app)/(dashboard)/corridor-diagnostics/layout.tsx` — mount `<CorridorDiagnosticsSignalsLayer />`

---

## Task 1: Add types for the signals API response

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/types/api.ts`

- [ ] **Step 1: Add types**

Append to `src/modules/trafficure.corridor-diagnostics/types/api.ts`:

```ts
export type SignalNodeType = "traffic_signal" | "crossing" | "junction"

export interface SignalNode {
  osm_node_id: number
  lat: number
  lon: number
  node_type: SignalNodeType
  nearest_road_id: string
  offset_ratio: number
  tags: Record<string, string>
}

export interface SignalRollup {
  road_id: string
  signal_count: number
  crossing_count: number
  junction_count: number
  length_m: number
  signals_per_km_guarded: number | null
}

export interface CorridorSignalsResponse {
  rollups: Record<string, SignalRollup>
  nodes: SignalNode[]
  missing: string[]
}
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/types/api.ts
git commit -m "feat(corridor-diagnostics): add SignalNode/SignalRollup/CorridorSignalsResponse types"
```

---

## Task 2: Add `fetchCorridorSignals` API helper

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/data/api.ts`

- [ ] **Step 1: Add the helper**

Edit `src/modules/trafficure.corridor-diagnostics/data/api.ts`. Add `CorridorSignalsResponse` to the existing import block, then append before the file's end:

```ts
export async function fetchCorridorSignals(
  roadIds: string[],
): Promise<CorridorSignalsResponse> {
  if (roadIds.length === 0) return { rollups: {}, nodes: [], missing: [] }
  const ids = encodeURIComponent(roadIds.join(","))
  return getJSON(`/api/corridor-diagnostics/signals?ids=${ids}`)
}
```

The full updated import block at the top of the file should be:

```ts
import type {
  ListCorridorsResponse,
  RunRequestBody,
  RunResponse,
  SegmentsResponse,
  JobLookupResponse,
  CorridorSignalsResponse,
} from "../types/api"
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/data/api.ts
git commit -m "feat(corridor-diagnostics): add fetchCorridorSignals client helper"
```

---

## Task 3: Server route — GET /api/corridor-diagnostics/signals

**Files:**
- Create: `src/routes/api/corridor-diagnostics/signals.tsx`

- [ ] **Step 1: Create the route file**

Create `src/routes/api/corridor-diagnostics/signals.tsx`:

```tsx
import { HTTPEvent, toWebRequest } from "vinxi/http"
import { diagnosticsDB } from "~/src/lib/corridor-diagnostics-db"

const BUFFER_M = 50
const MIN_LEN_FOR_DENSITY = 100

type NodeRow = {
  osm_node_id: string
  lat: number
  lon: number
  node_type: string
  nearest_road_id: string
  offset_ratio: number
  tags: Record<string, string> | null
  length_m: number
}

export async function GET(event: HTTPEvent) {
  try {
    const request = toWebRequest(event)
    const url = new URL(request.url)
    const idsParam = url.searchParams.get("ids")
    if (!idsParam) {
      return new Response(JSON.stringify({ error: "missing ids query param" }), {
        status: 400, headers: { "Content-Type": "application/json" },
      })
    }
    const ids = idsParam.split(",").map((s) => s.trim()).filter(Boolean)
    if (ids.length === 0) {
      return new Response(JSON.stringify({ rollups: {}, nodes: [], missing: [] }), {
        status: 200, headers: { "Content-Type": "application/json" },
      })
    }

    // One round-trip:
    //   seg     — corridor segments + lengths + geometry
    //   node    — signal/crossing/junction nodes within BUFFER_M of any seg
    //   ranked  — for each node, pick the segment with the smallest distance
    //   nearest — keep rn=1 row + project onto seg to compute offset_ratio
    //
    // We deliberately don't read raw.road_signal_density: its 50 m buffer is
    // set-membership and double-counts boundary nodes, while we want
    // nearest-segment assignment for the visual layer.
    const sql = `
      WITH seg AS (
        SELECT road_id::text AS road_id,
               road_length_meters::int AS length_m,
               geometry
          FROM road_segment
         WHERE road_id::text = ANY($1::text[])
      ),
      node AS (
        SELECT n.osm_node_id::text AS osm_node_id,
               n.lat, n.lon,
               n.node_type,
               n.tags,
               n.geom,
               s.road_id,
               s.length_m,
               s.geometry AS seg_geom,
               ST_Distance(n.geom::geography, s.geometry::geography) AS d_m
          FROM seg s
          JOIN raw.osm_overpass_node n
            ON ST_DWithin(n.geom::geography, s.geometry::geography, $2::int)
      ),
      ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                 PARTITION BY osm_node_id ORDER BY d_m ASC, road_id ASC
               ) AS rn
          FROM node
      )
      SELECT osm_node_id,
             lat, lon, node_type, tags,
             road_id AS nearest_road_id,
             length_m,
             ST_LineLocatePoint(seg_geom, ST_ClosestPoint(seg_geom, geom))::float AS offset_ratio
        FROM ranked
       WHERE rn = 1;
    `
    const result = await diagnosticsDB().query<NodeRow>(sql, [ids, BUFFER_M])

    // Build rollups from the ranked node set so per-segment counts match what
    // the layer renders (no buffer double-count).
    const rollups: Record<string, {
      road_id: string
      signal_count: number
      crossing_count: number
      junction_count: number
      length_m: number
      signals_per_km_guarded: number | null
    }> = {}
    for (const id of ids) {
      rollups[id] = {
        road_id: id,
        signal_count: 0,
        crossing_count: 0,
        junction_count: 0,
        length_m: 0,
        signals_per_km_guarded: null,
      }
    }

    const nodes = result.rows.map((r) => {
      const rid = r.nearest_road_id
      const roll = rollups[rid]
      if (roll) {
        roll.length_m = Number(r.length_m)
        if (r.node_type === "traffic_signal") roll.signal_count += 1
        else if (r.node_type === "crossing") roll.crossing_count += 1
        else if (r.node_type === "junction") roll.junction_count += 1
      }
      return {
        osm_node_id: Number(r.osm_node_id),
        lat: Number(r.lat),
        lon: Number(r.lon),
        node_type: r.node_type as "traffic_signal" | "crossing" | "junction",
        nearest_road_id: rid,
        offset_ratio: Number(r.offset_ratio),
        tags: r.tags ?? {},
      }
    })

    // Backfill length_m for segments that had zero matching nodes (so the
    // density chip can render even when signals=0).
    if (Object.values(rollups).some((r) => r.length_m === 0)) {
      const lenRes = await diagnosticsDB().query<{ road_id: string; length_m: number }>(
        `SELECT road_id::text AS road_id, road_length_meters::int AS length_m
           FROM road_segment WHERE road_id::text = ANY($1::text[])`,
        [ids],
      )
      for (const r of lenRes.rows) {
        const roll = rollups[r.road_id]
        if (roll && roll.length_m === 0) roll.length_m = Number(r.length_m)
      }
    }

    // Compute guarded density.
    for (const r of Object.values(rollups)) {
      r.signals_per_km_guarded =
        r.length_m >= MIN_LEN_FOR_DENSITY
          ? Math.round((r.signal_count * 1000.0 / r.length_m) * 100) / 100
          : null
    }

    const missing = ids.filter((id) => rollups[id]?.length_m === 0)
    return new Response(JSON.stringify({ rollups, nodes, missing }), {
      status: 200, headers: { "Content-Type": "application/json" },
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.error("[corridor-diagnostics/signals GET]", message)
    return new Response(JSON.stringify({ error: message }), {
      status: 500, headers: { "Content-Type": "application/json" },
    })
  }
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Smoke test the route**

Start the dev server:

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

In a second terminal, hit the endpoint with KOL_B's first segment (you can grab it from `data/v2_1/validation_corridors.json` — KOL_B chain[0].road_id is `ccae34ae-68f2-461b-ad35-e22ffed0cbca`):

```bash
curl -s 'http://localhost:3000/api/corridor-diagnostics/signals?ids=ccae34ae-68f2-461b-ad35-e22ffed0cbca' | jq '.rollups'
```

Expected: `signal_count: 10`, `crossing_count: 12`, `length_m: 1118`, `signals_per_km_guarded` ≈ `8.95`. (Numbers come from the verified DB pull.)

Then test PUNE_A's first segment for the empty case:

```bash
curl -s 'http://localhost:3000/api/corridor-diagnostics/signals?ids=53b8c7b4-c353-488c-992e-04298c2671b3' | jq '{nodes:(.nodes|length), rollup:.rollups}'
```

Expected: `nodes: 0`, `signal_count: 0`, `signals_per_km_guarded: 0` (494 m segment, 0 signals → 0/km, density is computed since length ≥ 100 m).

If empty: confirm the route is reachable (`curl -i` for status), then re-check `POSTGRES_HOST` env points at `192.168.2.97`.

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/routes/api/corridor-diagnostics/signals.tsx
git commit -m "feat(corridor-diagnostics): GET /api/corridor-diagnostics/signals route"
```

---

## Task 4: TanStack Query hook for signals

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.ts`

- [ ] **Step 1: Create the hook**

Create `src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.ts`:

```ts
import { useQuery } from "@tanstack/react-query"
import { fetchCorridorSignals } from "./api"

/**
 * Fetches signal/crossing/junction nodes (within 50 m, nearest-segment
 * attributed) for the given segment ids, plus per-segment rollups.
 *
 * Mirrors useSegmentsGeometry's caching shape so it lights up alongside the
 * existing geometry fetch when a corridor is loaded.
 */
export function useCorridorSignals(roadIds: string[] | undefined) {
  const ids = roadIds ?? []
  const key = ids.join(",")
  return useQuery({
    queryKey: ["corridor-diagnostics", "signals", key],
    queryFn: () => fetchCorridorSignals(ids),
    enabled: ids.length > 0,
    staleTime: 60_000,
  })
}
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/data/use-corridor-signals-query.ts
git commit -m "feat(corridor-diagnostics): useCorridorSignals query hook"
```

---

## Task 5: Add `signals` URL-state param

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts`
- Modify: `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts`

- [ ] **Step 1: Write failing tests**

Edit `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts`. Append to the `parseCorridorParams` describe block:

```ts
  it("defaults signals to false when missing", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A")).signals).toBe(false)
  })
  it("treats signals=on as true", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A&signals=on")).signals).toBe(true)
  })
  it("treats signals=off (or anything else) as false", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A&signals=garbage")).signals).toBe(false)
  })
```

And to the `buildCorridorSearch` describe block:

```ts
  it("emits signals=on only when toggled", () => {
    expect(buildCorridorSearch({ corridor: "PUNE_A", slice: "weekday", segment: null, signals: true }))
      .toBe("corridor=PUNE_A&slice=weekday&signals=on")
    expect(buildCorridorSearch({ corridor: "PUNE_A", slice: "weekday", segment: null, signals: false }))
      .toBe("corridor=PUNE_A&slice=weekday")
  })
```

The existing tests build `CorridorParams` literals without `signals` — they will now fail to typecheck once we add the field.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec vitest run src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts
```

Expected: typecheck failures plus test failures (no `signals` field).

- [ ] **Step 3: Update the parser/serializer**

Edit `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts`. Add `signals: boolean` to `CorridorParams`, parse it, serialize it, expose a setter:

```ts
import { useCallback } from "react"
import { useSearchParams } from "react-router"
import type { Slice } from "../types/corridor-diagnostics"

export interface CorridorParams {
  corridor: string | null
  slice: Slice
  segment: string | null
  /** Toggles the signals/crossings/junctions overlay layer. */
  signals: boolean
}

export function parseCorridorParams(p: URLSearchParams): CorridorParams {
  const corridor = p.get("corridor") || null
  const sliceRaw = p.get("slice")
  const slice: Slice = sliceRaw === "weekend" ? "weekend" : "weekday"
  const segment = p.get("segment") || null
  const signals = p.get("signals") === "on"
  return { corridor, slice, segment, signals }
}

export function buildCorridorSearch(s: CorridorParams): string {
  if (!s.corridor) return ""
  const out = new URLSearchParams()
  out.set("corridor", s.corridor)
  out.set("slice", s.slice)
  if (s.signals) out.set("signals", "on")
  return out.toString()
}

export function useCorridorUrlState() {
  const [params, setParams] = useSearchParams()
  const value = parseCorridorParams(params)

  const setCorridor = useCallback(
    (corridor: string | null) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        if (corridor) next.set("corridor", corridor)
        else { next.delete("corridor"); next.delete("segment") }
        return next
      }, { replace: true })
    },
    [setParams],
  )

  const setSlice = useCallback(
    (s: Slice) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set("slice", s)
        return next
      }, { replace: true })
    },
    [setParams],
  )

  const setSignals = useCallback(
    (on: boolean) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        if (on) next.set("signals", "on")
        else next.delete("signals")
        return next
      }, { replace: true })
    },
    [setParams],
  )

  return { ...value, setCorridor, setSlice, setSignals }
}
```

- [ ] **Step 4: Update existing test fixtures**

In `use-corridor-url-state.test.ts`, all existing `parseCorridorParams` `toEqual` calls and `buildCorridorSearch` literals must include `signals: false`. Update each `toEqual({...})` block to include `signals: false`, and update the `buildCorridorSearch` `signals: false` cases. Specifically:

```ts
  it("defaults slice to weekday when missing", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A"))).toEqual({
      corridor: "PUNE_A", slice: "weekday", segment: null, signals: false,
    })
  })
  it("accepts weekend slice", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A&slice=weekend"))).toEqual({
      corridor: "PUNE_A", slice: "weekend", segment: null, signals: false,
    })
  })
```

For `buildCorridorSearch`:

```ts
  it("emits corridor + slice in stable order", () => {
    expect(buildCorridorSearch({ corridor: "PUNE_A", slice: "weekday", segment: null, signals: false }))
      .toBe("corridor=PUNE_A&slice=weekday")
  })
  it("never serializes segment even when set on the input (round-2 dropped focus)", () => {
    expect(buildCorridorSearch({ corridor: "PUNE_A", slice: "weekend", segment: "abc", signals: false }))
      .toBe("corridor=PUNE_A&slice=weekend")
  })
  it("returns empty when corridor is null", () => {
    expect(buildCorridorSearch({ corridor: null, slice: "weekday", segment: null, signals: false })).toBe("")
  })
```

- [ ] **Step 5: Run tests until green**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec vitest run src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts \
        src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts
git commit -m "feat(corridor-diagnostics): add signals URL-state param"
```

---

## Task 6: Map signals emitter component

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer.tsx`

- [ ] **Step 1: Create the component**

Create `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer.tsx`:

```tsx
import { useEffect, useMemo } from "react"
import { useRio } from "@rio.js/client"

import { useCorridorUrlState } from "../data/use-corridor-url-state"
import { useCorridorSnapshotJobId, useJobPoll } from "../data/use-job-poll-query"
import { useCorridorSignals } from "../data/use-corridor-signals-query"
import type { SignalNodeType } from "../types/api"

export type SignalSymbol = {
  id: string                 // `${osm_node_id}` — stable, picks deterministic
  position: [number, number] // [lng, lat]
  node_type: SignalNodeType
  road_id: string
  tags: Record<string, string>
}

export type SignalsOverlayPayload = {
  symbols: SignalSymbol[]
}

const EMPTY: SignalsOverlayPayload = { symbols: [] }

/**
 * Subscribes to URL state + corridor job + signals query, and emits the
 * symbol payload for the existing overlay layer to consume. Mirrors
 * CorridorDiagnosticsMapLayer's pattern but for signal/crossing/junction
 * nodes rather than verdict-tinted segments.
 */
export function CorridorDiagnosticsSignalsLayer() {
  const rio = useRio()
  const { corridor, slice, signals: enabled } = useCorridorUrlState()
  const jobId = useCorridorSnapshotJobId(corridor, slice)
  const { data: job } = useJobPoll(jobId)
  const segmentIds = useMemo(() => job?.segment_ids ?? [], [job?.segment_ids])
  const { data } = useCorridorSignals(segmentIds)

  const payload = useMemo<SignalsOverlayPayload>(() => {
    if (!enabled || !data?.nodes?.length) return EMPTY
    const symbols: SignalSymbol[] = data.nodes.map((n) => ({
      id: String(n.osm_node_id),
      position: [n.lon, n.lat],
      node_type: n.node_type,
      road_id: n.nearest_road_id,
      tags: n.tags ?? {},
    }))
    return { symbols }
  }, [enabled, data])

  useEffect(() => {
    if (payload.symbols.length === 0) {
      rio.events.emit("corridor-diagnostics.signals.clear", {})
      return
    }
    rio.events.emit("corridor-diagnostics.signals.update", payload)
  }, [rio.events, payload])

  // Clear on unmount so the overlay doesn't leak across route changes.
  useEffect(() => {
    return () => {
      rio.events.emit("corridor-diagnostics.signals.clear", {})
    }
  }, [rio.events])

  return null
}
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer.tsx
git commit -m "feat(corridor-diagnostics): CorridorDiagnosticsSignalsLayer payload emitter"
```

---

## Task 7: Render the signals IconLayer in the overlay layer

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx`

- [ ] **Step 1: Add the icon-atlas builder, subscriber, and IconLayer**

Edit `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx`. Add the following at module scope, **above** `export function CorridorDiagnosticsOverlayLayer`:

```ts
import type { SignalNodeType } from "../types/api"
import type { SignalSymbol } from "./corridor-diagnostics-signals-layer"

const SIGNAL_ICON_SIZE = 48
const SIGNAL_TYPES: readonly SignalNodeType[] = ["traffic_signal", "crossing", "junction"]
const SIGNAL_RGB: Record<SignalNodeType, [number, number, number]> = {
  traffic_signal: [185, 28, 28],   // red-700
  crossing:       [37, 99, 235],   // blue-600
  junction:       [217, 119, 6],   // amber-600
}
const SIGNAL_ICON_MAPPING = (() => {
  const out: Record<string, { x: number; y: number; width: number; height: number; mask: false; anchorY: number }> = {}
  SIGNAL_TYPES.forEach((t, i) => {
    out[t] = {
      x: i * SIGNAL_ICON_SIZE,
      y: 0,
      width: SIGNAL_ICON_SIZE,
      height: SIGNAL_ICON_SIZE,
      mask: false,
      anchorY: SIGNAL_ICON_SIZE / 2,
    }
  })
  return out
})()

function buildSignalAtlas(haloRgb: [number, number, number]): HTMLCanvasElement | null {
  if (typeof document === "undefined") return null
  const c = document.createElement("canvas")
  c.width = SIGNAL_ICON_SIZE * SIGNAL_TYPES.length
  c.height = SIGNAL_ICON_SIZE
  const ctx = c.getContext("2d")
  if (!ctx) return null
  const [hr, hg, hb] = haloRgb
  const halo = `rgb(${hr}, ${hg}, ${hb})`
  SIGNAL_TYPES.forEach((t, i) => {
    const [r, g, b] = SIGNAL_RGB[t]
    const cx = i * SIGNAL_ICON_SIZE + SIGNAL_ICON_SIZE / 2
    const cy = SIGNAL_ICON_SIZE / 2
    // Halo ring
    ctx.beginPath()
    ctx.fillStyle = halo
    ctx.arc(cx, cy, 18, 0, Math.PI * 2); ctx.fill()
    // Body
    ctx.fillStyle = `rgb(${r}, ${g}, ${b})`
    if (t === "traffic_signal") {
      // Filled triangle, point up
      ctx.beginPath()
      ctx.moveTo(cx, cy - 12)
      ctx.lineTo(cx + 11, cy + 9)
      ctx.lineTo(cx - 11, cy + 9)
      ctx.closePath(); ctx.fill()
    } else if (t === "crossing") {
      // Filled diamond
      ctx.beginPath()
      ctx.moveTo(cx, cy - 12)
      ctx.lineTo(cx + 12, cy)
      ctx.lineTo(cx, cy + 12)
      ctx.lineTo(cx - 12, cy)
      ctx.closePath(); ctx.fill()
    } else {
      // Filled circle
      ctx.beginPath()
      ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.fill()
    }
  })
  return c
}
```

Inside the existing `CorridorDiagnosticsOverlayLayer` component, add (after the existing `iconAtlas = useMemo(...)` block):

```ts
  const [signalsPayload, setSignalsPayload] = useState<{ symbols: SignalSymbol[] }>({ symbols: [] })

  useEffect(() => {
    const onUpdate = (ev: { symbols: SignalSymbol[] } | undefined) =>
      setSignalsPayload({ symbols: ev?.symbols ?? [] })
    const onClear = () => setSignalsPayload({ symbols: [] })
    rio.events.on("corridor-diagnostics.signals.update", onUpdate)
    rio.events.on("corridor-diagnostics.signals.clear", onClear)
    return () => {
      rio.events.off("corridor-diagnostics.signals.update", onUpdate)
      rio.events.off("corridor-diagnostics.signals.clear", onClear)
    }
  }, [rio.events])

  const signalAtlas = useMemo(
    () => buildSignalAtlas([haloRgba[0], haloRgba[1], haloRgba[2]]),
    [isLightBaseMap], // eslint-disable-line react-hooks/exhaustive-deps
  )
```

In the same component's returned JSX, **inside the existing `<>`** and after the badges `MapLayer`, append:

```tsx
      {signalsPayload.symbols.length > 0 && signalAtlas && (
        <MapLayer
          id="corridor-diagnostics-signals"
          order={720}
          type={IconLayer}
          data={signalsPayload.symbols}
          iconAtlas={signalAtlas}
          iconMapping={SIGNAL_ICON_MAPPING}
          getIcon={(d: SignalSymbol) => d.node_type}
          getPosition={(d: SignalSymbol) => d.position}
          getSize={22}
          sizeUnits="pixels"
          pickable
        />
      )}
```

(`useState` is already imported at the top of the file. `IconLayer` and `MapLayer` are already imported.)

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx
git commit -m "feat(corridor-diagnostics): render signals/crossings IconLayer"
```

---

## Task 8: Mount the signals emitter in the layout

**Files:**
- Modify: `src/routes/(app)/(dashboard)/corridor-diagnostics/layout.tsx`

- [ ] **Step 1: Mount the new component**

Edit the layout file. Add this import in the existing import block:

```tsx
import { CorridorDiagnosticsSignalsLayer } from "../../../../modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-signals-layer"
```

In the `CorridorDiagnosticsContent` component's returned JSX, add the new layer right after the existing `<CorridorDiagnosticsMapLayer mapId="main" />` line:

```tsx
        <CorridorDiagnosticsMapLayer mapId="main" />
        <CorridorDiagnosticsSignalsLayer />
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Smoke test in the browser**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

In a browser, open `http://localhost:3000/corridor-diagnostics?corridor=KOL_B&slice=weekday&signals=on`. Wait for the corridor to load.

Expected: red triangle markers visible along the JL Nehru Rd / SP Mukherjee Rd path. Toggle the URL param to `signals=off` (manually edit) — markers vanish on next render.

If markers don't show: open DevTools → Network → confirm `/api/corridor-diagnostics/signals?ids=…` returns ≥70 nodes; if it does but markers are still missing, check the browser console for `IconLayer` errors.

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add 'src/routes/(app)/(dashboard)/corridor-diagnostics/layout.tsx'
git commit -m "feat(corridor-diagnostics): mount signals layer alongside map layer"
```

---

## Task 9: Toggle UI in the legend

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx`

- [ ] **Step 1: Replace the legend**

Replace the entire content of `src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx` with:

```tsx
import { useEffect, useMemo, useState } from "react"

import { useCorridorUrlState } from "../../data/use-corridor-url-state"
import { useCorridorSnapshotJobId, useJobPoll } from "../../data/use-job-poll-query"
import { useCorridorSignals } from "../../data/use-corridor-signals-query"
import { VERDICTS, verdictDotHex, verdictLabel, verdictLetter } from "../verdict-style"

const STORAGE_KEY = "cd.legend.expanded"
const DESCRIPTIONS: Record<string, string> = {
  ACTIVE_BOTTLENECK: "Origin of congestion — congests recurrently here",
  HEAD_BOTTLENECK:   "Leading edge of a queue — congestion forms downstream",
  QUEUE_VICTIM:      "Queueing back from a downstream bottleneck",
  SLOW_LINK:         "Persistently slow but no clear bottleneck signature",
  FREE_FLOW:         "Clear in this slice",
  NO_DATA:           "Not enough samples / not yet run",
}

function loadExpanded(): boolean {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw === "true"
  } catch { return false }
}
function saveExpanded(v: boolean) {
  try { window.localStorage.setItem(STORAGE_KEY, v ? "true" : "false") } catch { /* ignore */ }
}

function VerdictBadge({ v, size = 18 }: { v: typeof VERDICTS[number]; size?: number }) {
  return (
    <span
      className="inline-flex items-center justify-center rounded-full text-white font-bold"
      style={{
        width: size, height: size,
        backgroundColor: verdictDotHex(v),
        boxShadow: "0 0 0 2px #fff",
        fontSize: size <= 18 ? 10 : 12,
      }}
    >
      {verdictLetter(v)}
    </span>
  )
}

function useSignalCount(): number {
  const { corridor, slice } = useCorridorUrlState()
  const jobId = useCorridorSnapshotJobId(corridor, slice)
  const { data: job } = useJobPoll(jobId)
  const segmentIds = useMemo(() => job?.segment_ids ?? [], [job?.segment_ids])
  const { data } = useCorridorSignals(segmentIds)
  if (!data?.rollups) return 0
  return Object.values(data.rollups).reduce(
    (s, r) => s + r.signal_count + r.crossing_count + r.junction_count, 0,
  )
}

export function Legend() {
  const [expanded, setExpanded] = useState(false)
  useEffect(() => { setExpanded(loadExpanded()) }, [])
  const toggle = () => setExpanded((v) => { saveExpanded(!v); return !v })

  const { signals, setSignals } = useCorridorUrlState()
  const signalCount = useSignalCount()
  const toggleSignals = () => setSignals(!signals)

  if (expanded) {
    return (
      <div className="absolute bottom-4 left-4 z-[1001] pointer-events-auto bg-white border border-scale-300 rounded-lg shadow-md max-w-xs overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-scale-300">
          <div className="text-sm font-semibold text-scale-1200">Verdict legend</div>
          <button onClick={toggle} className="text-scale-1000 hover:text-scale-1200 text-base leading-none w-5 h-5 flex items-center justify-center">×</button>
        </div>
        <div className="p-3 space-y-2 text-xs">
          {VERDICTS.map((v) => (
            <div key={v} className="flex items-start gap-2">
              <VerdictBadge v={v} size={20} />
              <div className="min-w-0">
                <div className="text-sm font-medium text-scale-1200">{verdictLabel(v)}</div>
                <div className="text-xs text-scale-1000 leading-tight">{DESCRIPTIONS[v]}</div>
              </div>
            </div>
          ))}
          <label className="flex items-center gap-2 pt-2 mt-2 border-t border-scale-300 cursor-pointer">
            <input
              type="checkbox"
              checked={signals}
              onChange={toggleSignals}
              className="w-4 h-4"
              aria-label="Toggle signals overlay"
            />
            <span className="inline-flex items-center justify-center w-5 h-5">
              <span style={{
                width: 0, height: 0,
                borderLeft: "6px solid transparent",
                borderRight: "6px solid transparent",
                borderBottom: "10px solid #b91c1c",
              }} />
            </span>
            <span className="text-sm font-medium text-scale-1200">Signals</span>
            <span className="text-xs text-scale-1000">({signalCount})</span>
          </label>
        </div>
      </div>
    )
  }

  return (
    <div className="absolute bottom-4 left-4 z-[1001] pointer-events-auto bg-white border border-scale-300 rounded-full shadow-md flex items-center gap-3 px-3 py-1.5">
      {VERDICTS.map((v) => (
        <span key={v} className="inline-flex items-center gap-1.5">
          <VerdictBadge v={v} size={16} />
          <span className="text-xs text-scale-1100">{v === "NO_DATA" ? "No data" : verdictLabel(v).split(" ")[0]}</span>
        </span>
      ))}
      <button
        onClick={toggleSignals}
        title={signals ? "Hide signals & crossings" : "Show signals & crossings"}
        className={`ml-1 inline-flex items-center justify-center w-6 h-6 rounded-full border ${signals ? "border-[#b91c1c] bg-[#fee2e2]" : "border-scale-300 hover:border-scale-1000"}`}
        aria-pressed={signals}
        aria-label="Toggle signals overlay"
      >
        <span style={{
          width: 0, height: 0,
          borderLeft: "5px solid transparent",
          borderRight: "5px solid transparent",
          borderBottom: "8px solid #b91c1c",
        }} />
      </button>
      <button onClick={toggle} title="Expand legend" className="ml-1 w-5 h-5 rounded-full border border-scale-300 text-xs text-scale-1000 hover:text-scale-1200 leading-none">?</button>
    </div>
  )
}
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Smoke test in the browser**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

Open `http://localhost:3000/corridor-diagnostics?corridor=KOL_B&slice=weekday`. The collapsed legend pill at bottom-left should show a red-triangle-button toggle. Click it: markers appear. URL updates to include `signals=on`. Click again: markers disappear.

Expand the legend (`?`): verify the new "Signals (106)" row with checkbox is visible. (KOL_B totals: 70 signals + 36 crossings + 0 junctions = 106.)

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx
git commit -m "feat(corridor-diagnostics): legend toggle for signals overlay"
```

---

## Task 10: Corridor-level density chip in `KpiGrid`

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx`
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx`

- [ ] **Step 1: Extend `KpiGridProps`**

Edit `src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx`. Add a new prop and render an optional 5th cell as a span across both columns under the existing 2×2 grid:

Replace the file's existing content with:

```tsx
export interface KpiGridProps {
  totalLengthM: number
  segmentCount: number
  freeFlowLengthM: number
  stuckLengthM: number
  bottleneckCounts: { A: number; H: number; Q: number; S: number }
  summaryVerdict: "POINT" | "SYSTEMIC"
  simultaneityPct?: number
  contiguityPct?: number
  /** Optional structural overlay — corridor-level signal-density rollup. */
  signalRollup?: {
    signalCount: number
    crossingCount: number
    junctionCount: number
    totalLengthM: number
  }
}

function fmtKm(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m} m`
}
function pct(num: number, den: number): string {
  if (den <= 0) return "—"
  return `${Math.round((num / den) * 100)}%`
}
function fmtCorridorDensity(signalCount: number, totalLengthM: number): string {
  if (totalLengthM <= 0) return "—"
  const km = totalLengthM / 1000
  const d = signalCount / km
  return `${d.toFixed(1)} sig/km`
}

export function KpiGrid(p: KpiGridProps) {
  const { A, H, Q, S } = p.bottleneckCounts
  const stuckBreakdown = [A && `A:${A}`, H && `H:${H}`, Q && `Q:${Q}`, S && `S:${S}`]
    .filter(Boolean).join(" · ") || "—"
  const verdictHl = p.summaryVerdict === "SYSTEMIC" ? "text-[#9a3412]" : "text-[#E37400]"
  const verdictSub =
    `simultaneity ${typeof p.simultaneityPct === "number" ? `${p.simultaneityPct}%` : "—"}` +
    ` · contiguity ${typeof p.contiguityPct === "number" ? `${p.contiguityPct}%` : "—"}`
  const sig = p.signalRollup
  return (
    <div className="grid grid-cols-2">
      <Cell label="Total length" value={fmtKm(p.totalLengthM)} sub={`${p.segmentCount} segments`} brR brB />
      <Cell label="Free flow"    value={fmtKm(p.freeFlowLengthM)} sub={`${pct(p.freeFlowLengthM, p.totalLengthM)} of corridor`} valueClass="text-[#1E8E3E]" brB />
      <Cell label="Stuck"        value={fmtKm(p.stuckLengthM)}    sub={stuckBreakdown} valueClass="text-[#D93025]" brR brB={!!sig} />
      <Cell label="Pattern"      value={p.summaryVerdict}         sub={verdictSub} valueClass={verdictHl} brB={!!sig} />
      {sig && (
        <div className="col-span-2 px-3 py-2 flex items-baseline gap-3 text-sm tabular-nums">
          <span className="text-scale-1000">Signals</span>
          <span className="font-semibold text-scale-1200">
            Σ {sig.signalCount}
          </span>
          <span className="text-scale-1000">·</span>
          <span className="font-semibold text-scale-1200">crossings {sig.crossingCount}</span>
          {sig.junctionCount > 0 && (
            <>
              <span className="text-scale-1000">·</span>
              <span className="font-semibold text-scale-1200">junctions {sig.junctionCount}</span>
            </>
          )}
          <span className="text-scale-1000">·</span>
          <span className="font-semibold text-scale-1200">
            density {fmtCorridorDensity(sig.signalCount, sig.totalLengthM)}
          </span>
        </div>
      )}
    </div>
  )
}

function Cell({ label, value, sub, valueClass = "text-scale-1200", brR, brB }: {
  label: string; value: string; sub: string; valueClass?: string; brR?: boolean; brB?: boolean
}) {
  return (
    <div className={`px-3 py-2.5 flex flex-col gap-0.5 ${brR ? "border-r border-scale-300" : ""} ${brB ? "border-b border-scale-300" : ""}`}>
      <span className="text-base text-scale-1000">{label}</span>
      <span className={`text-lg font-bold leading-tight tabular-nums ${valueClass}`}>{value}</span>
      <span className="text-sm text-scale-1000">{sub}</span>
    </div>
  )
}
```

- [ ] **Step 2: Wire signals data through `verdict-tab.tsx`**

Edit `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx`.

Add the import after the existing data imports:

```ts
import { useCorridorSignals } from "../../data/use-corridor-signals-query"
```

Inside the `VerdictTab` component, after the line `const { data: geo } = useSegmentsGeometry(job.segment_ids)`, add:

```ts
  const { data: signals } = useCorridorSignals(job.segment_ids)
```

In the `KpiGrid` JSX block, replace its props with:

```tsx
        <KpiGrid
          totalLengthM={totalLengthM}
          segmentCount={items.length}
          freeFlowLengthM={freeFlowLengthM}
          stuckLengthM={stuckLengthM}
          bottleneckCounts={bottleneckCounts}
          summaryVerdict={verdict.summaryVerdict}
          simultaneityPct={verdict.simultaneityPct}
          contiguityPct={verdict.contiguityPct}
          signalRollup={signals ? {
            signalCount: Object.values(signals.rollups).reduce((s, r) => s + r.signal_count, 0),
            crossingCount: Object.values(signals.rollups).reduce((s, r) => s + r.crossing_count, 0),
            junctionCount: Object.values(signals.rollups).reduce((s, r) => s + r.junction_count, 0),
            totalLengthM,
          } : undefined}
        />
```

- [ ] **Step 3: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 4: Smoke test**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

Open `http://localhost:3000/corridor-diagnostics?corridor=KOL_B&slice=weekday`. Open the right panel → Verdict tab → Corridor stats card. Expected: a row reading approximately `Signals  Σ 70  ·  crossings 36  ·  density 8.8 sig/km`.

Open `?corridor=PUNE_A&slice=weekday`. Same row should read `Σ 0  ·  crossings 0  ·  density 0.0 sig/km`.

Stop the dev server.

- [ ] **Step 5: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx \
        src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx
git commit -m "feat(corridor-diagnostics): corridor-level signal-density chip in KpiGrid"
```

---

## Task 11: Per-segment signals + density columns in `SegmentChain`

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx`

- [ ] **Step 1: Extend `SegmentChainItem` and the row render**

Edit `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`.

Update the `SegmentChainItem` interface:

```ts
export interface SegmentChainItem {
  road_id: string
  order: number
  verdict: Verdict
  road_name: string
  length_m: number
  ff_speed_kmph?: number
  confidence?: { score: number; label: string }
  signals?: {
    signal_count: number
    crossing_count: number
    /** null when length_m < 100 */
    signals_per_km_guarded: number | null
  }
}
```

Inside `Row(...)`'s metadata `<div className="text-sm text-scale-1000 mt-0.5 tabular-nums">`, append the signals section. Replace that line with:

```tsx
          <div className="text-sm text-scale-1000 mt-0.5 tabular-nums">
            {item.length_m ? `${Math.round(item.length_m)} m` : "—"}
            {typeof item.ff_speed_kmph === "number" ? ` · ff ${item.ff_speed_kmph.toFixed(1)} km/h` : ""}
            {item.confidence ? ` · conf ${item.confidence.score.toFixed(2)} ${item.confidence.label.toUpperCase()}` : ""}
            {item.signals ? (
              <>
                {" · "}
                <span title="Signals within 50 m of this segment (nearest-attributed)">
                  sig {item.signals.signal_count}
                </span>
                {item.signals.crossing_count > 0 && (
                  <span title="Pedestrian crossings within 50 m">
                    {" · xing "}{item.signals.crossing_count}
                  </span>
                )}
                {" · "}
                <span title="Signals per km — suppressed for segments shorter than 100 m">
                  {item.signals.signals_per_km_guarded === null
                    ? "—"
                    : `${item.signals.signals_per_km_guarded.toFixed(1)} sig/km`}
                </span>
              </>
            ) : null}
          </div>
```

- [ ] **Step 2: Wire `signals` into the items in `verdict-tab.tsx`**

Edit `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx`.

Replace the `items` mapping block with:

```ts
  const items: SegmentChainItem[] = job.segment_ids.map((rid, i) => {
    const v = verdicts[rid]
    const seg = segByRid.get(rid)
    const sig = signals?.rollups[rid]
    return {
      road_id: rid,
      order: i + 1,
      verdict: isVerdict(v) ? v : "NO_DATA",
      road_name: seg?.road_name ?? "",
      length_m: Number(seg?.length_m ?? 0),
      ff_speed_kmph: freeflow[rid]?.ff_speed_kmph,
      confidence: confidence[rid] ? { score: confidence[rid].score, label: confidence[rid].label } : undefined,
      signals: sig ? {
        signal_count: sig.signal_count,
        crossing_count: sig.crossing_count,
        signals_per_km_guarded: sig.signals_per_km_guarded,
      } : undefined,
    }
  })
```

- [ ] **Step 3: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 4: Smoke test**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

Open `http://localhost:3000/corridor-diagnostics?corridor=KOL_B&slice=weekday`. In the right-panel Segments along the corridor card, each row should now show e.g. `1118 m · ff 30.4 km/h · sig 10 · xing 12 · 8.9 sig/km`.

Open `?corridor=DEL_AUROBINDO&slice=weekday`. Short segments (< 100 m, like Sri Aurobindo Marg S01–S04) should display `… · sig 0 · —`.

Stop the dev server.

- [ ] **Step 5: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx \
        src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx
git commit -m "feat(corridor-diagnostics): per-segment signals/density on SegmentChain rows"
```

---

## Task 12: Density tag on stuck verdicts

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`

- [ ] **Step 1: Render the density tag**

Edit `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`. The verdict pill currently lives in this block at the top of the row's content:

```tsx
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-base font-bold text-scale-1200 tabular-nums">
              S{String(item.order).padStart(2, "0")}
            </span>
            <span className={cn("text-xs font-bold rounded-full border px-2 py-0.5", pill.bg, pill.text, pill.border)}>
              {verdictLabel(item.verdict)}
            </span>
          </div>
```

Add a `densityTag` derivation just above the `return` of `Row(...)`:

```ts
  const STUCK = new Set<Verdict>(["ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK", "QUEUE_VICTIM", "SLOW_LINK"])
  const dens = item.signals?.signals_per_km_guarded
  let densityTag: string | null = null
  let densityClass = ""
  if (STUCK.has(item.verdict) && dens !== undefined && dens !== null) {
    if (dens >= 4) {
      densityTag = "signal-dominated"
      densityClass = "bg-[#fee2e2] text-[#991b1b] border-[#fecaca]"
    } else if (dens <= 0.5) {
      densityTag = "capacity-limited"
      densityClass = "bg-[#dbeafe] text-[#1e3a8a] border-[#bfdbfe]"
    }
  }
```

Replace the verdict-pill block with one that conditionally appends the tag:

```tsx
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-base font-bold text-scale-1200 tabular-nums">
              S{String(item.order).padStart(2, "0")}
            </span>
            <span className={cn("text-xs font-bold rounded-full border px-2 py-0.5", pill.bg, pill.text, pill.border)}>
              {verdictLabel(item.verdict)}
            </span>
            {densityTag && (
              <span
                className={cn("text-xs font-medium rounded-full border px-2 py-0.5", densityClass)}
                title={`signals_per_km = ${dens?.toFixed(1)}`}
              >
                {densityTag}
              </span>
            )}
          </div>
```

- [ ] **Step 2: Compile**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no new errors.

- [ ] **Step 3: Smoke test**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

Open `?corridor=KOL_B&slice=weekday`. Any stuck-verdict row on the densest stretch (S01/S02/S05/S06) should show a red `signal-dominated` pill alongside the verdict pill. Open `?corridor=PUNE_A&slice=weekday`; if any segment is stuck, the row should show a blue `capacity-limited` pill (PUNE_A has 0 sig/km on every segment ≥ 100 m).

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
cd /Users/lepton/Desktop/trafficure
git add src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx
git commit -m "feat(corridor-diagnostics): density tag on stuck verdicts"
```

---

## Task 13: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run unit tests**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec vitest run
```

Expected: all tests pass, including the new URL-state cases.

- [ ] **Step 2: Type-check the whole repo**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm exec tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: End-to-end smoke walk**

```bash
cd /Users/lepton/Desktop/trafficure && pnpm dev
```

In a browser:

1. `?corridor=KOL_B&slice=weekday` — confirm the legend pill shows the new toggle button. Click it → markers appear, URL gains `signals=on`. Refresh — markers persist (URL state).
2. `?corridor=PUNE_A&slice=weekday&signals=on` — confirm map has 0 markers, right-panel `Σ 0 · density 0.0 sig/km`.
3. `?corridor=DEL_AUROBINDO&slice=weekday&signals=on` — confirm small markers appear; per-segment column shows `—` for sub-100 m segments.
4. Toggle off via the button — markers vanish, URL drops `signals` param.
5. Hover any signal marker — tooltip shows `osm_node_id` + tag string (deck.gl picking handles this; tooltip surfaces via the existing pickable hover handler).

If any of these fail, address the issue and re-run from this step.

Stop the dev server.

- [ ] **Step 4: Commit any final tweaks**

```bash
cd /Users/lepton/Desktop/trafficure
git status
# only commit if there are uncommitted edits from the smoke-walk fixes
```

If clean, no commit needed. Plan complete.

---

## Self-review notes

- **Spec coverage:** API route (Task 3) ✓, hook (Task 4) ✓, URL state (Task 5) ✓, emitter (Task 6) ✓, IconLayer (Task 7) ✓, mount (Task 8) ✓, legend toggle expanded + collapsed (Task 9) ✓, corridor density chip (Task 10) ✓, per-segment annotation (Task 11) ✓, density tag on verdicts (Task 12) ✓, acceptance criteria covered by Task 13 ✓.
- **Brittleness facts:** `MIN_LEN_FOR_DENSITY = 100` guard implemented in Task 3 server side and surfaces as `null` → `"—"` in Tasks 11/12. `junction_count` rendered conditionally in Task 10 (hidden when 0). Nearest-segment assignment via `ROW_NUMBER() OVER` in Task 3.
- **No placeholders:** every step contains exact code, exact paths, exact commands.
- **Type consistency:** `SignalNode` / `SignalRollup` / `CorridorSignalsResponse` defined once in Task 1 and consumed verbatim downstream. `SignalSymbol` defined in Task 6 and imported by Task 7. URL-state `signals: boolean` is added to `CorridorParams` in Task 5 and consumed in Tasks 6, 9.
