# TraffiCure — Corridor Diagnostics v2 Design

**Purpose:** Produce a defensible per-corridor diagnosis — active bottleneck(s), congestion windows, propagation evidence, systemic-vs-point classification — from travel-time data alone, with no country-specific or time-of-day heuristics.

**Inputs:** per-segment 2-min weekday-median travel-time profile (720 buckets/day), segment length, adjacency order along the corridor, and (optionally) per-day onset rows.

**Outputs:** a `CorridorDiagnosis` record per corridor containing Stage 1–6 results and all intermediate evidence.

---

## Design principles

1. **Traffic-engineering first, heuristics last.** Every decision the pipeline makes must be reducible to a standard traffic-engineering concept (fundamental diagram, LWR shockwave, Bertini activation test, capacity drop). No rule is "it's 8-10 AM in India".
2. **Global, not Indian.** Anything that would break in Toronto, Jakarta, or on a US freeway feeder is not in the pipeline. The only number with a physical unit in the tunables is the 80 km/h urban-arterial free-flow ceiling.
3. **Travel-times only.** We have no volumes, no junction positions, no signal phasing, no capacity. Every claim must be defensible from travel-times alone.
4. **Connected corridors only.** If the corridor has a gap, we don't diagnose it. Long chains (e.g. the 20-segment JBN corridor) are preferred over short ones because adjacency evidence is the backbone of Stage 3 and Stage 4.
5. **Scalable.** Everything runs in O(N · 720) per corridor. No cross-day regressions, no PCA, no solver calls. A 100-segment corridor diagnosed in well under a second on a single core.

---

## The six stages

### Stage 1 — discover free-flow

For each segment independently:

1. Slide a 30-min window (15 consecutive 2-min buckets) across the full 720-bucket day.
2. For each window, compute the window median TT.
3. Rank all windows by median, ascending.
4. Take the 3 lowest-median windows.
5. Pool all buckets from those 3 windows (up to 45 buckets after de-duplication).
6. `ff_tt = p15(pooled)`.
7. If `length / ff_tt > 80 km/h`, clamp `ff_tt` to `length / (80 km/h)` and emit a warning.

**Why this works globally:** The quietest 30-min median of a segment's day is, in every city, the closest thing we can get to free-flow without volume data. p15 (not min) guards against GPS-spike outliers. The 80 km/h clamp guards against quiet-time extrapolation artefacts on high-speed segments (Google occasionally returns 120+ km/h medians on empty motorway feeders, which breaks the ratio classifier downstream). 80 km/h is chosen as a universal urban-arterial upper bound — corridors faster than that are motorway segments, and a separate pipeline would be used.

**Why not just `min(tt)`:** one 2-min bucket with a GPS glitch or a bike carrier on the highway moves `min` by 30 %. p15 of 45 buckets is stable.

**Why not 08:00–10:00:** see the regression report §5. In Koregaon Park S01 the true quietest window is 14:00–14:30; in the new-corridor NH-65 Diveghat section it's likely to be post-22:00. Fixing the window globally guarantees bias on roughly half of all corridors.

### Stage 2 — regime classification

For each segment, each 2-min bucket:

| ratio = v / v_ff | regime |
|---|---|
| ≥ 0.80 | FREE |
| 0.50–0.80 | APPROACHING |
| 0.30–0.50 | CONGESTED |
| < 0.30 | SEVERE |

Then a 3-bucket rolling majority smooth (6 min window) to kill single-bucket flicker.

**Why speed-ratio not tt-ratio:** speed is the physical quantity in the fundamental diagram. Ratios 0.8 / 0.5 / 0.3 correspond to the free / saturated / congested / jam regions of the standard triangular fundamental diagram across every empirical fit we've checked in the traffic-engineering literature.

### Stage 2b — primary congestion window(s)

For each bucket count the fraction of segments in {CONGESTED, SEVERE}. A bucket is "hot" if that fraction ≥ 25 %. Take contiguous runs of ≥ 15 hot buckets (30 min). Merge runs separated by gaps ≤ 15 buckets (30 min). Wrap-stitch across midnight if a run ends at 23:58 and another starts at 00:00.

Output: a list of (start_hhmm, end_hhmm) windows, possibly with +1 day suffix for overnight runs.

