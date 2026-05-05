# Corridor Diagnostics v3-A — Design Spec

**Date:** 2026-05-04
**Branch:** `vishwadoshi-lepton/v3-plan`
**Engine version target:** `v3.a.0`
**Author of intent:** user; doc captures the brainstorming output for deterministic execution by Claude.

---

## 0. Reading guide

This spec is the single source of truth for v3-A implementation. It is written so that an executing agent (specifically: a future Claude session) can implement v3-A end-to-end without re-litigating any decision. Every threshold, file path, function signature, SQL skeleton, error code, and pass/fail criterion is pinned. Whenever the implementation has a choice, the spec picks one.

If a question arises during implementation that the spec does not cover, the implementing agent must:
1. Stop and ask, OR
2. Pick the option that minimises change to v2.1 outputs and document the choice in `docs/CORRIDOR_DIAGNOSTICS_V3A_OPEN_DECISIONS.md`.

Implementation must NOT diverge from this spec without an explicit user override.

---

## 1. Overview

**v3-A is the corridor-deep extension of v2.1.** It adds four research-grounded Tier-1 modules on top of v2.1's six-stage diagnostic and introduces "Mode B" — point-in-time diagnostics anchored at an arbitrary timestamp `T` ("diagnose corridor A at 7pm today / yesterday / on April 15"). It does NOT touch v2.1 code, does NOT introduce a Delhi 3000-segment network (deferred to v3-B), and does NOT add a live-snapshot mode (Mode A — deferred to FUTURE_WORK).

### 1.1 What v3-A delivers

1. A new module `data/v3_a/` that wraps v2.1's stages 1–6 with anchor-time semantics (Mode B).
2. Four Tier-1 modules: **growth-rate** (Duan 2023), **percolation-on-corridor** (Li 2015 / Zeng 2019 / Ambühl 2023), **jam-tree + temporal precedence** (Serok 2022 + Duan 2023), **MFD with hysteresis** (Geroliminis & Daganzo 2008 / Saberi & Mahmassani 2013).
3. A "DOW anomaly" layered signal (today vs same-day-of-week typical), self-gating on sample size.
4. A unified output envelope with `schema_version: "v3"` and a `mode` discriminator.
5. An on-demand run lifecycle (submit → poll/stream → completed) with stage-progress events and a per-corridor concurrency-1 lock.
6. A two-tier cache (5-min TTL for today anchors, infinite for replay anchors).
7. A CLI (`python -m data.v3_a.cli`) to run any (corridor, anchor) combination.
8. A validation gate: pass-through equivalence on retrospective + Tier-1 sanity on KOL_B/KOL_C.

### 1.2 What v3-A does NOT deliver

