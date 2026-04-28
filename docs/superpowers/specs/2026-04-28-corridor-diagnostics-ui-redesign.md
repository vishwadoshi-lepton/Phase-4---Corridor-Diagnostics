# Corridor Diagnostics UI Redesign — Design Spec

**Date:** 2026-04-28
**Module:** `trafficure.corridor-diagnostics` (frontend, in `~/Desktop/trafficure`)
**Status:** Ready for implementation planning

## Why this redesign

The current `/corridor-diagnostics` view works but reads as a developer tool, not a product. Three things drive this:

1. The left-panel `CorridorCard` is dominated by a high-saturation gradient ribbon and a 6-colour heatstrip — too busy for a list you want to scan.
2. The corridor's segments are presented as a flat coloured strip with no directional indication, no segment-level identity, and no visual link to the markers on the map (which are tiny `"1·H"` text pills).
3. The right panel's Stages tab dumps raw `JSON.stringify` output for ten stages of pipeline state — useful for engineers, useless for anyone else, and inconsistent with how the alerts and analytics modules present their detail panels.

The redesign brings the view in line with the rest of the product (alerts inbox, analytics right-panel) — calmer surfaces, structured data, a cleaner segment language shared between the map and the panel.

## Out of scope

- **Map geometry rendering** beyond the marker swap. The `PathLayer` colours and widths stay as they are.
- **Backend / API changes.** The job snapshot, segment geometry, and `validation_corridors.json` shapes are unchanged.
- **Recurrence/onset compute changes.** This spec only restyles what we already have.
- **Mobile / narrow-width layout.** We optimize for the desktop right-panel width (~360–440px).

## Reference modules

- `trafficure.core/alert-card.tsx` — card pattern with coloured left border, neutral body, dividers.
- `trafficure.analytics/components/analytics-right-panel/detail-sections.tsx` — `StatsGrid4`, `SpeedComparisonGrid` (2×2 KPI grid styling we mirror).
- `trafficure.analytics/components/analytics-right-panel/analytics-right-panel.tsx` — header + tabs treatment.

## Design system anchors

**Always check existing modules before inventing.** When in doubt about a control, copy the alerts or analytics module verbatim before deciding to deviate. Cross-references already in this spec:

- **Cards / coloured left border** → `trafficure.core/alert-card.tsx` (`border-l-[5px]`, neutral body, dividers between rows).
- **2×2 KPI grid** → `analytics-right-panel/detail-sections.tsx` `StatsGrid4` (`overflow-hidden rounded-lg border border-scale-300`, two columns, 1 px dividers).
- **Right-panel header + tabs** → `analytics-right-panel/analytics-right-panel.tsx` `DetailTabs` (forest underline on active, `text-base font-medium`).
- **Section labels** → analytics' `SectionLabel` (small, uppercase, `tracking-wider`, dark grey).
- **Stat highlight hexes** → analytics' palette: red `#D93025`, orange `#E37400`, green `#1E8E3E`.
- **Inset surface** → `bg-scale-100` (`#FAF8F5` cream) for grouped content, never inset white-on-white.

If a new affordance shows up during implementation that isn't covered here or in those modules, stop and reuse the closest existing pattern from analytics/alerts before drawing something new.

### Spacing and shape

- **Radius:** `rounded-lg` (8 px) for cards, KPI grids, story block, segment rows, stage cards. `rounded-md` (6 px) for buttons. `rounded-full` only for pills and the verdict dot.
- **Card padding:** `px-4 py-3` minimum, `px-4 py-4` for the right-panel sections that contain a stat grid + body. **No tight `p-2` cards** anywhere — cramped feels developer-tool.
- **Block spacing inside the right panel:** `gap-4` (16 px) between top-level blocks (story → KPI grid → chain). Inside a block, `gap-2`–`gap-3`.
- **Borders** are 1 px, never thicker, except the verdict left-border accent on the corridor card and the 3 px inset border on hover/focused rows.

