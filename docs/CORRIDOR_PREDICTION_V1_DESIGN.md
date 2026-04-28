# Corridor Prediction v1 — Design Doc

**Status:** v1 scaffold complete end-to-end on synthetic replay data. Real TimesFM 2.5 inference wired in. Six corridors × three held-out days × 37 anchor ticks pre-computed. UI ships as 18 self-contained HTML replays. Not yet connected to live probe data.
**Audience:** whoever picks this up next to productionise, evaluate, or extend.
**Reference implementation:** Python, in `data/v2_1/predict/`. See §12 for the file map.

Read this alongside the v2.1 docs (`CORRIDOR_DIAGNOSTICS_V2_PRD.md`, `CORRIDOR_DIAGNOSTICS_V2_1_ENGINEER_HANDOFF.md`) — this layer consumes v2.1's output as a prior.

---

## 1. What this is, in one sentence

A short-horizon (90 min) traffic now-cast layer built on top of v2.1's diagnostic pipeline: for any corridor and any "anchor" moment during the day, predict each segment's traffic regime (FREE / APPROACHING / CONGESTED / SEVERE) for the next 45 two-minute buckets, using Google Research's TimesFM 2.5 foundation model *fused with v2.1's verdict and historical onset distribution*.

## 2. Why this exists — the problem statement

v2.1 answers **"why is this corridor broken right now"** — diagnostic. CityPulse (Phase 3) was designed to answer **"when will it be broken next"** — predictive, but runs independently of v2.1 and re-derives everything from scratch.

This layer bridges the two. It exploits the fact that v2.1 has already done the physics heavy-lifting: for each segment, it knows the verdict (`HEAD_BOTTLENECK` / `ACTIVE_BOTTLENECK` / `FREE_FLOW` / …), the recurrence band (`RECURRING` / `FREQUENT` / `OCCASIONAL` / …), and the distribution of per-day onset times. So we don't need to re-learn where bottlenecks are. We just need to predict *when they fire today, given the morning so far*.

Framing:

- **Cold path (v2.1, nightly):** the slow, physics-grounded, median-based diagnosis that tells us *where* structural bottlenecks live.
- **Hot path (this layer, every 2 min):** the fast, live-data-sensitive forecast that tells us *when* they fire today.

## 3. Scope and non-goals

**In scope (v1):**
- 90-min forward forecast, 2-min resolution, per segment.
- Consumes the same `road_id`-keyed inputs v2.1 uses.
- Produces a per-segment regime forecast + uncertainty bands + a fusion "agreement" flag against v2.1's historical expectation.
- Replay mode — simulate live operation by freezing the clock at an anchor minute-of-day on a held-out day and predicting forward.
- Operator-facing visual replay in a single HTML page per (corridor, date), with a two-marker slider UI.

**Out of scope (v1):**
- Live streaming from `traffic_observation` — the `LiveContextBuilder` has the hook, but the pull is not wired.
- Cross-segment coupling / shockwave-aware forecasting — TimesFM is run univariate, one series per segment. LWR propagation is not exploited at the forecaster level.
- Fine-tuning TimesFM on corridor-specific data. Zero-shot only.
- Uncertainty calibration on real probe data. Quantile bands are emitted but their coverage has not been verified on Indian urban traffic.
- Weekend slicing. Weekday only, matching v2.1's default.

## 4. Data contracts

### 4.1 Inputs

All three come from the existing v2.1 data directory — no new sources for v1.

| Input | Location | Shape |
|---|---|---|
| Corridor chains | `data/v2_1/validation_corridors.json` | `{cid: {chain: [{road_id, road_name, length_m, road_class}]}}` |
| Weekday-median profiles | `data/v2_1/profiles/all_profiles_weekday.json` | `{road_id: {min_of_day: tt_sec}}` — 720 buckets per day |
| Per-day onsets | `data/v2_1/onsets/all_onsets_weekday.json` | `[{rid, dt, om}]` — flat list, `om` is minute-of-day |
| v2.1 diagnosis | `runs/v2_1/v2_1_validation_weekday_structured.json` | Keyed by corridor id; verdicts, confidence, recurrence, freeflow |

