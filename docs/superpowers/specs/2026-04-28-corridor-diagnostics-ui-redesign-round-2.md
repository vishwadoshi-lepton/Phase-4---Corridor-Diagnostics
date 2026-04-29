# Corridor Diagnostics UI Redesign — Round 2 Refinements

**Date:** 2026-04-28
**Module:** `trafficure.corridor-diagnostics` (frontend)
**Status:** Approved, ready for implementation planning
**Supersedes:** sections 1, 2, 4.2, 6, 6.3 of `2026-04-28-corridor-diagnostics-ui-redesign.md`. All other sections of round 1 still hold.

## Why round 2

Round-1 shipped a working redesign, but a side-by-side comparison with the analytics module surfaced a handful of consistency gaps. The header still felt prototype-y, the panel body had no surface treatment to anchor the cards, the segment chain had a heavy click+focus lifecycle that wasn't paying for itself, and the map markers' white halo disappeared on light basemaps. Round 2 closes the gap so the diagnostic panel reads as part of the same product as alerts, analytics, and route-monitoring.

Reference modules (read these before implementing):
- `trafficure.analytics/components/analytics-right-panel/analytics-right-panel.tsx` — `CorridorDetailHeader`, the white→cream gradient, `<DetailTabs>` underline tabs.
- `trafficure.analytics/components/analytics-right-panel/detail-sections.tsx` — `SectionLabel`, `StatsGrid4`/`StatsGrid6` (already mirrored in our `KpiGrid`).
- `trafficure.analytics/components/analytics-right-panel/analytics-right-panel-skeletons.tsx` — `PanelSectionShell` (the white card on cream pattern).
- `trafficure.core/traffic-layer.tsx:43–55` — the `isLightBaseMap` derivation and `highlightBorderColor` swap.

## Round-2 decisions

### R2.1 — Surface palette (right panel + left panel)

**Right panel:**
- Outer panel container: `bg-scale-100` (`#FAF8F5`) — the cream/grey surface.
- Header (`.ph`): `bg-gradient-to-b from-white to-scale-100`, `border-b border-scale-300`, `px-4 py-3`. The gradient lets the bottom of the header blend into the cream body.
- Body wrapper: `flex flex-col gap-2 px-3 py-3` (or `gap-3` if rows feel cramped).
- Section card: `bg-white` + `border border-scale-300` + `rounded-lg` + `shadow-sm` + `p-4`. Each section card has an internal `<SectionLabel>` at the top.
- KPI grid stays `bg-white` inside the section card; its 1 px dividers separate cells. (No nested coloured surface inside white-on-grey.)

**Left panel** (mirrors the right):
- Outer container: `bg-scale-100` (cream).
- Top sub-tabs strip (Pre-built / From route / Custom): `border-b border-scale-300`, `px-3 py-2`. Tab buttons: white pill (`bg-white border border-scale-300 rounded-md`); active tab inverts to dark (`bg-scale-1200 text-white border-scale-1200`).
- Card list: `flex flex-col gap-2 p-3` on the cream surface.
- Slice toggle footer: a white strip pinned at the bottom (`bg-white border-t border-scale-300`, `px-3 py-2.5`) — the only persistent control on the panel keeps a clear anchor.

This is the same pattern analytics uses today; we're not inventing surface treatment.

### R2.2 — Right-panel header

Replaces section 2 of round 1.

- **Title row:** corridor's human name (`cdef.name`, e.g. "Fakri Hill Chowk → Mohammadwadi"), `text-xl font-bold text-scale-1200 truncate`. Right-aligned: `×` close button as a 32 × 32 ghost icon button (`<Button variant="ghost" size="icon">` with Phosphor `icon-[ph--x]`), no border.
- **Sub-line (single row, below the title):**
  - Left side: `[POINT|SYSTEMIC pill]  Weekday` (or `Weekend`). The verdict pill is `text-xs font-bold uppercase tracking-wider rounded-md px-2 py-0.5`. The slice text is `text-sm text-scale-1000`. **No segment count, no km here** — those move into the "Corridor stats" KPI grid below where they're already shown.
  - `flex-1` spacer fills the remaining width.
  - Right side: a 32 × 32 icon-only ghost button with Phosphor `icon-[ph--download-simple]`. **Tooltip on hover: "Download full report"**. Action: opens `job.dry_run_html_url` in a new tab. The previous `View full report ↗` text link is replaced.

The tabs sit immediately below the header inside the same gradient surface.

### R2.3 — Tabs

