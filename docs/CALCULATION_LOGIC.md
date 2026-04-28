# Corridor Diagnostic Pipeline — Calculation Logic

End-to-end specification of every formula, threshold, and decision rule used in the v2 + v2.1 pipeline.

Source files this document tracks:
- `data/corridor_diagnostics_v2.py` — core (v2)
- `data/v2_1/corridor_diagnostics_v2_1.py` — refinements (v2.1)
- `data/v2_1/pull_profiles.py`, `pull_onsets.py` — data extraction SQL
- `data/v2_1/run_validation.py` — orchestration

---

## 0. Pipeline at a glance

```
DB (traffic_observation)
    │
    ├── pull_profiles.py  ──►  all_profiles_{slice}.json    (per-rid 2-min median TT × 720 buckets)
    └── pull_onsets.py    ──►  all_onsets_{slice}.json      (per-rid per-date earliest onset minute-of-day)
                                       │
                                       ▼
                  diagnose_v21()  ──►  per-corridor structured diagnosis
                                       │
                                       ▼
       Stage 1 ── Stage 2 ── Stage 2b ── Stage 3 ── Stage 4 ── Stage 5 ── Stage 6
       free-flow  regimes   primary    Bertini +   shockwave   systemic   recurrence
                            windows    head        validation  vs point   typing
                                       │
                                       ▼
                            R7 confidence + R8 saturation
                                       │
                                       ▼
                                Per-segment verdicts
```

Time grid: every series is on a **2-min bucket** grid → 720 buckets per IST day. `STEP_MIN = 2`, `BUCKETS_PER_DAY = 720`.

---

## 1. Data extraction (DB → JSON)

### 1.1 Profile pull (`pull_profiles.py`)

For each requested `road_id` and slice (weekday: ISODOW 1–5; weekend: ISODOW 6–7), within the lookback window:

```sql
SELECT
    road_id,
    (HOUR_IST * 30 + MINUTE_IST / 2) AS bkt,                    -- 0..719
    percentile_cont(0.5) WITHIN GROUP (ORDER BY current_travel_time_sec) AS tt
FROM traffic_observation
WHERE road_id = ANY(:rids)
  AND event_time >= now() - (:days || ' days')::interval
  AND ISODOW_IST IN <slice filter>
GROUP BY road_id, bkt;
```

- `percentile_cont(0.5)` = **median** travel time per 2-min IST bucket, robust to outlier spikes.
- Output shape: `{ road_id: { minute_of_day: tt_sec } }` keyed by even minute (0, 2, 4, …, 1438).

### 1.2 Onset pull (`pull_onsets.py`)

Per (road_id, IST date), find the earliest minute-of-day where travel time stays above the segment's free-flow proxy by ≥1.5× for ≥10 min.

```
ff_tt_proxy(road_id) = p15( tt observed in 01:30–05:30 IST over the window )

For each (road_id, IST date):
  flag every 2-min bucket where tt > 1.5 × ff_tt_proxy
  use a 5-bucket trailing window sum (10 min)
  onset = MIN(minute_of_day) where the trailing sum ≥ 5
```

- Output shape: `[ {"rid", "dt", "om"} ]` — one row per (segment, date) that produced an onset.
- "ff_tt_proxy" here is **independent** of Stage 1's discovered free flow — it's a database-side proxy used purely to label per-day onset minutes for shockwave/recurrence stages.

---

## 2. Stage 1 — Discovered Free Flow

For each segment's 720-bucket TT series:

1. Slide a **30-min window** (15 buckets) across the day.
2. For each window, record its **median TT**.
3. Take the **3 windows with the lowest median TT** (`FF_N_WINDOWS = 3`).
4. Pool all 45 buckets from those 3 windows. Take the **15th percentile** of the pool → `raw_ff`.
5. Apply a physical floor: minimum TT corresponding to **80 km/h** speed cap (`FF_SPEED_CAP_KMPH`):
   ```
   min_tt_physical = length_m / (80 / 3.6)
   clamped_ff      = max(raw_ff, min_tt_physical)
   ff_speed_kmph   = length_m / clamped_ff × 3.6
   ```
6. Warn if speed < 8 km/h (`FF_SPEED_MIN_KMPH`) — segment may never reach true free flow.

**Why p15 of the 3 quietest 30-min windows?** The 3-quietest filter rejects sustained-quiet noise (e.g., outage zeros, holidays). p15 within the pool extracts a fast-but-not-impossible TT; pure min would amplify a single outlier.

---

## 3. Stage 2 — Regime classification

Per bucket, compute `speed_ratio = ff_tt / current_tt`. Map to one of four regimes:

| Regime | Speed ratio | Interpretation |
|---|---|---|
| FREE | ≥ 0.80 | within 20% of FFS |
| APPROACHING | [0.50, 0.80) | slowing toward congestion |
| CONGESTED | [0.30, 0.50) | clear congestion |
| SEVERE | < 0.30 | severe congestion |

