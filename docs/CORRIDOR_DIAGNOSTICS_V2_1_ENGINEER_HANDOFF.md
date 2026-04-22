# Corridor Diagnostics v2.1 — Engineer Handoff Brief

**Audience:** the engineer porting v2.1 to Java as a service that runs for any corridor on demand.
**Status:** v2.1 is validated on 6 corridors across Pune and Kolkata with zero cross-city tuning. Greenlit for production. Your job is to reimplement it in Java so it can be wired into the TraffiCure backend.
**Reference implementation:** Python, in `data/corridor_diagnostics_v2.py` (physics core) + `data/v2_1/corridor_diagnostics_v2_1.py` (refinements layer).

Read the two implementation files alongside this brief. This document is the "how to port it without re-deriving it" guide — the algorithm rationale lives in `CORRIDOR_DIAGNOSTICS_V2_PRD.md` and `CORRIDOR_DIAGNOSTICS_V2_DESIGN.md`. Read those first if you haven't already.

---

## 1. What you are building, in one sentence

A stateless Java service that takes a corridor (an ordered list of road segments) plus 22–30 weekdays of raw travel-time observations and returns a structured diagnosis: per-segment verdicts, primary congestion windows, active/head bottlenecks, systemic-vs-point classification, shockwave validation, and a confidence index for every verdict.

---

## 2. Inputs

Three things, sourced from the TraffiCure database.

### 2.1 Corridor chain
An ordered list of segments, typed as:

```java
public record CorridorSegment(
    String roadId,        // UUID-ish string, matches traffic_observation.road_id
    String roadName,      // human-readable, used in reports only
    double lengthM,       // segment length in metres, from road_segment
    String roadClass,     // "arterial" | "highway" | "collector" | "local"
    double startLat, double startLng,
    double endLat,   double endLng
);

public record Corridor(
    String corridorId,    // "PUNE_A", etc. — or a freshly-minted UUID
    String name,
    String city,          // "Pune" | "Kolkata" | ...
    List<CorridorSegment> chain   // order matters — index 0 = upstream, index N-1 = downstream
);
```

The chain is built either (a) from a saved `corridor_definitions` row or (b) by calling the chain walker — see §7.1.

### 2.2 Travel-time observations
Pulled fresh per invocation from `traffic_observation` for the segments in the chain:

```sql
SELECT road_id, event_time, current_travel_time_sec
  FROM traffic_observation
 WHERE road_id = ANY(:chainRoadIds)
   AND event_time >= :analysisStart  -- 30 calendar days back, IST midnight
   AND event_time <  :analysisEnd
   AND EXTRACT(ISODOW FROM event_time AT TIME ZONE 'Asia/Kolkata') BETWEEN 1 AND 5
```

Target window: 22–30 weekdays. Throw if fewer than 15 weekdays have any rows for the principal segment.

### 2.3 Per-day onset table (optional but preferred)
For Stage 4 preferred mode, you need one row per (segment, weekday) giving the first sustained crossing above 1.5× free-flow proxy. The SQL pattern is in §7.2. If this pull fails or returns fewer than 10 onsets for a segment, fall back to the no-onset Stage 4 mode (which uses the primary window midpoint as the onset). The pipeline must produce identical structural output regardless of mode.

---

## 3. Outputs

One `CorridorDiagnosis` object per call. Round-trip it through Jackson to match the shape of `runs/v2_1/v2_1_validation_structured.json` — that JSON is your golden target.