### 4.2 "Live" input (the held-out day)

A `HeldOutDay` carries the full 2-min trace for each segment of one corridor on one replay date:

```python
@dataclass
class HeldOutDay:
    corridor_id: str
    corridor_name: str
    city: str
    date: str              # ISO, e.g. "2026-04-22"
    source: str            # "synthetic" | "postgres"
    segments: list[SegTrace]

@dataclass
class SegTrace:
    rid: str               # road_id
    road_name: str
    segment_idx: str       # "S01", "S02", ...
    length_m: int
    road_class: str
    trace: list[float]     # 720 values, travel-time-in-seconds per 2-min bucket
    onset_min: int | None  # from onsets table for this (rid, date), if any
```

For v1, raw per-day rows are not accessible (Postgres env vars are not set in the dev environment), so `synthetic_day.py` generates deterministic, reproducible traces by perturbing the weekday-median profile (see §7). The `source` field flags this so the UI can label it. A future version swaps `build_held_out_days()` for a `traffic_observation` pull — the `HeldOutDay` shape does not change.

### 4.3 Outputs

One JSON per (corridor, held-out-date) in `data/v2_1/predict/forecasts/`:

```jsonc
{
  "corridor_id": "PUNE_A",
  "corridor_name": "Fakri Hill Chowk to Mohmmadwadi Junction ...",
  "city": "Pune",
  "date": "2026-04-22",
  "source": "synthetic",
  "forecaster_name": "timesfm-2.5-200m",
  "horizon_min": 90,
  "bucket_min": 2,
  "anchor_step_min": 30,
  "anchor_ticks": [120, 150, ..., 1200],           // minute-of-day

  "chain": [
    {"segment_idx": "S01", "rid": "...", "road_name": "...",
     "length_m": 494, "road_class": "Arterial",
     "verdict": "HEAD_BOTTLENECK", "confidence_score": 0.52,
     "confidence_label": "MEDIUM", "recurrence_label": "RECURRING",
     "recurrence_frac": 1.0, "ff_tt": 52.0}, ...
  ],

  "actual_day": [
    {"segment_idx": "S01", "rid": "...", "trace": [...720 values...],
     "regimes": [...720 strings...]}, ...
  ],

  "forecasts_by_anchor": {
    "840": {
      "anchor_min": 840,
      "segments": [
        {"segment_idx": "S01", "rid": "...", "ff_tt": 52.0,
         "point": [...45 values...],        // TimesFM mean
         "q10":   [...45 values...],        // 10th percentile
         "q90":   [...45 values...],        // 90th percentile
         "predicted_regimes": [...45 strings...],
         "fusion": {
           "skipped": false,
           "skip_reason": null,
           "congestion_onset_predicted_min": 842,
           "congestion_onset_typical_min":   858,
           "agreement": "EARLIER_THAN_USUAL",
           "fusion_note": "Forecast onset 14:02 is 16 min earlier than typical..."
         }}, ...
      ]
    }, ...
  }
}
```

The renderer consumes this verbatim. No post-processing outside the HTML.

## 5. Pipeline architecture