**Smoothing:** rolling-majority over a `±3 buckets` window (7-bucket span = 14 min). Removes single-bucket flickers.

---

## 4. Stage 2b — Primary congestion windows

Two definitions exist; **v2.1 uses the length-weighted form** (R1).

### v2 (legacy, count-based)
A bucket is "hot" iff ≥25% of segments are CONGESTED/SEVERE.

### v2.1 (length-weighted, R1)
A bucket is "hot" iff:

```
sum(length_m of segments in CONG/SEVR at bucket b) ≥ 0.25 × total_corridor_length
```

`IMPACT_MIN_FRAC = 0.25`. Rationale: a corridor with 3 short + 2 long segments doesn't become a "corridor-level event" just because the 3 short ones jam — but it does if 1 long one (carrying 60% of length) jams.

### Window assembly (both versions)
1. Find contiguous runs of hot buckets.
2. Merge consecutive runs separated by ≤30 min (`PRIMARY_WINDOW_GAP_MERGE`).
3. Wrap-merge: if one run ends at bucket 719 and another starts at 0, stitch them (encoded with `e_bucket ≥ 720`).
4. Drop runs shorter than 30 min (`PRIMARY_WINDOW_MIN_MIN`).

Output: `[ (start_bucket, end_bucket_inclusive), … ]`.

---

## 5. Stage 3 — Bottleneck activation

Two complementary tests, both requiring **≥10 min sustained** (`BERTINI_MIN_BUCKETS = 5`).

### 5.1 Bertini (three-point test, interior segments)

For each segment with both upstream and downstream neighbours:

```
For each bucket b:
   upstream(b)   ∈ {CONGESTED, SEVERE}   (BERTINI_UPSTREAM_REQ)
   current(b)    ∈ {CONGESTED, SEVERE}   (BERTINI_CURRENT_REQ)
   downstream(b) ∈ {FREE, APPROACHING}   (BERTINI_DOWNSTREAM_REQ)
```

A segment "activates" over a contiguous run of buckets satisfying all three for ≥5 buckets. After detection, runs are filtered to those that **overlap a v2.1 primary window** (suppresses midnight-wrap artifacts and quiet-hour flicker).

This is the classical Bertini bottleneck signature: queue building behind, tail pinching ahead — the dropping-capacity is **at this segment**.

### 5.2 Head-segment relaxation (R3, S01 only)

`bertini_activations()` skips the upstream check when there is no upstream segment, so v2 lets `S01` fire whenever current is congested and downstream is free. v2.1 makes that **explicit and labelled**:

- Compute head runs **without** the primary-window filter (catches sustained S01-only congestion outside any corridor-wide window).
- **Replace** S01's standard Bertini output with the head runs (single source of truth → label `HEAD_BOTTLENECK`).
- **Suppress S_N's Bertini entirely**: terminus has no downstream, the rule is undefined.

---

## 6. Stage 4 — Shockwave validation

Validates that adjacent congested segments behave like an **LWR backward-propagating wave** at 12–22 km/h.

### 6.1 Preferred path: per-day onsets

For each adjacent pair (A upstream, B downstream):

```
For each date where BOTH A and B have onset minutes:
    For each B-onset time tb:
        Find the closest A-onset ta with |ta - tb| ≤ 60 min  (SAME_EVENT_MAX_LAG_MIN)
        Record delta = ta - tb  (positive = A trails B = backward propagation)

observed_lag = median(deltas) across all matched pairs

dist_m   = 0.5 × length(A) + 0.5 × length(B)        (centre-to-centre proxy)
low_lag  = dist_m / (22 / 3.6) / 60                  (high speed → small lag)
high_lag = dist_m / (12 / 3.6) / 60                  (low speed  → large lag)

PASS iff (low_lag - 3) ≤ observed_lag ≤ (high_lag + 3)   (SHOCKWAVE_TOL_MIN = 3 min)
```

A **positive observed_lag** means A's onset comes after B's — congestion propagating upstream, exactly what LWR predicts. Negative or out-of-range lags suggest the pair isn't a shockwave-coupled bottleneck.

### 6.2 Fallback path: centroid on median profile

If no per-day onsets are available, compute a "congestion centroid" inside each segment's primary-window mask, weighted by `(tt/ff − 1.5)⁺`. The lag between centroids is then validated against the same LWR range. Mode label: `median centroid`.

---

## 7. Stage 5 — Systemic vs Point

The corridor verdict is **SYSTEMIC** if **either** test fires:

### 7.1 v2 simultaneous fraction
```
threshold = ceil(0.80 × n_segments)        (SYSTEMIC_ALL_FRACTION = 0.80)
At any bucket, count segments in CONG/SEVR.
SYSTEMIC iff some bucket has count ≥ threshold for ≥ 5 buckets (10 min).
```

