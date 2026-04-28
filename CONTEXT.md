# Phase 4 — Corridor Diagnostics v2

**Owner:** Umang
**Status:** Algorithm validated on 77 segments across 7 corridors and 4 road typologies. Zero tuning between regression run and blind test. Preferred-mode Stage 4 (per-day onset pull) is the only remaining engineering item.
**Kicked off:** 2026-04-09
**Last updated:** 2026-04-10

---

## What this phase is

The v2 corridor diagnostic is TraffiCure's first traffic-engineering-grade diagnostic pipeline. It replaces v1's heuristic approach with a six-stage pipeline grounded in classical physics (fundamental diagram of traffic flow, Bertini & Leal 2005 three-point active-bottleneck test, Lighthill-Whitham-Richards shockwave model).

The design goal was **zero city-specific tuning**. Same code, same thresholds, works in Pune, Delhi, Kolkata, Bengaluru, Mumbai. We spent this phase proving that property.

## What got built

1. **Algorithm** (`data/corridor_diagnostics_v2.py`) — six stages: free-flow discovery, regime classification, primary window detection, Bertini active-bottleneck test, LWR shockwave cross-check, systemic vs point, recurrence typing.
2. **Profile builders** (`data/profiles.py`, `data/profiles_new.py`) — 2-min weekday-median travel-time profiles for 77 segments, 22 weekdays each, pulled directly from `traffic_observation`.
3. **Corridor definitions** (`data/corridors_v2.py`) — topologically verified chains for the 4 original Pune corridors plus 3 blind-test corridors (JBN/BAP/HDV).
4. **Regression pass** on the 4 original Pune corridors, with a mid-phase discovery and fix of a −6h IST timezone label bug in the profile builder.
5. **Blind test** on 3 new corridors never seen by the algorithm: 39 segments, 49.2 km, covering dense urban arterial, signalised arterial, and highway-feeder-with-ghat-climb.
6. **PRD and design docs** explaining the pipeline end-to-end.

## Headline results

| Metric | Value |
|---|---|
| Corridors validated | 7 (4 regression + 3 blind) |
| Segments validated | 77 |
| Road typologies covered | 4 (dense urban, signalised arterial, highway feeder, ghat climb) |
| Tunable adjustments between runs | 0 |
| Segments hitting the 80 km/h ceiling clamp | 0 |
| Segments with Stage 1 warnings | 0 |
| Segments with free-flow windows in 01:34–07:40 IST band | 77 / 77 |

**JBN (20 segments, 27.6 km):** three independent active bottlenecks correctly separated — S07 St. Mery Chowk → Turf Club (principal, fires midday + PM), S11 Ramtekdi → Megacenter (PM), S14 15 Number → Shewalwadi (late PM). Peak simultaneous 10/20, not systemic.

**BAP (11 segments, 9.4 km):** one PM active bottleneck (S09 Gunjan Chowk → Shastrinagar, 30% SEVERE + 26% CONG) plus one AM slow link (S06 Chandrma Chowk → Sadalbaba Chowk, 56% CONG but no upstream queue — Bertini correctly does not fire). Peak 4/11, not systemic.

**HDV (8 segments, 12.2 km):** no primary congestion window. Only one isolated slow junction (S03). Correctly flagged as a quiet corridor. A heuristic-heavy v1 pipeline would have invented a peak window here; v2 refused.

## Known gaps

1. **Stage 4 shockwave validation is running in fallback mode.** Fallback uses the median profile's slow-patch centroid as a proxy for onset, which is unreliable on signal-dominated urban corridors because day-to-day onset variance gets smeared by the median. Preferred mode needs a per-segment per-weekday onset-time pull (~1,700 rows for 77 segments × 22 days). Scheduled next.
2. **Stage 6 recurrence typing is gated on the same per-day onset pull.**
3. **Weekend pass is deferred.** Weekdays only so far. Same code, separate input slice.
4. **Cross-city validation is deferred.** We have physics-based confidence the pipeline transfers to Delhi and Kolkata but have not demonstrated it on non-Pune probe data. Blocker: access to those feeds.
5. **Operator UI mockups are pre-v2** and show v1-style single-color bars. They need updating to show v2's verdict badges (ACTIVE BOTTLENECK / SLOW LINK / QUEUE VICTIM / FREE FLOW) and the Section 12 decision tree from the PRD.

## How to read this folder

