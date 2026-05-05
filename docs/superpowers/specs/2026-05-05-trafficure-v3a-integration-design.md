# Trafficure /corridor-diagnostics — v3-A Integration Spec

**Date:** 2026-05-05
**Repo target:** `/Users/lepton/Desktop/trafficure`
**Companion v3-A repo:** `/Users/lepton/conductor/workspaces/Phase 4 - Corridor Diagnostics/semarang`
**Engine version target:** `v3.a.0` (already shipped in `data/v3_a/`)
**Design fidelity:** every new component MUST reuse existing Trafficure primitives, tokens, and spacing. No new visual vocabulary.

---

## 0. Reading guide

This spec extends `/corridor-diagnostics` to support v3-A's Mode B. The implementing agent must:

1. Reuse existing Trafficure primitives (`<SectionCard>`, `<StatGrid>`, `<SegTable>`, `<NumberPill>`, `<StoryBlock>`, Rio.js `<Card>`, `<Tabs>`, `<Button>`, `<Tooltip>`, `<Skeleton>`, `<Icon>`, `cn`).
2. Use existing tokens (`scale-*`, the verdict-style.ts hex map, `bg-[#EAEDF2]`, `border-[#ECE5DC]`, `bg-[#FAF8F5]`, `border-forest-600`) — do NOT introduce new colour values except where this spec explicitly maps a regime to an existing verdict colour.
3. Wrap every numeric value in `tabular-nums`.
4. Stop and ask if a question arises that the spec doesn't cover.

---

## 1. Overview

Adds Mode B (point-in-time diagnostics anchored at any T) to the existing route. Concretely:

1. A **mode-tabs bar** at the top of the left panel (above the existing "Pre-built / From route / Custom" tabs) — three triggers: Retrospective / Today / Replay. Uses the same `<Tabs>` primitive as the existing tab bar; visually a second underline strip stacked above the first.
2. A **`<SectionCard label="Anchor T">`** in the left panel below the mode tabs (conditional on `mode === "today_as_of_T"`) containing a hybrid scrubber: scrubber bar + date/time inputs + quick-jump presets + `↻ Now` chip.
3. URL extension: `?mode=…&anchor=<ISO ts>`.
4. A **third tab "Insights"** in the right panel (visible only in Mode B) using the existing underline-tab pattern. Houses four stacked `<SectionCard>` blocks (growth-rate, percolation, jam-tree, MFD).
5. A **regime ribbon** pinned full-width above the right-panel tab strip (in Mode B only). Built as a `<SectionCard>` with row dividers matching the stage-card warm-beige pattern.
6. Map repaints by **regime at anchor T** in Mode B. Verdict letter badges removed entirely from the map (both modes).
7. Backend: existing Nitro handler branches on `body.diagnostic_mode`. v3-A path proxies to a Python FastAPI sidecar wrapping `data.v3_a.api`. v2.1 path unchanged.
8. Frontend reads `structured.schema_version === "v3"` to discriminate; reuses `useJobPoll`, TanStack Query cache, and existing error UI.

### 1.1 What this delivers

- v2.1 retrospective behaviour byte-identical to today (minus the verdict letter badges on the map, which are removed in both modes per Q8).
- Mode B end-to-end with all four Tier-1 modules visualised.
- Replay mode (any past day, cached forever).
- Single job poll per (corridor, day, mode); client-side scrubbing for the anchor cursor.

### 1.2 What this does NOT deliver

- No `mode = "live_snapshot"` (deferred — v3-A FUTURE_WORK §1).
- No SSE per-stage progress events.
- No new endpoint family `/api/v3a/*`.
- No new visual vocabulary — strictly reuses existing tokens and primitives.

---

## 2. Locked decisions index

| # | Decision | Locked value |
|---|---|---|
| Q1 | Integration shape | Extend `/corridor-diagnostics` in place; component-level mode discrimination |
| Q2 | Backend wiring | Reuse existing endpoints; branch in handler on `body.diagnostic_mode` |
| Q3 | URL state | `?corridor=…&mode=<retrospective\|today_as_of_T>&anchor=<ISO ts>`; `mode` defaults to `retrospective` |
| Q4 | Mode tabs placement | Top of left panel, above the existing flow tabs (Pre-built / From route / Custom) |
| Q5 | Anchor scrubber | Hybrid: 24h scrubber bar + date/time inputs + presets + `↻ Now` chip — wrapped in a `<SectionCard label="Anchor T">` |
| Q6 | Tier-1 surface | New "Insights" tab (third tab in right panel; underline style matching existing) |
| Q7 | Insights internal layout | Stacked vertical `<SectionCard>` blocks: growth-rate → percolation → jam-tree → MFD |
| Q8 | Map behaviour | Repaints by regime at anchor T (Mode B); verdict colours (Retrospective). Verdict letter badge layer removed in both modes |
| Q9 | Anchor scrubbing | One API call per (corridor, day, mode) at `anchor = end_of_day`; client-side cursor scrubs map + ribbon + chart traces |
| Q10a | Regime ribbon location | Full-width `<SectionCard>` strip pinned ABOVE the right-panel tab strip; visible across all three tabs in Mode B |
| Q10b | Backend dispatch | Python FastAPI sidecar `data/v3_a/server.py`; Trafficure Nitro proxies to it |
| Arch | Architecture | A — minimal extension of existing JobPolling, single envelope in `structured` |

---

## 3. Repository layout

### 3.1 Trafficure repo (`/Users/lepton/Desktop/trafficure`)

