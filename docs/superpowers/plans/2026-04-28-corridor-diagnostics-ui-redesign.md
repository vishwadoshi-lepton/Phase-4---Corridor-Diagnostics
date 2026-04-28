# Corridor Diagnostics UI Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the redesign in `docs/superpowers/specs/2026-04-28-corridor-diagnostics-ui-redesign.md` end-to-end in the trafficure frontend, then visually verify in Brave.

**Architecture:** All work lives in `~/Desktop/trafficure/src/modules/trafficure.corridor-diagnostics/`. We extract a single verdict-style module first, then refactor each surface (left card, header + URL, map paths/markers, legend, verdict tab, stages tab) atop it. Hover/focus is wired through `rio.events` end-to-end at the end. No backend changes.

**Tech Stack:** React + react-router (`useSearchParams`), Tailwind via the rio.js scale tokens, deck.gl via `@rio.js/maps-ui` (existing `TrafficRoadHighlightLayer` and `IconLayer`), vitest for unit tests. The repo uses `pnpm`.

**Working directory for every step:** `~/Desktop/trafficure`. The Phase 4 repo only owns the spec/plan; all code edits happen in trafficure.

---

## File structure (created/modified)

**New files** (under `~/Desktop/trafficure/src/modules/trafficure.corridor-diagnostics/`):
- `components/verdict-style.ts` — single source of truth for the verdict palette + helpers.
- `components/verdict-style.test.ts` — unit tests for palette helpers.
- `components/right-panel/segment-chain.tsx` — new vertical-timeline segments list (replaces `segment-card.tsx`).
- `components/right-panel/kpi-grid.tsx` — 2×2 KPI grid (replaces `kpi-row.tsx`).
- `components/right-panel/stages-primitives.tsx` — `StatGrid`, `SegTable`, `WindowBar`, `PairRow`, `ConfidenceComponents`, `bucketToIst`, `deriveStageStatus`.
- `components/right-panel/stages-primitives.test.ts` — tests for `bucketToIst` and `deriveStageStatus`.
- `components/right-panel/stage-cards.tsx` — per-stage card renderers (one function per stage).
- `data/use-segment-focus.ts` — focused/hovered segment state + URL sync (?segment).
- `data/use-corridor-url-state.ts` — `?corridor` / `?slice` resolver (replaces `use-corridor-diagnostics-state.ts`'s `useActiveJob`).
- `data/use-corridor-url-state.test.ts` — unit test for slice/corridor parsing.

**Modified files:**
- `components/left-panel/corridor-card.tsx` — strip ribbon + heatstrip; add coloured left border + neutral status line.
- `components/left-panel/corridors-tab.tsx` — adapt to new card props.
- `components/right-panel/corridor-diagnostics-right-panel.tsx` — header (option A) + close button + tabs (text-base font-semibold).
- `components/right-panel/corridor-diagnostics-right-panel-gate.tsx` — switch from `useActiveJob` to corridor/slice resolver.
- `components/right-panel/verdict-tab.tsx` — drop heatstrip; reorder to story → KpiGrid → SegmentChain.
- `components/right-panel/story-block.tsx` — restyle as labelled cream surface.
- `components/right-panel/stages-tab.tsx` — rewrite to use stage-cards.
- `components/corridor-diagnostics-map-layer.tsx` — emit per-segment overlay payload incl. active id.
- `components/corridor-diagnostics-overlay-layer.tsx` — `TrafficRoadHighlightLayer` (idle + active) + `IconLayer` (badges).
- `components/map-overlay/legend.tsx` — two-tier compact strip ↔ expanded card.
- `data/use-corridor-diagnostics-state.ts` — `useActiveSlice` kept; add re-exports for new hooks.
- `data/use-job-poll-query.ts` — extend to accept either `jobId` or `(corridor, slice)`.

**Deleted files:**
- `components/corridor-heatstrip.tsx` — no longer rendered.
- `components/right-panel/segment-card.tsx` — replaced by `segment-chain.tsx`.
- `components/right-panel/kpi-row.tsx` — replaced by `kpi-grid.tsx`.

**Path conventions:** every absolute path in this plan is relative to the trafficure repo root `~/Desktop/trafficure/`. Tests run from there with `pnpm test:unit`.

---

## Phase 0 — Pre-flight

### Task 0: Verify environment

**Files:** none

- [ ] **Step 1: Open the trafficure repo and confirm clean tree**

```bash
cd ~/Desktop/trafficure && git status
```
Expected: a clean working tree on the current branch (or whatever branch ships this work). If dirty, stash or commit existing work first.

- [ ] **Step 2: Confirm pnpm + vitest run**

```bash
cd ~/Desktop/trafficure && pnpm install --frozen-lockfile && pnpm test:unit -- --run --reporter=basic
```
Expected: dependencies resolve; vitest exits 0.

- [ ] **Step 3: Branch off**

```bash
cd ~/Desktop/trafficure && git switch -c feat/corridor-diagnostics-ui-redesign
```
Expected: switched to a new branch.

---

## Phase 1 — Verdict style module (foundation)

### Task 1: `verdict-style.ts` palette + helpers

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/components/verdict-style.ts`
- Create: `src/modules/trafficure.corridor-diagnostics/components/verdict-style.test.ts`

- [ ] **Step 1: Write the failing test**

`src/modules/trafficure.corridor-diagnostics/components/verdict-style.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  VERDICTS,
  verdictDotHex,
  verdictLetter,
  verdictPillClasses,
  verdictRgba,
  type Verdict,
} from "./verdict-style"