- No network-level analysis. No 3000-segment Delhi graph. No percolation across corridors. (→ v3-B)
- No live snapshot mode (`mode = "live_snapshot"`). (→ Mode A in FUTURE_WORK)
- No scaling-exponent module (Tier-1 #5 from research dossier). (→ FUTURE_WORK; needs ≥4 weeks data)
- No prediction layer. v1 prediction sub-pipeline (`data/v2_1/predict/`) is unaffected.
- No new database tables. No background workers. No daily extraction crons.
- No frontend code. v3-A defines the UI **API contract**; Trafficure UI is implemented separately by the frontend team using this contract.

---

## 2. Locked decisions index

Captured during the brainstorming dialogue. Implementation must match.

| # | Decision | Locked value |
|---|---|---|
| Q1 | v3 axis order | A first (corridor-deep) → B (network) later |
| Q2 | Mode meaning | Mode B (today-as-of-T) is MVP; Mode A deferred; long-term coexists with retrospective |
| Q3 | Tier-1 modules in MVP | Growth-rate, percolation-on-corridor, jam-tree, MFD. Scaling exponent → FUTURE_WORK |
| Q4 | Corridor coverage MVP | DEL_AUROBINDO + KOL_B + KOL_C. Engine runs corridor-agnostic |
| Q5 | Anchor T semantics | Single `datetime` param. Live = `now()`, today-scrub = today, replay = past `(day, time)` |
| Q6 | Baseline window | Trailing 22 weekdays (preserves v2.1) + same-DOW track when N≥3 |
| Q7 | Output schema | Unified envelope: `{schema_version, mode, anchor_ts, corridor_id, payload, meta}` |
| Q8 | UI page model | Single page, three modes in header (Retrospective / Today / Replay) |
| Q9 | Page layout | Two-column: timeline-first centerpiece + right sidebar (Tier-1 + verdicts + meta) |
| Q10 | Delhi registry | Defer to v3-B; v3-A does not materialise it |
| Q11 | Run trigger | On-demand. Cache: today=5min TTL, replay=infinite. Per-corridor concurrency=1 |
| Q12 | Run UX | Async-first API: submit → run_id → poll/stream stage events; visible run states; cache-meta chip on render |
| Q13 | Error policy | Hard errors → `failed`; soft (gap, thin baseline, quiet day) → `completed` with `partial: true` + `warnings: []` |
| Q14a | Engine location | New module `data/v3_a/` (sibling to `data/v2_1/`) |
| Q14b | Validation gate | Both pass-through equivalence (b1) AND Tier-1 sanity on KOL_B/KOL_C (b2) |
| Q15 | Architecture | Linear pipeline + Tier-1 module registry |

---

## 3. Repository layout (v3-A)

All paths relative to repo root.

```
data/v3_a/
├── __init__.py
├── README.md                      # module overview, links to this spec
├── run.py                         # main orchestrator: run_diagnostic(...)
├── api.py                         # run lifecycle: submit_run, get_run, in-memory registry
├── progress.py                    # ProgressEmitter, RunStatus, run records
├── cache.py                       # cache layer with TTL semantics
├── envelope.py                    # build the unified envelope dict
├── data_pull.py                   # SQL queries (today data, baseline data, raw onsets)
├── baseline.py                    # 22-weekday baseline + same-DOW track, as-of T
├── stages_v21.py                  # thin wrappers calling into data/v2_1/* with anchor semantics
├── regime_today.py                # build today's per-bucket regimes for the corridor (Mode B)
├── dow_anomaly.py                 # DOW deviation track
├── errors.py                      # error codes (hard + soft) + exceptions
├── cli.py                         # python -m data.v3_a.cli ...
├── tier1/
│   ├── __init__.py                # registry: Tier1Module ABC, register, list, run_all
│   ├── growth_rate.py
│   ├── percolation.py
│   ├── jam_tree.py
│   └── mfd.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── kolb_2026-04-22.json   # captured `traffic_observation` rows for one weekday
│   │   ├── kolb_baseline_22d.json # pre-computed baseline as of 2026-04-22 EOD
│   │   ├── kolc_2026-04-22.json
│   │   ├── kolc_baseline_22d.json
│   │   ├── del_aurobindo_2026-04-22.json
│   │   └── del_aurobindo_baseline_22d.json
│   ├── test_pass_through_equivalence.py
│   ├── test_tier1_sanity.py
│   ├── test_growth_rate.py
│   ├── test_percolation.py
│   ├── test_jam_tree.py
│   ├── test_mfd.py
│   ├── test_dow_anomaly.py
│   ├── test_envelope.py
│   ├── test_cache.py
│   ├── test_progress.py
│   ├── test_errors.py
│   ├── test_data_pull.py
│   └── test_cli.py
docs/
├── superpowers/specs/2026-05-04-corridor-diagnostics-v3a-design.md  # this file
├── CORRIDOR_DIAGNOSTICS_V3A_FUTURE_WORK.md                           # Mode A, Tier-1 #5, v3-B handoff
└── CORRIDOR_DIAGNOSTICS_V3A_OPEN_DECISIONS.md                        # only if the implementer hits a gap
```

The implementing agent creates this layout exactly. No other directories or files.

---

## 4. Conceptual model

### 4.1 Buckets

The pipeline operates on a **2-min bucket grid**: bucket 0 = `00:00:00`, bucket 1 = `00:02:00`, …, bucket 719 = `23:58:00`. Bucket index of a timestamp `t`: `floor((minute_of_day(t)) / 2)`.

`anchor_ts` is truncated **down** to the start of its 2-min bucket before any computation. The truncated form is the canonical anchor used throughout. The original is preserved in `meta.anchor_ts_received`.

### 4.2 Modes

The engine accepts three values for `mode`:
- `"today_as_of_T"` — the v3-A MVP. Inputs = today's data in `[start_of_day(anchor_ts), anchor_ts]` (inclusive both ends, bucket-aligned). Baselines computed as-of `anchor_ts.date()`.
- `"retrospective"` — v2.1 behaviour preserved. `anchor_ts` ignored; baselines use the standard v2.1 trailing window.
- `"live_snapshot"` — reserved; `mode = "live_snapshot"` raises `ModeNotImplemented` in v3-A.

For v3-A MVP, the orchestrator's primary path is `today_as_of_T`. The `retrospective` mode is supported in `data/v3_a/run.py` exclusively to power the **pass-through equivalence test (b1)** and is not exposed via the CLI default.

### 4.3 Anchor time semantics

- An anchor before the start of probed data history is rejected with `HARD_ERR_ANCHOR_PRE_HISTORY`.
- An anchor in the future (`anchor_ts > now()` at engine-run time) is rejected with `HARD_ERR_FUTURE_ANCHOR`.
- An anchor in `[start_of_day(now()), now()]` triggers TTL caching (5 min).
- An anchor before `start_of_day(now())` is "replay" — caching infinite (the inputs are immutable).

All times in IST (`Asia/Kolkata`). The engine accepts ISO 8601 strings; if no timezone is given, IST is assumed and a soft warning `SOFT_WARN_TZ_ASSUMED` is emitted.

### 4.4 Two regime arrays

A subtle but critical distinction between v2.1 and Mode B:

- v2.1's "regimes" come from a **typical-day median profile** built from the trailing 22 weekdays. The "regime at bucket b" is "what the typical day's regime would be at bucket b."
- Mode B's "regimes" come from **today's actual data**, bucket by bucket. The "regime at bucket b" is "what is happening on this corridor at bucket b on this specific day."

Mode B carries BOTH:
- `regimes_today_by_seg` — for Stages 2, 2b, 3, 5; for all Tier-1 modules.
- `regimes_typical_by_seg` — for the DOW anomaly comparison and for rendering the typical-day overlay in the UI.

Stage 1 (free-flow) is computed once, from the historical baseline. It does NOT vary with anchor (other than the as-of-T cutoff for which historical days are pooled). Stage 6 (recurrence) is computed on the historical days only.

---

## 5. Inputs

### 5.1 Engine signature

```python
# data/v3_a/run.py

def run_diagnostic(
    corridor_id: str,
    anchor_ts: str | datetime,
    *,
    mode: str = "today_as_of_T",
    progress: "ProgressEmitter | None" = None,
    config: "EngineConfig | None" = None,
) -> dict:
    """
    Run a v3-A diagnostic. Returns the unified envelope as a plain dict.
    Raises HardError subclasses on hard failures (caller converts to run.failed).
    """
```

`progress` is a callback receiver; if `None`, progress events are dropped silently.

`config` is optional; the default is `EngineConfig.default()` defined in `data/v3_a/__init__.py`. Config controls thresholds and is plumbed through to all modules. Implementation must not introduce additional knobs beyond those defined in §10.

### 5.2 Corridor definition source

The engine reads corridor definitions from `data/v2_1/validation_corridors.json` (existing v2.1 file). Each entry yields:
- `corridor_id`, `corridor_name`
- `segment_order: list[str]` — segment UUIDs in upstream-to-downstream order
- `segment_meta: dict[str, dict]` — `{length_m, name, road_class?}`

If `corridor_id` is not in `validation_corridors.json`, raise `HARD_ERR_UNKNOWN_CORRIDOR`. v3-A does NOT add new corridors. The MVP corridor list is enforced in tests only — the engine itself runs whatever is in the registry.

### 5.3 Database access

v3-A uses the same Postgres connection mechanism as v2.1 (`data/v2_1/_env.py`, which only exposes `load_dotenv`). Connection details come from environment variables already in use; the implementer does NOT introduce new env vars.

The two production Postgres instances are:
- `192.168.2.86` — primary (for KOL_B, KOL_C)
- `192.168.2.97` — Delhi polyline-derived segments (DEL_AUROBINDO subset)

`data_pull.py` adds a local helper `pick_connection(corridor_id) -> psycopg.Connection` that maps `DEL_AUROBINDO` (and any future polyline-derived corridors flagged with `polyline_derived: true` in `validation_corridors.json`) to `.97`, everything else to `.86`. Connection params for both hosts are read from the existing env vars `PG_HOST_PRIMARY`, `PG_HOST_DELHI`, `PG_USER`, `PG_PASSWORD`, `PG_DB` (already used by v2.1). v3-A does NOT modify `data/v2_1/_env.py`.

### 5.4 SQL queries

#### 5.4.1 Today's observations (for Mode B)

```sql
SELECT road_id, event_time, current_travel_time_sec
FROM traffic_observation
WHERE road_id = ANY(%(road_ids)s::text[])
  AND event_time >= %(start_of_day)s::timestamptz
  AND event_time <  %(upper_bound)s::timestamptz   -- exclusive
ORDER BY road_id, event_time;
```

`start_of_day` = midnight IST of `anchor_ts.date()`. `upper_bound = truncated_anchor + 2 minutes` so the truncated-anchor bucket itself is fully included and no observations from the next bucket leak in. Implementations MUST use this exact half-open interval `[start_of_day, truncated_anchor + 2min)`.

#### 5.4.2 Baseline observations (trailing 22 weekdays, as-of T)

```sql
SELECT road_id, event_time, current_travel_time_sec
FROM traffic_observation
WHERE road_id = ANY(%(road_ids)s::text[])
  AND event_time >= %(window_start)s::timestamptz   -- 30 calendar days before anchor.date()
  AND event_time <  %(window_end)s::timestamptz     -- start_of_day(anchor.date())
  AND extract(isodow from event_time at time zone 'Asia/Kolkata') BETWEEN 1 AND 5
ORDER BY road_id, event_time;
```

Then in Python, group by `(road_id, day, bucket)`, take median TT per group, then median across days per bucket per segment → the "typical day" profile (existing v2.1 behaviour). Filter to the most recent 22 distinct weekdays after grouping. If fewer than 5 weekdays available, raise `HARD_ERR_INSUFFICIENT_BASELINE`. If 5–14 weekdays available, emit `SOFT_WARN_THIN_BASELINE` with `actual_n_days` in the message.

#### 5.4.3 Same-DOW baseline (for DOW anomaly track)

```sql
SELECT road_id, event_time, current_travel_time_sec
FROM traffic_observation
WHERE road_id = ANY(%(road_ids)s::text[])
  AND event_time >= %(window_start)s::timestamptz   -- 6 weeks before anchor.date()
  AND event_time <  %(window_end)s::timestamptz     -- start_of_day(anchor.date())
  AND extract(isodow from event_time at time zone 'Asia/Kolkata') = %(target_dow)s
ORDER BY road_id, event_time;
```

`target_dow` = `isodow(anchor_ts)`. Then group as above. Final sample count = number of distinct same-DOW days in the result. Track is **available** iff `n_samples >= 3`; otherwise `available: false` and the track is omitted from the payload.

#### 5.4.4 Historical onsets (for Stage 4 shockwave + Stage 6 recurrence)

The existing v2.1 helper `data/v2_1/pull_onsets.py:pull_onsets(...)` is reused via `stages_v21.py`. The implementer adds an `as_of_date` parameter to that helper IF it does not already accept one — wrapping the existing function in v3_a/stages_v21.py to filter the returned list to days strictly before `anchor_ts.date()`. Do NOT modify pull_onsets.py itself; the filter happens in v3_a's wrapper.

### 5.5 Inputs to Tier-1 modules

After Stage 6, the orchestrator builds an **execution context** (`tier1.Context` dataclass) with:

```python
@dataclass(frozen=True)
class Context:
    corridor_id: str
    corridor_name: str
    anchor_ts: datetime              # truncated-to-bucket
    anchor_bucket: int               # 0..719
    today_date: date                 # anchor_ts.date()
    segment_order: tuple[str, ...]
    segment_meta: Mapping[str, dict] # {seg_id: {length_m, name, road_class?}}
    total_length_m: float
    n_buckets: int                   # anchor_bucket + 1
    regimes_today_by_idx: tuple[tuple[str, ...], ...]   # [seg_idx][bucket] -> regime label
    regimes_typical_by_idx: tuple[tuple[str, ...], ...] # [seg_idx][bucket] -> regime label (full 720)
    bertini_events: tuple[BertiniEvent, ...]            # from today's Stage 3
    head_bottleneck_events: tuple[HeadEvent, ...]       # from today's Stage 3 R3
    primary_windows_today: tuple[tuple[int, int], ...]
    historical_onsets_by_seg: Mapping[str, tuple[tuple[date, int], ...]]  # for jam-tree comparison
    today_onsets_by_seg: Mapping[str, int]              # earliest onset bucket today, per seg
    speed_today_by_idx: tuple[tuple[float, ...], ...]   # [seg_idx][bucket] -> kmph (computed from current TT and length)
    config: EngineConfig
```

Tier-1 modules receive only this `Context` and return only their module-specific result dict; they have no side effects.

`BertiniEvent` and `HeadEvent` are dataclasses with `(segment_id, segment_idx, t0_bucket, t1_bucket_inclusive)` and any v2.1-side metadata.

### 5.6 EngineConfig (the single source of all thresholds)

```python
@dataclass(frozen=True)
class EngineConfig:
    # v2.1-inherited (DO NOT change defaults; only mirrored here for docs)
    ff_ceiling_kmph: float = 80.0
    regime_thresholds: tuple[float, float, float] = (0.80, 0.50, 0.30)
    bertini_min_minutes: int = 10
    shockwave_kmph_range: tuple[float, float] = (12.0, 22.0)
    shockwave_tolerance_min: int = 3
    systemic_simul_pct: float = 0.80
    systemic_contig_pct: float = 0.60

    # v3-A new
    tier1_growth_window_buckets: int = 7         # 14 minutes; see §7.1 for justification
    tier1_growth_min_buckets: int = 4            # below this → INSUFFICIENT_DATA label
    tier1_growth_fast_m_per_min: float = 50.0    # Duan 2023
    tier1_growth_moderate_m_per_min: float = 10.0
    tier1_percolation_unit: str = "length_m"     # alternative: "segment_count" — pinned to length_m
    tier1_jamtree_adjacency_only: bool = True    # parents must be adjacent (1-D chain). Future v3-B may relax.
    tier1_mfd_density_unit: str = "length_fraction"
    dow_anomaly_n_weeks_lookback: int = 6
    dow_anomaly_min_samples: int = 3
    baseline_n_weekdays: int = 22
    baseline_min_weekdays: int = 5
    baseline_thin_threshold: int = 14            # below this → SOFT_WARN_THIN_BASELINE
    cache_today_ttl_sec: int = 300               # 5 minutes
    cache_anchor_truncation_sec: int = 120       # 2 minutes (bucket size)
    run_timeout_sec: int = 60                    # any single run >60s → HARD_ERR_TIMEOUT
    per_corridor_concurrency: int = 1
```

`EngineConfig.default()` returns this dataclass with no fields changed. Tests are allowed to construct alternate configs; production code must use `default()`.

---

## 6. Pipeline

Ordered. Each step emits one `progress` event when it starts and one when it completes (with `status="completed" | "skipped" | "failed"`). A failed step in a hard category stops the run.

| # | Stage name | Source | Inputs | Outputs |
|---|---|---|---|---|
| 1 | `s1_freeflow` | v2.1 (imported via stages_v21) | baseline profile (as-of T) | per-segment `ff_tt`, `ff_speed_kmph`, warnings |
| 2 | `s2_regimes_today` | new (`regime_today.py`) | today's segment TTs, `ff_tt` | `regimes_today_by_idx` |
| 2t | `s2_regimes_typical` | v2.1 logic on typical profile | baseline profile, `ff_tt` | `regimes_typical_by_idx` (full 720) |
| 2b | `s2b_primary_windows_today` | v2.1 length-weighted rule | `regimes_today_by_idx`, `lengths_m` | `primary_windows_today` |
| 3 | `s3_bertini_today` | v2.1 logic | `regimes_today_by_idx`, `primary_windows_today` | `bertini_events`, `head_bottleneck_events` |
| 4 | `s4_shockwave` | v2.1 logic | historical onsets (filtered as-of T) + today's onsets | shockwave pair list |
| 5 | `s5_systemic_today` | v2.1 (both v2 80% and v2.1 60% rules) | `regimes_today_by_idx`, `lengths_m` | `systemic_v2`, `systemic_v21` |
| 6 | `s6_recurrence` | v2.1 logic | historical onsets (filtered as-of T) | per-segment recurrence band |
| 7 | `s7_confidence_verdicts` | v2.1 logic | all of the above | per-segment verdict + confidence + breakdown + R8 baseline_flags |
| 8 | `tier1.growth_rate` | new | Context | `growth_rate` payload |
| 9 | `tier1.percolation` | new | Context | `percolation` payload |
| 10 | `tier1.jam_tree` | new | Context | `jam_tree` payload |
| 11 | `tier1.mfd` | new | Context | `mfd` payload |
| 12 | `dow_anomaly` | new | today's TTs, same-DOW baseline | `dow_anomaly` payload (or omitted if unavailable) |
| 13 | `envelope_assembly` | new | all of the above | unified envelope dict |

Numbering convention: the `#` column groups stages — `2`, `2t`, `2b` are all "stage 2 family"; `1` through `7` are the v2.1 + today-side block (rows with `s1_…` through `s7_…`); rows `8` through `12` are Tier-1 + DOW; row `13` is envelope assembly.

Stages 1–7 (the `s1_…` through `s7_…` rows, including 2t and 2b) are **mandatory**. A hard failure in any of them aborts the run. Rows 8–12 (Tier-1 modules + DOW) are **soft**: a failure emits `SOFT_WARN_TIER1_<name>_FAILED` (or `SOFT_WARN_DOW_FAILED`) and that payload becomes `null`; the run still completes with `partial: true`. Row 13 (envelope assembly) always runs after the soft block, even if Tier-1 failures occurred.

`s2_regimes_typical` is computed lazily — only if `dow_anomaly` is unavailable (so the operator sees the typical profile as a fallback overlay) OR if the UI requested it via a config flag (`config.always_compute_typical=True` is currently unused in MVP; pin `False` until UI decides).

For pass-through equivalence (b1), `mode = "retrospective"` runs ONLY stages 1, 2t, 2b (on typical), 3, 4, 5, 6, 7 — exactly as v2.1 does today. No today-side stages, no Tier-1, no DOW anomaly. The output envelope's `payload.tier1` is `{}` and `payload.stages_v21` matches v2.1's `to_plain_dict()` byte-for-byte (after key-order normalisation).

---

## 7. Tier-1 module specs

Each module implements the `Tier1Module` ABC:

```python
# data/v3_a/tier1/__init__.py

class Tier1Module(ABC):
    name: str                         # e.g. "growth_rate"
    @abstractmethod
    def required_inputs(self) -> set[str]: ...     # subset of Context attrs
    @abstractmethod
    def run(self, ctx: Context) -> dict: ...        # the module-specific payload

REGISTRY: list[Tier1Module] = []  # populated by `register(...)` on import

def register(module: Tier1Module) -> None: ...
def run_all(ctx: Context, progress: ProgressEmitter) -> dict[str, dict]: ...
```

`run_all` iterates `REGISTRY` in order, emits progress events, catches `Exception` per module (NOT `BaseException`), and on exception logs the traceback to `meta.warnings` and sets that module's payload to `None`. Order of registration = order of execution. Order is fixed in `tier1/__init__.py`:

```python
from .growth_rate import GrowthRate
from .percolation import Percolation
from .jam_tree import JamTree
from .mfd import MFD

register(GrowthRate())
register(Percolation())
register(JamTree())
register(MFD())
```

### 7.1 Growth-rate (`growth_rate.py`)

**Paper:** Duan et al. 2023, "Spreading and Recovery of Traffic Congestion in Urban Road Networks."

**Concept:** The slope of cluster growth in the first 15 minutes after a Bertini event predicts eventual cluster severity.

**Algorithm:**

For each event in `ctx.bertini_events ∪ ctx.head_bottleneck_events`:

1. `t0 = event.t0_bucket`. Define growth window `W = [t0, t0 + tier1_growth_window_buckets - 1]` clipped to `[t0, ctx.anchor_bucket]`.
2. Let `nbuckets = len(W)`. If `nbuckets < tier1_growth_min_buckets` (default 4), label = `"INSUFFICIENT_DATA"`, slope = `None`, samples = `nbuckets`. Skip to next event.
3. For each bucket `b ∈ W`, compute `cluster_length_m(b)`:
   - Start at `event.segment_idx`. Walk left while regime ∈ {CONGESTED, SEVERE}. Walk right same. Sum lengths of all walked segments INCLUDING the event segment.
   - If event segment regime at b is FREE/APPROACHING (regime "thawed"), `cluster_length_m(b) = 0`.
4. Convert window to minutes: bucket `b` → minute `b * 2`.
5. Fit OLS slope on (minute, cluster_length_m). If all `cluster_length_m` are zero → slope = 0.0, label = `"CONTAINED"`.
6. Classify by slope (units: m/min):
   - `slope >= tier1_growth_fast_m_per_min` (50) → `"FAST_GROWTH"`
   - `slope >= tier1_growth_moderate_m_per_min` (10) → `"MODERATE"`
   - else → `"CONTAINED"`
7. Emit `{event_id, segment_id, t0_minute, growth_window_minutes, samples_used, slope_m_per_min, cluster_length_m_at_t0, cluster_length_m_at_tend, label}`.

**Note on window size:** 15 min / 2 min = 7.5 buckets. Pinned to 7 buckets (= 14 minutes of clock time, 8 distinct samples including endpoints). This is the closest under-15min option that fits an integer number of 2-min buckets without over-extending.

**Output payload:**

```jsonc
"growth_rate": {
  "events": [
    {
      "event_id": "BERTINI-S03-1",
      "segment_id": "...",
      "segment_idx": 2,
      "t0_minute": 524,
      "t0_bucket": 262,
      "growth_window_minutes": 14,
      "samples_used": 7,
      "slope_m_per_min": 67.3,
      "cluster_length_m_at_t0": 200,
      "cluster_length_m_at_tend": 1110,
      "label": "FAST_GROWTH"
    }
    // …
  ],
  "summary": {
    "n_events": 5,
    "n_fast": 1, "n_moderate": 3, "n_contained": 1, "n_insufficient": 0
  }
}
```

`event_id` format: `"BERTINI-{segment_id}-{ordinal}"` where `ordinal` is `1, 2, …` per segment per day. `HEAD-{segment_id}-{ordinal}` for head_bottleneck events. Stable across cache hits.

### 7.2 Percolation-on-corridor (`percolation.py`)

**Papers:** Li et al. 2015, Zeng et al. 2019, Ambühl et al. 2023.

**Concept:** Track the largest (LCC) and second-largest connected component (SLCC) of CONGESTED ∪ SEVERE segments per bucket. The bucket where SLCC peaks is the systemic phase transition (the moment the two largest clusters are about to merge).

**Algorithm:**

For each `b ∈ [0, ctx.anchor_bucket]`:

1. Build occupied set `O_b = { i : ctx.regimes_today_by_idx[i][b] ∈ {"CONGESTED", "SEVERE"} }`.
2. Compute connected components on the chain (i, i+1) restricted to `O_b`. Each component has a length sum (in metres).
3. Sort component lengths descending → `[lcc, slcc, ...]`.
4. `lcc_trace[b] = lcc` (or 0 if empty), `slcc_trace[b] = slcc` (or 0 if `< 2` components).

Then:

- `onset_bucket = argmax(slcc_trace)` over `[0, anchor_bucket]`. If `max(slcc_trace) == 0`, `onset_bucket = None`.
- `onset_minute = onset_bucket * 2` if not None.
- `onset_lcc_m = lcc_trace[onset_bucket]`, `onset_slcc_m = slcc_trace[onset_bucket]`.
- `time_to_merge_minutes`: if `onset_bucket` is not None and there exists a later bucket `b* > onset_bucket` where `slcc_trace[b*] == 0` AND `lcc_trace[b*] >= lcc_trace[onset_bucket] + onset_slcc_m * 0.5`, then `time_to_merge_minutes = (b* - onset_bucket) * 2`; else `None`.

**Pin: percolation operates in length-units (metres).** Segment-count alternative is rejected (loses asymmetry between long and short segments).

**Output payload:**

```jsonc
"percolation": {
  "lcc_trace_m": [0, 0, …, 1500.2, 1500.2, …],     // length = anchor_bucket + 1
  "slcc_trace_m": [0, 0, …, 800.0, 750.0, …],
  "onset_bucket": 480,
  "onset_minute": 960,
  "onset_lcc_m": 1500.2,
  "onset_slcc_m": 800.0,
  "time_to_merge_minutes": 12,
  "summary": {
    "max_lcc_m": 2680.5,
    "max_slcc_m": 800.0,
    "buckets_with_2plus_components": 47
  }
}
```

If `onset_bucket is None`, all "onset_*" fields are `None`, `time_to_merge_minutes` is `None`, `summary.max_slcc_m = 0.0`.

### 7.3 Jam-tree + temporal precedence (`jam_tree.py`)

**Papers:** Serok et al. 2022 (cascade trees), Duan et al. 2023 (temporal precedence).

**Concept:** Build a causal tree of today's onsets. Onsets are sorted by time; each non-root attaches to the closest-in-time, adjacent earlier-onset segment. A v2.1 QUEUE_VICTIM that fires before its supposed-bottleneck neighbour is reclassified.

**Algorithm:**

1. Collect today's onsets:
   - For each segment `s`, define `onset_today(s)` = earliest bucket `b` where the segment enters CONG/SEVR after at least one prior bucket of FREE/APPR (or bucket 0 if it starts CONG/SEVR). If the segment never enters CONG/SEVR today, it has no onset.
   - Restrict to segments with onsets; build list `onsets = [(s, onset_today(s))]` sorted by bucket ascending, then by segment index ascending as tiebreaker.

2. For each `(s_i, b_i)` in order:
   - Find adjacent indices `j ∈ {idx(s_i) - 1, idx(s_i) + 1}` that are valid (within corridor bounds).
   - Among adjacent segments with `onset_today(s_j) < b_i`, pick the one with the largest `onset_today(s_j)` (closest in time, earlier).
   - If no candidate, `s_i` is an ORIGIN (root).
   - Else, `parent = s_j`.

3. Tree depth: BFS from each ORIGIN; `depth(root) = 0`.

4. **Temporal precedence reclassification of v2.1 verdicts:** for each segment `s` with `verdict == "QUEUE_VICTIM"` in v2.1:
   - Find adjacent ACTIVE_BOTTLENECK or HEAD_BOTTLENECK segments today (those segments fired Bertini today).
   - If `onset_today(s)` is strictly less than the onsets of all adjacent bottlenecks → emit a reclassification record:
     `{segment_id: s, v21_verdict: "QUEUE_VICTIM", tree_role: "ORIGIN" | "PROPAGATED", reason: "preceded supposed bottleneck", earlier_by_minutes: int}`.
   - Reclassifications are surfaced in the payload but DO NOT mutate `payload.stages_v21.verdicts`. The stages_v21 verdicts are the v2.1 truth; the jam-tree provides a *secondary causal annotation* the UI can layer on.

5. Compute summary stats: `n_origins`, `n_propagated`, `max_depth`, `n_reclassifications`.

**Output payload:**

```jsonc
"jam_tree": {
  "nodes": [
    {"segment_id": "...", "segment_idx": 0, "onset_bucket": 510, "onset_minute": 1020, "parent_segment_id": null, "depth": 0, "role": "ORIGIN"},
    {"segment_id": "...", "segment_idx": 1, "onset_bucket": 524, "onset_minute": 1048, "parent_segment_id": "...", "depth": 1, "role": "PROPAGATED"}
    // …
  ],
  "edges": [
    {"parent_segment_id": "...", "child_segment_id": "...", "lag_minutes": 28}
  ],
  "summary": {
    "n_origins": 2,
    "n_propagated": 5,
    "max_depth": 3,
    "n_reclassifications": 1
  },
  "queue_victim_reclassifications": [
    {
      "segment_id": "...",
      "v21_verdict": "QUEUE_VICTIM",
      "tree_role": "ORIGIN",
      "reason": "preceded supposed bottleneck",
      "earlier_by_minutes": 14
    }
  ]
}
```

If no segments have onsets today (quiet day), output is `{"nodes": [], "edges": [], "summary": {"n_origins": 0, "n_propagated": 0, "max_depth": 0, "n_reclassifications": 0}, "queue_victim_reclassifications": []}` and `SOFT_WARN_QUIET_DAY` is emitted.

### 7.4 MFD with hysteresis (`mfd.py`)

**Papers:** Geroliminis & Daganzo 2008, Saberi & Mahmassani 2013, Ambühl et al. 2023.

**Concept:** Plot length-weighted mean speed vs density (length-fraction in CONG/SEVR) for each bucket of the day; the loop traversed by these points has a measurable area = capacity-loss for the episode.

**Algorithm:**

For each `b ∈ [0, ctx.anchor_bucket]`:

1. `density(b) = sum(length_m of segments where regime ∈ {CONG, SEVR} at b) / total_length_m`. Range [0, 1].
2. `speed(b)` = length-weighted mean speed across all segments at b:
   `speed(b) = sum(length_m[i] * speed_today_by_idx[i][b]) / total_length_m` (kmph).
   - If a segment has missing data for bucket `b` (NaN speed), exclude it from the weighted average and rescale weights. If all segments are missing, `speed(b) = NaN`.

Now the trajectory is the list `points = [(density(0), speed(0)), …, (density(anchor_bucket), speed(anchor_bucket))]`.

3. Filter NaN points (do not interpolate).

4. Compute loop area:
   - If `len(points_filtered) < 4`, `loop_area = 0.0`, `loop_closes = false`, emit `SOFT_WARN_MFD_THIN`.
   - Else, treat points in time order as a polyline. The loop "closes" iff `density(0) ≤ 0.05` AND `density(anchor_bucket) ≤ 0.05`. If anchor_bucket is mid-day, set `loop_closes = false`.
   - Loop area via shoelace formula on the time-ordered polyline (signed area = `0.5 * sum(x_i * y_{i+1} - x_{i+1} * y_i)`). For a non-closing trajectory, conceptually close with a straight segment from end → start before computing shoelace.
   - Units: `density` ∈ [0,1] (dimensionless), `speed` in kmph → loop_area units = `kmph · density-fraction`. Sign: positive if traversed clockwise (typical: density rises then falls, speed falls then rises).

5. Compute `peak_density_bucket = argmax(density)` and `peak_density = density(peak_density_bucket)`.

6. Compute `recovery_lag_min`:
   - Find first bucket `b* > peak_density_bucket` where `density(b*) <= peak_density / 2` (density halved) — call this `b_d_recovery`.
   - Find first bucket `b' > peak_density_bucket` where `speed(b') >= ff_corridor_kmph - 5 km/h` where `ff_corridor_kmph` is the length-weighted mean of per-segment `ff_speed_kmph`. Call this `b_s_recovery`.
   - `recovery_lag_min = (b_s_recovery - b_d_recovery) * 2`. If either is undefined (anchor cuts off before recovery), `recovery_lag_min = None` and emit `SOFT_WARN_MFD_NO_RECOVERY`.

**Output payload:**

```jsonc
"mfd": {
  "speed_trace_kmph": [50.2, 50.1, …],            // length = anchor_bucket + 1; nulls allowed
  "density_trace_frac": [0.0, 0.0, …, 0.42, …],
  "loop_area": 12.4,                                // kmph · density-frac (signed)
  "loop_closes": true,
  "peak_density_bucket": 525,
  "peak_density_frac": 0.42,
  "recovery_lag_min": 47,
  "ff_corridor_kmph": 38.6
}
```

---

## 8. DOW anomaly track (`dow_anomaly.py`)

Computed AFTER Tier-1 modules. Independent of `tier1` registry.

**Algorithm:**

1. Pull same-DOW baseline (§5.4.3) → list of distinct day-keyed daily traces. `n_samples = len(distinct_days)`.
2. If `n_samples < dow_anomaly_min_samples` (3): emit nothing for `payload.dow_anomaly` (write a top-level `{"available": false, "n_samples": n_samples, "reason": "insufficient_samples"}` and stop).
3. Else, for each `b ∈ [0, ctx.anchor_bucket]`:
   - `today_corridor_tt(b)` = sum over all segments of `(today's TT at b)` if all segments present; else NaN.
   - `dow_typical_tt(b)` = median across the `n_samples` same-DOW days of (sum across segments of TT) per bucket.
   - `deviation_pct(b) = 100 * (today_corridor_tt(b) - dow_typical_tt(b)) / dow_typical_tt(b)` if both present and `dow_typical_tt(b) > 0`; else NaN.
4. `max_deviation_bucket = argmax(|deviation_pct|)`; `max_deviation_pct = deviation_pct[max_deviation_bucket]`.

**Output payload:**

```jsonc
"dow_anomaly": {
  "available": true,
  "n_samples": 5,
  "dow": "Monday",
  "today_corridor_tt_trace_sec": [...],
  "dow_typical_tt_trace_sec": [...],
  "deviation_pct_trace": [...],     // length = anchor_bucket + 1; nulls allowed
  "max_deviation_bucket": 540,
  "max_deviation_pct": 38.2
}
```

---

## 9. Output envelope (full schema)

`data/v3_a/envelope.py:build_envelope(...)` assembles this dict. Keys in this exact order. Every field is REQUIRED unless marked OPTIONAL.

```jsonc
{
  "schema_version": "v3",
  "engine_version": "v3.a.0",
  "mode": "today_as_of_T",            // or "retrospective"
  "corridor_id": "KOL_B",
  "corridor_name": "JLN Rd → SPM Rd → DPS Rd",
  "anchor_ts": "2026-05-04T19:00:00+05:30",   // truncated-to-bucket
  "run_id": "v3a-20260504T190000-KOL_B-7c1f",
  "computed_at": "2026-05-04T19:00:23.118+05:30",

  "meta": {
    "anchor_ts_received": "2026-05-04T19:01:14+05:30",
    "anchor_bucket": 570,
    "today_date": "2026-05-04",
    "tz": "Asia/Kolkata",
    "engine_version": "v3.a.0",
    "config_signature": "sha256:…",   // hash of EngineConfig dict for reproducibility

    "baseline_window": {
      "primary": {
        "type": "trailing_n_weekdays",
        "n_target_days": 22,
        "n_actual_days": 22,
        "start_date": "2026-04-04",
        "end_date": "2026-05-03",
        "thin_baseline": false
      },
      "dow_anomaly": {
        "type": "same_dow_trailing_n_weeks",
        "n_weeks_lookback": 6,
        "n_samples": 5,
        "dow": "Monday",
        "available": true
      }
    },

    "stages_run": [
      "s1_freeflow", "s2_regimes_today", "s2b_primary_windows_today",
      "s3_bertini_today", "s4_shockwave", "s5_systemic_today",
      "s6_recurrence", "s7_confidence_verdicts"
    ],
    "tier1_modules_run": ["growth_rate", "percolation", "jam_tree", "mfd"],
    "tier1_modules_skipped": [],

    "partial": false,
    "warnings": [
      // {"code": "SOFT_WARN_THIN_BASELINE", "message": "...", "context": {...}}
    ],
    "errors": []
  },

  "payload": {
    "stages_v21": {
      "freeflow": { /* per v2.1 */ },
      "primary_windows_today": [ /* list of [start_bucket, end_bucket_inclusive] */ ],
      "bertini": { /* per v2.1, but indexed on today's regimes */ },
      "head_bottleneck": { /* per v2.1 */ },
      "shockwave": [ /* per v2.1 */ ],
      "systemic_v2": { /* per v2.1 */ },
      "systemic_v21": { /* per v2.1 */ },
      "recurrence": { /* per v2.1 */ },
      "confidence": { /* per v2.1 */ },
      "verdicts": { /* per v2.1 */ },
      "baseline_flags": [ /* per v2.1 */ ]
    },
    "tier1": {
      "growth_rate": { /* §7.1 */ },
      "percolation": { /* §7.2 */ },
      "jam_tree":    { /* §7.3 */ },
      "mfd":         { /* §7.4 */ }
    },
    "dow_anomaly": { /* §8 */ }
  }
}
```

`run_id` format: `v3a-{YYYYMMDDTHHMMSS}-{corridor_id}-{4-hex-suffix}`. The 4-hex suffix is `sha256(canonical_inputs)[:4]` for determinism: same inputs → same run_id, which is used as the cache key.

`computed_at` is wall-clock IST at envelope-assembly time.

`config_signature` is `sha256(json.dumps(asdict(config), sort_keys=True))[:16]`.

---

## 10. Run lifecycle and API

### 10.1 RunStatus and RunRecord

```python
# data/v3_a/progress.py

class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class StageEvent:
    run_id: str
    stage: str
    status: Literal["started", "completed", "skipped", "failed"]
    ts: str            # ISO8601 IST
    duration_ms: int | None = None
    detail: dict | None = None     # e.g. {"warnings": [...]}

@dataclass
class RunRecord:
    run_id: str
    corridor_id: str
    anchor_ts: str         # truncated, ISO IST
    mode: str
    config_signature: str
    status: RunStatus
    submitted_at: str
    started_at: str | None = None
    completed_at: str | None = None
    events: list[StageEvent] = field(default_factory=list)
    result: dict | None = None     # the envelope dict
    error: dict | None = None      # {code, message, hint, traceback}
```

### 10.2 API surface (in-process Python; HTTP wrapper out of scope)

```python
# data/v3_a/api.py

def submit_run(
    corridor_id: str,
    anchor_ts: str | datetime,
    *,
    mode: str = "today_as_of_T",
    config: EngineConfig | None = None,
) -> str:
    """Returns run_id. Synchronously starts the run in a thread; returns immediately."""

def get_run(run_id: str) -> RunRecord: ...

def list_runs(*, corridor_id: str | None = None, status: RunStatus | None = None) -> list[RunRecord]: ...

def stream_events(run_id: str) -> Iterator[StageEvent]:
    """Yields events as they are produced. Blocks. Closes when run reaches a terminal status."""
```

State storage: in-memory dicts keyed by `run_id`, guarded by a module-level `threading.RLock`. RunRecords retained for the life of the process. (HTTP/persistence layer is for downstream integration, not v3-A.)

### 10.3 Concurrency

A `dict[corridor_id -> threading.Lock]` is held module-level. Before starting work for a corridor, the run thread acquires that corridor's lock. If `submit_run` is called for a corridor whose lock is already held AND there's an in-flight RUNNING run with identical `(corridor_id, truncated_anchor, mode, config_signature)`, the existing `run_id` is returned. Otherwise the new run waits on the lock.

### 10.4 Timeout

Each run has a `run_timeout_sec` budget (default 60). Enforced via a watchdog thread that sets a flag; the orchestrator polls the flag between stages and after each Tier-1 module. If exceeded, the in-flight stage finishes (no kill mid-stage; safe), then the run is marked `FAILED` with `HARD_ERR_TIMEOUT` and the reason includes which stage was running when the watchdog tripped.

### 10.5 Cache

```python
# data/v3_a/cache.py

@dataclass
class CacheKey:
    corridor_id: str
    anchor_ts_truncated: str   # ISO IST
    mode: str
    config_signature: str

class Cache:
    def get(self, key: CacheKey) -> dict | None: ...
    def put(self, key: CacheKey, envelope: dict, ttl_sec: int | None) -> None: ...
```

In-memory `dict[CacheKey -> (envelope, expires_at)]`. `ttl_sec=None` means no expiry (replay).

When `submit_run` is called:
1. Build `CacheKey`.
2. If hit and not expired → fabricate a synthetic completed `RunRecord` (status COMPLETED, events synthesised as [{stage: "cache_hit", status: "completed"}], result = cached envelope, with `meta.cache_hit = true` and `meta.computed_at` reflecting the original computation time). Return its run_id.
3. If miss → start a real run. On COMPLETED, `cache.put(key, envelope, ttl_sec=300 if today else None)`. "Today" = `anchor_ts_truncated.date() == now().date()`.

Cache survives only the process lifetime. Restart → cold cache. (Persistent cache out of scope.)

---

## 11. Error handling

### 11.1 Hard errors (run → FAILED)

Each is a class in `data/v3_a/errors.py` deriving from `HardError(Exception)`:

| Code | Class | When |
|---|---|---|
| `HARD_ERR_UNKNOWN_CORRIDOR` | `UnknownCorridor` | corridor_id not in validation_corridors.json |
| `HARD_ERR_FUTURE_ANCHOR` | `FutureAnchor` | anchor_ts > now() at submit time |
| `HARD_ERR_ANCHOR_PRE_HISTORY` | `AnchorPreHistory` | no observations exist before anchor |
| `HARD_ERR_NO_TODAY_DATA` | `NoTodayData` | zero observations in [start_of_day(T), T] |
| `HARD_ERR_INSUFFICIENT_BASELINE` | `InsufficientBaseline` | <5 weekdays of baseline data |
| `HARD_ERR_DB_UNREACHABLE` | `DBUnreachable` | connection failure |
| `HARD_ERR_TIMEOUT` | `Timeout` | run exceeded run_timeout_sec |
| `HARD_ERR_BAD_CONFIG` | `BadConfig` | invalid EngineConfig values |
| `HARD_ERR_INTERNAL` | `Internal` | catch-all for unexpected exceptions; includes traceback |

`error` field on RunRecord:

```jsonc
{"code": "HARD_ERR_NO_TODAY_DATA",
 "message": "No observations for KOL_B in [2026-05-04T00:00, 2026-05-04T19:00].",
 "hint": "Wait a few minutes, or pick a later anchor.",
 "traceback": "..." }
```

### 11.2 Soft warnings (run still COMPLETED, `partial: true`)

Each is a `dict` appended to `meta.warnings`. Codes:

| Code | When |
|---|---|
| `SOFT_WARN_THIN_BASELINE` | 5–14 weekdays of baseline data |
| `SOFT_WARN_DATA_GAP` | a segment has gaps >10 min in today's data |
| `SOFT_WARN_QUIET_DAY` | jam-tree empty (no onsets today) |
| `SOFT_WARN_TZ_ASSUMED` | anchor_ts had no tz; IST assumed |
| `SOFT_WARN_MFD_THIN` | MFD has fewer than 4 valid (density, speed) points |
| `SOFT_WARN_MFD_NO_RECOVERY` | anchor cuts off before MFD recovery |
| `SOFT_WARN_TIER1_<NAME>_FAILED` | a Tier-1 module raised an exception |
| `SOFT_WARN_DOW_FAILED` | DOW anomaly module raised an exception |

`partial = true` iff len(warnings) > 0 OR any Tier-1 payload is null.

`SOFT_WARN_DATA_GAP` is detected in `data_pull.py` after fetching today's data: for each segment, scan for adjacent observations with `event_time` gap > 10 minutes; if any, emit one warning per segment with the worst gap in `context.gap_minutes`.

### 11.3 Logging

Use Python's `logging` module. Logger name: `data.v3_a`. Default level: INFO. Stage start/complete logged at INFO. Soft warnings logged at WARNING. Hard errors logged at ERROR. No print statements anywhere in `data/v3_a/`.

---

## 12. CLI

`python -m data.v3_a.cli --corridor KOL_B --anchor "2026-05-04T19:00:00+05:30"`

Flags:
- `--corridor` (required): corridor_id from validation_corridors.json
- `--anchor` (required): ISO 8601, IST assumed if no tz
- `--mode` (default `today_as_of_T`)
- `--out` (default stdout): write envelope JSON to this path
- `--progress` (default `text`): one of `text`, `json`, `none`
- `--config-overrides` (optional): JSON string merged into EngineConfig.default()
- `--no-cache` (optional flag): bypass the cache for this run

Exit codes:
- 0 — completed (even if partial)
- 1 — failed (hard error)
- 2 — usage error
- 3 — timeout

CLI is THIN — it calls `submit_run` then `stream_events` then `get_run` and prints/writes accordingly. Implementation must be ≤120 LOC.

---

## 13. UI API contract

This spec does NOT implement the UI. It defines the API contract the frontend will consume.

The frontend is responsible for spawning HTTP. v3-A's Python module exposes only the in-process API (§10.2). A separate HTTP layer wraps `submit_run` / `get_run` / `stream_events`. Building that wrapper is OUT OF SCOPE for v3-A.

For brainstorming continuity, the contract is:

| Endpoint (out of v3-A scope) | Returns |
|---|---|
| `POST /v3a/run` body `{corridor_id, anchor_ts, mode}` | `{run_id, status}` |
| `GET /v3a/run/:run_id` | RunRecord-as-JSON |
| `GET /v3a/run/:run_id/events` (SSE) | stream of StageEvent |

Page layout (Q9): one page, mode toggle in header (Retrospective / Today / Replay), two-column body — left = compact map + full-width regime ribbon; right sidebar = Tier-1 panel + verdicts + meta.

---

## 14. Validation gate

A v3-A milestone is COMPLETE when both gates pass.

### 14.1 Gate b1 — pass-through equivalence

**Test:** `tests/test_pass_through_equivalence.py`.

For each of `KOL_B`, `KOL_C`, `DEL_AUROBINDO`:
1. Pick a fixed historical date `D` (e.g. `2026-04-22` for KOL_B/C; ad-hoc for Aurobindo).
2. Run `run_diagnostic(corridor_id, anchor_ts=D + 23:58 IST, mode="retrospective")`.
3. Run v2.1's existing `diagnose_v21(...)` on the same corridor + same baseline data → call v2.1's `to_plain_dict(out)`.
4. After normalising key order and rounding floats to 6 decimal places, the two dicts must be EQUAL.

Any divergence is a bug. The v3-A `retrospective` path is not allowed to alter v2.1 behaviour byte-for-byte (after normalisation).

### 14.2 Gate b2 — Tier-1 sanity on KOL_B / KOL_C

**Test:** `tests/test_tier1_sanity.py`.

Pick a known systemic weekday for each: a date `D_b` for KOL_B and `D_c` for KOL_C where v2.1's `systemic_v21` verdict is `SYSTEMIC` (these dates are confirmed in `docs/CORRIDOR_DIAGNOSTICS_V2_1_VALIDATION.md`).

Run `run_diagnostic(corridor_id, anchor_ts=D + 23:58 IST, mode="today_as_of_T")` for both.

Each run must satisfy ALL of:

| Check | Pass criterion |
|---|---|
| Run completes | `status == COMPLETED`, `meta.partial == false` (no soft warnings) |
| Growth-rate fires | `payload.tier1.growth_rate.summary.n_fast >= 1` OR `n_moderate >= 2` |
| Percolation onset within a primary window | `payload.tier1.percolation.onset_bucket` falls inside at least one tuple in `payload.stages_v21.primary_windows_today` |
| Jam-tree non-trivial | `payload.tier1.jam_tree.summary.n_origins >= 1` AND `payload.tier1.jam_tree.summary.n_propagated >= 1` |
| MFD measurable | `payload.tier1.mfd.peak_density_frac >= 0.30` AND `abs(payload.tier1.mfd.loop_area) >= 1.0` |

Both must pass. If one fails, treat the failure as discovery — re-examine thresholds or input quality before declaring v3-A done.

### 14.3 DEL_AUROBINDO sanity (informational, not gating)

A separate test runs Mode B on DEL_AUROBINDO for a recent weekday. Records: number of jam-tree ORIGINs vs v2.1's count of ACTIVE_BOTTLENECK verdicts on the same day. The expectation (per `RESEARCH_DEEP_DIVE.md`) is that jam-tree compresses a 13-bottleneck v2.1 verdict into a smaller origin set. The test asserts `n_origins < n_active_bottleneck_v21` and prints the ratio. This is **not** a gating test; it's a regression record.

---

## 15. Test plan

All tests use `pytest`. Fixtures in `data/v3_a/tests/fixtures/` are JSON dumps of pulled data, captured once at fixture-creation time.

### 15.1 Unit tests

- `test_growth_rate.py` — synthetic regime arrays exercising FAST_GROWTH / MODERATE / CONTAINED / INSUFFICIENT_DATA branches. Anchor-truncation behaviour. Boundary conditions (event at last bucket).
- `test_percolation.py` — single-cluster (slcc=0), two-cluster, multi-cluster, length-weighted vs segment-count consistency check, onset_bucket undefined case.
- `test_jam_tree.py` — single-origin chain, two-origin tree, no-onset corridor, QUEUE_VICTIM reclassification fixture.
- `test_mfd.py` — closing loop, non-closing loop, all-zero density, recovery-not-yet-reached.
- `test_dow_anomaly.py` — `n_samples<3` returns unavailable; valid case computes deviations.
- `test_envelope.py` — schema_version, run_id format, every required field present, key order respected.
- `test_cache.py` — TTL expiry for today, infinite for replay, cache hit synthesises stage events.
- `test_progress.py` — events emitted in order, RunStatus transitions valid.
- `test_errors.py` — each hard error class wraps the right context; soft warnings list not empty when triggered.
- `test_data_pull.py` — SQL parameter binding, gap detection, baseline thinness detection.
- `test_cli.py` — exit codes, output format, `--no-cache` bypass.

### 15.2 Integration / gates

- `test_pass_through_equivalence.py` — gate b1, three corridors.
- `test_tier1_sanity.py` — gate b2, two corridors.

### 15.3 Coverage target

≥85% line coverage on `data/v3_a/`. `data/v3_a/cli.py` and `data/v3_a/api.py` allowed to be ≥70% (CLI/integration boilerplate).

### 15.4 Test execution

`pytest data/v3_a/tests/ -v` is the command. CI integration is not in scope; the implementing agent runs it locally and reports results.

---

## 16. Implementation order

The implementing agent works through these in order. Each step ends with a green pytest run on the tests existing at that step.

1. **Scaffold** — create directory tree, empty files with module docstrings, `EngineConfig` dataclass, `errors.py`, `progress.py` (RunStatus + StageEvent + ProgressEmitter abstract class), `__init__.py`. No tests yet.

2. **Data pull** — `data_pull.py` with the three SQL skeletons. Tests use a fixture-replay shim (no live DB in tests).

3. **Baseline + DOW** — `baseline.py` builds the 22-weekday profile and same-DOW samples from raw rows. Tests verify median computation and thinness detection.

4. **stages_v21 wrappers + regime_today** — `regime_today.py` builds today's regimes from today's TTs + ff_tt. `stages_v21.py` calls into `data/v2_1/corridor_diagnostics_v2_1.py` for stages 1, 2t, 2b, 3, 4, 5, 6, 7. The `mode="retrospective"` path goes through `stages_v21.py` only and **must** match v2.1 byte-for-byte.

5. **Pass-through equivalence test (b1)** — `test_pass_through_equivalence.py` lights green for all three corridors before any Tier-1 code is written. This protects v2.1 behaviour throughout.

6. **Tier-1 #1 growth_rate.py + tests** — implement, register, test in isolation, integrate.

7. **Tier-1 #2 percolation.py + tests** — same.

8. **Tier-1 #3 jam_tree.py + tests** — same.

9. **Tier-1 #4 mfd.py + tests** — same.

10. **dow_anomaly.py + tests** — same.

11. **envelope.py + tests** — assemble the unified envelope; verify schema and key order.

12. **cache.py + tests** — TTL semantics, cache-hit event synthesis.

13. **api.py + tests** — submit_run, get_run, stream_events, concurrency lock, timeout watchdog.

14. **cli.py + tests** — exit codes, flag handling.

15. **Tier-1 sanity test (b2)** — `test_tier1_sanity.py` lights green on KOL_B and KOL_C using the locked sanity criteria.

16. **DEL_AUROBINDO regression record** — informational test, captures origin-count compression ratio.

17. **README + FUTURE_WORK doc** — `data/v3_a/README.md` (module overview pointing at this spec), `docs/CORRIDOR_DIAGNOSTICS_V3A_FUTURE_WORK.md` (Mode A, Tier-1 #5 scaling exponent, v3-B handoff).

After step 17, both gates green = v3-A complete.

---

## 17. Out-of-scope and FUTURE_WORK

Captured in `docs/CORRIDOR_DIAGNOSTICS_V3A_FUTURE_WORK.md` (created in step 17):

1. **Mode A — live snapshot.** A fourth mode that returns ONLY current-bucket regimes, percolation state, and active growth-rate events. No historical baselines used. Useful as a low-latency dashboard ping. Implementation: a thin orchestrator path that runs only stages 2 (regimes today, last bucket) + tier1.percolation (last bucket only) + tier1.growth_rate filtered to events with `t0 >= now() - 30min`.

2. **Tier-1 #5 — Scaling exponent.** Power-law fit on per-segment delay distributions across multiple weeks. Requires ≥4 weeks of trailing data. Activated for Pune/Kolkata once Pune/Kolkata >4 weeks; never for Delhi until ≥4 weeks of Delhi history exists. Adds module `tier1/scaling_exponent.py`, registers after MFD.

3. **v3-B network handoff.** v3-A's `Tier1Module` ABC is reusable for network-level modules (percolation across the city, betweenness centrality, community detection, SIS epidemic). v3-B will:
   - Build `delhi_segments.json` (3000 segments) and `delhi_edges.json` (adjacency).
   - Add a `network_run.py` orchestrator parallel to `run.py` that takes the registry instead of a corridor.
   - Reuse `data_pull.py`, `cache.py`, `progress.py`, `envelope.py` (mode = `"network"`).
   - Tier-1 modules largely don't transfer (they're 1-D-chain assumptions); new `tierN/` modules instead.

4. **Persistent cache.** Replace in-memory `Cache` with Redis or Postgres-backed when run-frequency justifies.

5. **HTTP wrapper.** A small FastAPI app exposing `submit_run` / `get_run` / `stream_events` (SSE) under `/v3a/*`. Frontend integration goal.

6. **Per-corridor calibration of growth-rate thresholds.** Duan 2023's 50/10 m/min thresholds were calibrated on freeways. Signalised arterials may need different cuts. Once we have ≥4 weeks of validated KOL_B/KOL_C/DEL_AUROBINDO Mode-B runs, fit corridor-specific thresholds and store in a calibration JSON.

---

## 18. Appendix A — Research-paper-to-module map

| Module | Paper / source | Concept |
|---|---|---|
| `tier1/growth_rate.py` | Duan et al. 2023, "Spreading and Recovery of Traffic Congestion in Urban Road Networks" | First-15-min growth slope predicts severity |
| `tier1/percolation.py` | Li et al. 2015 (PNAS), Zeng et al. 2019, Ambühl et al. 2023 | LCC/SLCC phase transition replaces 80% threshold |
| `tier1/jam_tree.py` | Serok et al. 2022 (cascade trees), Duan et al. 2023 (temporal precedence) | Causal origin vs propagated victim |
| `tier1/mfd.py` | Geroliminis & Daganzo 2008, Saberi & Mahmassani 2013, Ambühl et al. 2023 | Speed-density loop; loop area = capacity loss |
| `dow_anomaly.py` | (no single paper — operational design from Q5 brainstorm) | Today vs same-DOW typical, self-gating |

Excluded with reason:

| Method | Reason for exclusion |
|---|---|
| Anisotropic Smoothing (ASM) | Wrong physics for signalised arterials |
| GNNs (Graph WaveNet, T-GCN, DCRNN) | Insufficient Delhi training data |
| Signal-cycle decomposition | Requires <30s data; we have 2-min |
| 3D speed-map clustering on Delhi | Same data-thinness reason |
| Full causal graph inference | Needs hundreds of episodes; we have <50 |
| Tier-1 #5 Scaling exponent (Chen 2024 / Zeng 2025) | Needs ≥4 weeks data; deferred to FUTURE_WORK |

---

## 19. Appendix B — Glossary

- **Anchor T** (`anchor_ts`) — the timestamp at which the diagnostic is "as of." Bucket-truncated downward.
- **Bucket** — a 2-minute slot of clock time. 720 per day.
- **CONG / SEVR / APPR / FREE** — regime labels from v2.1's Stage 2.
- **LCC / SLCC** — largest / second-largest connected component in the percolation analysis.
- **Mode B** — `mode = "today_as_of_T"`. Runs v2.1 + Tier-1 on today's data with as-of-T baselines.
- **ORIGIN / PROPAGATED** — node roles in the jam-tree.
- **Same-DOW track** — same-day-of-week comparison surfaced when `n_samples ≥ 3`.
- **Soft warning vs hard error** — soft → run completes with `partial: true`; hard → run fails.
- **Tier-1 module** — one of the four research-grounded extensions (growth_rate / percolation / jam_tree / mfd).

---

## 20. Appendix C — Definition of Done

v3-A is shipped when ALL of the following hold simultaneously:

1. Repository has `data/v3_a/` matching §3 file layout exactly.
2. `pytest data/v3_a/tests/ -v` passes 100% green.
3. `tests/test_pass_through_equivalence.py` (b1) passes for KOL_B, KOL_C, DEL_AUROBINDO.
4. `tests/test_tier1_sanity.py` (b2) passes for KOL_B and KOL_C.
5. CLI runs end-to-end on at least one corridor and writes a valid envelope to disk.
6. `data/v3_a/README.md` and `docs/CORRIDOR_DIAGNOSTICS_V3A_FUTURE_WORK.md` exist and are accurate.
7. v2.1 code (`data/v2_1/`) is byte-identical to its state at v3-A's start commit (verified via `git diff data/v2_1/`).
8. Coverage ≥85% on `data/v3_a/`.

End of spec.