```
          ┌───── COLD PATH · nightly · reuses v2.1 ───────┐
          │                                               │
          │  traffic_observation  ──►  ProfileBuilder     │
          │        (30 wkdy)           (weekday medians)  │
          │                                  │            │
          │                                  ▼            │
          │                          v2.1 six stages      │
          │                                  │            │
          │                                  ▼            │
          │                     CorridorDiagnosis (JSON)  │
          │                                  │            │
          └──────────────────────────────────┼────────────┘
                                             │ (verdict, recurrence,
                                             │  onset distribution, ff_tt)
          ┌──── HOT PATH · per anchor ───────┼────────────┐
          │                                  │            │
          │  held-out day's                  │            │
          │  2-min trace      ─►  LiveContext│Builder     │
          │  (00:00 → anchor)   (C2 policy)  │            │
          │                        │         │            │
          │                        ▼         │            │
          │                  TimesFM 2.5     │            │
          │                     forecast     │            │
          │                        │         │            │
          │                        ▼         ▼            │
          │                  PredictionFusion             │
          │                        │                      │
          │                        ▼                      │
          │                  regime_mapper                │
          │                        │                      │
          │                        ▼                      │
          │              per-(corridor, date) JSON        │
          │                        │                      │
          │                        ▼                      │
          │                 render_replay                 │
          │                        │                      │
          │                        ▼                      │
          │          docs/replay/*_replay.html            │
          └────────────────────────────────────────────────┘
```

## 6. Context policy (C2)

The forecaster needs a contiguous time series per segment. Three candidate policies were considered:

- **C1 · today only.** Feed `[00:00, anchor)` of today. Honest, but at early anchors (e.g. 02:00) there are only 60 samples, too short for TimesFM to latch onto weekly seasonality.
- **C2 · history + today-so-far.** Prepend `N_history_days` same-weekday history days (from the weekday-median profile, tiled) then append today-so-far. Weekly seasonality is always in the context; context length grows with anchor.
- **C3 · today padded with median warm-up.** Replace the pre-anchor portion of today with the median profile. Keeps context length fixed but lies about what the model sees.

**v1 uses C2 with `N_history_days = 1`**, giving a context length of 720 + anchor_bucket (up to 1140 samples), which keeps TimesFM 2.5 CPU latency around 10 s per 48-series batched call. The upstream default of 7 history days was dropped when CPU inference at 5,760 samples exceeded 90 s per call. Swap back up when a GPU is available — the code path supports any N via `config.HISTORY_DAYS_CONCAT`.

## 7. Held-out day selection and synthesis

### 7.1 Selection

Three replay dates: **2026-04-21 · 22 · 23** (latest weekdays with onset rows in the v2.1 data window). These dates are excluded from historical onset comparisons in the fusion layer — the replay never sees itself.

### 7.2 Synthesis (dev-only)

Raw per-day rows are not in the repo. `synthetic_day.synthesise_trace()` generates a reproducible 720-sample trace for each (rid, date) by:

1. Sampling the weekday-median profile as the baseline.
2. Adding seeded Gaussian noise proportional to the local tt (≈4%).
3. Applying a timing jitter (±12 min @ 2σ) via `np.roll` of the profile.
4. Applying a magnitude jitter (±8% @ 2σ, clamped to ±25%) on peaks.
5. If the onsets table has an entry for this (rid, date), injecting a gentle 30-min tt rise locked to the recorded onset minute, so the replay's congestion onset matches ground truth.

The seed is derived from SHA-256 of `"{rid}|{date}"`. Runs are deterministic. The `source` field on `HeldOutDay` is set to `"synthetic"` and surfaces in the UI header.

**Production swap:** replace `build_held_out_days()` with a function that pulls raw `traffic_observation` rows for the target date(s), buckets them to 2 min, and emits `HeldOutDay` with `source="postgres"`. Nothing downstream changes.

## 8. Forecaster

### 8.1 Interface

```python
class Forecaster:
    name: str
    def forecast(self, horizon_steps: int, contexts: list[np.ndarray])
        -> tuple[np.ndarray, np.ndarray]:
        """
        contexts: list of N 1-D float arrays (one per segment)
        returns: (point (N, H), quantiles (N, H, 10))
                 quantile indices: 0 = mean, 1 = q10, 2 = q20, ..., 5 = q50, ..., 9 = q90
        """
```

### 8.2 TimesFM 2.5 backend