```java
public record CorridorDiagnosis(
    String corridorId,
    String corridorName,
    String city,
    Instant generatedAt,

    // Stage 1 — free-flow baselines, keyed by segment index (S01, S02, ...)
    Map<String, FreeFlowMeta> freeFlow,

    // Stage 2 — regime distribution per segment (FREE/APPR/CONG/SEVR percentages)
    Map<String, RegimeMix> regimes,

    // Stage 2b — corridor-level primary windows (R1 length-weighted)
    List<TimeWindow> primaryWindows,

    // Stage 3 — Bertini active bottlenecks, keyed by segment index
    // R3: S01's entries move into headBottlenecks; terminus is always empty
    Map<String, List<TimeInterval>> activeBottlenecks,
    Map<String, List<TimeInterval>> headBottlenecks,

    // Stage 4 — shockwave validation pairs
    List<ShockwavePair> shockwavePairs,
    double shockwavePassRate,
    ShockwaveMode shockwaveMode,  // PER_DAY_ONSETS | FALLBACK_MIDPOINT

    // Stage 5 — systemic classification (v2 rule + R5 contiguity)
    SystemicVerdict systemic,  // POINT | SYSTEMIC, with simultaneousFrac + contigFrac

    // Stage 6 — recurrence typing (RECURRENT | INTERMITTENT | ANOMALY)
    RecurrenceType recurrence,

    // R8 — baseline saturation flags (informational, never affects verdict)
    List<String> saturatedBaselineSegments,

    // Per-segment final verdict + confidence index (R7)
    Map<String, SegmentVerdict> verdicts
);

public enum VerdictType {
    FREE_FLOW,
    SLOW_LINK,           // persistent CONG, downstream is clear — local cause
    QUEUE_VICTIM,        // CONG inherited from a downstream bottleneck
    ACTIVE_BOTTLENECK,   // Bertini fired
    HEAD_BOTTLENECK      // R3 — S01 with sustained CONG, no upstream to prove Bertini
}

public record SegmentVerdict(
    VerdictType type,
    double confidence,   // 0..1, from CONFIDENCE_WEIGHTS
    Map<String,Double> confidenceBreakdown  // ff_tight, primary_overlap, onset_support, shockwave_support
);
```

Match field names and JSON shape exactly to the reference output — the test harness diffs the JSON, not the Java object.

---

## 4. Class / module breakdown

Map the Python pipeline to Java like this. One class per stage keeps the port testable.

| Python function | Java class | Notes |
|---|---|---|
| `build_profile()` in `save_profile.py` | `ProfileBuilder` | Converts raw observations into `Map<RoadId, Map<Integer /* minOfDay */, Double /* tt_sec */>>`. Weekday median per 2-min bucket (720 buckets/day). |
| `discover_free_flow()` in v2 | `Stage1_FreeFlow` | p15 of nightly buckets (01:30–05:30 IST). Returns `FreeFlowMeta(ff_tt_sec, ff_speed_kmph, nightly_iqr, peer_ratio, quiet_busy_ratio)`. Apply the 80 km/h clamp here; log a WARN if it trips. |
| `regime_classify()` in v2 | `Stage2_Regime` | Classify each 2-min bucket as FREE/APPR/CONG/SEVR using speed ratio vs free flow. Keep the thresholds exactly as in v2 (1.3×, 1.5×, 2.0×). |
| `detect_primary_windows_lenweighted()` in v2.1 | `Stage2b_PrimaryWindow` | **R1**: length-weighted impact score per bucket. Returns merged windows where `sum(length_m of CONG segs) / totalLen ≥ IMPACT_MIN_FRAC` for ≥ 30 min. |
| `bertini_active_bottleneck()` in v2 | `Stage3_Bertini` | The three-point test. Same logic as v2 including `up is None` (origin case) and `dn is None` (terminus case). |
| `head_bottleneck_intervals()` in v2.1 | `Stage3_HeadBottleneck` | **R3**: scans S01's CONG regimes for runs of ≥ `HEAD_BOTTLENECK_MIN_BUCKETS`. Called separately from Stage3_Bertini. |
| `shockwave_validation_from_onsets()` in v2 | `Stage4_Shockwave` | LWR backward propagation check. `expectedLag = distance_m / shockwaveSpeed_mps / 60`, where shockwave speed ∈ [12, 22] km/h. Observed lag comes from per-day onsets (preferred) or primary-window midpoints (fallback). A pair passes if observed lag lands inside the expected band. |
| `systemic_contiguity()` in v2.1 + v2's rule | `Stage5_Systemic` | v2 rule: ≥80 % simultaneously CONG in same bucket. **R5**: also compute the length-weighted share of the longest contiguous CONG run inside the primary window. Verdict stays SYSTEMIC if v2 rule fires; the contig fraction flows into the report and into R7 confidence. |
| `recurrence_type()` in v2 | `Stage6_Recurrence` | RECURRENT if the primary window recurs on ≥ 70 % of analysed weekdays; INTERMITTENT if 30–70 %; ANOMALY if < 30 %. Needs per-day onsets to work properly; fall back to "RECURRENT_UNVERIFIED" if no onsets. |
| `flag_saturated_baselines()` in v2.1 | `R8_BaselineCheck` | Segment is flagged if `ff_tt ≥ 2 × peer_median_ff_tt` AND `quiet_tt ≥ 0.7 × busy_tt`. Informational only — never changes a verdict. |
| `confidence_for_segment()` in v2.1 | `R7_ConfidenceIndex` | Sum of four 0.25-weighted signals. See §5.1. |
| `_verdict_for_segment()` + `_refine_slow_vs_victim()` in v2.1 | `VerdictResolver` | Priority: HEAD_BOTTLENECK > ACTIVE_BOTTLENECK > FREE_FLOW (if < 20 % CONG in primary window) > QUEUE_VICTIM > SLOW_LINK (refined if downstream is clear). See §5.2. |
| `diagnose_v21()` in v2.1 | `CorridorDiagnosticService.diagnose(Corridor, ...)` | Orchestrator. This is the public entry point of the service. |