### Type rules — what's allowed at what size

| Use | Class | Notes |
|---|---|---|
| Card title (corridor name, stage name, KPI value, story body) | `text-base` minimum; `text-lg font-bold` for KPI values and corridor titles | This is the floor for body text. |
| Sub-line under a title (`Pune · 6 segs · 4.4 km`, `522 m · ff 31.8 km/h`) | `text-sm text-scale-1000` | Allowed exception: only one level below the title. |
| Section label (`SEGMENTS ALONG THE CORRIDOR`) | `text-xs uppercase tracking-wider font-bold text-scale-1000` | Exception: visual differentiation. |
| Status pill / verdict pill | `text-xs font-bold` | Exception: pills are functional UI. |
| Legend descriptions | `text-xs` | Exception: lives over the map. |
| Tabs | `text-base font-semibold` | Match `DetailTabs` in analytics. |

Anything that doesn't fit a row above defaults to **`text-base`**. If a future addition wants to drop below `text-base`, the implementer must justify it against this table.

### Colour rules — secondary text floor

- Secondary / meta text uses `text-scale-1000` (`#374151`) — readable on white and on cream.
- **Never** use `text-scale-700` (`#9AA0A6`) for content. It's reserved for things like inactive icon strokes and disabled-state placeholders.
- **Never** use `text-scale-800` for body content either; if a piece of text is "less important", lower its size, don't lighten its colour. Visibility wins over hierarchy.

## Type & colour rules (apply to every component below)

- **Min font size: `text-base`** for all body text — corridor titles, sub-lines, story text, KPI labels, segment names, stage summaries. Allowed exceptions, kept narrow:
  - Status pills, verdict pills, and uppercase section labels (`tracking-wider`) may use `text-xs`.
  - Sub-meta lines that quantify a row (e.g., `522 m · ff 31.8 km/h · conf 0.50 MEDIUM` under a segment name) may use `text-sm`.
  - The legend may use `text-xs` for verdict descriptions because it sits over the map.
- **Secondary text** uses `text-scale-1000` (`#374151`) — not the washed-out `text-scale-700`.
- **Borders** use `border-scale-300`–`scale-500` family (`#D8D2CB` / `#ECE5DC`) — never `scale-200`.
- **Saturated colour is reserved for verdicts and KPI value highlights.** Pills, dots, the left-border accent on the corridor card, and the highlight hex on KPI values are the only places we use saturated colour. Surfaces stay neutral (white, cream `#FAF8F5`).
- **KPI value highlight hexes** match `StatsGrid4` in `analytics/detail-sections.tsx`: red `#D93025`, orange `#E37400`, green `#1E8E3E`. Use these in the Verdict tab's KPI grid for parity with analytics.
- **Tabular nums** for every number that's read in a column (lengths, speeds, confidence, percentages).

### Verdict palette (single source of truth)

| Verdict | Letter | Dot fill | Pill bg / text / border |
|---|---|---|---|
| `ACTIVE_BOTTLENECK` | A | `#b91c1c` | `#fee2e2` / `#991b1b` / `#fecaca` |
| `HEAD_BOTTLENECK`   | H | `#dc2626` | `#fee2e2` / `#991b1b` / `#fecaca` |
| `QUEUE_VICTIM`      | Q | `#ea580c` | `#ffedd5` / `#9a3412` / `#fed7aa` |
| `SLOW_LINK`         | S | `#a16207` | `#fef9c3` / `#854d0e` / `#fde68a` |
| `FREE_FLOW`         | F | `#16a34a` | `#dcfce7` / `#166534` / `#bbf7d0` |
| `NO_DATA`           | ? | `#737373` | `#f5f5f5` / `#525252` / `#e5e5e5` |

Centralize this in a single TS module (`verdict-style.ts` next to `corridor-heatstrip.tsx`) and import from every component below. The current `VERDICT_FILL` (in `corridor-heatstrip.tsx` and `corridor-card.tsx`) and `COLOR` (in `segment-card.tsx`) are deduped into it.