### 7.2 v2.1 contiguous-length (R5)
At each bucket, find the **maximum contiguous run** of CONG/SEVR segments and sum their lengths.
```
max_contig_frac = max over all buckets of (contig_run_length / total_corridor_length)
SYSTEMIC iff max_contig_frac ≥ 0.60                   (SYSTEMIC_CONTIG_MIN_FRAC = 0.60)
```

Rationale: 7 of 10 segments congested *in 3 disconnected pockets* is point-bottleneck noise; 7 of 10 *adjacent* segments congested is operationally systemic.

Final label:
- `SYSTEMIC` if either fires
- `POINT-BOTTLENECK` otherwise

---

## 8. Stage 6 — Recurrence typing

Counts in how many distinct days each segment had ≥1 onset.

```
For each segment s:
    n_days   = number of dates with at least one onset for s
    total    = number of distinct dates with at least one onset on ANY segment of the corridor
    frac     = n_days / total
```

Banded label:

| Frac threshold | Label |
|---|---|
| ≥ 0.75 | RECURRING |
| ≥ 0.50 | FREQUENT |
| ≥ 0.25 | OCCASIONAL |
| ≥ 0.01 | RARE |
| else | NEVER |

---

## 9. R7 — Confidence index (per segment)

A 0–1 score combining four components, each with a defined null-data fallback. Equal weights (0.25 each).

### 9.1 Components

**A. `ff_tight`** — consistency of the Stage 1 quiet-window pool.
```
quiet_meds = sorted medians of every 30-min sliding window
top3       = the 3 lowest quiet_meds
spread     = (top3[-1] - top3[0]) / raw_ff_sec
ff_tight   = clip(1 - spread, 0, 1)
```
Falls back to **0.5** if raw_ff is missing or fewer than 2 windows.

**B. `primary_overlap`** — does the segment fire inside a corridor-level event?
```
runs = Bertini runs for this segment (plus head runs if i = 0)
total_run_len  = sum of run lengths (in buckets)
inside_run_len = sum of buckets within runs that lie inside any primary window
primary_overlap = inside_run_len / total_run_len     (if there are runs)
                = 0.7    if no runs and no primary window  (neutral)
                = 0.4    if corridor has primary window but this segment has no runs
                = 0.0    otherwise
```

**C. `onset_support`** — onset volume.
```
n_onsets = number of onset rows for this segment
onset_support = min(1.0, n_onsets / 5.0)
```
Saturates at 5 onsets.

**D. `shockwave_support`** — does the flanking pair pass Stage 4?
```
flanking_pairs = Stage-4 results where this segment is in the pair (and not skipped)
shockwave_support = (# of pass) / (# of flanking)
                  = 0.5 if there are no flanking pairs (neutral)
```

### 9.2 Aggregate
```
score = 0.25 × ff_tight + 0.25 × primary_overlap + 0.25 × onset_support + 0.25 × shockwave_support
label = HIGH    if score ≥ 0.75
        MEDIUM  if 0.50 ≤ score < 0.75
        LOW     otherwise
```

---

## 10. R8 — Baseline-saturated sanity flag

Detects segments whose "free flow" is really chronic congestion.

```
med_corridor_speed = median of ff_speed_kmph across all segments in this corridor

For each segment:
    peer_ratio       = med_corridor_speed / segment.ff_speed_kmph
    quiet_busy_ratio = min(quiet_window_meds) / max(quiet_window_meds)
    baseline_saturated = (peer_ratio ≥ 2.0) AND (quiet_busy_ratio ≥ 0.70)
```

`peer_ratio ≥ 2.0` → segment is >2× slower than the corridor median.
`quiet_busy_ratio ≥ 0.70` → tt never meaningfully drops (no real off-peak).
The combination = "perpetually saturated link". The pipeline does **not** override the discovered ff_tt — it only emits a warning so the operator knows the regime baseline is on a soft foundation.

---

## 11. Per-segment operator verdicts

Five labels, derived in `_verdict_for_segment()` + `_refine_slow_vs_victim()`:

| Verdict | Trigger |
|---|---|
| `HEAD_BOTTLENECK` | i = 0 AND head-bottleneck runs exist |
| `ACTIVE_BOTTLENECK` | Bertini runs exist for this segment |
| `FREE_FLOW` | No corridor primary window OR `frac of CONG/SEVR inside primary window < 20%` |
| `QUEUE_VICTIM` | ≥20% CONG/SEVR inside primary window AND downstream **also** ≥20% congested in window |
| `SLOW_LINK` | ≥20% CONG/SEVR inside primary window AND downstream <20% (no spillback) |

The `QUEUE_VICTIM` vs `SLOW_LINK` split is the second pass: if the downstream isn't queueing too, this segment is a slow link of its own, not a downstream-queue victim. The terminus segment is forced to `SLOW_LINK` (no downstream to evaluate).