Every stage class should be stateless and take its inputs by parameter — no fields, no DI beyond thresholds. That makes each stage independently testable.

---

## 5. Subtle bits that will bite you

### 5.1 The four confidence signals (R7)

All four are in [0, 1]. Default weights are 0.25 each; keep them injectable so we can retune without a redeploy.

```
ff_tight          = clamp01(1 - (nightly_IQR / ff_tt))            // tighter p15 cluster → higher
primary_overlap   = sum(buckets in CONG that fall inside any primary window) / sum(buckets in CONG)
onset_support     = min(1, onsets_for_segment / 10)               // 10+ onsets → 1.0
shockwave_support = 1 if at least one Stage 4 pair with this seg in (up, dn) passed, else 0

confidence = 0.25 * (ff_tight + primary_overlap + onset_support + shockwave_support)
```

### 5.2 Verdict priority (the order matters)

```
for each segment s in chain:
    if s is S01 and head_bottleneck.containsKey(s): -> HEAD_BOTTLENECK
    else if active_bottleneck.containsKey(s):       -> ACTIVE_BOTTLENECK
    else if regime.congFrac(s, within: primaryWindows) < 0.20: -> FREE_FLOW
    else:
        // s is congested in the primary window but not a bottleneck
        downstream_clear = all seg in chain[i+1..] has CONG frac < 0.20 in primary windows
        if downstream_clear: -> SLOW_LINK
        else:                -> QUEUE_VICTIM
```

S_N (terminus) never gets ACTIVE_BOTTLENECK — its Bertini entry is always empty. Do not remove this line; it's a design decision, not a bug. The rationale is in PRD §13a R3.

### 5.3 The IST timezone trap