```
src/
├── modules/
│   └── trafficure.corridor-diagnostics/
│       ├── data/
│       │   ├── api.ts                              # MODIFY — extend RunRequestBody + Job types (diagnostic_mode, anchor_ts)
│       │   ├── envelope-types.ts                   # NEW — V3aEnvelope and module payload types (mirrors data/v3_a/envelope.py)
│       │   └── url-state.ts                        # MODIFY — extend useCorridorUrlState with mode + anchor
│       ├── components/
│       │   ├── left-panel/
│       │   │   ├── corridor-diagnostics-left-panel.tsx   # MODIFY — insert <ModeTabs> + conditional <AnchorScrubber>
│       │   │   ├── mode-tabs.tsx                          # NEW — Rio.js <Tabs> with three triggers
│       │   │   └── anchor-scrubber.tsx                    # NEW — <SectionCard label="Anchor T">
│       │   ├── right-panel/
│       │   │   ├── corridor-diagnostics-right-panel.tsx   # MODIFY — three-tab strip in Mode B; pin <RegimeRibbon> above tabs
│       │   │   ├── regime-ribbon.tsx                      # NEW — full-width pinned strip
│       │   │   ├── dow-anomaly-chip.tsx                   # NEW — small chip above ribbon (right-aligned)
│       │   │   └── insights-tab/
│       │   │       ├── index.tsx                          # NEW — tab container, mode-gated
│       │   │       ├── growth-rate-section.tsx            # NEW — <SectionCard label="Growth-rate">
│       │   │       ├── percolation-section.tsx            # NEW — <SectionCard label="Percolation">
│       │   │       ├── jam-tree-section.tsx               # NEW — <SectionCard label="Jam-tree">
│       │   │       └── mfd-section.tsx                    # NEW — <SectionCard label="MFD hysteresis">
│       │   ├── map-overlay/
│       │   │   └── corridor-diagnostics-map-layer.tsx     # MODIFY — remove verdict letter badge layer; add Mode-B regime colour
│       │   └── verdict-style.ts                           # MODIFY — add REGIME_PAINT map (FREE/APPR/CONG/SEVR → existing hex colours from verdict palette)
│       └── hooks/
│           ├── useAnchorBucket.ts                  # NEW — derived ISO → bucket index
│           ├── useEnvelope.ts                      # NEW — discriminator hook on schema_version
│           └── useAnchorCursor.ts                  # NEW — client-side cursor state separate from URL anchor
└── routes/
    ├── (app)/(dashboard)/corridor-diagnostics/
    │   ├── layout.tsx                              # MODIFY — read URL mode/anchor; gate Insights tab + ribbon
    │   └── page.tsx                                # unchanged
    └── api/
        └── corridor-diagnostics/
            ├── run.ts                              # MODIFY — branch on body.diagnostic_mode; proxy to FastAPI sidecar in Mode B
            └── run/[jobId].ts                      # MODIFY — discriminate by run_id prefix; proxy to sidecar for v3-A jobs
```

### 3.2 v3-A repo (`semarang`)

```
data/v3_a/
├── server.py                                       # NEW — FastAPI app wrapping submit_run / get_run
└── tests/
    └── test_server.py                              # NEW — endpoint smoke tests
```

The Trafficure repo gains 12 files and modifies 7. The v3-A repo gains 2 files. No existing Trafficure files are renamed.

---

## 4. URL state

`/corridor-diagnostics?corridor=<cid>&mode=<m>&anchor=<iso>&slice=<s>&segment=<rid>&signals=on`

| Param | Type | Default | Notes |
|---|---|---|---|
| `corridor` | string | none | corridor id (e.g. `KOL_B`) |
| `mode` | `retrospective \| today_as_of_T` | `retrospective` | `live_snapshot` reserved |
| `anchor` | ISO 8601 string | omitted | required when `mode === "today_as_of_T"`; auto-set to bucket-truncated `now()` when first switching to Today |
| `slice` | `weekday \| weekend` | `weekday` | consumed only in Retrospective; ignored in Mode B |
| `segment`, `signals` | as today | as today | unchanged |

`useCorridorUrlState()` extension:

```ts
type CorridorParams = {
  corridor?: string;
  mode: "retrospective" | "today_as_of_T";
  anchor?: string;
  slice: "weekday" | "weekend";
  segment?: string;
  signals?: "on";
  // derived flag (not URL-bound):
  isReplay?: boolean;   // when in Mode B and anchor's date < today's date
};
```

Setters:
- `setMode(m, opts?: { isReplay?: boolean })` — when switching to Mode B without an anchor, sets anchor to bucket-truncated `now()`.
- `setAnchor(iso)` — 2-min-truncates and writes ISO IST.

---

## 5. Component spec

### 5.0 Design system anchors

**Reuse these primitives — do not re-implement.**

| Primitive | Source | Use in v3-A |
|---|---|---|
| `<Tabs>`, `<TabsList>`, `<TabsTrigger>` | `@rio.js/ui/tabs` | Mode tabs (left panel); existing flow tabs unchanged |
| `<Card>`, `<CardContent>` | `@rio.js/ui/card` | Inside `<SectionCard>` for nested cards if needed |
| `<Button>` | `@rio.js/ui/button` | Quick-jump presets, ↻ Now, retry buttons |
| `<Icon>` | `@rio.js/ui/icon` | All Phosphor icons |
| `<Tooltip>`, `<TooltipContent>`, `<TooltipTrigger>` | `@rio.js/ui/tooltip` | Hover details on ribbon cells, chart points |
| `<Skeleton>` | `@rio.js/ui/components/skeleton` | Loading placeholders |
| `cn` | `@rio.js/ui/lib/utils` | All conditional className concat |
| `<SectionCard>` | `right-panel/section-card.tsx` | Outer container for every Insights section, the regime ribbon, and the anchor scrubber panel |
| `<SectionLabel>` | `right-panel/section-label.tsx` | If a sub-block needs a label inside a SectionCard |
| `<StatGrid>` | `right-panel/stages-primitives.tsx` | KV grids inside Tier-1 sections (e.g. percolation onset metrics) |
| `<SegTable>` | `right-panel/stages-primitives.tsx` | Tabular data inside Tier-1 sections (e.g. growth-rate event list) |
| `<NumberPill>` | `right-panel/stages-primitives.tsx` | Section number badges (1, 2, 3, 4 for the four Tier-1 modules) |
| `<StoryBlock>` | `right-panel/story-block.tsx` | Brief explanation paragraph at the bottom of percolation/MFD sections |
| `<WindowBar>` | `right-panel/stages-primitives.tsx` | Reuse for primary-window strips inside Tier-1 sections if helpful |

**Tokens to use exclusively:**

| Surface / property | Class |
|---|---|
| Card / panel background | `bg-scale-100` |
| Card border | `border border-scale-300 rounded-lg shadow-sm` |
| Internal grid wrapper | `border border-scale-300 rounded-lg overflow-hidden bg-white` (matches `<StatGrid>`) |
| Right-panel content area | `bg-[#EAEDF2]` |
| Table header | `bg-[#FAF8F5]` |
| Stage / row divider | `border-b border-[#ECE5DC]` |
| Section divider | `border-b border-scale-300` |
| Active tab underline | `border-forest-600 text-forest-600` |
| Section label | `text-sm font-semibold text-scale-1200 uppercase tracking-[0.08em] mb-2.5` |
| Card title | `text-base font-semibold text-scale-1200` |
| Body text | `text-base text-scale-1200` (primary), `text-base text-scale-1000` (secondary), `text-sm text-scale-1000` (small) |
| Muted metadata | `text-xs text-scale-1000` |
| Metric value | `text-lg font-bold tabular-nums` (colour from `colorOf(highlight)` mirroring `<StatGrid>`) |
| Number formatting | EVERY numeric value wrapped in `tabular-nums` |
| Card spacing | `px-4 py-3` for headers, `px-3 py-2.5` for cells, `gap-2` between sections |
| Pill (verdict style) | `rounded-full border px-2 py-0.5 text-xs font-bold` with colour scheme from `verdict-style.ts` |