Replaces the segmented-control look. Match analytics' `DetailTabs`:

```
flex border-b border-scale-300        (container)
flex-1 py-2 text-center text-base font-medium border-b-2 -mb-px   (tab)
active   →  border-forest-600 text-forest-600
inactive →  text-scale-1000 border-transparent hover:text-scale-1200
```

No rounded pills around the tabs.

### R2.4 — Segment chain interaction model

Replaces section 6.3 "States" + section 8 of round 1.

- **Hover only.** Click on a row no longer triggers focus.
- **No `?segment` URL state.** The `&segment=` parameter is removed entirely. We do not write or read `?segment`.
- **`useSegmentFocus` collapses to `useSegmentHover`** — only `hoveredId` + `emitHover`, no focused state, no scroll-into-view, no URL syncer. The module is renamed for clarity.
- **Visual:** the active row gets `bg-[rgba(13,59,46,0.04)]` (very subtle forest tint) + `rounded-md`. **No** inset border, **no** scale-up on the dot, **no** halo growth. The map mirrors: only the casing+arrows grow on hover, the badge does not scale (drop the 30→34 jump from round 1).

This drops a lot of code — the entire URL syncer, the focus event subscriptions, the scroll-into-view effect, the dot's `scale(1.1)` transform, and the `?segment` param handling in `parseCorridorParams`/`buildCorridorSearch`. Keep `parseCorridorParams` returning `segment: null` for backwards-compat-on-load (a stale link with `?segment=` should still load the panel without crashing), but stop writing it.

### R2.5 — Per-segment deep-link button

Replaces the `↗` text-arrow button.

- Square 32 × 32 button, `rounded-md`, `bg-[rgba(99,102,241,0.10)]` (soft indigo wash), `text-[#4f46e5]` (indigo-600).
- Icon: Phosphor `icon-[ph--arrow-square-out]` (16 × 16 inside the button).
- **Tooltip on hover: "View segment analytics"** — use the existing `<InfoTooltip>` / tooltip primitive in `trafficure.core/components/info-tooltip.tsx`, or a Radix tooltip if that's the rio convention. Default trigger is hover; respect the screenshot the user attached.
- Hover: `bg-[rgba(99,102,241,0.18)]`. Click: opens `/analytics/<encodeURIComponent(segment.road_id)>` in a new tab. `event.stopPropagation()` because the row no longer has its own click handler, but the button still shouldn't bubble.

### R2.6 — Type & color rules (re-affirmed)

- **Min `text-base`** for body, with the same exceptions as round 1: pills, section labels, sub-meta lines, legend.
- **Explicitly fix every remaining `text-scale-700`** for content text in the corridor-diagnostics module — replace with `text-scale-1000`. Implementer must grep before merge: `grep -rn "text-scale-700" src/modules/trafficure.corridor-diagnostics`. Out-of-scope tabs (segments-tab / routes-tab / run-button / run-progress-chip) are still allowed to keep their existing styling — only fix what's reachable from the new flow.
- **`text-[11px]` is banned for content.** The remaining instance in `corridors-tab.tsx`'s slice toggle was already replaced in the round-1 review fix; verify nothing else uses it.

### R2.7 — Map markers + paths on light basemaps

Replaces section 4.2 of round 1's halo treatment.

Read the basemap style from the rio store and pick the contrast color:

```tsx
import { useMapsRow } from "@rio.js/maps-ui/hooks/use-maps-row" // or whatever the project uses

const mapRow = useMapsRow("main")
const isLightBaseMap = Boolean(mapRow?.style && mapRow.style.toLowerCase().includes("light"))
const haloRgba: [number, number, number, number] = isLightBaseMap
  ? [60, 65, 67, 255]
  : [255, 255, 255, 255]
```

Apply this `haloRgba` to:
1. **The IconLayer atlas:** when generating the per-verdict badge canvas (`buildIconAtlas`), the outer "halo" ring (currently drawn with `ctx.fillStyle = "#FFFFFF"` at radius 26) becomes `rgb(${r}, ${g}, ${b})` from `haloRgba`. The atlas must be rebuilt when `isLightBaseMap` changes — key `useMemo` on `isLightBaseMap`.
2. **The path casing:** in the two `TrafficRoadHighlightLayer` calls, `borderColor` becomes the same `haloRgba` instead of hard-coded white.