---

## 1. Left-panel corridor cards (`corridor-card.tsx`)

**Goal:** stop the cards from screaming. Verdict colour stays as an at-a-glance scan signal but moves to a thin left border, matching the alerts module pattern.

**Removed:**
- Gradient ribbon (`linear-gradient(90deg, ribbon.from, ribbon.to)`).
- Mini `Heatstripette` SVG.

**Added / changed:**
- `border-l-[5px]` keyed to `summary_verdict`:
  - POINT → `#b91c1c` (red)
  - SYSTEMIC → `#9a3412` (deep orange)
  - No prior run → `#D8D2CB` (neutral)
- Body becomes a single row: title + subtitle, with `Run` / `Re-run` button on the right (kept).
- Below the title, a single neutral text line: `POINT · 5 min ago` (or `SYSTEMIC · 12 min ago`, or `Not yet run` for no last_run). `text-scale-1000`, `text-base`.
- `selected` state: keep the existing amber `ring-2 ring-amber-500`.

**Layout:**
```
┌─[5px verdict colour]──────────────┐
│  Magarpatta → Hadapsar     [Run]  │
│  Pune · 6 segs · 4.40 km          │
│  POINT · 5 min ago                │
└───────────────────────────────────┘
```

---

## 2. Right-panel header (`corridor-diagnostics-right-panel.tsx`)

**Locked: option A (minimal) + close button.**

- Title row: `corridor.name` + verdict pill (POINT/SYSTEMIC) inline, `text-lg font-bold`. Right side: `View full report ↗` link, then a 28×28 outlined `×` close button (`border-scale-300`).
- Sub-line: `<city> · <slice> · <n_segments> segments · <km> km`, `text-base text-scale-1000`.
- Tabs `Verdict` / `Stages` immediately below the divider, `text-base font-semibold`, forest underline on active (matches `analytics-right-panel.tsx` `DetailTabs`).
- Close button clears `?corridor` and `?slice` from the URL and emits `corridor-diagnostics.selection.clear` so the right panel collapses.

**Note on the verdict pill:** the pill is computed from the same `isSystemic` logic that today drives `summaryVerdict` in `verdict-tab.tsx`. Hoist that derivation into a hook (`useCorridorVerdict(job)`) so the header and the Verdict tab don't drift.

---

## 3. URL shape

Drop `?job=<uuid>`. Use named, stable params:

- `?corridor=<cid>` — required when the right panel is open.
- `&slice=weekday|weekend` — required when corridor is set.
- `&segment=<road_id>` — optional, present iff a segment is focused.

The route reducer resolves `(corridor, slice)` → `job_id` via the existing `fetchSnapshot()` call. `job_id` becomes purely internal state. Bookmarks survive re-runs.

When the user clicks `Run` on a corridor card, the URL updates to that `corridor` (slice unchanged — slice is global to the panel and toggled separately). Once the job lands, the right panel renders the new snapshot. If a `?segment` was set for a different corridor, it's dropped on corridor change.

When `?segment` is set on initial load, the panel scrolls the row into view and flies the map to the segment's bbox.

---

## 4. Map paths and markers (`corridor-diagnostics-map-layer.tsx`, `corridor-diagnostics-overlay-layer.tsx`)

### 4.1 Paths — reuse `TrafficRoadHighlightLayer`

**Replace** today's three custom deck.gl layers (a black shadow `PathLayer`, a verdict-coloured `PathLayer`, a `TextLayer` rendering `"N·L"` pills) with a single **`TrafficRoadHighlightLayer`** — the same composite layer the rest of the product already uses (`roads-layer.tsx`, `traffic-layer.tsx`, `citypulse-overlay-layer.tsx`). It comes with built-in casing rendering and a built-in `arrowLength` prop that generates true along-the-path arrows via `generateArrowLines()` in `traffic-utils.ts`. We do not draw any custom chevron geometry.