**Phosphor icons used in this integration:** `icon-[ph--clock-duotone]` (anchor), `icon-[ph--play-duotone]` (run), `icon-[ph--arrow-counter-clockwise-duotone]` (↻ Now / replay), `icon-[ph--calendar-blank-duotone]` (date), `icon-[ph--gauge-duotone]` (MFD), `icon-[ph--graph-duotone]` (jam-tree), `icon-[ph--lightning-duotone]` (growth-rate), `icon-[ph--share-network-duotone]` (percolation), `icon-[ph--caret-down]` / `icon-[ph--caret-right]` (collapsibles).

### 5.1 `<ModeTabs>` (Q4)

File: `components/left-panel/mode-tabs.tsx`.

Reuse the existing left-panel tab pattern verbatim. The corridor-diagnostics left panel already starts with:

```tsx
<div className="px-3 sm:px-4 py-2 border-b border-scale-300 bg-scale-100">
  <Tabs value={tab} onValueChange={…} className="w-full">
    <TabsList className="w-full">
      <TabsTrigger value="corridors" className="flex-1">Pre-built</TabsTrigger>
      …
    </TabsList>
  </Tabs>
</div>
```

Insert ABOVE this block an identical-shape header div:

```tsx
<div className="px-3 sm:px-4 py-2 border-b border-scale-300 bg-scale-100">
  <Tabs value={mode} onValueChange={onChangeMode} className="w-full">
    <TabsList className="w-full">
      <TabsTrigger value="retrospective" className="flex-1">Retrospective</TabsTrigger>
      <TabsTrigger value="today_as_of_T" className="flex-1">Today</TabsTrigger>
      <TabsTrigger value="replay" className="flex-1">Replay</TabsTrigger>
    </TabsList>
  </Tabs>
</div>
```

Note: the URL knows two values for `mode` (`retrospective` / `today_as_of_T`). The third tab `replay` is a UI-only state — when active, internally `mode = "today_as_of_T"` and `isReplay = true`. The Tabs component's `value` is mapped via:

```tsx
const tabValue = mode === "today_as_of_T" ? (isReplay ? "replay" : "today_as_of_T") : "retrospective";
```

`onChangeMode(v)` writes the URL params accordingly.

### 5.2 `<AnchorScrubber>` (Q5)

File: `components/left-panel/anchor-scrubber.tsx`.

Visible only when `mode === "today_as_of_T"`. Wrapped in a `<SectionCard>` so it inherits the existing card visual:

```tsx
<div className="px-3 sm:px-4 py-3 bg-scale-100 border-b border-scale-300">
  <div className="bg-scale-100 border border-scale-300 rounded-lg shadow-sm p-3">
    <div className="text-sm font-semibold text-scale-1200 uppercase tracking-[0.08em] mb-2.5">
      Anchor T
    </div>
    {/* … contents … */}
  </div>
</div>
```

(Note: this uses the `<SectionCard>` shape inline rather than wrapping with the component, because `<SectionCard>` is currently a right-panel-only export. Either move it to a shared location or duplicate the shell; either is acceptable, just keep classNames identical.)

**Internal contents, top-to-bottom:**

1. **Scrubber bar** (custom, ~12 px tall):

```tsx
<div className="relative h-3 bg-scale-200 border border-scale-300 rounded-md overflow-hidden">
  {/* Filled portion 0 → cursor */}
  <div
    className="absolute inset-y-0 left-0 bg-forest-600/20 border-r border-forest-600"
    style={{ width: `${(cursorBucket / 720) * 100}%` }}
  />
  {/* Knob */}
  <div
    className="absolute -top-1 w-1.5 h-5 bg-forest-600 rounded-sm shadow-sm cursor-grab"
    style={{ left: `calc(${(cursorBucket / 720) * 100}% - 3px)` }}
    onMouseDown={onScrubStart}
  />
</div>
{/* Hour ticks */}
<div className="relative h-3 mt-0.5">
  {[0, 6, 12, 18, 24].map(h => (
    <span key={h} className="absolute text-[10px] text-scale-1000 tabular-nums" style={{ left: `${(h * 30 / 720) * 100}%`, transform: "translateX(-50%)" }}>
      {String(h).padStart(2, "0")}
    </span>
  ))}
</div>
```

Drag is *visual-only* (cursor moves) until release; release fires `setAnchor`.

2. **Date and time inputs** (controlled `<input>` elements, classed with the existing pattern):

```tsx
<div className="flex items-center gap-2 mt-3">
  {isReplay && (
    <label className="flex items-center gap-1.5 text-sm text-scale-1200">
      <Icon className="icon-[ph--calendar-blank-duotone] text-scale-1000" />
      <input
        type="date"
        value={anchorDate}
        onChange={…}
        className="bg-white border border-scale-300 rounded-md px-2 py-1 text-sm tabular-nums text-scale-1200"
      />
    </label>
  )}
  <label className="flex items-center gap-1.5 text-sm text-scale-1200">
    <Icon className="icon-[ph--clock-duotone] text-scale-1000" />
    <input
      type="time"
      step={120}
      value={anchorTime}
      onChange={…}
      className="bg-white border border-scale-300 rounded-md px-2 py-1 text-sm tabular-nums text-scale-1200"
    />
  </label>
</div>
```

3. **Quick-jump presets and `↻ Now` chip** — use Rio.js `<Button>` with `variant="outline"` and `size="sm"`:

```tsx
<div className="flex items-center gap-1.5 mt-2.5">
  <Button variant="outline" size="sm" onClick={() => preset(-60)}>−1h</Button>
  <Button variant="outline" size="sm" onClick={() => preset(-30)}>−30m</Button>
  <Button variant="outline" size="sm" onClick={() => preset(+30)}>+30m</Button>
  <span className="ml-auto" />
  <Button variant="primary" size="sm" onClick={jumpToNow}>
    <Icon className="icon-[ph--arrow-counter-clockwise-duotone] mr-1" />
    Now
  </Button>
</div>
```

State: a single `anchorISO` state at the parent level; all three controls (scrubber knob, date input, time input) are controlled views over it.

### 5.3 `<RegimeRibbon>` (Q10a, Q9)

File: `components/right-panel/regime-ribbon.tsx`.

Pinned full-width ABOVE the right-panel tab strip when `mode === "today_as_of_T"`. Wrapped as a `<SectionCard>`:

```tsx
<div className="px-3 py-3 bg-[#EAEDF2]">
  <div className="bg-scale-100 border border-scale-300 rounded-lg shadow-sm p-3">
    <div className="flex items-center justify-between mb-2">
      <span className="text-sm font-semibold text-scale-1200 uppercase tracking-[0.08em]">
        Regimes today
      </span>
      <DowAnomalyChip />   {/* §5.7 */}
    </div>
    {/* The ribbon body */}
    <div className="flex flex-col">
      {segmentOrder.map((seg, idx, arr) => (
        <div
          key={seg}
          className={cn(
            "grid items-center py-1.5",
            idx !== arr.length - 1 && "border-b border-[#ECE5DC]",
          )}
          style={{ gridTemplateColumns: "120px 1fr" }}
        >
          <div className="pr-2 truncate text-sm text-scale-1200 tabular-nums">
            {`S${String(idx + 1).padStart(2, "0")}`}
            <span className="ml-1.5 text-xs text-scale-1000 truncate">{segMeta[seg].name}</span>
          </div>
          <div className="relative h-3.5 bg-scale-200 rounded-sm overflow-hidden">
            {/* 720 cells, but rendered as a single SVG/canvas for perf */}
            <RibbonRow regimes={regimes[seg]} anchorBucket={anchorBucket} />
            {/* Anchor cursor line */}
            <div
              className="absolute inset-y-0 w-px bg-forest-600 pointer-events-none"
              style={{ left: `${(cursor / 720) * 100}%` }}
            />
            {/* Bertini overlay */}
            {bertini[seg]?.map(([t0, t1]) => (
              <div
                key={`${t0}-${t1}`}
                className="absolute inset-y-0 border-l border-r border-scale-1100/40 bg-scale-1100/10"
                style={{ left: `${(t0 / 720) * 100}%`, width: `${((t1 - t0 + 1) / 720) * 100}%` }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
    {/* Hour ticks below the rows */}
    <div className="grid mt-1" style={{ gridTemplateColumns: "120px 1fr" }}>
      <div />
      <div className="relative h-3">
        {[0,3,6,9,12,15,18,21,24].map(h => (
          <span key={h} className="absolute text-[10px] text-scale-1000 tabular-nums" style={{ left: `${(h * 30 / 720) * 100}%`, transform: "translateX(-50%)" }}>
            {String(h).padStart(2,"0")}
          </span>
        ))}
        {/* Primary windows as faint forest strips */}
        {primaryWindows.map(([s, e]) => (
          <div
            key={`${s}-${e}`}
            className="absolute inset-y-0 bg-forest-600/8 border-l border-r border-forest-600/40"
            style={{ left: `${(s / 720) * 100}%`, width: `${((e - s + 1) / 720) * 100}%` }}
          />
        ))}
        {/* Percolation onset marker (forest-600 vertical line, dashed) */}
        {percolationOnset != null && (
          <div
            className="absolute inset-y-0 w-px border-l border-dashed border-forest-600"
            style={{ left: `${(percolationOnset / 720) * 100}%` }}
          />
        )}
      </div>
    </div>
  </div>
</div>
```

**Regime → colour mapping** — defined in `verdict-style.ts` as a new export `REGIME_PAINT`, mirroring the existing verdict palette:

```ts
export const REGIME_PAINT: Record<string, string> = {
  FREE:        "#16a34a",  // matches FREE_FLOW dot
  APPROACHING: "#a16207",  // matches SLOW_LINK dot
  CONGESTED:   "#ea580c",  // matches QUEUE_VICTIM dot
  SEVERE:      "#b91c1c",  // matches ACTIVE_BOTTLENECK dot
  NO_DATA:     "#737373",  // matches NO_DATA dot
};
```

Cells with `b > anchorBucket` are rendered at `opacity: 0.35` ("post-anchor, no data yet").

Hover on a cell: `<Tooltip>` shows `S## · 14:32 · CONGESTED` (segment + time + regime), styled with the existing tooltip primitive defaults.

Click on a row: focuses that segment via the existing URL `segment` param.

`<RibbonRow>` is implemented as an SVG `<rect>` array (one rect per bucket). For 41 segments × 720 buckets that's ~30k rects total, which renders fine in a single SVG. If profiling shows lag on lower-end devices, swap to a `<canvas>` (same shape, one row at a time).

### 5.4 Map layer modifications (Q8)

File: `components/map-overlay/corridor-diagnostics-map-layer.tsx`.

Two changes:

**(a) Remove the verdict letter badge layer.** The existing icon-atlas canvas + symbol layer (the one that renders A/H/Q/S/F badges on segment midpoints) is deleted in both Retrospective and Mode B. Operators read verdicts from the right panel exclusively.

**(b) Mode-conditional segment colour.**

```tsx
const getColor = useMemo(() => (segment: SegmentFeature) => {
  if (mode === "retrospective") {
    return verdictHexColor(verdicts[segment.road_id]);   // existing path
  }
  // Mode B
  const regime = regimes[segment.road_id]?.[anchorCursor] ?? "NO_DATA";
  return REGIME_PAINT[regime];
}, [mode, verdicts, regimes, anchorCursor]);
```

`updateTriggers: { getColor: anchorCursor }` so Deck.gl repaints only the colour accessor on cursor change (no full layer reload).

### 5.5 Anchor cursor model (Q9)

File: `hooks/useAnchorCursor.ts`.

Two state values, tightly coupled:

| State | Source | When it changes |
|---|---|---|
| URL `anchor` | `useCorridorUrlState()` | scrubber drag-release · date/time input change · quick-jump preset · `↻ Now` |
| `anchorCursor` (bucket index) | React context provided at the right-panel root | scrubber drag (live) · whenever URL anchor changes (snap) |

Drag-release semantics:
- Drag updates `anchorCursor` only.
- Release: write URL `anchor`. If only the time-of-day changed within the same date, **no re-fetch** (the envelope already has full-day regimes). If the date changed, `useJobPoll` invalidates and a new envelope is fetched.

Subscribers to `anchorCursor`:
- `<MapLayer>` — segment colour (via `updateTriggers`)
- `<RegimeRibbon>` — vertical cursor line per row + post-cursor opacity
- `<PercolationSection>` — vertical cursor line on LCC/SLCC chart
- `<MFDSection>` — highlighted point on density-vs-speed scatter
- `<DowAnomalyChip>` dropdown — vertical cursor line on deviation sparkline

### 5.6 `<InsightsTab>` (Q6, Q7)

File: `components/right-panel/insights-tab/index.tsx`.