`TrafficRoadHighlightLayer` already exposes `borderColor` as a prop. The pattern of swapping it on `isLightBaseMap` is exactly what `traffic-layer.tsx:54-56` does today (`highlightBorderColor`). Reuse that derivation, do not invent new flags.

Halo and casing always travel together — don't update one without the other or you'll get a black-haloed badge sitting on a white-casing line.

### R2.8 — Component map (incremental — what changes from round 1)

| File | Change |
|---|---|
| `corridor-diagnostics-right-panel.tsx` | Header gradient, sub-line restructure, ghost `×`, icon-only download button + tooltip. Wrap body in `bg-scale-100`. |
| `right-panel/verdict-tab.tsx` | Each section (story / kpi / chain) wrapped in a new `<SectionCard>` with internal `<SectionLabel>`. Body container becomes `flex flex-col gap-2 px-3 py-3`, no longer `gap-4 px-4 py-4`. |
| `right-panel/section-card.tsx` | **New.** `bg-white border border-scale-300 rounded-lg shadow-sm p-4` + internal label slot. |
| `right-panel/section-label.tsx` | **New.** `text-sm font-semibold text-scale-1200 uppercase tracking-[0.08em] mb-2.5`. (Or imports the analytics one if it's exported.) |
| `right-panel/segment-chain.tsx` | Drop click handler on the row (delete `onClick`). Drop scale + halo growth on the dot. Replace `↗` button with the new soft-indigo `<button>` containing the `arrow-square-out` SVG + tooltip. Add tooltip via existing tooltip primitive. |
| `data/use-segment-focus.ts` | Rename file → `use-segment-hover.ts`. Strip everything except `hoveredId` + `emitHover`. Drop the URL syncer + `setSegment` import. |
| `data/use-corridor-url-state.ts` | Keep `parseCorridorParams` returning `segment: null` for stale-link tolerance, but drop `setSegment` from the returned API. |
| `corridor-diagnostics-overlay-layer.tsx` | Stop reading focus state. Use only `hoveredId`. Atlas now keyed on `isLightBaseMap`; halo color matches; `borderColor` of both `TrafficRoadHighlightLayer` instances swaps with the basemap. Drop the active badge `getSize` 30→34 — keep the active segment's casing + arrows growth, but the badge stays at 30 throughout. |
| `corridor-diagnostics-map-layer.tsx` | No change beyond what round-1 ship already did. |
| `left-panel/corridor-diagnostics-left-panel.tsx` | Outer wrapper `bg-scale-100`. Sub-tabs row gets `border-b border-scale-300`. |
| `left-panel/corridors-tab.tsx` | List wrapper becomes `flex flex-col gap-2 p-3`. Footer gets `bg-white border-t border-scale-300`. |
| `left-panel/corridor-card.tsx` | Add `shadow-sm` (was already `border border-scale-300`). Slightly larger `text-base` title (was `text-sm`/`text-base` mixed). |
| `right-panel/segment-card.tsx` | Already deleted in round 1 — no action. |

## Out of scope (still)

- Backend / API changes.
- Mobile / narrow-width layout.
- The legacy `?job` URL flow used by `segments-tab` / `routes-tab` / `run-button` — out of scope per the round-1 carve-out and still out of scope here. The `RunProgressChip` already bridges both flows after the round-1 review fix.
- The "stages" tab body. Round 1's per-stage cards stand as-is (with the `PrimaryWindowsBody` SegTable fix from the review). No round-2 changes there.

## Acceptance criteria

1. Right panel: opens to a cream surface with three white section cards. Header reads `Fakri Hill Chowk → Mohammadwadi` (the human name). Sub-line is exactly `[POINT] Weekday` + a download icon on the right with a "Download full report" tooltip. Tabs are underlined, not pills.
2. Hovering a segment row in the chain tints it forest-very-faint and grows the matching map segment's casing + arrows. No click does anything to the row. The deep-link button works and shows "View segment analytics" on hover.
3. Switching the basemap from dark to light keeps the verdict badges + casing readable: halo flips from white to dark grey, casing flips with it.
4. Left panel: cream surface with white floating corridor cards (verdict-coloured 5 px left border). Slice footer is a white strip at the bottom.
5. No `?segment` URL parameter is ever written; loading a stale link with `?segment=` doesn't crash but the segment isn't highlighted (no focus state exists).
6. `grep -rn "text-scale-700\|text-\[11px\]" src/modules/trafficure.corridor-diagnostics/components/{left-panel,right-panel,map-overlay,corridor-diagnostics-{map,overlay}-layer.tsx}` returns nothing for content text.