Per-feature props derived from the active segment id (`focusedId ?? hoveredId`):

| Prop | Idle (segment != active) | Active (segment == active) |
|---|---|---|
| `getCasingColor` | `[255, 255, 255, 255]` | `[255, 255, 255, 255]` |
| `getCasingWidth` (px) | `12` | `18` |
| `getColor` | verdict RGBA | verdict RGBA |
| `getWidth` (px) | `5` | `6` |
| `arrowLength` | `null` | `15` (or `getArrowSizeForZoom(zoom, 6).arrowLength` when zoom-aware sizing is desired — pick whichever the analytics overlays standardize on) |

`pickable: true` so the layer emits its own `onHover` / `onClick`. We do not need the standalone shadow `PathLayer` anymore; the casing covers it.

**No end-cap arrowhead at the corridor terminus.** The arrows belong to the active segment only.

**No dimming** of the other segments. The only visual change on the map when something is active is the active segment growing thicker and gaining arrows.

The casing layer's white ends naturally read as boundary ticks between adjacent verdict colours, so we do not draw extra ticks.

### 4.2 Markers — circular verdict badge via `IconLayer`

**Replace** the existing `TextLayer` (`"N·L"` text pills) with a deck.gl **`IconLayer`** rendering the same circular badge used in the right-panel chain.

- Badge: 28 px circle, fill = verdict colour, white letter (F/A/H/Q/S/?), `box-shadow: 0 0 0 3px #fff`.
- **No order chip** on the map (the map is the geographic view; segment numbering belongs in the panel).
- Generate the icon atlas once via an off-screen canvas, keyed by `verdict` only — one icon per verdict.
- Position: geometric midpoint of the segment polyline (the same `midpoint(path)` we already compute in `corridor-diagnostics-map-layer.tsx`).
- Active state (hover OR focused — visually identical): badge scales to 1.15× and the white halo grows from 3 px to 4 px. No colour change.
- `pickable: true`, so map → panel hover/focus wiring works from the badge as well as from the path.

The `text` field on `CorridorOverlaySymbol` is no longer needed; the type becomes `{ id, position, verdict }` (the `rgba` is implicit in the icon atlas key).

---

## 5. Map legend (`map-overlay/legend.tsx`) — two-tier

**Default state: compact horizontal strip** at `bottom: 14, left: 14`.

```
[F] Free  [A] Active  [H] Head  [Q] Queue  [S] Slow  [?] No data    [?]
```

- Each pair is a 16-px badge (same icon language as the map markers) + a single-word label, `text-xs`, `text-scale-1100`.
- A small `?` button at the right expands to the full card.

**Expanded state:** the same card the legend already produces today — badge + label + 1-line description per verdict. `text-xs` for descriptions stays acceptable (legend exemption from the `text-base` rule).

State persisted to `localStorage["cd.legend.expanded"]`.

---

## 6. Verdict tab (`verdict-tab.tsx`)

The current `CorridorHeatstrip` at the top of this tab is **removed** (the chain replaces it; the heatstrip duplicated information without adding any).

**New top-to-bottom layout, 14 px gap between blocks:**

### 6.1 Story block
- A labelled cream surface (not a left-border stripe). `bg-[#FAF8F5]`, `border border-scale-300`, `rounded-lg`, `padding 10px 12px`.
- Small label `Verdict` (forest-coloured, uppercase `text-xs font-bold tracking-wider`) on top.
- Body `text-base text-scale-1200 leading-relaxed`. Drawn from `job.story`.
- Hidden if `job.story` is empty.