The right-panel tab strip becomes three triggers in Mode B (Verdict / Stages / **Insights**) using the existing underline-tab pattern:

```tsx
<div className="flex border-b border-scale-300">
  {(["verdict", "stages", ...(modeB ? ["insights"] : [])] as const).map(t => (
    <button
      key={t}
      onClick={() => setTab(t)}
      className={cn(
        "flex-1 py-2 text-center text-base font-medium transition-colors border-b-2 -mb-px",
        tab === t
          ? "border-forest-600 text-forest-600"
          : "text-scale-1000 border-transparent hover:text-scale-1200",
      )}
    >
      {t === "insights" ? "Insights" : t === "verdict" ? "Verdict" : "Stages"}
    </button>
  ))}
</div>
```

The Insights tab body is the existing right-panel content shell (`pretty-scroll bg-[#EAEDF2] px-3 py-3`) with a vertical stack:

```tsx
<div className="flex flex-col gap-2 px-3 py-3">
  <GrowthRateSection />
  <PercolationSection />
  <JamTreeSection />
  <MfdSection />
</div>
```

Each child is a `<SectionCard label="…">`. Section number badges use `<NumberPill n={1..4} />` placed to the left of the section label inside its header (mirroring how `stages-tab.tsx` puts the green stage number to the left of each stage's label).

### 5.7 Tier-1 module section specs

For each section, use this consistent shell:

```tsx
<SectionCard label={
  <span className="flex items-center gap-2">
    <NumberPill n={1} />
    <span>Growth-rate</span>
    <span className="ml-auto text-[10px] font-mono text-scale-1000 normal-case tracking-normal">
      Duan 2023
    </span>
  </span>
}>
  {/* body */}
</SectionCard>
```

(`<NumberPill>` is the existing 24-px `bg-[#1A1A1A]` circle. Adapt or re-use the green stage-number variant `bg-[#0D3B2E]` if visually preferred — pin choice during implementation, but consistent across all four sections.)

#### 5.7.1 `<GrowthRateSection>` (NumberPill 1)

Reads `payload.tier1.growth_rate`.

1. **Summary header** as a single line of count chips below the label (separate row inside the card body):

```tsx
<div className="flex flex-wrap gap-1.5 mb-3 text-xs font-bold uppercase">
  <span className="rounded-full border px-2 py-0.5 bg-[#fee2e2] text-[#991b1b] border-[#fecaca]">
    {gr.summary.n_fast} fast
  </span>
  <span className="rounded-full border px-2 py-0.5 bg-[#ffedd5] text-[#9a3412] border-[#fed7aa]">
    {gr.summary.n_moderate} moderate
  </span>
  <span className="rounded-full border px-2 py-0.5 bg-[#dcfce7] text-[#166534] border-[#bbf7d0]">
    {gr.summary.n_contained} contained
  </span>
  {gr.summary.n_insufficient > 0 && (
    <span className="rounded-full border px-2 py-0.5 bg-[#f5f5f5] text-[#525252] border-[#e5e5e5]">
      {gr.summary.n_insufficient} insufficient
    </span>
  )}
</div>
```

(Pill styles match `verdict-style.ts` exactly for FAST→ACTIVE_BOTTLENECK red, MODERATE→QUEUE_VICTIM orange, CONTAINED→FREE_FLOW green, INSUFFICIENT→NO_DATA grey.)

2. **Events table** using `<SegTable>`:

```tsx
<SegTable
  cols={[
    { label: "t0",       width: "60px" },
    { label: "Segment",  width: "1fr" },
    { label: "Slope (m/min)", width: "100px", align: "right" },
    { label: "Cluster",  width: "90px", align: "right" },
    { label: "Label",    width: "110px" },
  ]}
  rows={gr.events.map(ev => ({ … }))}
/>
```

Column rendering: `t0` formatted `HH:MM` with `tabular-nums`; slope as `+67.3` / `−5.2` / `—` (insufficient) with `tabular-nums`; label rendered as a verdict-style pill matching the chip palette above.

3. **Empty state**: `<StoryBlock>` with text "No Bertini events on this day."

#### 5.7.2 `<PercolationSection>` (NumberPill 2)

Reads `payload.tier1.percolation`.

1. **`<StatGrid>` 4-column** with: `Onset`, `LCC at onset`, `SLCC at onset`, `Time to merge`.
   - Onset: `HH:MM` value + `bucket {N}` sub.
   - LCC / SLCC: metres formatted with `tabular-nums`.
   - Time to merge: integer minutes or em-dash.

```tsx
<StatGrid
  cols={4}
  cells={[
    { label: "Onset",            value: bucketToHHMM(perc.onset_bucket), sub: `bucket ${perc.onset_bucket}` },
    { label: "LCC at onset",     value: fmtM(perc.onset_lcc_m),           highlight: "ok" },
    { label: "SLCC at onset",    value: fmtM(perc.onset_slcc_m),          highlight: "warn" },
    { label: "Time to merge",    value: perc.time_to_merge_minutes != null ? `${perc.time_to_merge_minutes}m` : "—" },
  ]}
/>
```

2. **LCC / SLCC trace chart** — a 720-bucket two-line SVG sparkline below the grid:
   - LCC: forest-green stroke `#0D3B2E` (use `text-forest-600` as fill ref).
   - SLCC: amber stroke `#a16207`.
   - Vertical orange dashed line at `onset_bucket`.
   - Vertical forest-600 line at `anchorCursor` (live).
   - Background: `bg-white`, border `border border-scale-300 rounded-lg p-3` matching `<StatGrid>`.
   - Height: 120 px.
   - Hour ticks below.

3. **Footer explanation** as `<StoryBlock>`: "LCC = largest connected component of CONG/SEVR segments. SLCC peak = the bucket where two clusters were about to merge."

#### 5.7.3 `<JamTreeSection>` (NumberPill 3)

Reads `payload.tier1.jam_tree`.

1. **`<StatGrid>` 4-column**: `Origins`, `Propagated`, `Max depth`, `Reclassifications`.
   - Highlight `Reclassifications` as `warn` if > 0 (orange).

2. **Tree diagram** — custom SVG (~120 LOC). Layout:
   - Origins along the top, oldest first.
   - Propagated children below their parent, indented by depth × 24 px.
   - Each node: a 18 px circle filled with the regime colour at the node's onset bucket (using `REGIME_PAINT`), white ring (`box-shadow: 0 0 0 2px #fff`), with the segment short label `S##` and onset HH:MM in a tooltip.
   - Edges: thin lines between parent and child, `stroke-scale-300`. Edge label: `lag_minutes`m (using `tabular-nums`).
   - Wrapped in `bg-white border border-scale-300 rounded-lg p-3 max-h-[280px] overflow-auto`.

3. **Reclassifications callout** (only if `n_reclassifications > 0`): a yellow info box matching the existing UI vocabulary:

```tsx
<div className="mt-3 rounded-md border bg-[#fef9c3] border-[#fde68a] text-[#854d0e] px-3 py-2 text-sm">
  <div className="font-semibold mb-1">{n} segment(s) reclassified — preceded their supposed bottleneck.</div>
  <ul className="list-disc list-inside space-y-0.5">
    {reclassifications.map(r => (
      <li key={r.segment_id} className="tabular-nums">
        {segLabel(r.segment_id)} — earlier by {r.earlier_by_minutes}m
      </li>
    ))}
  </ul>
</div>
```

4. **Empty state**: "No onsets today (quiet day)."

#### 5.7.4 `<MfdSection>` (NumberPill 4)

Reads `payload.tier1.mfd`.

1. **`<StatGrid>` 3-column** (two rows = 6 cells):
   - Row 1: `Peak density`, `Peak time`, `Loop closes`
   - Row 2: `Loop area`, `Recovery lag`, `FF speed`
   - `Peak density` highlight: `warn` if > 0.5 else `ok`.
   - `Recovery lag` highlight: `bad` if > 60 min else `warn` if > 30 min else `ok`.

2. **Density-vs-speed scatter** — a custom SVG (no Nivo needed; ~80 LOC):
   - x-axis: density (0 → max); y-axis: speed (0 → ff_corridor_kmph + 5).
   - Polyline of `(density[b], speed[b])` for b in `[0, anchorBucket]`.
   - Colour gradient along the polyline: morning → noon → evening (use sequential colour scale `bg-scale-200 → text-forest-600`); or simpler — single forest-600 line.
   - Highlighted dot at the cursor's bucket: 6 px circle, fill `text-forest-600`, white ring.
   - Hovered point: `<Tooltip>` with `b={bucket} · {density}% · {speed} km/h · {HH:MM}`.
   - Wrapped in `bg-white border border-scale-300 rounded-lg p-3`, height 200 px.

3. **Footer explanation** as `<StoryBlock>`: "Loop area = capacity loss this day. Recovery lag = minutes between density halving and speed returning near free-flow."

### 5.8 `<DowAnomalyChip>` (placement: above the regime ribbon, right-aligned)

File: `components/right-panel/dow-anomaly-chip.tsx`.

Compact chip rendered ONLY when `payload.dow_anomaly.available === true`. Uses the existing `<RunProgressChip>`-style vocabulary:

```tsx
const tone = absDev < 10 ? "ok" : absDev < 25 ? "warn" : "bad";
const cls = {
  ok:    "bg-[#dcfce7] text-[#166534] border-[#bbf7d0]",
  warn:  "bg-[#fef9c3] text-[#854d0e] border-[#fde68a]",
  bad:   "bg-[#fee2e2] text-[#991b1b] border-[#fecaca]",
}[tone];

return (
  <button
    type="button"
    onClick={toggleDropdown}
    className={cn(
      "px-2 py-1 rounded-full text-xs font-medium border tabular-nums inline-flex items-center gap-1.5",
      cls,
    )}
  >
    <Icon className="icon-[ph--calendar-blank-duotone]" />
    {dow.dow} {dev > 0 ? "+" : ""}{dev.toFixed(0)}% vs typical
  </button>
);
```

Click expands a dropdown showing the deviation_pct_trace as a thin sparkline (same SVG primitives as the percolation trace, height 60 px) plus N samples and DOW.

If `available === false`, render nothing (silent gating — do not show "DOW unavailable").

---

## 6. Data layer

### 6.1 Type definitions

File: `data/envelope-types.ts` (NEW). Mirrors `data/v3_a/envelope.py`:

```ts
export type V3aEnvelope = {
  schema_version: "v3";
  engine_version: string;
  mode: "today_as_of_T" | "retrospective";
  corridor_id: string;
  corridor_name: string;
  anchor_ts: string;          // ISO IST
  run_id: string;             // "v3a-…"
  computed_at: string;

  meta: {
    anchor_ts_received: string;
    anchor_bucket: number;
    today_date: string;
    tz: "Asia/Kolkata";
    engine_version: string;
    config_signature: string;
    baseline_window: {
      primary: { type: "trailing_n_weekdays"; n_target_days: number; n_actual_days: number; start_date: string | null; end_date: string | null; thin_baseline: boolean };
      dow_anomaly: { type: "same_dow_trailing_n_weeks"; n_weeks_lookback: number; n_samples: number; dow: number; available: boolean };
    };
    stages_run: string[];
    tier1_modules_run: string[];
    tier1_modules_skipped: string[];
    partial: boolean;
    warnings: Array<{ code: string; message: string; context: Record<string, unknown> }>;
    errors: unknown[];
  };

  payload: {
    stages_v21: V21Stages;            // existing v2.1-shaped data, today's regimes for Mode B
    tier1: {
      growth_rate: GrowthRateEnvelope | null;
      percolation: PercolationEnvelope | null;
      jam_tree:    JamTreeEnvelope | null;
      mfd:         MfdEnvelope | null;
    };
    dow_anomaly: DowAnomalyEnvelope;
  };
};
```

(Each module type mirrors its Python counterpart in `data/v3_a/tier1/*.py` — `events[]`, `lcc_trace_m[]`, `nodes[]`, `density_trace_frac[]` etc. Implement the full type definitions verbatim from the Python schemas in `data/v3_a/envelope.py` and the four `tier1/*.py` files.)

### 6.2 RunRequestBody / Job extension

File: `data/api.ts`. Add fields:

```ts
type RunRequestBody = {
  // existing
  mode_target?: "corridor" | "segments";    // (existing field; rename only if back-compat allows)
  corridor_id?: string;
  segment_ids?: string[];
  slice?: "weekday" | "weekend";
  save_as_corridor?: boolean;
  force_refresh?: boolean;

  // new
  diagnostic_mode?: "retrospective" | "today_as_of_T";    // default "retrospective"
  anchor_ts?: string;                                      // ISO 8601 IST
};
```

Note on naming: the existing `mode` field that selects corridor-vs-segments is left as-is for back-compat (rename to `mode_target` is OPTIONAL — implementer's call). The new diagnostic-mode field is named `diagnostic_mode` to avoid collision either way.

`Job.structured` — typed as `V21Structured | V3aEnvelope` (discriminated union). The existing v2.1 path returns `V21Structured` (no schema_version field); v3-A returns `V3aEnvelope` with `schema_version === "v3"`.

### 6.3 Backend dispatch (Q2, Q10b)

File: `src/routes/api/corridor-diagnostics/run.ts`.

```ts
export default defineEventHandler(async (event) => {
  const body = await readBody<RunRequestBody>(event);

  if (body.diagnostic_mode === "today_as_of_T") {
    if (!body.corridor_id) throw createError({ statusCode: 400, message: "corridor_id required" });
    if (!body.anchor_ts)   throw createError({ statusCode: 400, message: "anchor_ts required for today_as_of_T" });
    const resp = await $fetch<{ run_id: string; status: string }>("/v3a/run", {
      method: "POST",
      baseURL: process.env.V3A_SIDECAR_URL || "http://localhost:8001",
      body: {
        corridor_id: body.corridor_id,
        anchor_ts: body.anchor_ts,
        mode: "today_as_of_T",
      },
    });
    return { job_id: resp.run_id };
  }

  // Existing v2.1 path — UNCHANGED
  return existingV21Runner(body);
});
```

File: `src/routes/api/corridor-diagnostics/run/[jobId].ts`.

```ts
export default defineEventHandler(async (event) => {
  const jobId = getRouterParam(event, "jobId");
  if (jobId?.startsWith("v3a-")) {
    const rec = await $fetch(`/v3a/run/${jobId}`, { baseURL: process.env.V3A_SIDECAR_URL });
    return mapV3aRunRecordToJob(rec);
  }
  return existingV21JobLookup(jobId);
});
```

`mapV3aRunRecordToJob(rec)` returns:

```ts
{
  job_id: rec.run_id,
  status: rec.status === "running" ? "running_validation" : rec.status,   // map to existing JobStatus union
  started_at: rec.started_at,
  finished_at: rec.completed_at,
  corridor_id: rec.corridor_id,
  slice: "weekday",                        // unused in Mode B
  segment_ids: [],                         // unused in Mode B
  structured: rec.result,                  // the full V3aEnvelope
  story: undefined,
  error: rec.error?.message,
}
```

### 6.4 FastAPI sidecar (`data/v3_a/server.py`)

```python
"""FastAPI sidecar exposing data.v3_a.api over HTTP. Spec §6.4."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from data.v3_a.api import submit_run, get_run
from data.v3_a.errors import HardError

app = FastAPI()

class RunRequest(BaseModel):
    corridor_id: str
    anchor_ts: str
    mode: str = "today_as_of_T"

@app.post("/v3a/run")
def run(req: RunRequest):
    try:
        run_id = submit_run(req.corridor_id, req.anchor_ts, mode=req.mode)
        return {"run_id": run_id, "status": "queued"}
    except HardError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())

@app.get("/v3a/run/{run_id}")
def get(run_id: str):
    try:
        return get_run(run_id).to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})

@app.get("/v3a/health")
def health():
    return {"status": "ok"}
```

Run with `uvicorn data.v3_a.server:app --host 0.0.0.0 --port 8001`. Process management (systemd / docker / etc) is operator-decision; out of scope for this spec.

---

## 7. State management & data flow

```
URL params (corridor, mode, anchor, slice, segment, signals)
     │
     ▼
useCorridorUrlState()  ──────► (corridor, mode, anchor, slice, …)
     │
     ▼
useCorridorSnapshotJobId(corridor, mode, anchor) ───► POST /api/corridor-diagnostics/run
     │                                                   (server dispatches v2.1 OR v3-A)
     ▼
useJobPoll(jobId, every: 2000ms)  ──► GET /api/corridor-diagnostics/run/:jobId
     │
     ▼
useEnvelope(jobId)  ──► returns
     │   { kind: "v3a", envelope: V3aEnvelope } | { kind: "v21", structured: V21Structured }
     ▼
mode-specific render tree:
  - v21: existing Verdict + Stages tabs, existing map
  - v3a: Verdict + Stages + Insights tabs, regime ribbon pinned above tabs,
         map regime-recolour, anchor cursor scrubbing
```

`useAnchorCursor` (client-only):

```
<AnchorScrubber> drag/release
     │ (drag updates: anchorCursor only)
     │ (release: writes URL anchor → re-fetch only if day changed)
     ▼
anchorCursor (React context)
     │
     ▼ ─► <MapLayer>      updateTriggers → segment colour
     ▼ ─► <RegimeRibbon>  vertical line + post-cursor opacity
     ▼ ─► <PercolationSection>  vertical line on LCC/SLCC chart
     ▼ ─► <MfdSection>    highlighted point on density-vs-speed
     ▼ ─► <DowAnomalyChip> dropdown sparkline cursor
```

---

## 8. Error & loading states

### 8.1 Hard errors

Land in the existing `Job.error` field. The error code prefix governs the rendering:

- `HARD_ERR_NO_TODAY_DATA` → banner: "No data for {corridor} today yet. Try a later anchor."
- `HARD_ERR_FUTURE_ANCHOR` → banner: "Anchor in the future — pick a past or current time."
- `HARD_ERR_INSUFFICIENT_BASELINE` → banner: "Not enough historical days for this corridor."
- `HARD_ERR_TIMEOUT` / `HARD_ERR_DB_UNREACHABLE` → banner with retry `<Button>`.
- Unknown / `HARD_ERR_INTERNAL` → "Something went wrong" + the message.

Banner styled like the existing `<RunProgressChip>` error state: `bg-red-50 border-red-300 text-red-800 rounded-md px-3 py-2 text-sm`, positioned at the top of the right-panel content area.

### 8.2 Soft warnings (`meta.partial === true`)

A small chip in the right-panel header next to the corridor name, using the `<DowAnomalyChip>`-style vocabulary:

```tsx
<button className="px-2 py-1 rounded-full text-xs font-medium border tabular-nums bg-[#fef9c3] text-[#854d0e] border-[#fde68a]">
  <Icon className="icon-[ph--warning-diamond-duotone] mr-1" />
  Partial · {warnings.length} warning{warnings.length !== 1 ? "s" : ""}
</button>
```

Click expands a drawer showing each `meta.warnings[]` item with code + message.

A Tier-1 module section that received `null` payload renders an "Insufficient data — see warnings" placeholder (same `<StoryBlock>` style) instead of its chart.

### 8.3 Loading states

Use existing `<Skeleton>`. The right-panel tab badges show a spinner (Phosphor `icon-[ph--circle-notch-duotone] animate-spin`). The regime ribbon shows a tall skeleton block. Tier-1 sections show short skeletons. The map shows the existing run-progress chip — unchanged.

---

## 9. Testing

### 9.1 Unit tests (frontend, `vitest`)

New tests:
- `mode-tabs.test.tsx` — three triggers, URL writes, `replay` UI state collapses to `mode === "today_as_of_T"` with `isReplay = true`.
- `anchor-scrubber.test.tsx` — drag→release → URL write; typed inputs update knob; presets (-1h, -30m, +30m); `↻ Now` jumps to current bucket; date input only visible in Replay.
- `regime-ribbon.test.tsx` — colour mapping (REGIME_PAINT), post-anchor opacity, anchor cursor line position, primary-window strips, percolation onset marker, Bertini overlays.
- `useEnvelope.test.tsx` — discriminate v3a (`schema_version === "v3"`) vs v21 (no schema_version).
- `useAnchorBucket.test.tsx` — ISO → bucket index.
- `useAnchorCursor.test.tsx` — drag-only updates cursor, release updates URL, day-change vs same-day re-fetch.
- Each Insights section component — render with fixture envelope (snapshot tests fine).

### 9.2 Integration / E2E (`playwright`)

- Switch to Today mode → scrubber appears → drag → URL anchor updates → API called once → map repaints → ribbon cursor moves.
- Switch to Replay mode → date input appears → pick a past day → new envelope fetched → all sections re-render.
- Switch back to Retrospective → URL anchor cleared → existing v2.1 page renders, behavior unchanged from pre-integration baseline.
- Soft warning path: trigger a `partial: true` envelope → "Partial · N warnings" chip appears → click → drawer shows warnings.
- Hard error path: trigger `HARD_ERR_FUTURE_ANCHOR` → banner appears with the right copy.

### 9.3 Backend tests

- `data/v3_a/tests/test_server.py` — FastAPI endpoint smoke tests with mocked `submit_run`.
- Trafficure Nitro unit tests for the dispatch branch in `run.ts`.

### 9.4 Visual regression

Screenshots for the four locked layouts:
- Mode tabs strip (Retrospective / Today / Replay) with each active.
- Anchor scrubber expanded (Today vs Replay).
- Regime ribbon (zoomed to a single corridor like KOL_B for clarity).
- Insights tab with all four sections populated.

### 9.5 Validation gate

Integration is COMPLETE when:
1. Existing v2.1 retrospective behaviour is regression-tested against pre-integration screenshots (no visual diffs other than the removed verdict letter badges on the map).
2. Mode B end-to-end flows succeed for KOL_B and DEL_AUROBINDO using fixture data via the FastAPI sidecar.
3. All four Insights sections populate from real envelope data.
4. Map regime colours change as the anchor cursor moves (visual regression against a screenshot).

---

## 10. Implementation order

The implementing agent works through these in order. Each step ends green before the next starts.

1. **FastAPI sidecar** (`data/v3_a/server.py` + tests). `uvicorn` smoke test up.
2. **`envelope-types.ts`** — TypeScript types mirroring the Python envelope shape.
3. **URL state extension** (`url-state.ts` + tests). `mode` and `anchor` parsed/written.
4. **`useEnvelope` hook** + tests — discriminator on `schema_version`.
5. **Backend dispatch** — modify Nitro `run.ts` and `run/[jobId].ts`. v2.1 regression suite green (existing E2E unchanged).
6. **`<ModeTabs>`** — left-panel insertion above existing flow tabs.
7. **`<AnchorScrubber>`** — left-panel insertion below mode tabs (conditional).
8. **`useAnchorCursor`** + context — wire up to ribbon + map + section charts (data-only; renderers come next).
9. **Map layer modifications** — remove verdict letter badges, add Mode-B regime colour with `updateTriggers`.
10. **`<RegimeRibbon>`** — pinned above tab strip; SVG row implementation.
11. **Right-panel three-tab strip** — add `Insights` trigger conditional on Mode B.
12. **Insights sections** — one PR per section (growth-rate, percolation, jam-tree, MFD).
13. **`<DowAnomalyChip>`** — chip above ribbon, right-aligned.
14. **Error UI** — hard-error banner + soft-warning chip + drawer.
15. **E2E + visual regression** — full Mode B flow + Replay + back to Retrospective.

After step 15, both gates green = integration complete.

---

## 11. Out-of-scope and FUTURE_WORK

1. **Live snapshot mode (`mode = "live_snapshot"`)** — UI prepared (a fourth potential tab) but engine support deferred to v3-A FUTURE_WORK §1.
2. **SSE per-stage progress events** — revisit if engine runtime exceeds 5–8 s in production; Architecture B candidate.
3. **Persistent cache** — v3-A FUTURE_WORK §4. The FastAPI sidecar uses in-memory cache; restart = cold cache.
4. **Cross-corridor / network views** — v3-B.
5. **Threshold-calibration UI** — operator-facing way to retune growth-rate thresholds per corridor (FUTURE_WORK §6 in v3-A spec).

---

## 12. Definition of done

The Trafficure v3-A integration is shipped when:

1. `/corridor-diagnostics` renders both Retrospective (unchanged behaviour, minus the removed verdict badge layer on the map) and Mode B correctly.
2. All new components have unit tests with ≥80% line coverage.
3. The Playwright E2E suite covers: Retrospective → Today → Replay → back-to-Retrospective with map repaint, ribbon cursor updates, and Insights tab populated.
4. Visual regression screenshots match approved mockups for the four locked layouts.
5. v2.1 retrospective E2E tests pass identically to pre-integration baseline.
6. The FastAPI sidecar serves all v3-A traffic; no Python subprocesses are spawned per request.
7. The verdict letter badge layer is removed from the map in both modes.
8. This spec lives at `docs/superpowers/specs/2026-05-05-trafficure-v3a-integration-design.md` and is referenced from `docs/CORRIDOR_DIAGNOSTICS_V3A_FUTURE_WORK.md`.

---

## 13. Glossary

- **Anchor T** — timestamp at which Mode B is computed. URL-bound.
- **Anchor cursor** — client-side state representing the live visual cursor; distinct from URL anchor; driven by scrubber drag.
- **Mode B** — `mode === "today_as_of_T"`. The MVP v3-A mode.
- **Sidecar** — the Python FastAPI process exposing `data.v3_a.api` over HTTP, separate from Trafficure's Nitro server.
- **Envelope** — the unified v3-A output dict (schema §9 of the v3-A design spec).
- **Regime ribbon** — full-width strip with one row per segment, 720 cells per row, coloured by regime at each bucket.
- **Insights tab** — third tab in the right panel (after Verdict and Stages), Mode-B-only.
- **REGIME_PAINT** — the new export in `verdict-style.ts` mapping regime labels (FREE/APPR/CONG/SEVR) to the existing verdict palette hex colours.

End of spec.