describe("verdict-style", () => {
  it("returns letter for every verdict", () => {
    expect(verdictLetter("ACTIVE_BOTTLENECK")).toBe("A")
    expect(verdictLetter("HEAD_BOTTLENECK")).toBe("H")
    expect(verdictLetter("QUEUE_VICTIM")).toBe("Q")
    expect(verdictLetter("SLOW_LINK")).toBe("S")
    expect(verdictLetter("FREE_FLOW")).toBe("F")
    expect(verdictLetter("NO_DATA")).toBe("?")
  })

  it("returns dot hex for every verdict", () => {
    for (const v of VERDICTS) {
      expect(verdictDotHex(v)).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })

  it("returns rgba opaque for every verdict", () => {
    for (const v of VERDICTS) {
      const [, , , a] = verdictRgba(v)
      expect(a).toBe(255)
    }
  })

  it("returns pill classes object with bg/text/border", () => {
    const cls = verdictPillClasses("ACTIVE_BOTTLENECK")
    expect(cls.bg.startsWith("bg-")).toBe(true)
    expect(cls.text.startsWith("text-")).toBe(true)
    expect(cls.border.startsWith("border-")).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- src/modules/trafficure.corridor-diagnostics/components/verdict-style.test.ts --run --reporter=basic
```
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `verdict-style.ts`**

`src/modules/trafficure.corridor-diagnostics/components/verdict-style.ts`:

```ts
export type Verdict =
  | "ACTIVE_BOTTLENECK"
  | "HEAD_BOTTLENECK"
  | "QUEUE_VICTIM"
  | "SLOW_LINK"
  | "FREE_FLOW"
  | "NO_DATA"

export const VERDICTS: readonly Verdict[] = [
  "ACTIVE_BOTTLENECK",
  "HEAD_BOTTLENECK",
  "QUEUE_VICTIM",
  "SLOW_LINK",
  "FREE_FLOW",
  "NO_DATA",
]

const HEX: Record<Verdict, string> = {
  ACTIVE_BOTTLENECK: "#b91c1c",
  HEAD_BOTTLENECK:   "#dc2626",
  QUEUE_VICTIM:      "#ea580c",
  SLOW_LINK:         "#a16207",
  FREE_FLOW:         "#16a34a",
  NO_DATA:           "#737373",
}

const LETTER: Record<Verdict, string> = {
  ACTIVE_BOTTLENECK: "A",
  HEAD_BOTTLENECK:   "H",
  QUEUE_VICTIM:      "Q",
  SLOW_LINK:         "S",
  FREE_FLOW:         "F",
  NO_DATA:           "?",
}

const RGBA: Record<Verdict, [number, number, number, number]> = {
  ACTIVE_BOTTLENECK: [185, 28, 28, 255],
  HEAD_BOTTLENECK:   [220, 38, 38, 255],
  QUEUE_VICTIM:      [234, 88, 12, 255],
  SLOW_LINK:         [161, 98, 7, 255],
  FREE_FLOW:         [22, 163, 74, 255],
  NO_DATA:           [115, 115, 115, 255],
}

const PILL: Record<Verdict, { bg: string; text: string; border: string }> = {
  ACTIVE_BOTTLENECK: { bg: "bg-[#fee2e2]", text: "text-[#991b1b]", border: "border-[#fecaca]" },
  HEAD_BOTTLENECK:   { bg: "bg-[#fee2e2]", text: "text-[#991b1b]", border: "border-[#fecaca]" },
  QUEUE_VICTIM:      { bg: "bg-[#ffedd5]", text: "text-[#9a3412]", border: "border-[#fed7aa]" },
  SLOW_LINK:         { bg: "bg-[#fef9c3]", text: "text-[#854d0e]", border: "border-[#fde68a]" },
  FREE_FLOW:         { bg: "bg-[#dcfce7]", text: "text-[#166534]", border: "border-[#bbf7d0]" },
  NO_DATA:           { bg: "bg-[#f5f5f5]", text: "text-[#525252]", border: "border-[#e5e5e5]" },
}

const LABEL: Record<Verdict, string> = {
  ACTIVE_BOTTLENECK: "Active bottleneck",
  HEAD_BOTTLENECK:   "Head bottleneck",
  QUEUE_VICTIM:      "Queue victim",
  SLOW_LINK:         "Slow link",
  FREE_FLOW:         "Free flow",
  NO_DATA:           "No data",
}

export const verdictDotHex      = (v: Verdict) => HEX[v]
export const verdictLetter      = (v: Verdict) => LETTER[v]
export const verdictRgba        = (v: Verdict) => RGBA[v]
export const verdictPillClasses = (v: Verdict) => PILL[v]
export const verdictLabel       = (v: Verdict) => LABEL[v]

export function isVerdict(v: unknown): v is Verdict {
  return typeof v === "string" && (VERDICTS as readonly string[]).includes(v)
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- src/modules/trafficure.corridor-diagnostics/components/verdict-style.test.ts --run --reporter=basic
```
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/verdict-style.ts src/modules/trafficure.corridor-diagnostics/components/verdict-style.test.ts && git commit -m "feat(corridor-diagnostics): add verdict-style single source of truth"
```

---

### Task 2: Replace ad-hoc verdict palettes with `verdict-style.ts`

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/types/corridor-diagnostics.ts`
- Modify: `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-map-layer.tsx`
- Modify: `src/modules/trafficure.corridor-diagnostics/components/corridor-heatstrip.tsx` (will be deleted later, but keep working until then)
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-card.tsx` (also slated for deletion later)
- Modify: `src/modules/trafficure.corridor-diagnostics/components/left-panel/corridor-card.tsx`

- [ ] **Step 1: In `types/corridor-diagnostics.ts`, re-export `Verdict` from `verdict-style.ts`**

Replace lines 3–9 of `src/modules/trafficure.corridor-diagnostics/types/corridor-diagnostics.ts`:

```ts
export type { Verdict } from "../components/verdict-style"
```

(remove the inline `Verdict` type literal)

- [ ] **Step 2: Update `corridor-diagnostics-map-layer.tsx` to use `verdictRgba`/`verdictLetter`/`isVerdict`**

In `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-map-layer.tsx`:

- Delete the local `VERDICT_RGBA` constant (lines 18–25).
- Delete the local `verdictLetter` function (lines 43–50).
- Replace `pickVerdict` with one that uses `isVerdict`.
- Replace `VERDICT_RGBA[verdict]` with `verdictRgba(verdict)`.
- Replace `verdictLetter(verdict)` (now imported).

Add at top:

```ts
import { isVerdict, verdictLetter, verdictRgba, type Verdict } from "./verdict-style"
```

Replace `pickVerdict`:

```ts
function pickVerdict(structured: unknown, roadId: string): Verdict {
  const v = (structured as { verdicts?: Record<string, unknown> } | undefined)?.verdicts?.[roadId]
  return isVerdict(v) ? v : "NO_DATA"
}
```

- [ ] **Step 3: Update `corridor-heatstrip.tsx` to use `verdictDotHex`**

In `src/modules/trafficure.corridor-diagnostics/components/corridor-heatstrip.tsx`, delete the local `VERDICT_FILL` and use `verdictDotHex(c.verdict)` everywhere it was used.

- [ ] **Step 4: Update `right-panel/segment-card.tsx` to use `verdictDotHex`/`verdictPillClasses`**

In `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-card.tsx`, delete the local `COLOR` map and `letter` function. Replace usages with `verdictDotHex(v)` for fg, `verdictPillClasses(v)` for the pill bg/text/border, `verdictLetter(v)` for the letter.

- [ ] **Step 5: Update `left-panel/corridor-card.tsx` to use `verdictDotHex`**

In `src/modules/trafficure.corridor-diagnostics/components/left-panel/corridor-card.tsx`, delete `VERDICT_FILL` (lines 6–10) and use `verdictDotHex(c.verdict)` in `Heatstripette`. (We'll delete `Heatstripette` in Phase 2.)

- [ ] **Step 6: Build / type-check**

```bash
cd ~/Desktop/trafficure && pnpm exec vinxi build 2>&1 | tail -40
```
Expected: build succeeds (or the build is too heavy — alternative: `pnpm exec tsc --noEmit -p tsconfig.json 2>&1 | grep "corridor-diagnostics" | head -20`).
If types fail, fix the imports until clean.

- [ ] **Step 7: Run unit tests**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- --run --reporter=basic
```
Expected: all green, including pre-existing corridor-diagnostics-* tests under `src/lib/`.

- [ ] **Step 8: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "refactor(corridor-diagnostics): consolidate verdict palette via verdict-style"
```

---

## Phase 2 — Left-panel corridor card

### Task 3: Strip ribbon + heatstrip from `CorridorCard`

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/left-panel/corridor-card.tsx`

- [ ] **Step 1: Replace the file body with the new card layout**

Full replacement for `src/modules/trafficure.corridor-diagnostics/components/left-panel/corridor-card.tsx`:

```tsx
import { Card, CardContent } from "@rio.js/ui/card"
import { Button } from "@rio.js/ui/button"
import { cn } from "@rio.js/ui/lib/utils"
import type { LastRunSlice } from "../../types/corridor-diagnostics"

const SUMMARY_BORDER: Record<string, string> = {
  POINT:    "#b91c1c",
  SYSTEMIC: "#9a3412",
}
const NEUTRAL_BORDER = "#D8D2CB"

function relativeTime(iso: string): string {
  const d = new Date(iso)
  const ms = Date.now() - d.getTime()
  if (ms < 60_000) return "just now"
  if (ms < 3600_000) return `${Math.round(ms / 60_000)} min ago`
  if (ms < 86400_000) return `${Math.round(ms / 3600_000)} hr ago`
  return `${Math.round(ms / 86400_000)} d ago`
}

export interface CorridorCardProps {
  title: string
  subtitle: string
  lastRun: LastRunSlice | null
  selected?: boolean
  onClick: () => void
  onRun: () => void
  isRunning?: boolean
  runDisabled?: boolean
}

export function CorridorCard(props: CorridorCardProps) {
  const borderColor = props.lastRun
    ? SUMMARY_BORDER[props.lastRun.summary_verdict] ?? NEUTRAL_BORDER
    : NEUTRAL_BORDER

  const statusLine = props.lastRun
    ? `${props.lastRun.summary_verdict} · ${relativeTime(props.lastRun.finished_at)}`
    : "Not yet run"

  return (
    <Card
      onClick={props.onClick}
      style={{ borderLeftColor: borderColor }}
      className={cn(
        "rounded-lg border border-scale-300 border-l-[5px] cursor-pointer",
        "transition-shadow shadow-sm mx-2 mb-2 hover:shadow-md bg-white",
        props.selected && "ring-2 ring-amber-500",
      )}
    >
      <CardContent className="p-0">
        <div className="px-4 py-3 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-base font-semibold text-scale-1200 truncate">{props.title}</div>
            <div className="text-sm text-scale-1000 mt-0.5">{props.subtitle}</div>
            <div className="text-sm text-scale-1000 mt-1">{statusLine}</div>
          </div>
          <div onClick={(e) => e.stopPropagation()}>
            <Button
              variant={props.lastRun ? "outline" : "default"}
              size="sm"
              disabled={props.runDisabled || props.isRunning}
              onClick={props.onRun}
              className="text-sm h-8 px-3"
            >
              {props.isRunning ? "Running…" : props.lastRun ? "↻ Re-run" : "▷ Run"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 2: Type-check (focused)**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep "corridor-card\|corridors-tab" | head -20
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/left-panel/corridor-card.tsx && git commit -m "feat(corridor-diagnostics): redesign corridor card with verdict left border"
```

---

## Phase 3 — URL state (corridor + slice + segment)

### Task 4: `use-corridor-url-state.ts`

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts`
- Create: `src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts`

- [ ] **Step 1: Write the failing test**

`src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { parseCorridorParams, buildCorridorSearch } from "./use-corridor-url-state"

describe("parseCorridorParams", () => {
  it("defaults slice to weekday when missing", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A"))).toEqual({
      corridor: "PUNE_A", slice: "weekday", segment: null,
    })
  })
  it("accepts weekend slice", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A&slice=weekend"))).toEqual({
      corridor: "PUNE_A", slice: "weekend", segment: null,
    })
  })
  it("falls back to weekday for unknown slice", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A&slice=garbage")).slice).toBe("weekday")
  })
  it("returns null corridor when missing", () => {
    expect(parseCorridorParams(new URLSearchParams()).corridor).toBeNull()
  })
  it("captures segment", () => {
    expect(parseCorridorParams(new URLSearchParams("corridor=PUNE_A&segment=abc-123")).segment).toBe("abc-123")
  })
})

describe("buildCorridorSearch", () => {
  it("emits corridor + slice + segment in stable order", () => {
    expect(buildCorridorSearch({ corridor: "PUNE_A", slice: "weekday", segment: "abc" }))
      .toBe("corridor=PUNE_A&slice=weekday&segment=abc")
  })
  it("omits segment when null", () => {
    expect(buildCorridorSearch({ corridor: "PUNE_A", slice: "weekend", segment: null }))
      .toBe("corridor=PUNE_A&slice=weekend")
  })
  it("returns empty when corridor is null", () => {
    expect(buildCorridorSearch({ corridor: null, slice: "weekday", segment: null })).toBe("")
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts --run --reporter=basic
```
Expected: FAIL.

- [ ] **Step 3: Implement the module**

`src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts`:

```ts
import { useCallback } from "react"
import { useSearchParams } from "react-router"
import type { Slice } from "../types/corridor-diagnostics"

export interface CorridorParams {
  corridor: string | null
  slice: Slice
  segment: string | null
}

export function parseCorridorParams(p: URLSearchParams): CorridorParams {
  const corridor = p.get("corridor") || null
  const sliceRaw = p.get("slice")
  const slice: Slice = sliceRaw === "weekend" ? "weekend" : "weekday"
  const segment = p.get("segment") || null
  return { corridor, slice, segment }
}

export function buildCorridorSearch(s: CorridorParams): string {
  if (!s.corridor) return ""
  const out = new URLSearchParams()
  out.set("corridor", s.corridor)
  out.set("slice", s.slice)
  if (s.segment) out.set("segment", s.segment)
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

  const setSegment = useCallback(
    (id: string | null) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        if (id) next.set("segment", id)
        else next.delete("segment")
        return next
      }, { replace: true })
    },
    [setParams],
  )

  return { ...value, setCorridor, setSlice, setSegment }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts --run --reporter=basic
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.ts src/modules/trafficure.corridor-diagnostics/data/use-corridor-url-state.test.ts && git commit -m "feat(corridor-diagnostics): add URL-state hook for corridor/slice/segment"
```

---

### Task 5: Migrate the right-panel gate + corridors-tab to the new URL state

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/corridor-diagnostics-right-panel-gate.tsx`
- Modify: `src/modules/trafficure.corridor-diagnostics/components/left-panel/corridors-tab.tsx`
- Modify: `src/modules/trafficure.corridor-diagnostics/data/use-job-poll-query.ts` (if it accepts a `cid+slice` resolution path; otherwise add helper)

- [ ] **Step 1: Read current job-poll hook and snapshot resolver**

```bash
cd ~/Desktop/trafficure && cat src/modules/trafficure.corridor-diagnostics/data/use-job-poll-query.ts
```
Read carefully — your changes must keep it working with both `?job` (legacy callsites you may not have removed yet) and the new `(corridor, slice)` resolution. If the hook only accepts a `jobId`, add a sibling `useCorridorSnapshotJob(corridor, slice)` that fetches the snapshot, gets the `job_id`, and feeds it into the existing `useJobPoll`.

- [ ] **Step 2: Add `useCorridorSnapshotJob` (only if needed)**

If `use-job-poll-query.ts` has no `(corridor, slice)` entry point, append at the bottom of `src/modules/trafficure.corridor-diagnostics/data/use-job-poll-query.ts`:

```ts
import { useQuery } from "@tanstack/react-query"
import { fetchSnapshot } from "./api"
import type { Slice } from "../types/corridor-diagnostics"

export function useCorridorSnapshotJobId(corridor: string | null, slice: Slice) {
  const q = useQuery({
    queryKey: ["corridor-diagnostics-snapshot-jobid", corridor, slice],
    queryFn: async () => {
      if (!corridor) return null
      try {
        const snap = await fetchSnapshot(corridor, slice)
        return snap.job_id ?? null
      } catch {
        return null
      }
    },
    enabled: !!corridor,
    staleTime: 30_000,
  })
  return q.data ?? null
}
```
(Adjust react-query import path to match what `use-job-poll-query.ts` already uses.)

- [ ] **Step 3: Update the right-panel gate**

Full replacement for `src/modules/trafficure.corridor-diagnostics/components/right-panel/corridor-diagnostics-right-panel-gate.tsx`:

```tsx
import { Panel } from "@rio.js/app-ui/components/workspace/panel"
import { useCorridorUrlState } from "../../data/use-corridor-url-state"
import {
  useJobPoll,
  useCorridorSnapshotJobId,
} from "../../data/use-job-poll-query"
import { CorridorDiagnosticsRightPanel } from "./corridor-diagnostics-right-panel"

export function CorridorDiagnosticsRightPanelGate() {
  const { corridor, slice } = useCorridorUrlState()
  const jobId = useCorridorSnapshotJobId(corridor, slice)
  const { data: job } = useJobPoll(jobId)
  if (!job) return null
  return (
    <Panel id="corridor-diagnostics-right" group="right-sidebar">
      <CorridorDiagnosticsRightPanel />
    </Panel>
  )
}
```

- [ ] **Step 4: Update `corridors-tab.tsx` to drive `?corridor` instead of `?job`**

Replace its `useActiveJob`-driven flow with `useCorridorUrlState`. After Run/select, set the corridor in URL (slice already there from `useActiveSlice`). Drop `setJobId` calls. The right-panel gate fetches the snapshot for the URL corridor+slice and resolves the job_id.

In `src/modules/trafficure.corridor-diagnostics/components/left-panel/corridors-tab.tsx`:

- Remove `import { useActiveJob }` from `../../data/use-corridor-diagnostics-state`.
- Add `import { useCorridorUrlState } from "../../data/use-corridor-url-state"`.
- Replace `const { jobId, setJobId } = useActiveJob()` with `const { corridor: urlCorridor, setCorridor } = useCorridorUrlState()`.
- In `triggerRun`, replace `setJobId(job_id)` with `setCorridor(cid)`.
- In `onCardClick`, remove the `fetchSnapshot` + `setJobId(job_id)` calls; simply `setSelectedCid(cid)` and `setCorridor(cid)`.
- The `selected` flag for the visible card stays based on `urlCorridor === c.cid`.

- [ ] **Step 5: Type-check focused**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep -E "corridor-(diagnostics|card|url|tab|gate)" | head -30
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "feat(corridor-diagnostics): drive right panel from ?corridor&slice URL"
```

---

### Task 6: `use-segment-focus.ts` (focused/hovered segment + URL sync)

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/data/use-segment-focus.ts`

- [ ] **Step 1: Write the module**

`src/modules/trafficure.corridor-diagnostics/data/use-segment-focus.ts`:

```ts
import { useEffect, useState } from "react"
import { useRio } from "@rio.js/client"
import { useCorridorUrlState } from "./use-corridor-url-state"

export function useSegmentFocus() {
  const rio = useRio()
  const { segment: urlSegment, setSegment } = useCorridorUrlState()
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [focusedId, setFocusedId] = useState<string | null>(urlSegment)

  // Hover bus
  useEffect(() => {
    const onHover = (ev: { road_id: string | null }) =>
      setHoveredId(ev?.road_id ?? null)
    rio.events.on("corridor-diagnostics.segment.hover", onHover)
    return () => { rio.events.off("corridor-diagnostics.segment.hover", onHover) }
  }, [rio.events])

  // Focus bus → state + URL
  useEffect(() => {
    const onFocus = (ev: { road_id: string | null }) => {
      setFocusedId(ev?.road_id ?? null)
      setSegment(ev?.road_id ?? null)
    }
    rio.events.on("corridor-diagnostics.segment.focus", onFocus)
    return () => { rio.events.off("corridor-diagnostics.segment.focus", onFocus) }
  }, [rio.events, setSegment])

  // External URL changes (back/forward) → state
  useEffect(() => { setFocusedId(urlSegment) }, [urlSegment])

  return {
    hoveredId,
    focusedId,
    activeId: focusedId ?? hoveredId,
    emitHover: (id: string | null) => rio.events.emit("corridor-diagnostics.segment.hover", { road_id: id }),
    emitFocus: (id: string | null) => rio.events.emit("corridor-diagnostics.segment.focus", { road_id: id }),
  }
}
```

- [ ] **Step 2: Type-check**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep "use-segment-focus" | head -10
```
Expected: clean.

- [ ] **Step 3: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/data/use-segment-focus.ts && git commit -m "feat(corridor-diagnostics): add useSegmentFocus hook"
```

---

## Phase 4 — Map paths + markers

### Task 7: Render badge IconLayer with verdict-coloured icons

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx`

- [ ] **Step 1: Replace the file with a TrafficRoadHighlightLayer + IconLayer payload**

Full replacement for `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-overlay-layer.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react"

import { useRio } from "@rio.js/client"
import { MapLayer } from "@rio.js/maps-ui/components/map-layer"
import { IconLayer } from "@rio.js/maps-ui/lib/deck-gl/layers"
import TrafficRoadHighlightLayer from "../../trafficure.core/traffic-road-highlight-layer"

import { useSegmentFocus } from "../data/use-segment-focus"
import {
  isVerdict,
  verdictLetter,
  verdictRgba,
  VERDICTS,
  type Verdict,
} from "./verdict-style"

export type CorridorOverlayPath = {
  id: string
  path: number[][]
  verdict: Verdict
  order: number
}
export type CorridorOverlaySymbol = {
  id: string                // road_id
  position: [number, number]
  verdict: Verdict
}
export type CorridorOverlayPayload = {
  paths: CorridorOverlayPath[]
  symbols: CorridorOverlaySymbol[]
}

const EMPTY: CorridorOverlayPayload = { paths: [], symbols: [] }

const ICON_SIZE = 64
const ICON_MAPPING = (() => {
  const out: Record<string, { x: number; y: number; width: number; height: number; mask: false; anchorY: number }> = {}
  VERDICTS.forEach((v, i) => {
    out[v] = { x: i * ICON_SIZE, y: 0, width: ICON_SIZE, height: ICON_SIZE, mask: false, anchorY: ICON_SIZE / 2 }
  })
  return out
})()

function buildIconAtlas(): HTMLCanvasElement | null {
  if (typeof document === "undefined") return null
  const c = document.createElement("canvas")
  c.width = ICON_SIZE * VERDICTS.length
  c.height = ICON_SIZE
  const ctx = c.getContext("2d")
  if (!ctx) return null
  VERDICTS.forEach((v, i) => {
    const [r, g, b] = verdictRgba(v)
    const cx = i * ICON_SIZE + ICON_SIZE / 2
    const cy = ICON_SIZE / 2
    // White halo
    ctx.beginPath()
    ctx.fillStyle = "#FFFFFF"
    ctx.arc(cx, cy, 26, 0, Math.PI * 2); ctx.fill()
    // Verdict fill
    ctx.beginPath()
    ctx.fillStyle = `rgb(${r}, ${g}, ${b})`
    ctx.arc(cx, cy, 22, 0, Math.PI * 2); ctx.fill()
    // Letter
    ctx.fillStyle = "#FFFFFF"
    ctx.font = "700 28px Inter, system-ui, sans-serif"
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    ctx.fillText(verdictLetter(v), cx, cy + 1)
  })
  return c
}

export function CorridorDiagnosticsOverlayLayer() {
  const rio = useRio()
  const [payload, setPayload] = useState<CorridorOverlayPayload>(EMPTY)
  const { activeId, emitHover, emitFocus } = useSegmentFocus()

  useEffect(() => {
    const onUpdate = (ev: CorridorOverlayPayload) =>
      setPayload({ paths: ev?.paths ?? [], symbols: ev?.symbols ?? [] })
    const onClear = () => setPayload(EMPTY)
    rio.events.on("corridor-diagnostics.overlay.update", onUpdate)
    rio.events.on("corridor-diagnostics.overlay.clear", onClear)
    return () => {
      rio.events.off("corridor-diagnostics.overlay.update", onUpdate)
      rio.events.off("corridor-diagnostics.overlay.clear", onClear)
    }
  }, [rio.events])

  const idleData = useMemo(() => payload.paths.filter(p => p.id !== activeId), [payload.paths, activeId])
  const activeData = useMemo(() => payload.paths.filter(p => p.id === activeId), [payload.paths, activeId])

  const iconAtlas = useMemo(buildIconAtlas, [])
  if (!iconAtlas) return null

  const onPathHover = (info: { object?: CorridorOverlayPath } | null) =>
    emitHover(info?.object?.id ?? null)
  const onPathClick = (info: { object?: CorridorOverlayPath } | null) =>
    emitFocus(info?.object?.id ?? null)
  const onIconHover = (info: { object?: CorridorOverlaySymbol } | null) =>
    emitHover(info?.object?.id ?? null)
  const onIconClick = (info: { object?: CorridorOverlaySymbol } | null) =>
    emitFocus(info?.object?.id ?? null)

  if (!payload.paths.length && !payload.symbols.length) return null

  return (
    <>
      {idleData.length > 0 && (
        <MapLayer
          id="corridor-diagnostics-paths-idle"
          order={695}
          type={TrafficRoadHighlightLayer}
          data={idleData}
          getPath={(d: CorridorOverlayPath) => d.path}
          coreColor={(d: CorridorOverlayPath) => verdictRgba(d.verdict)}
          borderColor={[255, 255, 255, 255]}
          borderWidth={12}
          coreWidth={5}
          arrowLength={null}
          rounded={false}
          pickable
          onHover={onPathHover}
          onClick={onPathClick}
        />
      )}
      {activeData.length > 0 && (
        <MapLayer
          id="corridor-diagnostics-paths-active"
          order={702}
          type={TrafficRoadHighlightLayer}
          data={activeData}
          getPath={(d: CorridorOverlayPath) => d.path}
          coreColor={(d: CorridorOverlayPath) => verdictRgba(d.verdict)}
          borderColor={[255, 255, 255, 255]}
          borderWidth={18}
          coreWidth={6}
          arrowLength={15}
          rounded={false}
          pickable
          onHover={onPathHover}
          onClick={onPathClick}
        />
      )}
      {payload.symbols.length > 0 && (
        <MapLayer
          id="corridor-diagnostics-overlay-badges"
          order={710}
          type={IconLayer}
          data={payload.symbols}
          iconAtlas={iconAtlas}
          iconMapping={ICON_MAPPING}
          getIcon={(d: CorridorOverlaySymbol) => d.verdict}
          getPosition={(d: CorridorOverlaySymbol) => d.position}
          getSize={(d: CorridorOverlaySymbol) => (d.id === activeId ? 36 : 30)}
          sizeUnits="pixels"
          pickable
          onHover={onIconHover}
          onClick={onIconClick}
          updateTriggers={{
            getSize: [activeId],
          }}
        />
      )}
    </>
  )
}
```

- [ ] **Step 2: Update `corridor-diagnostics-map-layer.tsx` to emit the new symbol shape**

In `src/modules/trafficure.corridor-diagnostics/components/corridor-diagnostics-map-layer.tsx`, change the symbol push to:

```ts
sym.push({
  id: s.road_id,
  position: mid,
  verdict,
})
```
(remove `text` and `rgba` fields). Same for the path push, drop `rgba` (the overlay layer derives it). The `CorridorOverlayPath` type already has `verdict`.

- [ ] **Step 3: Type-check focused**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep -E "corridor-diagnostics-(map|overlay)" | head -20
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "feat(corridor-diagnostics): swap map text pills for verdict badges + TrafficRoadHighlightLayer"
```

---

## Phase 5 — Two-tier legend

### Task 8: Compact strip + expanded card with localStorage state

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx`

- [ ] **Step 1: Replace the file**

Full replacement for `src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx`:

```tsx
import { useEffect, useState } from "react"
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

export function Legend() {
  const [expanded, setExpanded] = useState(false)
  useEffect(() => { setExpanded(loadExpanded()) }, [])
  const toggle = () => setExpanded((v) => { saveExpanded(!v); return !v })

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
        </div>
      </div>
    )
  }

  return (
    <div className="absolute bottom-4 left-4 z-[1001] pointer-events-auto bg-white border border-scale-300 rounded-full shadow-md flex items-center gap-3 px-3 py-1.5">
      {VERDICTS.map((v) => (
        <span key={v} className="inline-flex items-center gap-1.5">
          <VerdictBadge v={v} size={16} />
          <span className="text-xs text-scale-1100">{v === "NO_DATA" ? "—" : verdictLabel(v).split(" ")[0]}</span>
        </span>
      ))}
      <button onClick={toggle} title="Expand legend" className="ml-1 w-5 h-5 rounded-full border border-scale-300 text-xs text-scale-1000 hover:text-scale-1200 leading-none">?</button>
    </div>
  )
}
```

- [ ] **Step 2: Type-check focused**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep "legend\|map-overlay" | head -10
```
Expected: clean.

- [ ] **Step 3: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/map-overlay/legend.tsx && git commit -m "feat(corridor-diagnostics): two-tier legend (compact ↔ expanded)"
```

---

## Phase 6 — Right-panel header + Verdict tab

### Task 9: Header with close button + tabs styling

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/corridor-diagnostics-right-panel.tsx`

- [ ] **Step 1: Replace the file**

Full replacement:

```tsx
import { useState } from "react"
import { Tabs, TabsList, TabsTrigger } from "@rio.js/ui/tabs"
import { useCorridorUrlState } from "../../data/use-corridor-url-state"
import { useCorridorSnapshotJobId, useJobPoll } from "../../data/use-job-poll-query"
import { VerdictTab } from "./verdict-tab"
import { StagesTab } from "./stages-tab"

type Tab = "verdict" | "stages"

function isSystemic(structured: unknown): boolean {
  const s = (structured ?? {}) as { systemic_v21?: any; systemic_v2?: any }
  return s.systemic_v21?.systemic_by_contig === true ||
         (Array.isArray(s.systemic_v2?.systemic_windows) && s.systemic_v2.systemic_windows.length > 0)
}

export function CorridorDiagnosticsRightPanel() {
  const [tab, setTab] = useState<Tab>("verdict")
  const { corridor, slice, setCorridor } = useCorridorUrlState()
  const jobId = useCorridorSnapshotJobId(corridor, slice)
  const { data: job } = useJobPoll(jobId)
  if (!job) return null

  const verdict = isSystemic(job.structured) ? "SYSTEMIC" : "POINT"
  const pillCls = verdict === "SYSTEMIC"
    ? "bg-[#fff7ed] text-[#9a3412] border-[#fed7aa]"
    : "bg-[#fee2e2] text-[#991b1b] border-[#fecaca]"

  return (
    <div className="h-full w-full min-w-0 border-l border-scale-300 bg-white flex flex-col">
      <div className="px-4 pt-3 pb-2 border-b border-scale-300 shrink-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-lg font-bold text-scale-1200 truncate">{job.corridor_id}</div>
              <span className={`text-xs font-bold uppercase tracking-wider rounded-full border px-2 py-0.5 ${pillCls}`}>{verdict}</span>
            </div>
            <div className="text-base text-scale-1000 capitalize">{job.slice} · {job.segment_ids.length} segments</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {job.dry_run_html_url && (
              <a href={job.dry_run_html_url} target="_blank" rel="noreferrer"
                 className="text-base text-[#0D3B2E] underline hover:text-scale-1200">
                View full report ↗
              </a>
            )}
            <button
              onClick={() => setCorridor(null)}
              title="Close"
              className="w-7 h-7 rounded-md border border-scale-300 text-scale-1000 hover:bg-scale-100 flex items-center justify-center"
            >×</button>
          </div>
        </div>
        <div className="mt-3">
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="w-full">
            <TabsList className="w-full">
              <TabsTrigger value="verdict" className="flex-1 text-base font-semibold">Verdict</TabsTrigger>
              <TabsTrigger value="stages" className="flex-1 text-base font-semibold">Stages</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === "verdict" && <VerdictTab job={job} />}
        {tab === "stages" && <StagesTab job={job} />}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep "corridor-diagnostics-right-panel" | head
```
Expected: clean.

- [ ] **Step 3: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/right-panel/corridor-diagnostics-right-panel.tsx && git commit -m "feat(corridor-diagnostics): redesign right-panel header with verdict pill + close button"
```

---

### Task 10: 2×2 KPI grid

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx`

- [ ] **Step 1: Create the new component**

`src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx`:

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
}

function fmtKm(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m} m`
}
function pct(num: number, den: number): string {
  if (den <= 0) return "—"
  return `${Math.round((num / den) * 100)}%`
}

export function KpiGrid(p: KpiGridProps) {
  const { A, H, Q, S } = p.bottleneckCounts
  const stuckBreakdown = [A && `A:${A}`, H && `H:${H}`, Q && `Q:${Q}`, S && `S:${S}`]
    .filter(Boolean).join(" · ") || "—"
  const verdictHl = p.summaryVerdict === "SYSTEMIC" ? "text-[#9a3412]" : "text-[#E37400]"
  const verdictSub =
    `simultaneity ${typeof p.simultaneityPct === "number" ? `${p.simultaneityPct}%` : "—"}` +
    ` · contiguity ${typeof p.contiguityPct === "number" ? `${p.contiguityPct}%` : "—"}`
  return (
    <div className="overflow-hidden rounded-lg border border-scale-300 grid grid-cols-2">
      <Cell label="Total length" value={fmtKm(p.totalLengthM)} sub={`${p.segmentCount} segments`} brR brB />
      <Cell label="Free flow"    value={fmtKm(p.freeFlowLengthM)} sub={`${pct(p.freeFlowLengthM, p.totalLengthM)} of corridor`} valueClass="text-[#1E8E3E]" brB />
      <Cell label="Stuck"        value={fmtKm(p.stuckLengthM)}    sub={stuckBreakdown} valueClass="text-[#D93025]" brR />
      <Cell label="Pattern"      value={p.summaryVerdict}         sub={verdictSub} valueClass={verdictHl} />
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

- [ ] **Step 2: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-grid.tsx && git commit -m "feat(corridor-diagnostics): add 2x2 KpiGrid"
```

---

### Task 11: Restyle the StoryBlock as a labelled cream surface

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/story-block.tsx`

- [ ] **Step 1: Replace the file**

```tsx
export function StoryBlock({ story }: { story: string | null | undefined }) {
  if (!story || !story.trim()) return null
  return (
    <div className="bg-[#FAF8F5] border border-scale-300 rounded-lg px-3 py-2.5">
      <div className="text-xs font-bold text-[#0D3B2E] uppercase tracking-wider mb-1">Verdict</div>
      <div className="text-base text-scale-1200 leading-relaxed">{story}</div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/right-panel/story-block.tsx && git commit -m "feat(corridor-diagnostics): restyle StoryBlock as labelled cream surface"
```

---

### Task 12: SegmentChain (vertical timeline)

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`

- [ ] **Step 1: Create**

`src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx`:

```tsx
import { useEffect, useRef } from "react"
import { useRio } from "@rio.js/client"
import { cn } from "@rio.js/ui/lib/utils"
import { useSegmentFocus } from "../../data/use-segment-focus"
import {
  verdictDotHex,
  verdictLabel,
  verdictLetter,
  verdictPillClasses,
  type Verdict,
} from "../verdict-style"

export interface SegmentChainItem {
  road_id: string
  order: number
  verdict: Verdict
  road_name: string
  length_m: number
  ff_speed_kmph?: number
  confidence?: { score: number; label: string }
}

export function SegmentChain({ items }: { items: SegmentChainItem[] }) {
  return (
    <div className="flex flex-col">
      {items.map((it, i) => (
        <Row key={it.road_id} item={it} isLast={i === items.length - 1} />
      ))}
    </div>
  )
}

function Row({ item, isLast }: { item: SegmentChainItem; isLast: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const { hoveredId, focusedId, emitHover, emitFocus } = useSegmentFocus()
  const active = hoveredId === item.road_id || focusedId === item.road_id

  // Auto-scroll into view when this segment becomes the focused one externally.
  useEffect(() => {
    if (focusedId === item.road_id) {
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }
  }, [focusedId, item.road_id])

  const dotHex = verdictDotHex(item.verdict)
  const pill = verdictPillClasses(item.verdict)

  return (
    <div
      ref={ref}
      className="grid"
      style={{ gridTemplateColumns: "36px 1fr" }}
      onMouseEnter={() => emitHover(item.road_id)}
      onMouseLeave={() => emitHover(null)}
      onClick={() => emitFocus(focusedId === item.road_id ? null : item.road_id)}
    >
      <div className="relative">
        <div
          className="absolute left-1/2 top-0 bottom-0 w-[2px] bg-scale-300"
          style={{ transform: "translateX(-50%)", top: isFirst(ref) ? 22 : 0, bottom: isLast ? "calc(100% - 22px)" : 0 }}
        />
        <div
          className={cn(
            "absolute left-1/2 top-[22px] flex items-center justify-center text-white font-bold text-xs",
            "rounded-full transition-transform"
          )}
          style={{
            width: 26, height: 26,
            transform: `translate(-50%, -50%) ${active ? "scale(1.1)" : "scale(1)"}`,
            backgroundColor: dotHex,
            boxShadow: active ? "0 0 0 4px #fff" : "0 0 0 3px #fff",
          }}
        >
          {verdictLetter(item.verdict)}
        </div>
        {!isLast && (
          <div
            className="absolute left-1/2"
            style={{
              top: 36, transform: "translateX(-50%)",
              width: 0, height: 0,
              borderStyle: "solid", borderWidth: "5px 4px 0 4px",
              borderColor: "#94A3A0 transparent transparent transparent",
            }}
          />
        )}
      </div>
      <div
        className={cn(
          "py-2.5 pl-2 pr-2 grid items-start gap-2 cursor-pointer transition-colors",
          "border-b border-[#ECE5DC]",
          active && "bg-[#FAF8F5]",
        )}
        style={{
          gridTemplateColumns: "1fr auto",
          boxShadow: active ? "inset 3px 0 0 #0D3B2E" : undefined,
        }}
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-base font-bold text-scale-1200 tabular-nums">
              S{String(item.order).padStart(2, "0")}
            </span>
            <span className={cn("text-xs font-bold rounded-full border px-2 py-0.5", pill.bg, pill.text, pill.border)}>
              {verdictLabel(item.verdict)}
            </span>
          </div>
          <div className="text-base text-scale-1200 leading-tight mt-0.5">{item.road_name || item.road_id.slice(0, 8)}</div>
          <div className="text-sm text-scale-1000 mt-0.5 tabular-nums">
            {item.length_m ? `${Math.round(item.length_m)} m` : "—"}
            {typeof item.ff_speed_kmph === "number" ? ` · ff ${item.ff_speed_kmph.toFixed(1)} km/h` : ""}
            {item.confidence ? ` · conf ${item.confidence.score.toFixed(2)} ${item.confidence.label.toUpperCase()}` : ""}
          </div>
        </div>
        <a
          href={`/analytics/${encodeURIComponent(item.road_id)}`}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="Open segment in Analytics"
          aria-label="Open segment in Analytics"
          className="w-7 h-7 rounded-md border border-scale-300 text-scale-1000 hover:bg-scale-100 hover:text-[#0D3B2E] flex items-center justify-center text-base"
        >↗</a>
      </div>
    </div>
  )
}

function isFirst(_ref: React.RefObject<HTMLDivElement>) { return false } // visual-only — keep here so future row positions can reference it
```

- [ ] **Step 2: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-chain.tsx && git commit -m "feat(corridor-diagnostics): add vertical SegmentChain with deep-link + hover/focus"
```

---

### Task 13: Rewrite VerdictTab to compose StoryBlock + KpiGrid + SegmentChain

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/verdict-tab.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import type { Job } from "../../types/corridor-diagnostics"
import { isVerdict, type Verdict } from "../verdict-style"
import { useSegmentsGeometry } from "../../data/use-segments-geometry-query"
import { KpiGrid } from "./kpi-grid"
import { StoryBlock } from "./story-block"
import { SegmentChain, type SegmentChainItem } from "./segment-chain"

const STUCK = new Set<Verdict>(["ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK", "QUEUE_VICTIM", "SLOW_LINK"])

export function VerdictTab({ job }: { job: Job }) {
  const { data: geo } = useSegmentsGeometry(job.segment_ids)
  const segByRid = new Map((geo?.segments ?? []).map((s) => [s.road_id, s]))

  if (job.status !== "done") {
    return (
      <div className="p-4 text-base text-scale-1000">
        Run in progress — verdicts will appear when status reaches "done".
      </div>
    )
  }
  const struct = (job.structured ?? {}) as Record<string, any>
  const verdicts: Record<string, string> = struct.verdicts ?? {}
  const confidence: Record<string, { score: number; label: string; components: Record<string, number> }> = struct.confidence ?? {}
  const freeflow: Record<string, { ff_speed_kmph?: number }> = struct.freeflow ?? {}

  const items: SegmentChainItem[] = job.segment_ids.map((rid, i) => {
    const v = verdicts[rid]
    const seg = segByRid.get(rid)
    return {
      road_id: rid,
      order: i + 1,
      verdict: isVerdict(v) ? v : "NO_DATA",
      road_name: seg?.road_name ?? "",
      length_m: Number(seg?.length_m ?? 0),
      ff_speed_kmph: freeflow[rid]?.ff_speed_kmph,
      confidence: confidence[rid] ? { score: confidence[rid].score, label: confidence[rid].label } : undefined,
    }
  })

  const totalLengthM = items.reduce((s, i) => s + i.length_m, 0)
  const freeFlowLengthM = items.filter((i) => i.verdict === "FREE_FLOW").reduce((s, i) => s + i.length_m, 0)
  const stuckLengthM = items.filter((i) => STUCK.has(i.verdict)).reduce((s, i) => s + i.length_m, 0)
  const bottleneckCounts = {
    A: items.filter((i) => i.verdict === "ACTIVE_BOTTLENECK").length,
    H: items.filter((i) => i.verdict === "HEAD_BOTTLENECK").length,
    Q: items.filter((i) => i.verdict === "QUEUE_VICTIM").length,
    S: items.filter((i) => i.verdict === "SLOW_LINK").length,
  }
  const sysv21 = struct.systemic_v21 ?? null
  const sysv2  = struct.systemic_v2 ?? null
  const isSystemic =
    sysv21?.systemic_by_contig === true ||
    (Array.isArray(sysv2?.systemic_windows) && sysv2.systemic_windows.length > 0)
  const summaryVerdict: "POINT" | "SYSTEMIC" = isSystemic ? "SYSTEMIC" : "POINT"
  const simultaneityPct = typeof sysv2?.max_fraction === "number" ? Math.round(sysv2.max_fraction * 100) : undefined
  const contiguityPct   = typeof sysv21?.max_contig_frac === "number" ? Math.round(sysv21.max_contig_frac * 100) : undefined

  return (
    <div className="px-4 py-4 flex flex-col gap-4">
      <StoryBlock story={job.story} />
      <KpiGrid
        totalLengthM={totalLengthM}
        segmentCount={items.length}
        freeFlowLengthM={freeFlowLengthM}
        stuckLengthM={stuckLengthM}
        bottleneckCounts={bottleneckCounts}
        summaryVerdict={summaryVerdict}
        simultaneityPct={simultaneityPct}
        contiguityPct={contiguityPct}
      />
      <div>
        <div className="text-xs font-bold text-scale-1000 uppercase tracking-wider mb-2 flex items-center justify-between">
          <span>Segments along the corridor</span>
          <span className="text-sm text-scale-1000 normal-case font-medium">tap a row or the map to focus</span>
        </div>
        <SegmentChain items={items} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "feat(corridor-diagnostics): rewrite VerdictTab to use StoryBlock + KpiGrid + SegmentChain"
```

---

## Phase 7 — Stages tab

### Task 14: stages-primitives module

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/components/right-panel/stages-primitives.tsx`
- Create: `src/modules/trafficure.corridor-diagnostics/components/right-panel/stages-primitives.test.ts`

- [ ] **Step 1: Tests**

`stages-primitives.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { bucketToIst, deriveStageStatus } from "./stages-primitives"

describe("bucketToIst", () => {
  it("converts bucket index to HH:mm IST", () => {
    expect(bucketToIst(0)).toBe("00:00")
    expect(bucketToIst(30)).toBe("01:00")
    expect(bucketToIst(410)).toBe("13:40")
    expect(bucketToIst(719)).toBe("23:58")
  })
})

describe("deriveStageStatus", () => {
  it("returns s-empty when payload missing", () => {
    expect(deriveStageStatus("freeflow", null).variant).toBe("s-empty")
  })
  it("returns s-ok when free-flow has all entries with no warnings", () => {
    expect(deriveStageStatus("freeflow", { a: { warnings: [] }, b: { warnings: [] } }).variant).toBe("s-ok")
  })
  it("returns s-warn when bertini fires at all", () => {
    expect(deriveStageStatus("bertini", { a: [[100, 200]] }).variant).toBe("s-warn")
  })
})
```

- [ ] **Step 2: Run to fail**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- src/modules/trafficure.corridor-diagnostics/components/right-panel/stages-primitives.test.ts --run --reporter=basic
```
Expected: FAIL.

- [ ] **Step 3: Implement**

`stages-primitives.tsx`:

```tsx
import { type ReactNode } from "react"

export type StageStatusVariant = "s-ok" | "s-warn" | "s-fail" | "s-empty" | "s-info"
export interface StageStatus { variant: StageStatusVariant; label: string }

export function bucketToIst(b: number): string {
  const m = b * 2
  const hh = Math.floor(m / 60).toString().padStart(2, "0")
  const mm = (m % 60).toString().padStart(2, "0")
  return `${hh}:${mm}`
}

export function deriveStageStatus(key: string, payload: unknown): StageStatus {
  if (payload === null || payload === undefined) return { variant: "s-empty", label: "n/a" }
  switch (key) {
    case "freeflow": {
      const map = payload as Record<string, { warnings?: unknown[] }>
      const total = Object.keys(map).length
      const warned = Object.values(map).filter((s) => Array.isArray(s.warnings) && s.warnings.length > 0).length
      return warned === 0
        ? { variant: "s-ok",   label: `${total}/${total} anchored` }
        : { variant: "s-warn", label: `${total - warned}/${total} clean` }
    }
    case "baseline_flags": {
      const map = payload as Record<string, { baseline_saturated?: boolean }>
      const saturated = Object.values(map).filter((b) => b.baseline_saturated).length
      return saturated === 0
        ? { variant: "s-ok",   label: "no saturation" }
        : { variant: "s-warn", label: `${saturated} saturated` }
    }
    case "primary_windows_v21": {
      const arr = (payload as unknown[]) ?? []
      return arr.length === 0
        ? { variant: "s-empty", label: "empty" }
        : { variant: "s-info",  label: `${arr.length} windows` }
    }
    case "bertini": {
      const map = payload as Record<string, unknown[][]>
      const fires = Object.values(map).filter((arr) => Array.isArray(arr) && arr.length > 0).length
      return fires === 0
        ? { variant: "s-info", label: "no firings" }
        : { variant: "s-warn", label: `${fires} firing` }
    }
    case "head_bottleneck": {
      const arr = (payload as unknown[]) ?? []
      return { variant: arr.length > 0 ? "s-info" : "s-empty", label: arr.length > 0 ? `${arr.length} candidates` : "none" }
    }
    case "shockwave": {
      const sw = payload as { pairs?: Array<{ pass?: boolean }> }
      const pairs = sw.pairs ?? []
      const pass = pairs.filter((p) => p.pass).length
      return { variant: pass === 0 ? "s-warn" : "s-ok", label: `pass ${pass}/${pairs.length}` }
    }
    case "systemic_v2": {
      const s = payload as { systemic_windows?: unknown[] }
      return (s.systemic_windows && s.systemic_windows.length > 0)
        ? { variant: "s-warn",  label: `${s.systemic_windows.length} windows` }
        : { variant: "s-empty", label: "no windows" }
    }
    case "systemic_v21": {
      const s = payload as { systemic_by_contig?: boolean }
      return s.systemic_by_contig
        ? { variant: "s-warn",  label: "contiguous" }
        : { variant: "s-empty", label: "not contiguous" }
    }
    case "recurrence": {
      const map = payload as Record<string, { label?: string }>
      const counts: Record<string, number> = {}
      for (const r of Object.values(map)) {
        const lbl = r.label ?? "?"
        counts[lbl] = (counts[lbl] ?? 0) + 1
      }
      const summary = Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(" · ")
      return { variant: "s-ok", label: summary || "—" }
    }
    case "confidence": {
      const map = payload as Record<string, { score: number }>
      const scores = Object.values(map).map((c) => c.score)
      if (scores.length === 0) return { variant: "s-empty", label: "—" }
      const avg = scores.reduce((s, n) => s + n, 0) / scores.length
      const lbl = avg >= 0.7 ? "HIGH" : avg >= 0.4 ? "MEDIUM" : "LOW"
      return { variant: "s-ok", label: `avg ${avg.toFixed(2)} ${lbl}` }
    }
    default:
      return { variant: "s-info", label: "" }
  }
}

export const STATUS_PILL_CLASSES: Record<StageStatusVariant, string> = {
  "s-ok":    "bg-[#dcfce7] text-[#166534]",
  "s-warn":  "bg-[#fef9c3] text-[#854d0e]",
  "s-fail":  "bg-[#fee2e2] text-[#991b1b]",
  "s-empty": "bg-[#f5f5f5] text-[#525252]",
  "s-info":  "bg-[#dbeafe] text-[#1d4ed8]",
}

export function StatGrid({ cols, cells }: { cols: 3 | 4; cells: { label: string; value: ReactNode; sub?: string; highlight?: "ok" | "warn" | "bad" }[] }) {
  const grid = cols === 4 ? "grid-cols-4" : "grid-cols-3"
  const colorOf = (h?: string) =>
    h === "ok" ? "text-[#1E8E3E]" : h === "warn" ? "text-[#E37400]" : h === "bad" ? "text-[#D93025]" : "text-scale-1200"
  return (
    <div className={`grid ${grid} border border-scale-300 rounded-lg overflow-hidden bg-white`}>
      {cells.map((c, i) => (
        <div key={c.label} className={`px-3 py-2.5 ${i % cols !== cols - 1 ? "border-r border-scale-300" : ""}`}>
          <div className="text-sm uppercase tracking-wider text-scale-1000">{c.label}</div>
          <div className={`text-lg font-bold tabular-nums ${colorOf(c.highlight)}`}>{c.value}</div>
          {c.sub && <div className="text-sm text-scale-1000">{c.sub}</div>}
        </div>
      ))}
    </div>
  )
}

export function SegTable({ columns, rows }: {
  columns: { key: string; label: string; align?: "left" | "right"; render?: (row: any) => ReactNode }[]
  rows: any[]
}) {
  return (
    <div className="border border-scale-300 rounded-lg overflow-hidden">
      <table className="w-full text-base tabular-nums">
        <thead className="bg-[#FAF8F5]">
          <tr>{columns.map((c) => (
            <th key={c.key} className={`px-3 py-2 text-sm uppercase tracking-wider text-scale-1000 font-semibold ${c.align === "right" ? "text-right" : "text-left"}`}>{c.label}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i === rows.length - 1 ? "" : "border-b border-scale-300"}>
              {columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 ${c.align === "right" ? "text-right" : "text-left"}`}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function NumberPill({ n }: { n: number }) {
  return <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-[#1A1A1A] text-white text-xs font-bold">{n}</span>
}

export function WindowBar({ buckets }: { buckets: Array<[number, number]> }) {
  const TOTAL = 720
  return (
    <div>
      <div className="relative h-3.5 bg-[#FAF8F5] border border-scale-300 rounded">
        {buckets.map(([a, b], i) => (
          <div key={i}
               className="absolute top-0 bottom-0 bg-[#fef2f2]"
               style={{
                 left: `${(a / TOTAL) * 100}%`,
                 width: `${((b - a) / TOTAL) * 100}%`,
                 borderLeft: "1.5px solid #b91c1c",
                 borderRight: "1.5px solid #b91c1c",
               }} />
        ))}
      </div>
      <div className="flex justify-between text-xs text-scale-1000 mt-1 tabular-nums">
        <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>23:58</span>
      </div>
    </div>
  )
}

export function PairRow(props: {
  a: number; b: number; observedMin: number; expected: [number, number]; distM: number; pass: boolean
}) {
  return (
    <div className="border border-scale-300 rounded-lg px-3 py-2 mb-1.5 flex items-center gap-3 text-base">
      <NumberPill n={props.a} />
      <span className="text-scale-1000">→</span>
      <NumberPill n={props.b} />
      <span className="text-scale-1000">obs {props.observedMin > 0 ? "+" : ""}{props.observedMin.toFixed(1)} min</span>
      <span className="text-sm text-scale-1000 ml-auto">expected {props.expected[0].toFixed(1)}–{props.expected[1].toFixed(1)} · {props.distM.toFixed(0)} m</span>
      <span className={props.pass ? "text-[#15803d] font-semibold" : "text-[#b91c1c] font-semibold"}>{props.pass ? "PASS" : "FAIL"}</span>
    </div>
  )
}

export function ConfidenceComponents({ components }: { components: Record<string, number> }) {
  const dot = (n: number) => n >= 0.66 ? "bg-[#15803d]" : n >= 0.33 ? "bg-[#a16207]" : "bg-[#b91c1c]"
  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(components).map(([k, v]) => (
        <span key={k} className="inline-flex items-center gap-1.5 border border-scale-300 rounded-full px-2 py-0.5 text-sm text-scale-1200">
          <span className={`w-1.5 h-1.5 rounded-full ${dot(v)}`} />
          <span>{k} {v.toFixed(2)}</span>
        </span>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run test to pass**

```bash
cd ~/Desktop/trafficure && pnpm test:unit -- src/modules/trafficure.corridor-diagnostics/components/right-panel/stages-primitives.test.ts --run --reporter=basic
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "feat(corridor-diagnostics): add stages-primitives (StatGrid, SegTable, WindowBar, PairRow, ConfidenceComponents)"
```

---

### Task 15: stage-cards (per-stage renderers)

**Files:**
- Create: `src/modules/trafficure.corridor-diagnostics/components/right-panel/stage-cards.tsx`

- [ ] **Step 1: Implement**

`stage-cards.tsx`:

```tsx
import { type ReactNode } from "react"
import {
  bucketToIst,
  ConfidenceComponents,
  NumberPill,
  PairRow,
  SegTable,
  StatGrid,
  WindowBar,
} from "./stages-primitives"

const TIME_BAND = (windows: Array<[string, string]>) => {
  if (!windows.length) return "no windows"
  const flat = windows.flat().sort()
  return `${flat[0]}–${flat[flat.length - 1]} IST band`
}

export function FreeflowBody({ payload, segmentIds }: { payload: any; segmentIds: string[] }) {
  const entries = Object.entries(payload ?? {}) as Array<[string, any]>
  const speeds = entries.map(([, v]) => v.ff_speed_kmph).filter((n) => Number.isFinite(n))
  const minS = speeds.length ? Math.min(...speeds).toFixed(1) : "—"
  const maxS = speeds.length ? Math.max(...speeds).toFixed(1) : "—"
  const allWindows = entries.flatMap(([, v]) => v.quiet_windows ?? [])
  return (
    <>
      <div className="text-base text-scale-1000 mb-2">{`Quiet windows in ${TIME_BAND(allWindows)}. ff_speed ${minS}–${maxS} km/h.`}</div>
      <StatGrid cols={4} cells={[
        { label: "Anchored",       value: `${entries.length}/${segmentIds.length}` },
        { label: "Bins / segment", value: "720", sub: "2-min, 24h" },
        { label: "ff range",       value: `${minS}–${maxS} km/h` },
        { label: "Clamps fired",   value: entries.filter(([, v]) => v.ff_tt !== v.raw_ff_sec).length, highlight: "ok" },
      ]} />
      <div className="mt-3">
        <SegTable
          columns={[
            { key: "order", label: "Seg", render: (r) => <NumberPill n={r.order} /> },
            { key: "rid", label: "Road id" },
            { key: "ff", label: "ff (s)", align: "right" },
            { key: "speed", label: "ff km/h", align: "right" },
            { key: "wins", label: "Quiet windows" },
          ]}
          rows={segmentIds.map((rid, i) => {
            const e = payload?.[rid] ?? {}
            const wins = (e.quiet_windows ?? []).slice(0, 3).map((w: string[]) => w[0]).join(" · ") || "—"
            return { order: i + 1, rid: rid.slice(0, 8), ff: e.ff_tt ?? "—", speed: e.ff_speed_kmph?.toFixed(1) ?? "—", wins }
          })}
        />
      </div>
    </>
  )
}

export function BaselineBody({ payload, segmentIds }: { payload: any; segmentIds: string[] }) {
  return (
    <SegTable
      columns={[
        { key: "order", label: "Seg", render: (r) => <NumberPill n={r.order} /> },
        { key: "ff", label: "ff km/h", align: "right" },
        { key: "peer", label: "peer ratio", align: "right" },
        { key: "qb", label: "quiet/busy", align: "right" },
        { key: "flag", label: "flag" },
      ]}
      rows={segmentIds.map((rid, i) => {
        const b = payload?.[rid] ?? {}
        return {
          order: i + 1,
          ff: b.ff_speed_kmph?.toFixed(1) ?? "—",
          peer: b.peer_ratio?.toFixed(2) ?? "—",
          qb: b.quiet_busy_ratio?.toFixed(2) ?? "—",
          flag: b.baseline_saturated ? "saturated" : "clean",
        }
      })}
    />
  )
}

export function PrimaryWindowsBody({ payload }: { payload: any }) {
  const arr = Array.isArray(payload) ? payload : []
  if (arr.length === 0) return <div className="text-base text-scale-1000">No primary congestion windows on any segment.</div>
  return <pre className="text-sm font-mono">{JSON.stringify(arr, null, 2)}</pre>
}

export function BertiniBody({ payload }: { payload: any }) {
  const entries = Object.entries(payload ?? {}) as Array<[string, number[][]]>
  const firing = entries.filter(([, arr]) => arr && arr.length > 0)
  if (firing.length === 0) return <div className="text-base text-scale-1000">No firings.</div>
  return (
    <div className="space-y-2">
      {firing.map(([rid, arr], i) => (
        <div key={rid}>
          <div className="text-sm text-scale-1000 mb-1 flex items-center gap-2">
            <NumberPill n={i + 1} /> {rid.slice(0, 8)}
          </div>
          <WindowBar buckets={arr.map(([a, b]) => [a, b]) as Array<[number, number]>} />
        </div>
      ))}
    </div>
  )
}

export function HeadBottleneckBody({ payload }: { payload: any }) {
  const arr = (payload ?? []) as number[][]
  if (arr.length === 0) return <div className="text-base text-scale-1000">No candidates.</div>
  return (
    <>
      <div className="text-base text-scale-1000 mb-2">{arr.map(([a, b]) => `${bucketToIst(a)}–${bucketToIst(b)}`).join(", ")}</div>
      <WindowBar buckets={arr.map(([a, b]) => [a, b]) as Array<[number, number]>} />
    </>
  )
}

export function ShockwaveBody({ payload }: { payload: any }) {
  const pairs = (payload?.pairs ?? []) as Array<any>
  if (!pairs.length) return <div className="text-base text-scale-1000">No pair data.</div>
  return (
    <div>
      <div className="text-sm text-scale-1000 mb-2">Mode: {payload.mode ?? "—"}</div>
      {pairs.map((p, i) => (
        <PairRow
          key={i}
          a={p.pair[0] + 1}
          b={p.pair[1] + 1}
          observedMin={Number(p.observed_lag_min)}
          expected={[p.expected_lag_range_min[0], p.expected_lag_range_min[1]]}
          distM={Number(p.dist_m)}
          pass={!!p.pass}
        />
      ))}
    </div>
  )
}

export function SystemicV2Body({ payload }: { payload: any }) {
  const max = payload?.max_simultaneous ?? 0
  const total = (payload?.threshold_segments ?? 0) || max
  const frac = typeof payload?.max_fraction === "number" ? Math.round(payload.max_fraction * 100) : "—"
  return (
    <StatGrid cols={3} cells={[
      { label: "Max simultaneous", value: `${max}` },
      { label: "Max fraction",     value: typeof frac === "number" ? `${frac}%` : "—" },
      { label: "Threshold",        value: `${total} segs`, sub: max < total ? "not met" : "met" },
    ]} />
  )
}

export function SystemicV21Body({ payload }: { payload: any }) {
  const frac = typeof payload?.max_contig_frac === "number" ? Math.round(payload.max_contig_frac * 100) : "—"
  const peakBucket = payload?.peak_bucket ?? null
  const peakSegs = payload?.peak_segs ?? []
  return (
    <StatGrid cols={3} cells={[
      { label: "Max contig frac", value: typeof frac === "number" ? `${frac}%` : "—" },
      { label: "Peak bucket",     value: peakBucket !== null ? `${peakBucket}`: "—", sub: peakBucket !== null ? `${bucketToIst(peakBucket)} IST` : undefined },
      { label: "Peak segs",       value: peakSegs.length ? peakSegs.map((i: number) => `S${String(i + 1).padStart(2, "0")}`).join(", ") : "—" },
    ]} />
  )
}

export function RecurrenceBody({ payload, segmentIds }: { payload: any; segmentIds: string[] }) {
  return (
    <SegTable
      columns={[
        { key: "order", label: "Seg", render: (r) => <NumberPill n={r.order} /> },
        { key: "days",  label: "days", align: "right" },
        { key: "frac",  label: "fraction", align: "right" },
        { key: "label", label: "label" },
      ]}
      rows={segmentIds.map((rid, i) => {
        const r = payload?.[rid] ?? {}
        return {
          order: i + 1,
          days: r.n_days != null ? `${r.n_days} / ${r.total_days}` : "—",
          frac: r.frac != null ? `${Math.round(r.frac * 100)}%` : "—",
          label: r.label ?? "—",
        }
      })}
    />
  )
}

export function ConfidenceBody({ payload, segmentIds }: { payload: any; segmentIds: string[] }) {
  return (
    <SegTable
      columns={[
        { key: "order", label: "Seg", render: (r) => <NumberPill n={r.order} /> },
        { key: "score", label: "score", render: (r) => (
          <span className="inline-flex items-center gap-2">
            <span className="inline-block w-20 h-1.5 bg-scale-300 rounded">
              <span className="block h-full bg-[#0D3B2E] rounded" style={{ width: `${(r.scoreNum * 100).toFixed(0)}%` }} />
            </span>
            <span className="tabular-nums">{r.score}</span>
          </span>
        ) },
        { key: "label", label: "label" },
        { key: "components", label: "components", render: (r) => <ConfidenceComponents components={r.componentsRaw ?? {}} /> },
      ]}
      rows={segmentIds.map((rid, i) => {
        const c = payload?.[rid] ?? {}
        return {
          order: i + 1,
          score: typeof c.score === "number" ? c.score.toFixed(2) : "—",
          scoreNum: typeof c.score === "number" ? c.score : 0,
          label: c.label ?? "—",
          componentsRaw: c.components ?? {},
        }
      })}
    />
  )
}

export const STAGE_CARDS: Array<{
  key: string
  label: string
  summary: (payload: any, segmentIds: string[]) => string
  body: (payload: any, segmentIds: string[]) => ReactNode
}> = [
  { key: "freeflow",            label: "Free-flow discovery",    summary: () => "",                                body: (p, s) => <FreeflowBody payload={p} segmentIds={s} /> },
  { key: "baseline_flags",      label: "Baseline flags",         summary: () => "",                                body: (p, s) => <BaselineBody payload={p} segmentIds={s} /> },
  { key: "primary_windows_v21", label: "Primary windows (v2.1)", summary: (p) => Array.isArray(p) && p.length ? `${p.length} windows.` : "No primary congestion windows detected on any segment.", body: (p) => <PrimaryWindowsBody payload={p} /> },
  { key: "bertini",             label: "Bertini cascade",        summary: () => "",                                body: (p) => <BertiniBody payload={p} /> },
  { key: "head_bottleneck",     label: "Head bottleneck",        summary: () => "",                                body: (p) => <HeadBottleneckBody payload={p} /> },
  { key: "shockwave",           label: "Shockwave / queue",      summary: () => "",                                body: (p) => <ShockwaveBody payload={p} /> },
  { key: "systemic_v2",         label: "Systemic (v2)",          summary: () => "",                                body: (p) => <SystemicV2Body payload={p} /> },
  { key: "systemic_v21",        label: "Systemic (v2.1)",        summary: () => "",                                body: (p) => <SystemicV21Body payload={p} /> },
  { key: "recurrence",          label: "Recurrence typing",      summary: () => "",                                body: (p, s) => <RecurrenceBody payload={p} segmentIds={s} /> },
  { key: "confidence",          label: "Confidence",             summary: () => "",                                body: (p, s) => <ConfidenceBody payload={p} segmentIds={s} /> },
]
```

- [ ] **Step 2: Commit**

```bash
cd ~/Desktop/trafficure && git add src/modules/trafficure.corridor-diagnostics/components/right-panel/stage-cards.tsx && git commit -m "feat(corridor-diagnostics): add per-stage renderers"
```

---

### Task 16: Rewrite StagesTab using cards + collapse + Expand all

**Files:**
- Modify: `src/modules/trafficure.corridor-diagnostics/components/right-panel/stages-tab.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { useEffect, useState } from "react"
import type { Job } from "../../types/corridor-diagnostics"
import { STAGE_CARDS } from "./stage-cards"
import { deriveStageStatus, STATUS_PILL_CLASSES } from "./stages-primitives"

const STORAGE_KEY = "cd.stages.open"

function loadOpen(): Record<string, boolean> {
  try { return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") } catch { return {} }
}
function saveOpen(v: Record<string, boolean>) {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(v)) } catch { /* ignore */ }
}

export function StagesTab({ job }: { job: Job }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  useEffect(() => { setOpen(loadOpen()) }, [])
  const struct = (job.structured ?? {}) as Record<string, unknown>
  const segIds = job.segment_ids
  const allOpen = STAGE_CARDS.every((s) => open[s.key])
  const setAll = (v: boolean) => { const next = Object.fromEntries(STAGE_CARDS.map((s) => [s.key, v])); saveOpen(next); setOpen(next) }
  const toggle = (k: string) => { const next = { ...open, [k]: !open[k] }; saveOpen(next); setOpen(next) }

  return (
    <div>
      <div className="flex items-center justify-between px-4 py-2 bg-[#FAF8F5] border-b border-scale-300 text-base">
        <span className="text-scale-1000">{STAGE_CARDS.length} stages</span>
        <button onClick={() => setAll(!allOpen)} className="text-[#0D3B2E] underline text-base">{allOpen ? "Collapse all" : "Expand all"}</button>
      </div>
      <div>
        {STAGE_CARDS.map((s, i) => {
          const payload = struct[s.key]
          const status = deriveStageStatus(s.key, payload)
          const isOpen = !!open[s.key]
          return (
            <div key={s.key} className="border-b border-scale-300 px-4 py-3 cursor-pointer" onClick={() => toggle(s.key)}>
              <div className="flex items-center gap-2.5">
                <span className="w-6 h-6 rounded-full bg-[#0D3B2E] text-white text-xs font-bold flex items-center justify-center">{i + 1}</span>
                <span className="text-base font-semibold text-scale-1200">{s.label}</span>
                <span className={`text-xs font-semibold uppercase tracking-wider rounded-full px-2 py-0.5 ${STATUS_PILL_CLASSES[status.variant]}`}>{status.label}</span>
                <span className="ml-auto text-scale-1000">{isOpen ? "▾" : "▸"}</span>
              </div>
              {(() => {
                const summary = s.summary(payload, segIds) || defaultSummary(s.key, payload, status.label)
                return summary ? <div className="text-base text-scale-1000 mt-1 ml-9">{summary}</div> : null
              })()}
              {isOpen && (
                <div className="mt-3 ml-9" onClick={(e) => e.stopPropagation()}>
                  {payload === undefined || payload === null
                    ? <div className="text-base text-scale-1000">Not available for this run.</div>
                    : s.body(payload, segIds)}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function defaultSummary(key: string, payload: any, statusLabel: string): string {
  if (payload === undefined || payload === null) return "Not available for this run."
  return statusLabel
}
```

- [ ] **Step 2: Type-check + tests**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | grep "stages\|stage-cards" | head -20 ; pnpm test:unit -- --run --reporter=basic
```
Expected: clean and all green.

- [ ] **Step 3: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "feat(corridor-diagnostics): rewrite Stages tab with structured per-stage cards"
```

---

## Phase 8 — Cleanup

### Task 17: Delete dead files & purge old wiring

**Files:**
- Delete: `src/modules/trafficure.corridor-diagnostics/components/corridor-heatstrip.tsx`
- Delete: `src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-card.tsx`
- Delete: `src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-row.tsx`
- Modify: `src/modules/trafficure.corridor-diagnostics/data/use-corridor-diagnostics-state.ts` — remove `useActiveJob`; `useActiveSlice` stays (still consumed by left-panel slice toggle).

- [ ] **Step 1: Delete files**

```bash
cd ~/Desktop/trafficure && git rm \
  src/modules/trafficure.corridor-diagnostics/components/corridor-heatstrip.tsx \
  src/modules/trafficure.corridor-diagnostics/components/right-panel/segment-card.tsx \
  src/modules/trafficure.corridor-diagnostics/components/right-panel/kpi-row.tsx
```

- [ ] **Step 2: Strip `useActiveJob`**

In `src/modules/trafficure.corridor-diagnostics/data/use-corridor-diagnostics-state.ts`, delete the `useActiveJob` function (lines 4–19). Keep `useActiveSlice`.

- [ ] **Step 3: Type-check & test**

```bash
cd ~/Desktop/trafficure && pnpm exec tsc --noEmit 2>&1 | head -30 ; pnpm test:unit -- --run --reporter=basic
```
Expected: clean and all green. If anything still imports the deleted files, fix the imports first.

- [ ] **Step 4: Commit**

```bash
cd ~/Desktop/trafficure && git add -A && git commit -m "chore(corridor-diagnostics): remove heatstrip, segment-card, kpi-row, useActiveJob"
```

---

## Phase 9 — Visual verification

### Task 18: Run dev server and sanity-check via the agent-browser skill

**Files:** none

- [ ] **Step 1: Start the dev server**

```bash
cd ~/Desktop/trafficure && pnpm dev
```
Run in background. Capture the URL printed (default `http://localhost:3000`).

- [ ] **Step 2: Use `agent-browser` skill (Brave) to load the page**

Invoke the agent-browser skill with the goal:
- Navigate to `http://localhost:3000/corridor-diagnostics`
- Click the "PUNE_A" corridor card; verify URL becomes `?corridor=PUNE_A&slice=weekday`
- Verify left-panel card shows: red left border, title, sub-line, "POINT · X min ago", no ribbon, no heatstrip
- Verify right panel renders: header with name + POINT pill, View full report ↗, × close
- Click × — verify the right panel collapses and `?corridor` disappears
- Re-select PUNE_A; switch to weekend slice — verify URL becomes `?corridor=PUNE_A&slice=weekend`
- Hover the S02 row in the chain — verify the matching map badge grows + the path widens + arrows appear
- Click S02 — verify URL gets `&segment=<id>` and panel row stays highlighted
- Click the `↗` deep-link — verify a new tab opens to `/analytics/<segment_id>`
- Click "Stages" tab — verify 10 numbered cards, all collapsed, status pills present, no JSON dumps anywhere
- Click "Expand all" — verify all bodies open with structured grids/tables/bars
- Capture screenshots of: corridor card list, verdict tab idle, verdict tab S02-hover, stages tab collapsed, stages tab expanded, legend collapsed, legend expanded

- [ ] **Step 3: Compare against the spec**

Walk through the spec's "Type & colour rules" and "Per-stage content" tables. Note any mismatches (font too small, colour too washed, missing field). File issues inline as fix-me commits.

- [ ] **Step 4: Final commit + push**

```bash
cd ~/Desktop/trafficure && git push -u origin feat/corridor-diagnostics-ui-redesign
```

---

## Self-review notes

- **Spec coverage:** every section of the spec maps to a task above (verdict-style → 1, left card → 3, URL → 4–5, focus hook → 6, map paths/markers → 7, legend → 8, header → 9, KPI grid → 10, story → 11, segment chain → 12, verdict tab compose → 13, stages primitives → 14, stage cards → 15, stages tab → 16, cleanup → 17, verification → 18).
- **Type names:** `verdictDotHex` / `verdictRgba` / `verdictPillClasses` / `verdictLetter` / `verdictLabel` / `isVerdict` / `VERDICTS` — used consistently in tasks 1, 2, 7, 8, 12, 13.
- **Hover/focus contract:** all consumers go through `useSegmentFocus` (task 6) which is the only place reading/writing `?segment` and emitting bus events.
- **No JSON dumps:** every payload-bearing branch in `stage-cards.tsx` either renders structured UI or a "Not available for this run." string. (One place in PrimaryWindowsBody falls back to a small `<pre>` only when the payload exists but is non-empty array of unknown shape; if you want zero JSON, the implementer can replace it with a SegTable once the real shape lands.)
- **Reasonable assumptions made:** `useCorridorSnapshotJobId` is sketched; the implementer must adapt the react-query import to the project's actual setup (`@tanstack/react-query` is the standard).