### 6.2 KPI grid (2×2)
- Mirrors `StatsGrid4` from `analytics-right-panel/detail-sections.tsx`: `overflow-hidden rounded-lg border border-scale-300`, two columns, 1 px dividers between cells.
- Cells: each `padding 10px 12px`, label `text-base text-scale-1000`, value `text-lg font-bold tabular-nums`, sub `text-sm text-scale-1000`.
- Cells (in this order):
  1. **Total length** — `<km>`, sub `<n> segments`. Neutral colour.
  2. **Free flow** — `<km>`, sub `<pct>% of corridor`. Green (`text-[#1E8E3E]`).
  3. **Stuck** — `<km>`, sub `A:<n> · H:<n> · Q:<n> · S:<n>` (only nonzero counts). Red (`text-[#D93025]`).
  4. **Pattern** — `POINT` or `SYSTEMIC`, sub `simultaneity <pct>% · contiguity <pct>%`. Orange (`text-[#E37400]`) for POINT; deeper red-orange (`text-[#9a3412]`) for SYSTEMIC.

This replaces the current `KpiRow` 4-column horizontal layout.

### 6.3 Per-segment chain
Section header: `Segments along the corridor` (`text-xs font-bold uppercase tracking-wider text-scale-1000`), with a right-aligned hint `tap a row or the map to focus` in `text-sm text-scale-1000 normal-case`.

Below it, a vertical timeline:

- 36-px-wide left rail, 1 px column for the rail line (`border-scale-300`, `2 px wide`).
- Each row's `dot`: 26 × 26 px circle, fill = verdict colour, white letter, white halo (`box-shadow: 0 0 0 3px #fff`).
- Downward arrow (5×4 triangle, colour `#94A3A0`) below each dot except the last.
- Row content in a 2-column subgrid: main column (id + pill, name, meta) on the left, deep-link button on the right.
- Main column:
  - Line 1: `S0X` (`text-base font-bold tabular-nums`) + verdict pill (`text-xs font-bold rounded-full bg/border/text from palette`).
  - Line 2: road name (`text-base text-scale-1200`).
  - Line 3: `<length_m> m · ff <ff_speed> km/h · conf <score> <LABEL>` (`text-sm text-scale-1000`). Sub-line is exempt from `text-base`.
- Deep-link button: 28 × 28 outlined button with `↗` glyph, `title="Open segment in Analytics"`, `aria-label` set. `onClick`: opens `/analytics/<segment.road_id>` in a new tab. `event.stopPropagation()` so it doesn't trigger focus.
- Row separator: 1 px `border-scale-200`-ish (`#ECE5DC`) at the bottom of `.rcontent`. Last row has no separator.

The existing `SegmentCard` component (in `right-panel/segment-card.tsx`) is replaced. The `confidence.components` deep-dive (currently a collapsible "Components" section under each segment row) is **moved to the Stages tab's Confidence stage** — we never want two places that show the same components grid.

#### States

Hover and focused are **visually identical**. The only difference is stickiness.

- **Idle:** as above.
- **Active (hover OR focused):** `.rcontent` gets `bg-scale-100` (`#FAF8F5`) + a slightly stronger inset `box-shadow: inset 3px 0 0 #0D3B2E` and the dot scales 1.1× with its white halo growing from 3 px to 4 px. No coloured tint, no amber/forest split — same affordance the map paths use ("active" = grow, no colour change).

Focused stays applied until cleared (clicking the row again, clicking empty map, Esc, or closing the panel). Hover applies only while the cursor is over the row or the matching map element.

---

## 7. Stages tab (`stages-tab.tsx`)

**Replace** the current 10 accordions, each rendering `JSON.stringify(val, null, 2)`, with 10 numbered structured cards. **No raw JSON anywhere.**

### Top-of-tab controls
- A single thin row above the cards: left side `<n> stages`, right side `Expand all` / `Collapse all` text link (toggles based on current global state).
- `bg-[#FAF8F5]`, `border-b border-scale-300`, `padding 8px 16px`, `text-sm`.