Start with `CORRIDOR_DIAGNOSTICS_V2_PRD.md` (at the top level of this folder) — it is the single end-to-end explainer. It walks through the problem statement, data foundation, every stage of the algorithm, how results come out, and how an engineer uses them. Read that first.

Then:

- For deeper algorithm internals and design rationale → `docs/CORRIDOR_DIAGNOSTICS_V2_DESIGN.md`
- For empirical validation and the blind-test write-up → `docs/CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md`
- For the raw pipeline output on any corridor → `runs/`
- For the code that produced all of this → `data/`
- For the first-pass UI mockups (need updating to v2) → `mockups/`

## Folder layout

```
Phase 4 - Corridor Diagnostics/
├── CONTEXT.md                                 ← you are here
├── CORRIDOR_DIAGNOSTICS_V2_PRD.md             ← start here, end-to-end explainer
│
├── docs/
│   ├── CORRIDOR_DIAGNOSTICS_V2_DESIGN.md       algorithm internals & design
│   ├── CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md   empirical results + blind test
│   └── CORRIDOR_DIAGNOSTICS_SUMMARY.txt        v1 legacy reference
│
├── data/
│   ├── corridor_diagnostics_v2.py              the six-stage pipeline
│   ├── corridors_v2.py                         chain definitions (7 corridors, 77 segs)
│   ├── profiles.py                             2-min weekday profiles, original 4 corridors (38 segs)
│   ├── profiles_new.py                         2-min weekday profiles, blind-test corridors (39 segs)
│   ├── run_blind_new.py                        blind-test runner
│   └── v1_per_corridor_reports/                v1 legacy per-corridor outputs, kept for compare
│
├── runs/
│   ├── v2_original4_run_CORRECTED.txt          v2 on the 4 original corridors (post IST fix)
│   ├── v2_original4_run.txt                    pre-fix, kept for history
│   ├── v2_blind_new_run.txt                    v2 on JBN/BAP/HDV joined
│   ├── v2_blind_JBN.txt                        v2 on JBN individually
│   ├── v2_blind_BAP.txt                        v2 on BAP individually
│   └── v2_blind_HDV.txt                        v2 on HDV individually
│
└── mockups/
    ├── corridor-diagnostics-mockup.html        pre-v2 operator UI mockup
    └── mundhwa-corridor-diagnostics.html       pre-v2 Mundhwa-specific mockup
```

## Prediction layer (v1, on top of v2.1)

A short-horizon (90-min) now-cast layer was scaffolded on 2026-04-23 that consumes v2.1's output as a prior and uses Google Research's TimesFM 2.5 foundation model as the forecaster. Six corridors × three held-out days × 37 anchor ticks are pre-computed and delivered as self-contained HTML replays with a dual-marker slider (anchor + playhead; past = actual, forecast window = predicted, beyond horizon = actual again). The pipeline code lives at `data/v2_1/predict/`. The design doc is `docs/CORRIDOR_PREDICTION_V1_DESIGN.md`. The replays are at `docs/replay/index.html`. This layer currently runs on synthetic held-out days (the `traffic_observation` pull for raw per-day rows is still pending).

## Relation to earlier phases

- **Phase 1 (Foundation)** set up the probe-data ingestion pipeline and `traffic_observation` schema. Phase 4 consumes it directly.
- **Phase 2 (Enhanced Intelligence)** introduced v1's diagnostic pipeline and the per-corridor reports in `data/v1_per_corridor_reports/`. Phase 4 replaces v1's diagnostic with a traffic-engineering-grade v2.
- **Phase 3 (CityPulse)** was designed as the predictive layer independent of v2.1. The new prediction layer in `data/v2_1/predict/` partially occupies that space by anchoring TimesFM forecasts on v2.1's verdict + onset distribution. Whether to merge or keep separate is an open question.

## Next engineering tasks (in order)

1. Pull per-weekday onset rows for all 77 segments (`onsets_new.json`, ~1,700 rows).
2. Re-run Stage 4 in preferred mode. Expect shockwave pass rates to rise on pairs where Bertini already fires.
3. Run Stage 6 recurrence typing. Turn each ACTIVE BOTTLENECK verdict into `recurrent / frequent / episodic`.
4. Update the operator UI mockups in `mockups/` to render v2's verdict badges and decision tree.
5. Pull a Delhi corridor and re-run the pipeline as a cross-city validation.