**Why 25 % / 30 min:** 25 % is the lowest fraction at which a cluster of congested segments on a 4–12 segment corridor is evidence of a real corridor-level event rather than a single-segment incident. 30 min is below the shortest real PM peak on any Pune corridor in our data and above the longest spurious single-event queue (~15 min).

### Stage 3 — Bertini activation intervals

Restricted to the primary windows only, for each interior segment S_i (i.e. both S_{i-1} and S_{i+1} exist):

```
S_i is ACTIVELY BOTTLENECKING at bucket b iff
    smoothed_regime(S_{i-1}, b) ∈ {CONG, SEVR}   AND
    smoothed_regime(S_i,     b) ∈ {CONG, SEVR}   AND
    smoothed_regime(S_{i+1}, b) ∈ {FREE, APPR}
```

Contiguous runs of ≥ 5 buckets (10 min) are emitted as activation intervals.

**Why this is the right rule:** This is Bertini & Leal (2005)'s three-point test. An active bottleneck is, by definition, the segment where queued traffic upstream meets free flow downstream. Any segment that does not meet this criterion is either:
- (a) free-flowing (boring),
- (b) a spillback queue from a downstream active bottleneck (which will not pass the test because its downstream is also congested), or
- (c) upstream of the active bottleneck but inheriting its queue (same reason).

So on a well-defined corridor with one active bottleneck, exactly one segment passes this test at any bucket. When multiple segments pass (e.g. Pune Station → Kanha fires S01 and S09 simultaneously), we have independent bottlenecks, which Stage 3 reports individually — we don't collapse them. When a segment is the corridor terminus (no downstream in our chain), we skip it rather than make assumptions about its downstream regime.

**Edge segments:** if the corridor has no downstream segment for S_N (terminus), S_N cannot fire Bertini. We accept this and don't extrapolate. User's instruction was explicit: if there's no downstream, don't use it.

### Stage 4 — shockwave validation (LWR backward propagation)

For each adjacent pair (A, B) where A is upstream and B is downstream:

**Preferred mode (per-day onsets):**
1. Load per-day onset rows `{road_id, date, onset_min_of_day}`.
2. For each date, collect the set of A-onsets and B-onsets.
3. Pair each B onset with the closest A onset within ±60 min (same-event cap).
4. Compute the median lag `Δ = onset_A - onset_B` (positive = A triggered after B, i.e. classical backward propagation).
5. Expected lag range: `dist(A,B) / (22 km/h)` to `dist(A,B) / (12 km/h)`.
6. Pass if observed median lag is within the expected range ± 3 min tolerance.

**Fallback mode (median profile centroid):** if per-day onsets aren't available, use the centre-of-mass of the "above 1.5 × ff" region of each segment's median profile. This is less reliable but better than nothing.

**Why 12–22 km/h:** the standard empirical range for LWR shockwave backward-propagation speed in urban arterial traffic. 12 km/h is a dense-jam wave, 22 km/h is a light-congestion wave. Anything outside this range is not a classical shockwave and we shouldn't claim it as one.

**Why Stage 4 pass rates are often low:** see the regression report §8. Signal-dominated corridors don't shockwave-propagate. Multiple concurrent bottlenecks break the chain. Day-to-day onset noise is larger than the expected lag on short segments. Stage 4 is a positive confirmation when it fires, never a gate.

### Stage 5 — systemic vs point

Compute `peak_frac = max_b ( |{i : regime(S_i, b) ∈ {CONG, SEVR}}| / N )`.

- `peak_frac ≥ 80 %` → **systemic** (demand exceeds corridor-level capacity; no single segment is the bottleneck)
- otherwise → **point-bottleneck** (one or a few segments are the active bottleneck, the rest inherit queue or flow)

This is a binary decision and deliberately coarse. The intent is to tell the operator "fix S04" vs "you need to add a lane everywhere", which is a completely different operational action.

### Stage 6 — recurrence classification (optional)

Uses per-day onset rows. For each segment, count distinct weekdays in the analysis window on which it had an onset. Band:

| weekdays with onset | label |
|---|---|
| ≥ 90 % | RECURRING |
| 70–90 % | FREQUENT |
| 40–70 % | OCCASIONAL |
| 10–40 % | RARE |
| < 10 % | NEVER |