`traffic_observation.event_time` is stored in UTC. All diagnostic windows — nightly p15 free-flow window, primary window clock times, onset timestamps in the report — must be in **Asia/Kolkata**. Do the conversion exactly once, at the ProfileBuilder boundary. Never store IST `Instant` values (that's a type lie); use `LocalTime` + a date for display and `Instant` for everything else.

A previous bug in v1 had nightly p15 windows landing in the afternoon because of a stray UTC/IST flip. The v2 fix is in `profiles.py` — replicate it. Add a unit test that asserts "ff discovery window is 01:30–05:30 IST" for at least one segment.

### 5.4 Minute-of-day indexing

Profiles are keyed by minute of day (0..1438, step 2). Converting between 2-min bucket index `b` and minute of day is `mod = b * 2`. That's it — no off-by-one. Primary windows are returned as `(startMinOfDay, endMinOfDay)` tuples; convert to `LocalTime` only when rendering the report.

### 5.5 Bertini edge cases

```
bertini(upIdx, midIdx, dnIdx):
    if up is None:      // origin — only mid and dn exist
        test simplifies to "mid is sustained CONG AND dn has a queue-discharge drop"
        THIS ONLY FIRES AT INDEX 0 (S01). v2.1 zeroes this out and routes to head_bottleneck instead.
    if dn is None:      // terminus — only up and mid exist
        test simplifies to "up is free AND mid is sustained CONG"
        v2.1 zeroes this out unconditionally (see §5.2).
```

Keep the `up is None` logic in Stage3_Bertini intact — v2 still uses it to compute the raw signal — but have the VerdictResolver discard the S01 entry and replace with the head bottleneck result. This separation lets you regression-test Stage 3 independently of R3.

### 5.6 Stage 4 in fallback mode

If you don't have per-day onsets for a segment, substitute the midpoint of the primary window containing its CONG regime. The pass/fail logic and output shape are identical — only the `shockwaveMode` field in the output differs. Never let fallback mode silently degrade confidence; the `onset_support` signal in R7 will already reflect the missing data.

### 5.7 Tunables, frozen for now

```
FF_SPEED_CAP_KMPH             = 80
BERTINI_MIN_BUCKETS           = 5      // 10 min floor
PRIMARY_WINDOW_MIN_FRAC       = 0.25   // v2 unchanged
IMPACT_MIN_FRAC               = 0.25   // R1 length-weighted
SHOCKWAVE_LOW_KMPH            = 12
SHOCKWAVE_HIGH_KMPH           = 22
SAME_EVENT_MAX_LAG_MIN        = 60
SYSTEMIC_ALL_FRACTION         = 0.80   // v2 simultaneity rule
SYSTEMIC_CONTIG_MIN_FRAC      = 0.60   // R5
BASELINE_PEER_RATIO           = 2.0    // R8
BASELINE_QUIET_BUSY_RATIO     = 0.70   // R8
HEAD_BOTTLENECK_MIN_BUCKETS   = 5      // = BERTINI_MIN_BUCKETS
CONFIDENCE_WEIGHTS            = { ff_tight: 0.25, primary_overlap: 0.25,
                                   onset_support: 0.25, shockwave_support: 0.25 }
```

Put these in an `CorridorDiagnosticConfig` record with defaults; allow override via Spring config for retuning.

---

## 6. Test harness — the golden fixture

The six validation corridors are your entire regression suite. If your Java port matches the Python reference JSON on all six, v2.1 behaviour is preserved.

### 6.1 Fixture files

Under `data/v2_1/`:
- `validation_corridors.json` — 6 corridor chains (3 Pune + 3 Kolkata, 48 segments)
- `profiles/all_profiles.json` — `{road_id: {minute_of_day: tt_sec}}` for all 48 segments
- `onsets/all_onsets.json` — flat array of `{rid, dt, om}` rows (4,540 total)
- `../../runs/v2_1/v2_1_validation_structured.json` — expected output, one object per corridor

### 6.2 Diff strategy

```java
@ParameterizedTest
@ValueSource(strings = {"PUNE_A", "PUNE_B", "PUNE_C", "KOL_A", "KOL_B", "KOL_C"})
void matchesPythonReference(String corridorId) {
    Corridor c = loadCorridor(corridorId);
    Map<String, TreeMap<Integer, Double>> profiles = loadProfiles();
    List<OnsetRow> onsets = loadOnsets();
    JsonNode expected = loadExpectedOutput(corridorId);

    CorridorDiagnosis actual = service.diagnose(c, profiles, onsets);

    assertJsonEquivalent(expected, toJson(actual), FLOAT_TOLERANCE_1E_3);
}
```

Float tolerance: `1e-3` is generous enough to absorb NumPy ↔ BigDecimal rounding differences but tight enough to catch real logic errors. Use a recursive JSON comparator — do **not** compare the stringified JSON.

### 6.3 Expected results cheat sheet

Use this to sanity-check before you run the diff:

| Corridor | Segs | Verdict | Simultaneous / contig | Active | Head | SW pass |
|---|---|---|---|---|---|---|
| PUNE_A | 6 | POINT | 33 % / 15 % | 1 | 1 (S01) | 20 % |
| PUNE_B | 9 | POINT | 22 % / 14 % | 1 | 0 | 0 % |
| PUNE_C | 8 | POINT | 38 % / 28 % | 1 | 0 | 29 % |
| KOL_A | 7 | POINT | 71 % / 51 % | 3 | 0 | 17 % |
| KOL_B | 7 | SYSTEMIC | 86 % / 44 % | 4 | 0 | 17 % |
| KOL_C | 11 | SYSTEMIC | 91 % / 89 % | 4 | 1 (S01) | 40 % |

If your Java port says PUNE_A is SYSTEMIC or KOL_C has zero head bottlenecks, something is wrong — start by checking the IST conversion and then the R3 wiring.

### 6.4 Per-stage unit tests

Don't rely only on the end-to-end diff. Each stage class gets its own test:

- `Stage1_FreeFlowTest` — feed a synthetic segment with a known p15, assert the free-flow value.
- `Stage2_RegimeTest` — feed synthetic buckets with known speed ratios, assert regime classification.
- `Stage2b_PrimaryWindowTest` — construct a corridor where a 200 m link is CONG and all 1 km links are FREE; assert no primary window fires (R1).
- `Stage3_BertiniTest` — three-point tests with known up/mid/dn traces.
- `Stage3_HeadBottleneckTest` — S01 with a sustained CONG run; assert one HEAD interval; assert ACTIVE_BOTTLENECK for S01 is empty after VerdictResolver runs.
- `Stage4_ShockwaveTest` — feed known distances and onsets, assert pass/fail per pair.
- `Stage5_SystemicTest` — both the simultaneity rule and the contiguity rule, independently.
- `R7_ConfidenceTest` — feed known signal values, assert the weighted sum.
- `R8_BaselineCheckTest` — feed a segment with an absurdly inflated ff_tt, assert the flag.

---

## 7. SQL you'll need

### 7.1 Chain walker (optional — only needed if the caller doesn't pass a pre-built chain)

The Python version is in `data/v2_1/build_chains.py`. Port it as a `CorridorChainBuilder` class that takes a seed `roadId` + direction (upstream/downstream) and walks adjacency via PostGIS `ST_DWithin(ST_EndPoint(a.geom), ST_StartPoint(b.geom), 35)`. Enforce the straightness ratio (≥ 0.55) and the name-core dedupe exactly as the Python does.

### 7.2 Per-day onsets

```sql
WITH bucketed AS (
    SELECT
        o.road_id,
        (o.event_time AT TIME ZONE 'Asia/Kolkata')::date AS dt,
        EXTRACT(HOUR FROM o.event_time AT TIME ZONE 'Asia/Kolkata') * 60
            + EXTRACT(MINUTE FROM o.event_time AT TIME ZONE 'Asia/Kolkata') AS mod_min,
        o.current_travel_time_sec AS tt,
        ff.ff_tt_sec * 1.5 AS threshold
    FROM traffic_observation o
    JOIN free_flow_proxy ff ON ff.road_id = o.road_id
    WHERE o.road_id = ANY(:chainRoadIds)
      AND o.event_time >= :analysisStart
      AND o.event_time <  :analysisEnd
      AND EXTRACT(ISODOW FROM o.event_time AT TIME ZONE 'Asia/Kolkata') BETWEEN 1 AND 5
),
flagged AS (
    SELECT *, CASE WHEN tt > threshold THEN 1 ELSE 0 END AS over
    FROM bucketed
),
runs AS (
    SELECT road_id, dt, mod_min,
           SUM(over) OVER (PARTITION BY road_id, dt
                           ORDER BY mod_min
                           ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS sustained
    FROM flagged
)
SELECT road_id AS rid, dt, MIN(mod_min) AS om
FROM runs
WHERE sustained >= 5   -- 10 min sustained
GROUP BY road_id, dt
ORDER BY road_id, dt;
```

The service caches the `free_flow_proxy` table per (city, analysis window). Invalidate weekly.

---

## 8. Non-functional requirements

- **Latency budget**: 2 seconds per corridor on a 30-day, 11-segment chain. This is comfortable — the Python reference runs in 800 ms on the same hardware without any vectorisation beyond NumPy. Java should beat it.
- **Memory**: bounded by `segments × 720 buckets × 30 days × 8 bytes`. An 11-segment corridor is ~2 MB of raw profile data. Don't stream — load everything in RAM.
- **Determinism**: two runs with the same inputs must return byte-identical JSON. No `HashMap` iteration in serialized output — use `TreeMap` or an explicit ordering comparator.
- **Idempotence**: the diagnose call is a pure function of (Corridor, observations, onsets). No DB writes during diagnosis. Persist the result separately if the caller wants to store it.
- **Observability**: emit a metric for `stage4.shockwave_pass_rate` per corridor per run. That's the single number that tells you if Stage 4 is working on a new city.

---

## 9. Sequence of PRs I'd suggest

1. **PR 1 — skeleton + data contracts.** Records, enums, empty stage classes, the config class, a JSON round-trip test against the golden fixture (expected to fail on everything).
2. **PR 2 — Stage 1 + Stage 2.** Free-flow discovery and regime classification. Diff just the `freeFlow` and `regimes` sections of the golden output.
3. **PR 3 — Stage 2b.** R1 length-weighted primary windows. Diff `primaryWindows`.
4. **PR 4 — Stage 3.** Bertini + R3 head bottleneck. Diff `activeBottlenecks` and `headBottlenecks`.
5. **PR 5 — Stage 4.** Shockwave validation in both modes. Diff `shockwavePairs`, `shockwavePassRate`, `shockwaveMode`.
6. **PR 6 — Stage 5 + Stage 6 + R8.** Systemic, recurrence, baseline flag. Diff the remaining top-level fields.
7. **PR 7 — R7 confidence + VerdictResolver.** The verdict priority logic and confidence math. By now the full JSON diff on all 6 corridors should pass.
8. **PR 8 — service wiring.** `CorridorDiagnosticService`, the SQL repositories, the Spring endpoint, the caching layer.

At the end of PR 7 you should be able to run the end-to-end fixture test and see green on all 6 corridors. That's production-ready.

---

## 10. File manifest for the handoff email

Send the engineer this exact list:

**Specs (read first)**
1. `CORRIDOR_DIAGNOSTICS_V2_PRD.md` — §13a is the v2.1 section
2. `docs/CORRIDOR_DIAGNOSTICS_V2_DESIGN.md` — algorithm rationale
3. `docs/CORRIDOR_DIAGNOSTICS_V2_1_VALIDATION.md` — what "correct output" looks like
4. `docs/CORRIDOR_DIAGNOSTICS_V2_1_ENGINEER_HANDOFF.md` — this file

**Reference implementation (treat as pseudocode)**
5. `data/corridor_diagnostics_v2.py`
6. `data/v2_1/corridor_diagnostics_v2_1.py`
7. `data/v2_1/run_validation.py`
8. `data/v2_1/build_chains.py`
9. `data/v2_1/save_profile.py`

**Golden fixture (for JUnit)**
10. `data/v2_1/validation_corridors.json`
11. `data/v2_1/profiles/all_profiles.json`
12. `data/v2_1/onsets/all_onsets.json`
13. `runs/v2_1/v2_1_validation_structured.json`
14. `runs/v2_1/v2_1_validation_report.txt` — human-readable version of the same run, useful when a test fails and he wants to eyeball what went wrong

Any questions, come back to me — don't re-derive the thresholds from scratch. Every number in here was chosen for a reason that's documented somewhere in the PRD or the validation report.