---

## 12. Corridor-level verdicts

```
Corridor SYSTEMIC iff:
    v2 max_fraction ≥ 0.80          (simultaneous count rule)
    OR
    v2.1 max_contig_frac ≥ 0.60     (contiguous-length rule)

else: POINT-BOTTLENECK
```

---

## 13. Tunables reference

All v2 thresholds (`corridor_diagnostics_v2.py`):

| Constant | Value | Used in |
|---|---|---|
| `STEP_MIN` | 2 min | bucket size |
| `BUCKETS_PER_DAY` | 720 | derived |
| `FF_WINDOW_MIN` | 30 min | Stage 1 sliding window |
| `FF_N_WINDOWS` | 3 | Stage 1 quiet pool count |
| `FF_PCTILE` | 15 | Stage 1 percentile |
| `FF_SPEED_CAP_KMPH` | 80 | Stage 1 physical clamp |
| `FF_SPEED_MIN_KMPH` | 8 | Stage 1 warning threshold |
| `REGIME_FREE_RATIO` | 0.80 | Stage 2 |
| `REGIME_APPROACHING_RATIO` | 0.50 | Stage 2 |
| `REGIME_CONGESTED_RATIO` | 0.30 | Stage 2 |
| `REGIME_SMOOTH_BUCKETS` | 3 | Stage 2 majority span |
| `BERTINI_MIN_BUCKETS` | 5 | Stage 3 sustain (10 min) |
| `SHOCKWAVE_LOW_KMPH` | 12 | Stage 4 LWR lower |
| `SHOCKWAVE_HIGH_KMPH` | 22 | Stage 4 LWR upper |
| `SHOCKWAVE_TOL_MIN` | 3 | Stage 4 tolerance |
| `SAME_EVENT_MAX_LAG_MIN` | 60 | Stage 4 onset pairing |
| `SYSTEMIC_ALL_FRACTION` | 0.80 | Stage 5 simultaneous |
| `SYSTEMIC_WINDOW_BUCKETS` | 5 | Stage 5 sustain |
| `PRIMARY_WINDOW_MIN_FRAC` | 0.25 | Stage 2b (v2 count rule) |
| `PRIMARY_WINDOW_MIN_MIN` | 30 | Stage 2b min duration |
| `PRIMARY_WINDOW_GAP_MERGE` | 30 | Stage 2b gap merge |
| `RECURRENCE_BANDS` | 0.75 / 0.50 / 0.25 / 0.01 | Stage 6 |

All v2.1 thresholds (`corridor_diagnostics_v2_1.py`):

| Constant | Value | Used in |
|---|---|---|
| `IMPACT_MIN_FRAC` | 0.25 | R1 length-weighted primary window |
| `SYSTEMIC_CONTIG_MIN_FRAC` | 0.60 | R5 contig-length systemic |
| `BASELINE_PEER_RATIO` | 2.0 | R8 peer slowness |
| `BASELINE_QUIET_BUSY_RATIO` | 0.70 | R8 saturation |
| `HEAD_BOTTLENECK_MIN_BUCKETS` | 5 (= Bertini sustain) | R3 |
| `CONFIDENCE_WEIGHTS` | 0.25 each | R7 |
| Confidence labels | ≥0.75 HIGH, ≥0.50 MEDIUM, else LOW | R7 |

---

## 14. v2 → v2.1 deltas

| Refinement | What changed |
|---|---|
| **R1** | Primary window: segment-count fraction → length-weighted fraction |
| **R3** | S01 head-bottleneck made explicit and labelled; S_N Bertini suppressed |
| **R5** | Systemic verdict additionally fires on max-contiguous-length ≥ 60% |
| **R7** | New per-segment 0–1 confidence index (4 components × 0.25 weight) |
| **R8** | Baseline-saturated warning when ff_speed < ½ corridor median AND quiet/busy ≥ 0.70 |

Deferred to a future phase: R2 (road-class ff clamp), R4 (mandatory per-day onsets), R6 (signal-cycle-aware Bertini).

---

## 15. Slice semantics

`--slice weekday` and `--slice weekend` are honoured everywhere that touches DB time:
- Profile pull: filters by `EXTRACT(ISODOW FROM event_time AT TIME ZONE 'Asia/Kolkata') BETWEEN 1 AND 5` or `IN (6, 7)`.
- Onset pull: same filter.
- Validation/dry-run scripts read the slice-suffixed JSONs (`all_profiles_weekday.json`, etc.).
- Outputs are slice-suffixed (`v2_1_validation_weekday_*`, `*_weekend_dry_run.html`).

The slice is a **cohort filter**, not a per-day rerun — every metric is computed against the median 720-bucket profile of the chosen slice over the lookback window.