Used by the alert pipeline (not the diagnosis pipeline) to distinguish "today's congestion is typical" from "today's congestion is anomalous".

---

## Tunables — full table

All tunables are single constants at the top of `corridor_diagnostics_v2.py`. None are country- or corridor-specific.

```
STEP_MIN        = 2        # bucket width
BUCKETS_PER_DAY = 720

FF_WINDOW_MIN   = 30       # sliding window for ff discovery
FF_N_WINDOWS    = 3        # best-N to pool
FF_PCTILE       = 15       # percentile inside the pool
FF_SPEED_CAP_KMPH = 80     # physical ceiling

REGIME_FREE_RATIO        = 0.80
REGIME_APPROACHING_RATIO = 0.50
REGIME_CONGESTED_RATIO   = 0.30
REGIME_SMOOTH_BUCKETS    = 3

BERTINI_MIN_BUCKETS    = 5      # 10 min sustained
BERTINI_UPSTREAM_REQ   = {"CONGESTED", "SEVERE"}
BERTINI_CURRENT_REQ    = {"CONGESTED", "SEVERE"}
BERTINI_DOWNSTREAM_REQ = {"FREE", "APPROACHING"}

SHOCKWAVE_LOW_KMPH   = 12
SHOCKWAVE_HIGH_KMPH  = 22
SHOCKWAVE_TOL_MIN    = 3
SAME_EVENT_MAX_LAG_MIN = 60

PRIMARY_WINDOW_MIN_FRAC  = 0.25
PRIMARY_WINDOW_MIN_MIN   = 30
PRIMARY_WINDOW_GAP_MERGE = 30
```

---

## Scalability

- Stage 1: O(N × 720) per corridor. A 50-segment corridor = 36 k operations.
- Stage 2: O(N × 720).
- Stage 2b: O(N × 720).
- Stage 3: O(N × 720).
- Stage 4: O(N × D) where D is number of days of onset data (typically 22).
- Stage 5: O(N × 720).
- Stage 6: O(N × D).

Total: < 1 second per corridor on a single CPU core. A 50-segment corridor could be run every 2 minutes alongside the fresh travel-time refresh without hitting the budget. A 100-segment corridor is still well within budget.

The Stage 1 free-flow discovery and Stage 2 regime classification can be cached per segment (they don't depend on corridor topology), which makes the marginal cost of diagnosing a new corridor over segments already in the cache effectively O(N × 720) only for Stage 2b + 3 + 5, which is negligible.

---

## Output schema (CorridorDiagnosis)

```python
@dataclass
class CorridorDiagnosis:
    corridor_id: str
    corridor_name: str
    n_segments: int
    total_length_m: float
    ff_discovery: list[dict]            # Stage 1
    regime_distribution: list[dict]     # Stage 2
    primary_windows: list[tuple]        # Stage 2b
    bertini_intervals: dict             # Stage 3, seg_idx -> list of (start_b, end_b)
    shockwave_checks: list[dict]        # Stage 4
    shockwave_mode: str                 # "per-day onsets" | "median centroid"
    systemic: bool                      # Stage 5
    peak_simul_cong_frac: float
    recurrence: dict | None             # Stage 6
    warnings: list[str]
```

Each field is independently consumable by downstream systems (the alerts pipeline, the driver-facing app, the ops dashboard).

---

## What's intentionally not included

1. **No demand model.** Without volumes we can't estimate q or k; attempting to fake them with ratios introduces unfixable bias.
2. **No cross-corridor coupling.** Each corridor is diagnosed independently. Corridor-graph coupling (e.g. "Jedhe's congestion is caused by Satara Road's congestion") is a separate problem and will be solved with a graph layer on top of per-corridor diagnoses.
3. **No ML.** Every threshold is a single constant with a traffic-engineering justification. No training data, no drift, no retraining schedule. When we have capacity data we'll revisit this.
4. **No alert generation.** This pipeline profiles recurring patterns. The alerts pipeline compares today's live data against the recurring profile; it is a separate component and will consume this pipeline's output.
5. **No direction guessing.** The pipeline assumes the caller has passed segments in the correct order along the corridor. Corridor chaining is done upstream via PostGIS `ST_DWithin` + `ST_Azimuth` adjacency.

---

**Source:** [corridor_diagnostics_v2.py](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/data/corridor_diagnostics_v2.py)