### Stage card structure (uniform across all 10)
- `border-bottom border-scale-300`, `padding 12px 16px`, `cursor-pointer` (clicking the header toggles).
- **Header row** (always visible):
  - 24 × 24 circular numbered chip (`bg-forest text-white`).
  - Stage name `text-base font-semibold`.
  - Status pill on the right (uppercase, rounded-full, `text-xs font-semibold`):
    - `s-ok` — green (`bg-[#dcfce7] text-[#166534]`)
    - `s-warn` — amber (`bg-[#fef9c3] text-[#854d0e]`)
    - `s-fail` — red (`bg-[#fee2e2] text-[#991b1b]`)
    - `s-empty` — neutral (`bg-[#f5f5f5] text-[#525252]`)
    - `s-info` — blue (`bg-[#dbeafe] text-[#1d4ed8]`)
  - Chevron `▸` / `▾` at the far right.
- **One-line summary** below the header (always visible), `text-base text-scale-1000`, indented 34 px to align with the stage name.
- **Body** (only when expanded), indented 34 px, top margin 12 px.

### Default open state and persistence
- All cards collapsed by default.
- Toggle stored in `localStorage["cd.stages.open"]` as a JSON `Record<stageKey, boolean>`. Survives reloads.
- The `Expand all` / `Collapse all` link toggles all keys at once.

### Shared body primitives

The body of each stage uses one or more of these primitives. They live in `right-panel/stages-primitives.tsx` (new file).

#### `<StatGrid cells={...} cols={3|4} />`
- `border border-scale-300 rounded-lg overflow-hidden`, `grid grid-cols-{cols}`.
- Cell: `padding 9px 12px`, label `text-sm uppercase tracking-wider text-scale-1000`, value `text-lg font-bold tabular-nums`, optional sub `text-sm text-scale-1000`.
- Optional `highlight: "ok" | "warn" | "bad"` per cell — recolours the value.

#### `<SegTable columns={...} rows={...} />`
- A small per-segment table for stages whose data is naturally tabular.
- `border border-scale-300 rounded-lg overflow-hidden`, `text-base tabular-nums`.
- Header: `bg-[#FAF8F5] text-sm uppercase tracking-wider text-scale-1000 font-semibold`.
- Each row's first cell is a 22 × 22 dark numbered pill (the segment order).
- Cells right-align numerics. Last row has no border-bottom.

#### `<WindowBar buckets={...} totalBuckets={720} />`
- A 720-bucket time-of-day bar (00:00–23:58 IST). 14 px tall, cream background, 1 px border.
- Each `[start, end]` window is a soft-tinted span with red side-bars.
- Below the bar, a small axis: `00:00 · 06:00 · 12:00 · 18:00 · 23:58`, `text-xs text-scale-1000`.
- Used by Bertini and Head-bottleneck stages.

#### `<PairRow pair, observed, expected, dist, pass />`
- `border border-scale-300 rounded-lg`, `padding 8px 12px`, `text-base`.
- Format: `[N] → [M]   obs <X> min   expected <a>–<b> · <d> m   PASS|FAIL`.
- PASS in green, FAIL in red, both `font-semibold`.
- Used by Shockwave stage.

#### `<ConfidenceComponents components={...} />`
- A wrap of small pills, each `border border-scale-300 rounded-full`, with a 6 × 6 dot (green / amber / red based on the value bucket: ≥0.66 / 0.33–0.66 / <0.33) and the label + value.

### Per-stage content

For each stage, the card shows:

| # | Stage | Status pill text | Summary one-liner | Body |
|---|---|---|---|---|
| 1 | **Free-flow discovery** | `<n>/<total> anchored` (ok if all anchored, warn otherwise) | `Quiet windows in <hh:mm>–<hh:mm> IST band. ff_speed <min>–<max> km/h. <weekdays> weekdays, <date_range>.` | StatGrid (4 cols): Date range / Weekdays sampled / Bins per segment (`720`, sub `2-min, 24h`) / Clamps fired (ok if 0). SegTable: `Seg / Road / ff_tt (s) / ff_speed / Quiet windows`. |
| 2 | **Baseline flags** | `no saturation` / `<n> saturated` | `Corridor median <X> km/h. Peer ratios <a>–<b>. Quiet/busy ratios <a>–<b>.` | SegTable: `Seg / ff km/h / peer ratio / quiet/busy / flag`. |
| 3 | **Primary windows (v2.1)** | `empty` (s-empty) or `<n> windows` | `<n> primary congestion windows detected.` or `No primary congestion windows detected on any segment.` | If non-empty: SegTable with start/end + segs covered. If empty: no body. |
| 4 | **Bertini cascade** | `<n> firing` (warn if ≥1, info if 0) | `S0X fires bucket <a>–<b>` (one summary sentence per firing) | WindowBar showing firing windows; if multiple segments fire, one bar per segment with a leading `S0X` chip. |
| 5 | **Head bottleneck** | `<n> candidates` | `Buckets <a>–<b>, <c>–<d>, …` | Single WindowBar with all candidates shaded. |
| 6 | **Shockwave / queue** | `pass <p>/<total>` | `<mode> mode. <p> pair(s) within expected lag, <f> fail.` | List of `<PairRow>` (one per `pairs[]`). |
| 7 | **Systemic (v2)** | `no windows` / `<n> windows` | `Peak simultaneity <pct>% (<n>/<total> segs). Threshold ≥ <t>. Verdict: <POINT/SYSTEMIC>.` | StatGrid (3 cols): Max simultaneous / Max fraction / Systemic threshold. If `systemic_windows.length > 0`, append a SegTable. |
| 8 | **Systemic (v2.1 contiguity)** | `not contiguous` / `contiguous` | `Peak contiguous fraction <pct>% at S0a–S0b (bucket <b>).` | StatGrid (3 cols): Max contig frac / Peak bucket (sub: HH:MM IST) / Peak segs. |
| 9 | **Recurrence typing** | `<n> RECURRING · <m> FREQUENT` (ok overall) | `Onset present on ≥75% of weekdays for <n>/<total> segments.` | SegTable: `Seg / days / fraction / label`. |
| 10 | **Confidence** | `avg <X> <LABEL>` | `Per-segment <min>–<max>. Driven by <top-component-1> + <top-component-2>; <weakest> is the weakest input.` | SegTable: `Seg / score (with bar) / label / components`. The `components` cell renders `<ConfidenceComponents>`. |

**Bucket → time conversion:** every bucket index `b` is rendered in IST as `hh:mm` using `b * 2` minutes from `00:00`. Centralized helper `bucketToIst(b: number): string` in `stages-primitives.tsx`.

**Status pill derivation:** lives in a single `deriveStageStatus(key, payload)` function — keeps the rendering layer free of branching.

**Missing payload:** if a stage's payload is `null` or `undefined`, render the card with status `s-empty` and the summary `Not available for this run.` — never throw, never render JSON. (Some stages legitimately don't fire on every corridor; calling that "fail" would be misleading.)

---

## 8. Hover / focus interaction model

Centralized through the existing `rio.events` bus.

### Events

| Event | Payload | Emitted by | Consumed by |
|---|---|---|---|
| `corridor-diagnostics.segment.hover` | `{ road_id: string \| null }` | Map marker, panel row | Map marker, panel row, heatstrip (none after redesign) |
| `corridor-diagnostics.segment.focus` | `{ road_id: string \| null }` | Map marker (click), panel row (click) | Map marker, panel row, URL syncer, map camera |

### Behaviour

Hover and focused share the same visual treatment — only the lifetime differs.

| Action | Effect |
|---|---|
| Hover map badge / segment path | Fire `segment.hover`. Panel row goes active. Panel scrolls into view if off-screen. No URL change. |
| Hover panel row | Fire `segment.hover`. Map segment goes active (path grows + arrows appear, badge scales). Map does **not** pan. |
| Click map badge / segment path | Fire `segment.focus`. Panel row stays active. Panel scrolls + sticks. Map flies to the segment bbox. URL gets `&segment=<road_id>`. |
| Click panel row | Same as clicking the map element. |
| Click `↗` deep-link | Opens `/analytics/<road_id>` in a new tab. Does **not** fire focus or hover. |
| Click empty map / Esc / re-click the focused row | Fire `segment.focus` with `null`. URL drops `&segment`. |

