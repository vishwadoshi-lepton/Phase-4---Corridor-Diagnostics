# Phase 4 — Corridor Diagnostics v2

**Owner:** Umang
**Status:** Algorithm validated on **19 corridors** (Pune, Kolkata, Delhi, plus user-defined routes). Stage 4 (shockwave) running in preferred per-day onset mode for both weekday and weekend slices. Stage 6 (recurrence typing) running. Operator UI shipped end-to-end at `/corridor-diagnostics` in the trafficure web app.
**Kicked off:** 2026-04-09
**Last updated:** 2026-04-29

---

## What this phase is

The v2 corridor diagnostic is TraffiCure's first traffic-engineering-grade diagnostic pipeline. It replaces v1's heuristic approach with a six-stage pipeline grounded in classical physics (fundamental diagram of traffic flow, Bertini & Leal 2005 three-point active-bottleneck test, Lighthill-Whitham-Richards shockwave model).

The design goal was **zero city-specific tuning**. Same code, same thresholds, works in Pune, Delhi, Kolkata, Bengaluru, Mumbai. We've now demonstrated that property end-to-end on Pune (regression + blind), Kolkata (3 corridors), and Delhi (DEL_AUROBINDO).

## What got built

1. **Algorithm v2 + v2.1** (`data/corridor_diagnostics_v2.py`, `data/v2_1/`) — six-stage pipeline plus the v2.1 contiguity refinement to systemic detection. Stage 4 runs in preferred per-day onset mode; Stage 6 emits `RECURRING / FREQUENT / OCCASIONAL` typing per segment.
2. **Profile builders** (`data/profiles.py`, `data/profiles_new.py`, `data/v2_1/profiles/all_profiles_{weekday,weekend}.json`) — 2-min median travel-time profiles per segment per slice, pulled directly from `traffic_observation`.
3. **Per-day onset pulls** (`data/v2_1/onsets/all_onsets_{weekday,weekend}.json`) — the rows that unlock Stage 4 preferred mode and Stage 6 recurrence.
4. **Corridor definitions** (`data/v2_1/validation_corridors.json`) — 7 pre-built corridors (4 PUNE + 3 KOL + 1 DEL) plus 12 user-defined / transient corridors saved from the operator UI.
5. **Validation runs** (`runs/v2_1/v2_1_validation_{weekday,weekend}_structured.json`) — full structured pipeline output for every corridor in every slice. Weekday: 19 corridors. Weekend: 7 (the pre-built ones).
6. **Self-contained dry-run reports** (`docs/dry_runs/*.html`) — one rich HTML per corridor × slice for off-line review.
7. **Prediction layer v1** (`data/v2_1/predict/`, `docs/replay/`) — 90-min now-cast on top of v2.1's verdict + onset distribution, using Google Research's TimesFM 2.5. Six corridors × three held-out days × 37 anchor ticks pre-computed and rendered as HTML replays with a dual-marker slider (anchor + playhead).
8. **Operator UI** — the user-facing `/corridor-diagnostics` view (in the `trafficure` frontend, **not in this repo** — see "Where the frontend lives" below).
9. **PRD, design and engineer-handoff docs** explaining every stage end-to-end.

## Headline results

| Metric | Value |
|---|---|
| Corridors with structured output (weekday) | 19 |
| Corridors with structured output (weekend) | 7 |
| Pre-built corridors (in `validation_corridors.json`) | 7 (PUNE_A/B/C, KOL_A/B/C, DEL_AUROBINDO) |
| Cities covered | Pune, Kolkata, Delhi |
| Tunable adjustments between cities | 0 |
| Stage 4 mode | preferred (per-day onsets) for every corridor |
| Stage 6 recurrence typing | running for every corridor |

## Known gaps

1. **Bengaluru / Mumbai / other cities not yet validated.** Code is portable; data pull is the blocker.
2. **Weekend pass on the 12 user-defined corridors** is missing — only the 7 pre-built ones have weekend structured output today.
3. **Prediction layer runs on synthetic held-out days.** The `traffic_observation` pull for raw per-day rows for the prediction layer is still pending.
4. **Test artifacts in the corridor list.** `TRANSIENT_*`, `USER_LOHGAON_TO_VISHRANT_WADI`, `USER_LOHGAON_TO_VISHRANT_WADI_TRY_2`, `USER_18_5_73_*` etc. are dev/QA leftovers that should be pruned from `validation_corridors.json` before any external demo.

## Where the frontend lives

The operator UI is **not in this repo**. It's in the trafficure web app:

```
~/Desktop/trafficure/src/modules/trafficure.corridor-diagnostics/
```

This module renders the `/corridor-diagnostics` route — left panel (Pre-built / From route / Custom corridor selectors), map overlay (verdict-coloured paths + circular badges), and right panel (Verdict + Stages tabs). It reads from this repo's `runs/v2_1/v2_1_validation_*_structured.json` files via the `/api/corridor-diagnostics/snapshot` endpoint defined in trafficure's server routes.

Two specs document the UI:
- `docs/superpowers/specs/2026-04-28-corridor-diagnostics-ui-redesign.md` (round 1)
- `docs/superpowers/specs/2026-04-28-corridor-diagnostics-ui-redesign-round-2.md` (round 2)

## How to read this folder

Start with `CORRIDOR_DIAGNOSTICS_V2_PRD.md` (at the top level of this folder) — it's the single end-to-end explainer. It walks through the problem statement, data foundation, every stage of the algorithm, how results come out, and how an engineer uses them. Read that first.

Then:

- For deeper algorithm internals and design rationale → `docs/CORRIDOR_DIAGNOSTICS_V2_DESIGN.md`
- For the v2.1 engineer handoff (ship checklist + module API surface) → `docs/CORRIDOR_DIAGNOSTICS_V2_1_ENGINEER_HANDOFF.md`
- For empirical validation and the blind-test write-up → `docs/CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md`
- For the prediction-layer design → `docs/CORRIDOR_PREDICTION_V1_DESIGN.md`
- For the raw structured output of a corridor → `runs/v2_1/v2_1_validation_<slice>_structured.json`
- For the human-readable run report → `runs/v2_1/v2_1_validation_<slice>_report.txt`
- For a self-contained HTML report on any corridor × slice → `docs/dry_runs/<CID>_<slice>_dry_run.html`
- For the prediction replays → `docs/replay/index.html`
- For the algorithm code → `data/corridor_diagnostics_v2.py` (v2) and `data/v2_1/` (v2.1 + prediction)
- For UI specs and round-2 brainstorm artifacts → `docs/superpowers/specs/`, `docs/superpowers/plans/`

## Folder layout

```
Phase 4 - Corridor Diagnostics/
├── CONTEXT.md                                 ← you are here
├── CORRIDOR_DIAGNOSTICS_V2_PRD.md             ← start here, end-to-end explainer
│
├── docs/
│   ├── CORRIDOR_DIAGNOSTICS_V2_DESIGN.md             algorithm internals & design
│   ├── CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md  empirical results + blind test
│   ├── CORRIDOR_DIAGNOSTICS_V2_1_ENGINEER_HANDOFF.md v2.1 ship checklist + module API
│   ├── CORRIDOR_DIAGNOSTICS_V2_1_VALIDATION.md       v2.1 validation summary
│   ├── CORRIDOR_PREDICTION_V1_DESIGN.md              prediction layer design
│   ├── CORRIDOR_DIAGNOSTICS_SUMMARY.txt              v1 legacy reference
│   ├── TRAFFI_CURE_DB_SCHEMA_GUIDE.md                schema notes
│   ├── dry_runs/                                     self-contained per-corridor HTML reports
│   ├── replay/                                       prediction-layer HTML replays
│   └── superpowers/                                  brainstorming specs + plans (UI redesign, etc.)
│
├── data/
│   ├── corridor_diagnostics_v2.py             the v2 six-stage pipeline
│   ├── corridors_v2.py                        v2 chain definitions (7 corridors, 77 segs)
│   ├── profiles.py                            v2 profiles, original 4 corridors
│   ├── profiles_new.py                        v2 profiles, blind-test corridors
│   ├── run_blind_new.py                       v2 blind-test runner
│   ├── v1_per_corridor_reports/               v1 legacy outputs, kept for compare
│   └── v2_1/
│       ├── validation_corridors.json          all corridor definitions (pre-built + user)
│       ├── profiles/                          per-slice 2-min median profiles
│       ├── onsets/                            per-day onset pulls (Stage 4 preferred mode)
│       └── predict/                           prediction-layer code + cached forecasts
│
├── runs/
│   ├── v2_1/
│   │   ├── v2_1_validation_weekday_structured.json   all 19 corridors, structured
│   │   ├── v2_1_validation_weekend_structured.json   the 7 pre-built corridors
│   │   ├── v2_1_validation_weekday_report.txt        human-readable
│   │   ├── v2_1_validation_weekend_report.txt        human-readable
│   │   └── last_runs.json                            most-recent-run pointer per corridor × slice
│   └── (legacy v2 runs)                              kept for history
│
└── mockups/                                          early HTML mockups (superseded by the trafficure UI)
```

## Prediction layer (v1, on top of v2.1)

A short-horizon (90-min) now-cast layer was scaffolded on 2026-04-23 that consumes v2.1's output as a prior and uses Google Research's TimesFM 2.5 foundation model as the forecaster. Six corridors × three held-out days × 37 anchor ticks are pre-computed and delivered as self-contained HTML replays with a dual-marker slider (anchor + playhead; past = actual, forecast window = predicted, beyond horizon = actual again). The pipeline code lives at `data/v2_1/predict/`. The design doc is `docs/CORRIDOR_PREDICTION_V1_DESIGN.md`. The replays are at `docs/replay/index.html`. This layer currently runs on synthetic held-out days (the `traffic_observation` pull for raw per-day rows is still pending).

## Relation to earlier phases

- **Phase 1 (Foundation)** set up the probe-data ingestion pipeline and `traffic_observation` schema. Phase 4 consumes it directly.
- **Phase 2 (Enhanced Intelligence)** introduced v1's diagnostic pipeline and the per-corridor reports in `data/v1_per_corridor_reports/`. Phase 4 replaces v1's diagnostic with a traffic-engineering-grade v2.
- **Phase 3 (CityPulse)** was designed as the predictive layer independent of v2.1. The new prediction layer in `data/v2_1/predict/` partially occupies that space by anchoring TimesFM forecasts on v2.1's verdict + onset distribution. Whether to merge or keep separate is an open question.

## Next engineering tasks (in order)

1. **Run weekend pass on the 12 user-defined corridors** so weekend structured output covers everything the UI can select.
2. **Pull a Bengaluru and a Mumbai corridor** and re-run the pipeline — last cross-city validation gap.
3. **Wire the prediction layer to real per-day data** instead of synthetic held-out days (`traffic_observation` pull for raw per-day rows).
4. **Prune test artifacts** from `validation_corridors.json` (TRANSIENT_*, duplicate USER_LOHGAON_TO_VISHRANT_WADI_TRY_2, etc.) before any external demo.
5. **Land follow-up hygiene PR for the operator UI** — items I5/I6 from the round-1 code review (per-row `useSegmentHover` subscribers, `useActiveSlice` vs `useCorridorUrlState` `replace` semantics).