- Checkpoint: `google/timesfm-2.5-200m-pytorch` (Apache-2.0).
- Installation: `pip install git+https://github.com/google-research/timesfm.git` + `pip install torch`. The PyPI `timesfm==1.0` is stale and won't install on Python ≥3.12.
- Compile-time config: `max_context=1200, max_horizon=64, normalize_inputs=True, use_continuous_quantile_head=True, force_flip_invariance=True, infer_is_positive=True, fix_quantile_crossing=True`.
- Runtime: one batched call per (date, anchor) across all 48 segments of the 6 corridors → ~10 s on CPU per call. Full precompute of all 111 (date × anchor) combos took ~28 min on a single CPU in dev.

### 8.3 Statistical baseline fallback

`StatisticalBaselineForecaster` implements the same interface without requiring torch. For each series it forecasts `future_profile_median + recent_deviation` and emits quantile bands sampled from the residual distribution. Runs in ~2 s for the full precompute. Used when:

- `torch` or the `timesfm` package isn't importable.
- `--baseline` is passed to `precompute.py` for fast iteration.

The baseline is **not** a stand-in for TimesFM's behaviour — it is deliberately conservative (rarely predicts congestion inside the horizon). Useful for plumbing, not for evaluation.

## 9. PredictionFusion — the v2.1 prior

For each (segment, anchor) the fusion layer produces a small record that the UI displays below the corridor view:

```python
@dataclass
class SegmentFusion:
    skipped: bool                           # v2.1 FREE_FLOW + HIGH confidence → skip
    skip_reason: str | None
    congestion_onset_predicted_min: int | None   # first CONG in forecast, or None
    congestion_onset_typical_min: int | None     # median historical onset in this window
    agreement: str                          # AGREE | EARLIER | LATER | NO_PREDICTED | NO_HISTORICAL
    fusion_note: str                        # one-liner for the UI tooltip
```

### 9.1 Typical-onset scoping

"Typical onset" is the median of historical onsets that **fell inside the anchor's 90-min window**, not an all-time-of-day average. This is the correct comparison — it answers "did this segment historically congest in a window like this one?"

### 9.2 Agreement thresholds

`AGREE` when `|predicted - typical| ≤ 20 min`. Tolerance is configurable in `fusion.py::ONSET_AGREEMENT_TOL_MIN`.

### 9.3 Gating

When v2.1's verdict is `FREE_FLOW` and its confidence label is `HIGH`, the segment is marked `skipped`. The forecast is still computed (for consistency) but the UI greys it out and displays the skip reason.

## 10. UI — the replay page

One self-contained HTML per (corridor, held-out-date), embedded forecast JSON. No external dependencies.

### 10.1 The slider

Two draggable markers on a 00:00–24:00 rail:

- **Anchor** (orange dot) — snaps to pre-computed 30-min anchor ticks in `[02:00, 20:00]`. Represents the moment the forecaster is called. Movable either by drag or by the dropdown.
- **Playhead** (blue diamond) — free-scrubbing across the whole day. Represents *what moment to display on the corridor*.