### URL syncer

A small effect (`useSegmentFocusUrlSync`) listens to `segment.focus` and writes `?segment=` via `navigate({ search }, { replace: true })`. On mount, it reads `?segment` and emits an initial focus event. Replace not push — so back/forward still navigates corridor changes, not focus changes.

---

## 9. Component map (what changes in the repo)

| File | Change |
|---|---|
| `left-panel/corridor-card.tsx` | Strip ribbon + heatstrip. Add coloured left border + neutral status line. |
| `right-panel/corridor-diagnostics-right-panel.tsx` | Header A layout + close button. Hoist verdict derivation to `useCorridorVerdict`. |
| `right-panel/verdict-tab.tsx` | Remove heatstrip call. Reorder: story → KPI grid → chain. Replace `KpiRow` + `SegmentCard` stack. |
| `right-panel/kpi-row.tsx` | **Replace** with `KpiGrid` (2×2, alerts/analytics styling). Keep filename, change shape. |
| `right-panel/segment-card.tsx` | **Replace** with `segment-chain.tsx` rendering the timeline. Drop the components grid (moved to Stages → Confidence). |
| `right-panel/story-block.tsx` | Re-style: cream surface + `Verdict` label, drop the left border. |
| `right-panel/stages-tab.tsx` | Rewrite. New per-stage structured renderers via `stages-primitives.tsx`. |
| `right-panel/stages-primitives.tsx` | **New.** `StatGrid`, `SegTable`, `WindowBar`, `PairRow`, `ConfidenceComponents`, `bucketToIst`, `deriveStageStatus`. |
| `corridor-heatstrip.tsx` | **Delete.** No longer rendered anywhere. Move `VERDICT_FILL` to `verdict-style.ts`. |
| `verdict-style.ts` | **New.** Single source of truth for the verdict palette + helper `verdictLetter(v)`. |
| `map-overlay/legend.tsx` | Two-tier (compact strip ↔ expanded card). |
| `corridor-diagnostics-map-layer.tsx` | Build IconLayer atlas (canvas-rendered badge per verdict). Drop `text` field on symbols. Make symbols pickable. |
| `corridor-diagnostics-overlay-layer.tsx` | Replace `TextLayer` with `IconLayer`. Add hover + focus ring rendering. |
| `data/use-corridor-diagnostics-state.ts` | Add `useFocusedSegment()` + URL sync. Read `?corridor` / `?slice` / `?segment` on mount. |
| `data/use-job-poll-query.ts`, `use-run-mutation.ts` | No change. |
| Routing (wherever `/corridor-diagnostics` is mounted) | Replace `?job=<uuid>` with `?corridor`/`?slice` parsing. Keep snapshot resolution path. |

## 10. Testing notes

- The verdict palette source of truth (`verdict-style.ts`) is unit-testable: every `Verdict` literal returns a defined entry.
- `bucketToIst` and `deriveStageStatus` are pure — unit-test directly.
- The hover / focus event chain has three subscribers (map, panel, URL syncer) — test in `corridor-diagnostics-project-provider.tsx` integration tests by firing events and asserting state.
- Visual regression: snapshots of the Verdict tab in `idle` / `hover` / `focused` states for one POINT and one SYSTEMIC corridor.

## 11. Migration / rollout

- No backend migration. The structured payload shape is unchanged.
- Client-side: ship behind no flag — the redesign replaces the existing UI atomically. The current view has no users outside the team; there's no surface area worth feature-flagging.
- After ship, delete `corridor-heatstrip.tsx` and `segment-card.tsx`'s old confidence-components grid in the same PR. No "kept for backwards compat" leftovers.