Three zones are rendered on the rail:
- **Past-of-anchor** — green tint. Playhead here → segments show actual observed regime.
- **Forecast window (`[anchor, anchor+90]`)** — violet diagonal hatching. Playhead here → segments show TimesFM prediction; rects get a violet dashed outline.
- **Future-of-horizon** — blue tint. Playhead here → segments show actual (this is the rest of the day's ground truth, useful for scrubbing past the horizon).

### 10.2 The corridor view

Segments are drawn as rectangles **proportional to length**, coloured by the current regime at the playhead, with:

- Segment label (`S01`, `S02`, …) below.
- Sub-label showing `length · regime_now`.
- **Dynamic bottleneck icon** above the segment, shown only when the live regime is `CONGESTED` (orange `!`) or `SEVERE` (red `⚠`). Icon outline is violet-dashed when the playhead is in the forecast zone, solid dark when in actual.

v2.1 structural verdicts (`HEAD_BOTTLENECK`, `ACTIVE_BOTTLENECK`) are shown in the per-segment detail cards below, not on the bar itself — the bar stays a live regime monitor.

### 10.3 Detail cards

One per segment, showing verdict badge, recurrence band, predicted onset (from TimesFM), typical onset (from v2.1 onsets), and the agreement flag colour-coded:
- `AGREE` — green
- `EARLIER_THAN_USUAL` — amber
- `LATER_THAN_USUAL` — sky
- `NO_PREDICTED` — red
- `NO_HISTORICAL` — muted

### 10.4 Controls

- `Play / Pause` — advances the playhead forward 2 min per tick, configurable 10×/20×/60×/120× real-time.
- `Reset` — recentre anchor at midday, playhead 30 min ahead.
- `Anchor` dropdown — jump to any of the 37 pre-computed anchor ticks.

### 10.5 Index page

`docs/replay/index.html` lists all 18 HTMLs.

## 11. Configuration reference

All tunables are in `data/v2_1/predict/config.py`:

```python
BUCKET_MIN              = 2               # bucket size in minutes
ANCHOR_START_MIN        = 120             # 02:00 IST — earliest anchor
ANCHOR_END_MIN          = 1200            # 20:00 IST — latest anchor
ANCHOR_STEP_MIN         = 30              # anchor resolution

HORIZON_MIN             = 90
HORIZON_STEPS           = 45

HISTORY_DAYS_CONCAT     = 1               # C2 context: history days to prepend
MIN_OBSERVED_CTX        = 60              # minimum today-so-far samples

REGIME_FREE_MIN         = 0.80            # speed_ratio thresholds, v2.1 consistent
REGIME_APPR_MIN         = 0.50
REGIME_CONG_MIN         = 0.30

HELD_OUT_DATES          = ["2026-04-21", "2026-04-22", "2026-04-23"]
CORRIDORS_TO_RUN        = ["PUNE_A", "PUNE_B", "PUNE_C",
                           "KOL_A",  "KOL_B",  "KOL_C"]

Q10_IDX, Q50_IDX, Q90_IDX = 1, 5, 9       # TimesFM quantile indices
```

Fusion thresholds: `fusion.py::ONSET_AGREEMENT_TOL_MIN = 20`.

## 12. File / module reference

```
data/v2_1/predict/
├── __init__.py
├── config.py               ← tunables + paths + anchor-tick generator
├── data_loader.py          ← corridor/profile/onset/diagnosis loaders
├── synthetic_day.py        ← held-out-day generator (swap for Postgres in prod)
├── live_context.py         ← C2 context assembly (history ++ today-so-far)
├── forecaster.py           ← TimesFMForecaster + StatisticalBaselineForecaster
├── regime_mapper.py        ← tt_sec → FREE/APPR/CONG/SEVR
├── fusion.py               ← v2.1 prior reconciliation
├── precompute.py           ← orchestrator; batched cross-corridor inference
├── render_replay.py        ← self-contained HTML per (corridor, date)
└── README.md               ← quick-start; points here for the design

data/v2_1/predict/held_out_days.json       ← generated by synthetic_day.py
data/v2_1/predict/forecasts/*.json         ← generated by precompute.py
docs/replay/*.html                         ← generated by render_replay.py
```

## 13. How to run it

```bash
# one-time: install deps
pip3 install --user numpy pandas torch
pip3 install --user "git+https://github.com/google-research/timesfm.git"

# 1. build held-out-day traces (synthetic, deterministic)
python3 -m data.v2_1.predict.synthetic_day

# 2. precompute all forecasts
#    TimesFM path (default): ~28 min on CPU
python3 -m data.v2_1.predict.precompute
#    baseline path (fast iteration): ~2 s
python3 -m data.v2_1.predict.precompute --baseline

# 3. render all HTML replays
python3 -m data.v2_1.predict.render_replay

# 4. open the index
open docs/replay/index.html
```

## 14. Known limitations — what's honest to call out

1. **Synthetic held-out day.** The replay isn't ground truth yet — it's a deterministic perturbation of the weekday median. Until Postgres access is wired, the "predicted vs actual" comparison is a smoke test, not a validation.
2. **Univariate forecaster.** TimesFM sees each segment independently. The LWR shockwave coupling that v2.1 validated is not used at prediction time. A single upstream-segment covariate (via `forecast_with_covariates`) would be the cheapest upgrade.
3. **Context trimmed for CPU latency.** `HISTORY_DAYS_CONCAT = 1` is a compute compromise. GPU deployment should raise it to 7+.
4. **Quantile calibration unverified.** TimesFM 2.5's continuous quantile head emits `q10` and `q90` bands, but nobody has measured PI coverage on Indian urban traffic. The bands are plotted but not yet trusted.
5. **No live streaming.** Replay only. Hook exists in `LiveContextBuilder`; caller must swap the held-out-day load for a rolling `traffic_observation` pull.
6. **Weekday only.** Mirrors v2.1's default. Weekend slicing would need a separate `held_out_dates` and `profiles_weekend.json` path.
7. **Anchor density is coarse (30 min).** Fine for the UI scrubber, suboptimal for evaluation metrics that want per-2-min predictability curves. Raising to 2-min requires 15× more compute.
8. **No evaluation harness.** We produce "predicted" and "actual" side-by-side but there's no `compute_mae_by_time_of_day()` utility yet. That's the obvious next script.

## 15. Roadmap / open questions

**Next obvious moves, roughly in priority order:**

1. **Wire real probe data.** Add `postgres_pull.py` replacing `synthetic_day.py`. Validate the replay end-to-end on one real held-out day.
2. **Evaluation harness.** Per-segment regime-accuracy, onset MAE, directional correctness (did we predict the onset hour right?), all as functions of time-of-day. Emit both JSON and an HTML summary per corridor.
3. **Upstream-covariate TimesFM.** Feed segment `i-1`'s series as a `dynamic_numerical` covariate to segment `i`'s forecast. Re-evaluate and compare to univariate.
4. **GPU inference.** Raise `HISTORY_DAYS_CONCAT` to 7. Measure latency and accuracy delta.
5. **Live mode.** A continuously-running daemon that anchors at every 2 min from `now` and publishes the latest forecast + fusion JSON to a topic/endpoint.
6. **Weekend slice.** Mirror the `_weekend` suffix that already exists in `profiles/`.
7. **Incident detection.** Use the quantile bands on `actual_day` data to flag anomalies as they happen (v2.5 quantile head supports backcasting too).
8. **UI: evaluation overlay mode.** When playhead is in the forecast zone, toggle between "predicted" and "actual + predicted hatched overlay" to see the disagreement visually.
9. **UI: predictability curve.** Small line chart alongside the corridor showing MAE-as-a-function-of-anchor for the current held-out day. Tells the operator which anchors to trust.

**Open questions worth discussing later:**

- Should the predictor's output be consumed by CityPulse (Phase 3) or is it a separate surface? They overlap in purpose.
- Is "foundation model + v2.1 prior" the right factoring, or should v2.1 be embedded as an input feature to a single trained model instead of a post-hoc layer?
- How do we handle the day-of-week effect we talked about but skipped in v1 — do we train separate models per weekday, or add weekday as a categorical covariate, or let TimesFM's context length handle it?
- What's the right SLA for prediction freshness in a real deployment — every 2 min, every 30 s, streaming?

---

## Relation to the other phases

- **Phase 1 (Foundation)** — consumed directly: `traffic_observation`, `road_segment`.
- **Phase 2 (v1 diagnostic)** — irrelevant; this layer rides v2.1, not v1.
- **Phase 3 (CityPulse)** — *this layer occupies CityPulse's space*. The original Phase 3 plan was a from-scratch predictor. This layer is a simpler, v2.1-anchored alternative. Decide later whether to merge or keep separate.
- **Phase 4 (v2 / v2.1 diagnostic)** — parent layer. The v2.1 output is the prior that makes this layer's fusion work.
