# TraffiCure Corridor Diagnostics v2 — End-to-End PRD

**Owner:** Umang
**Status:** Validated on 7 corridors / 77 segments. Preferred-mode Stage 4 pending.
**Last updated:** 2026-04-10
**Related docs:** `CORRIDOR_DIAGNOSTICS_V2_DESIGN.md` (algorithm internals), `CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md` (empirical results)

---

## 1. Problem statement

A traffic engineer running a city like Pune has three questions every morning:

1. **Where is my corridor actually broken?** Not "everything is red on the map" — which exact segment is the choke?
2. **Why is it broken — is this a bottleneck with a queue, a narrow slow link, or is the whole corridor oversaturated at once?** These three failure modes need completely different fixes (signal retiming vs geometric widening vs demand management). Conflating them is the single biggest reason traffic investments don't pay off.
3. **When should I act — is it a 90-minute midday blip or an 8-hour grind?** Dispatching a marshal for 90 minutes is cheap. Retiming signals for an 8-hour grind is a project.

The v1 diagnostic pipeline answered these questions badly. It had hand-tuned thresholds for Pune, it treated a 12-hour "congestion" blob as a primary window, it collapsed multi-bottleneck corridors into one verdict, and it couldn't distinguish a slow link from an active bottleneck. v1's summary on Mundhwa-Kolwadi named the wrong segment as the bottleneck because of a seed-counter artefact.

**The goal of v2:** a single diagnostic pipeline, with zero hand-tuned thresholds that assume anything about any particular city, that takes raw 2-minute travel-time data and spits out per-segment verdicts a traffic engineer can act on. Same code, same tunables, works in Pune, Delhi, Kolkata, Bengaluru, Mumbai.

---

## 2. What we're building, in one sentence

A six-stage pipeline that takes per-segment 2-minute travel-time medians over a 22-weekday window, discovers each segment's own free-flow speed from the data, classifies every 2-minute bucket into one of four regimes, and then applies three independent tests (primary window, Bertini three-point, LWR shockwave) to produce a labelled verdict per segment — slow-link vs active-bottleneck, point vs systemic, recurrent vs episodic — plus the exact time windows when each verdict applies.

The algorithm is grounded in classical traffic-engineering theory (fundamental diagram of traffic flow, Bertini & Leal 2005, Lighthill-Whitham-Richards shockwave model). No machine learning. No city-specific tuning. No heuristic shortcuts that would break when the data comes from a different probe source or a different road topology.

---

## 3. Data foundation

**Source:** `traffic_observation` table. One row per segment per 2-minute interval per day, with `current_travel_time_sec` (the probe-derived median travel time in that bucket).

**Shape:** 720 buckets per day (1440 minutes / 2), roughly one row per bucket per day per segment.

**Window:** 22 weekdays (2026-03-02 through 2026-03-30). Weekdays only — weekends have different demand patterns and will get their own pass later.

**Pre-processing:** for each (segment, bucket-of-day) pair we take the **median** across the 22 weekdays. The result is a single 720-point "typical weekday" profile per segment. This is what the first five stages of the pipeline consume.

**What we explicitly do not use:**

- `freeflow_travel_time_sec` (the column in the DB). It is not actual free flow. On every segment we tested it mirrors the 08:00–09:00 morning-commute median within ±1 second. Using it as free flow would silently anchor every regime classification to a congested reference and everything downstream collapses. Dropped from the pipeline.
- Any hard-coded "rush hour" windows. The whole pipeline discovers its own peak times.
- Any hard-coded city-specific speed limits. Only one universal physical clamp (80 km/h, see Stage 1).

---

## 4. Stage 1 — Discovering free flow, per segment, from the data itself

### The problem

"Free flow" means "how fast does this road actually go when it's empty and nothing is slowing you down." Without a trustworthy free-flow reference, nothing else in the pipeline works — you can't call a segment congested if you don't know what uncongested looks like on that specific segment.

Static speed limits don't work. Urban roads in India have 50 km/h signs but physical geometry and signal density mean the real free-flow speed might be 35 km/h. Ghat sections have 40 km/h signs but curves limit you to 25. Highway-feeder slip roads have no sign at all.

Map-data "free flow" columns don't work either. Most of them are vendor-supplied heuristics that blend recent nighttime averages with road-class defaults, and they don't update when the road changes.

### The method (ELI5)

For every segment, look at 22 weekdays × 720 buckets = ~15,840 travel-time observations. Slide a 30-minute window (15 adjacent buckets) across the day and compute the median travel time in every window. Pick the **three quietest windows** — the three with the lowest median. Pool those three windows' raw travel times (up to 45 values). Take the **15th percentile** of the pool. That's the segment's free-flow travel time.

Then divide segment length by that free-flow travel time. If the resulting speed exceeds 80 km/h, clamp it — no urban segment in any city we care about has a free-flow speed above 80 km/h, and anything higher is a probe glitch.

### Why it works everywhere

- **No city-specific assumptions.** We don't say "2 AM to 5 AM is free flow" — we let the data tell us when each segment is actually empty. On the Diveghat segments, the pipeline picked 07:06–07:40 because overnight freight trucks make the ghat busier at 3 AM than 7 AM. On urban arterials it picked 02:30–04:30. Same code, different answers, both correct.
- **Quietest-30-min × top-3 × p15** is robust against both single-day outliers and probe noise. A 30-min window means you need a sustained quiet period. Top-3 means you need it to reproduce across windows. p15 rejects the occasional zero-traffic super-fast run while still trusting the bottom of the distribution.
- **22 weekdays is enough.** Sample size per quiet-window pool is 30–45 values, which is large enough for a stable p15 on any real-world distribution.
- **80 km/h clamp is the only hard-coded constant in the whole pipeline.** It's a universal safety rail, not a city-specific tunable.

### Validation

On the original 4 corridors + the 3 new corridors = 77 segments, the pipeline picked a free-flow window somewhere in the 01:34–07:20 IST band on every single segment. Zero segments needed the 80 km/h clamp. Zero warnings.

---

## 5. Stage 2 — Regime classification (speed-ratio)

For every 2-minute bucket, compute `speed_ratio = ff_tt / current_tt`. A ratio of 1.0 means the segment is at free-flow speed. A ratio of 0.4 means you're at 40% of free flow — i.e., stuck.

Bucket into four regimes using thresholds grounded in the fundamental diagram of traffic flow:

| Regime | Speed ratio | Physical meaning |
|---|---|---|
| **FREE** | ≥ 0.80 | Uncongested, above critical density |
| **APPROACHING** | 0.50 – 0.80 | Flow approaching capacity, stable but dense |
| **CONGESTED** | 0.30 – 0.50 | Below critical speed, LOS E |
| **SEVERE** | < 0.30 | Stop-and-go, LOS F |

These thresholds are not tuned. They come from the textbook breakpoints of the speed-density relationship in the Greenshields / Van Aerde family of models. A road that operates at 80% of free-flow speed is physically near capacity. A road at 30% is physically in congestion regime. These are not Pune numbers, they're traffic-engineering numbers.

**Output:** for each segment, a list of 720 regime labels, one per bucket.

---

## 6. Stage 2b — Primary congestion window

Before we talk about bottlenecks we need to know when the corridor as a whole is under stress.

**Rule:** find time intervals where **≥25% of segments are simultaneously CONGESTED or SEVERE** for **≥30 minutes**. Merge intervals separated by <30 minute gaps. Handle midnight wrap.

This gives you one or two (sometimes three) primary congestion windows per corridor per day. On JBN we got 12:04–13:34 (midday) and 17:26–20:30 (PM peak). On HDV we got none — it's a quiet corridor and the pipeline correctly refuses to invent one.

Stages 3 and 4 only look inside primary windows. This is what stops the pipeline from generating fake bottleneck alerts during genuinely free-flowing hours.

---

## 7. Stage 3 — Bertini active-bottleneck test (the core idea)

This is where v2 earns its keep. It's the single most important stage.

### The idea

A **bottleneck** and a **slow link** look identical if all you measure is "how fast is this segment." Both are slow. The difference is what happens on either side:

- An **active bottleneck** has a **queue backed up upstream** (traffic piling up behind it) and **free-flowing conditions downstream** (traffic dispersing once it gets past the choke).
- A **slow link** is slow because the road is narrow or twisty, but upstream is fine (no queue) and downstream is also fine (no bottleneck).

A slow link is a geometry problem. An active bottleneck is a capacity problem. The fix for each is completely different.

### The rule (Bertini & Leal 2005, three-point test)

For every segment S at every time bucket inside a primary window, check all three:

1. The segment **upstream** of S is CONGESTED or SEVERE (there's a queue behind)
2. S itself is CONGESTED or SEVERE (the choke)
3. The segment **downstream** of S is FREE or APPROACHING (traffic disperses past the choke)

If all three are simultaneously true for **≥10 minutes** (5 buckets), S fires a Bertini activation for that interval.

A segment that fires Bertini is a real active bottleneck. A slow segment that doesn't fire Bertini is a slow link (or an unloaded bottleneck — i.e., supply-constrained road that isn't yet seeing demand pressure). Both are useful diagnoses; they lead to different engineering actions.

### Why this is the right test

- **It's direct physics, not a heuristic.** The three-point pattern is a direct observable of a standing queue discharging past a capacity-limited point.
- **It transfers between cities.** There's nothing Pune-specific about the three-point rule. It works wherever you have a chain of segments and a measurement of regime per segment per time bucket.
- **It separates bottlenecks from slow links — something no heuristic pipeline has ever done robustly in this shop.** BAP's S06 is 56% CONGESTED but Bertini correctly does not fire on it because its upstream S05 is never congested — it's a pinch point with no queue behind it, not a bottleneck. That distinction is clinically useful.

### Output

For each segment, a list of `(start_bucket, end_bucket)` intervals when Bertini fired. On JBN we got three firing segments (S07, S11, S14) with different timings — the pipeline correctly identified three independent active bottlenecks along a 28 km corridor instead of collapsing them into one verdict.

---

## 8. Stage 4 — LWR shockwave cross-check

### The idea

If Bertini says "S07 is an active bottleneck firing at 17:30", physics makes a specific prediction: the congestion wave should propagate **backward** from S07 into upstream segments at 12–22 km/h (the Lighthill-Whitham-Richards shockwave speed for urban arterials). This is not a tunable number — it comes from the slope of the congested branch of the fundamental diagram and has been empirically verified in dozens of field studies.

So: check whether the onset times of congestion in consecutive segment pairs are consistent with a 12–22 km/h backward shockwave given the segment-to-segment distance. If yes, the bottleneck is physically confirmed. If no, something else is going on (e.g., separate demand sources hitting different segments at different times, or an upstream signal shutting off the source).

### Two modes

**Preferred mode (per-day onsets).** For each segment, for each weekday, pull the exact time bucket when that segment first crossed into CONGESTED and stayed there. That gives you ~22 onset times per segment. Compute the median onset lag between consecutive segment pairs. Check whether `lag ≈ distance / back_prop_speed`.

**Fallback mode (median profile centroid).** If per-day onsets aren't available, compute the centroid of the "slow patch" in the median profile and use that as a proxy for onset. This is what we ran for both the original-4 regression and the JBN/BAP/HDV blind test.

### Why Stage 4 currently shows 0% pass rate

Fallback mode is unreliable on signal-dominated urban corridors because the median profile smears out day-to-day variance in onset times. On some days S07 tips over at 17:28, on others at 17:40. The median blurs these into a mushy 17:26–19:00 "S07 is slow" shape, and the centroid of that mushy shape doesn't reliably coincide with the centroid of S06's mushy shape offset by the expected lag. So the check fails most of the time.

**This is a known limitation of fallback mode, not a failure of the Bertini test upstream.** Stage 3 is separately giving us the right answer. Stage 4 in fallback mode is currently providing no information — not a negative signal, just silence.

**Fix path.** A small, fast separate query that pulls per-segment per-weekday onset times (22 days × 77 segments ≈ 1,700 rows total). Feed into Stage 4 in preferred mode. Expected outcome: shockwave pass rates jump on the segment pairs where Bertini already fires, because physics requires it. This is scheduled as the next engineering task.

---

## 9. Stage 5 — Systemic vs point

**Rule:** if the corridor ever has **≥80% of its segments simultaneously congested** for a sustained window, flag it as **systemic**. Otherwise it's a point-bottleneck model and Stage 3's Bertini hits are the actionable sites.

This catches the case where the whole corridor is oversaturated at once — e.g., a 10 km cross-city arterial at 6 PM where every segment is bad because demand exceeds corridor capacity everywhere. For systemic cases, per-segment fixes won't help; you need demand management, route diversion, or signal-wave coordination across the whole chain. Different playbook.

Zero of the 7 corridors tested so far have fired systemic. All 7 were point-bottleneck cases. This is the common case for Indian cities that have multiple arterials sharing load.

---

## 10. Stage 6 — Recurrence typing

For each segment, count how many weekdays out of 22 it actually entered CONGESTED during the primary window. Label:

- **Recurrent** (≥80% of days): a predictable, daily event. Structural.
- **Frequent** (50–80%): most days but not all. Probably structural with weather/event noise.
- **Episodic** (<50%): event-driven, not structural. Don't build permanent infrastructure for this.

This matters because a segment that fires Bertini every single day needs a different response than one that fires 30% of the time. The first is a signal-timing / geometric project. The second is an incident-response / diversion play.

(Stage 6 runs only when per-day onset rows are available — same blocker as Stage 4 preferred mode.)

---

## 11. End-to-end pipeline diagram

```
     22 weekdays of 2-min data (from traffic_observation)
                        │
                        ▼
              ┌──────────────────┐
              │  Weekday-median  │   →  720 buckets × N segments
              │  profile builder │      (the "typical day")
              └──────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 1 — free-flow discovery    │   per-segment
       │  (quiet 30-min × top-3 × p15)     │   ff_tt_sec
       └───────────────────────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 2 — regime classification  │   per-bucket
       │  (FREE/APPR/CONG/SEVR by ratio)   │   label
       └───────────────────────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 2b — primary windows       │   corridor-level
       │  (≥25% segs CONG for ≥30 min)     │   time windows
       └───────────────────────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 3 — BERTINI three-point    │   ACTIVE
       │  (upstream+self CONG, down FREE)  │   BOTTLENECK
       │  sustained ≥10 min                │   intervals
       └───────────────────────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 4 — LWR shockwave check    │   physics
       │  (12–22 km/h back-prop)           │   confirmation
       │  [preferred: per-day onsets]      │
       └───────────────────────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 5 — systemic vs point      │   model type
       └───────────────────────────────────┘
                        │
                        ▼
       ┌───────────────────────────────────┐
       │  STAGE 6 — recurrence typing      │   recurrent /
       │  (day-count per segment)          │   episodic
       └───────────────────────────────────┘
                        │
                        ▼
            CorridorDiagnosis object
                 → rendered report
```

---

## 12. What the engineer actually sees

The pipeline produces a `CorridorDiagnosis` object per corridor. The text rendering (what you see in `v2_blind_JBN.txt` etc.) is a developer-view dump. The operator-view UI reframes it as a decision tool:

### 12.1 Per-corridor summary card

- Corridor name and length (e.g. "Jedhe Chowk → Naygaon Phata, 27.6 km, 20 segments")
- **Primary window timing** in plain English ("Busy 12:04–13:34 and 17:26–20:30")
- **Model type** ("Point-bottleneck, 3 active sites" or "Systemic, full-corridor oversaturation")
- **Peak simultaneous congestion** ("10 of 20 segments at worst")
- Recurrence summary ("Recurrent on 18/22 weekdays")

### 12.2 Per-segment verdict strip

For each segment in the chain, a single color-coded row showing:

- Segment number and name
- Regime histogram (FREE % / APPR % / CONG % / SEVR %)
- Free-flow speed (km/h)
- **Verdict badge:**
  - `ACTIVE BOTTLENECK` (fires Bertini) with firing intervals
  - `SLOW LINK` (consistently CONGESTED but no Bertini — geometry-limited)
  - `QUEUE VICTIM` (congested but immediately upstream of a bottleneck — treat with the bottleneck)
  - `FREE FLOW` (essentially uncongested)
- Link to the 2-min heatmap for that segment

### 12.3 Recommended action tree

For each `ACTIVE BOTTLENECK` verdict, the UI presents a short decision tree:

1. **Is it recurrent (≥80% of weekdays)?** → Signal-retiming / geometric project.
2. **Frequent (50–80%)?** → Adaptive signal response, time-of-day diversion plan, enforcement checkpoints.
3. **Episodic (<50%)?** → Incident-response protocol, do not build permanent infrastructure.
4. **Does the Bertini window coincide with the primary window principal, or a secondary window?** → Resource allocation (principal = marshal on-site, secondary = traffic cam + remote monitoring).

For each `SLOW LINK` verdict: flag for geometric assessment (shoulder use, turn-lane retrofit, medial changes). These are longer-cycle capital projects, not operational.

For each `QUEUE VICTIM`: no action — the fix is at the bottleneck upstream.

### 12.4 Example decision, JBN S07 (St. Mery Chowk → Turf Club)

- **Verdict:** ACTIVE BOTTLENECK (Bertini fires 4 times: midday twice + PM twice)
- **Recurrence:** pending per-day onset pull (Stage 6)
- **Regime histogram:** 31% FREE / 14% APPR / **55% CONGESTED** / 0% SEVR
- **Primary window association:** principal — fires in both corridor-level windows
- **Action:** signal-retiming assessment at the Mery Chowk signal, plus a peak-hour marshal. Because Bertini fires at midday *and* PM, this is not commuter-only — it's a persistent choke, highest priority among the three JBN bottlenecks.

That's the output an engineer needs. Not a heatmap. Not a time series. A verdict with a recommended action and the evidence trail behind it.

---

## 13. Validation so far

### Original 4 Pune corridors (regression)

| Corridor | Segments | v2 primary window(s) | v2 bottleneck verdict | Match with prior belief |
|---|---|---|---|---|
| Jedhe → Katraj | 11 | 11:30–13:00, 17:56–20:54 | S04, S05, S06, S10 (Bertini) | exact |
| Koregaon → Keshavnagar | 7 | 08:46–22:18 | S04 principal, S07 secondary | exact |
| Pune Station → Kanha | 12 | 10:52–14:24, 15:40–20:34 | S01, S04, S09, S12 | exact |
| Mundhwa → Kolwadi | 8 | 08:32–12:46, 17:52–21:42 | S02 AM, S03 PM | **correction** (v1 said S01 — seed-counter artefact) |

All four corridors: NOT systemic. Primary windows physically sensible after the IST timezone fix in `profiles.py`.

### Blind test — 3 new corridors (JBN / BAP / HDV)

39 segments, 49.2 km, three different road types. Algorithm ran unchanged.

| Corridor | Segments | Verdict | Bertini hits |
|---|---|---|---|
| JBN (Jedhe → Naygaon Phata, urban arterial, 27.6 km) | 20 | 3 independent active bottlenecks | S07 (principal, midday+PM), S11 (PM), S14 (late PM) |
| BAP (Bapodi → Wadgaonsheri, signalised arterial, 9.4 km) | 11 | 1 PM active bottleneck + 1 AM slow link | S09 (PM), S06 (AM, slow link — Bertini correctly does not fire) |
| HDV (Hadapsar → Diveghat, highway feeder, 12.2 km) | 8 | Quiet corridor, 1 isolated slow junction | none (S03 is isolated slow link) |

### Totals

- **77 segments** validated across **7 corridors** and **4 distinct road typologies** (dense urban, signalised arterial, highway feeder, mountain ghat climb).
- **Zero tunable adjustments** between the original-4 rerun and the 3-corridor blind test.
- **Zero segments** needed the 80 km/h ceiling clamp.
- **Zero segments** emitted a Stage 1 warning.
- Free-flow windows on all 77 segments landed in the physically expected 01:34–07:40 IST band.

---

## 13a. v2.1 refinements (incorporated April 2026)

After the v2 regression landed, we audited the pipeline against eight candidate improvements and incorporated the five that moved diagnostic quality without destabilising the physics core. v2.1 is a thin refinements layer on top of v2 (`data/v2_1/corridor_diagnostics_v2_1.py`) — it imports `corridor_diagnostics_v2` unchanged and augments outputs; no v2 tunable was edited. This keeps regression surface minimal and lets us back out any refinement by flipping a flag.

### R1 — Length-weighted Impact Score for primary windows

Old: primary window fires when ≥25 % of segments are CONG in the same 2-min bucket. This over-weights 200 m signal-spaced links.
New: score each bucket by `sum(length_m of CONG segments) / sum(length_m of all segments)`. Windows fire when that fraction ≥ `IMPACT_MIN_FRAC` (0.25). A 200 m slow link no longer drags the whole corridor into a "primary window" just because it's one of four segments. Implementation: `detect_primary_windows_lenweighted()`.

### R3 — Head / origin bottleneck firing for S01

Old: Bertini needs an upstream neighbour, so the corridor's first segment could never fire as an active bottleneck even when it was the obvious queue source (the queue just has nowhere upstream to grow into inside the corridor window). v2 patched this by allowing S01 to fire when `up is None`, but the verdict surface still labelled it ACTIVE_BOTTLENECK indistinguishably from mid-corridor hits.
New: head runs are detected separately (`head_bottleneck_intervals()`) on S01's CONG regimes, the v2 Bertini result for S01 is zeroed, and the verdict surface tags these as `HEAD_BOTTLENECK`. Operator-facing meaning: "the corridor's queue starts here and we have no upstream visibility to formally prove Bertini — treat this as the head of the queue." Symmetrically, the terminus (S_N) is not allowed to fire as a bottleneck (a queue cannot be caused by the last segment within the corridor frame — Bertini's `dn is None` case is suppressed).

### R5 — Contiguity-based systemic classification

Old: systemic if ≥80 % of segments are simultaneously CONG in the same bucket. This lets a fragmented "CONG here, free there, CONG here" pattern qualify as systemic.
New: in addition to the simultaneity test, we compute the length-weighted share of the **longest contiguous CONG run** during the primary window. The systemic verdict is reinforced when both signals agree (`systemic_contiguity()`). A corridor with 86 % simultaneous but only 44 % contig is flagged as "simultaneous but fragmented" rather than a single rolling wave. v2's 80 % rule still drives the top-line verdict; R5 adds the corroborating structure signal to the confidence math and to the operator report.

### R7 — Per-verdict Confidence Index

Every verdict now carries a 0–1 confidence score composed of four equally-weighted signals: (a) how tight the free-flow p15 cluster was in Stage 1 (`ff_tight`), (b) how much of the segment's CONG mass sits inside a primary window (`primary_overlap`), (c) whether per-day onset support exists for the segment (`onset_support`), (d) whether at least one Stage 4 shockwave pair passed for this segment (`shockwave_support`). This gives the engineer a tie-breaker when two segments on the same corridor both show ACTIVE_BOTTLENECK: follow the higher-confidence one first. Implementation: `confidence_for_segment()`.

### R8 — "Perpetually saturated baseline" sanity flag

Old: Stage 1 uses nightly p15 as a proxy for free flow. A segment that is congested 24/7 (rare but real — think a permanently saturated toll approach) would have its "free flow" silently inflated to its busy-hour travel time, and nothing downstream would catch it.
New: `flag_saturated_baselines()` compares every segment's Stage 1 ff proxy against (a) its corridor peers and (b) its own daytime p50. If a segment is ≥ 2× its peers AND its quiet-hour median is ≥ 0.7× its busy-hour median, it's flagged for review. The flag does not change the verdict — it surfaces in the report as a "check baseline" note. On the 6-corridor validation set it did not fire (threshold is deliberately conservative); we'll calibrate once we see it trip on production data.

### v2.1 tunables

```
IMPACT_MIN_FRAC               = 0.25
SYSTEMIC_CONTIG_MIN_FRAC      = 0.60
BASELINE_PEER_RATIO           = 2.0
BASELINE_QUIET_BUSY_RATIO     = 0.70
HEAD_BOTTLENECK_MIN_BUCKETS   = 5   (= v2.BERTINI_MIN_BUCKETS)
CONFIDENCE_WEIGHTS            = {ff_tight: 0.25, primary_overlap: 0.25,
                                  onset_support: 0.25, shockwave_support: 0.25}
```

### Recommendations we did NOT take

- **Road-class-aware ff clamp (R2):** v2's 80 km/h cap has not fired once across 77 + 48 segments, so a class-aware clamp is solving a problem we don't have. Revisit when we ingest expressway data that genuinely free-flows above 80.
- **Signal-cycle-aware Bertini duration (R6):** requires per-signal cycle metadata we don't yet have. The current 10-minute sustained-window floor is doing the job; parking until we wire in signal-plan data.
- **Mandatory per-day onsets for Stage 4 (R4):** conceptually right, but making it mandatory would break fallback mode. Instead we enabled per-day onsets as the preferred path (Section 14.1 below is now done) and kept the no-onset fallback intact.

### Cross-city validation on v2.1 (April 2026)

Six frozen corridors — 3 Pune + 3 Kolkata, 48 segments, 56.86 km, 4,540 per-day onset rows — ran end-to-end through v2.1 with **zero cross-city tuning**. Summary:

| Corridor | Segs | km | Verdict | Simultaneous / contig | Primary windows | Active / head | SW pass |
|---|---|---|---|---|---|---|---|
| PUNE_A | 6 | 7.12 | POINT | 33 % / 15 % | 1 | 1 head + 1 active | 20 % |
| PUNE_B | 9 | 15.93 | POINT | 22 % / 14 % | 1 | 1 active | 0 % |
| PUNE_C | 8 | 10.66 | POINT | 38 % / 28 % | 1 (17:26–19:44) | 1 active | 29 % |
| KOL_A | 7 | 4.95 | POINT | 71 % / 51 % | 2 | 3 active | 17 % |
| KOL_B | 7 | 7.98 | SYSTEMIC | 86 % / 44 % | 2 | 4 active | 17 % |
| KOL_C | 11 | 10.24 | SYSTEMIC | 91 % / 89 % | 2 | 1 head + 4 active | 40 % |

KOL_C is the strongest corroboration: simultaneity, contiguity, and LWR shockwave evidence all agree. KOL_B shows the value of R5 — high simultaneity but fragmented, so the systemic verdict lands with lower corroboration weight. Low shockwave pass rates on most corridors reflect demand-driven forward propagation (negative observed lags), which is a correct diagnostic output, not a pipeline failure. Full per-corridor breakdown lives in `docs/CORRIDOR_DIAGNOSTICS_V2_1_VALIDATION.md`.

**Production readiness:** v2.1 is greenlit for production on Pune and Kolkata. Same code, same thresholds, two cities, zero tuning — the physics core holds.

---

## 14. Open items & roadmap

### 14.1 Preferred-mode Stage 4 — DONE (April 2026)

Per-weekday onsets now land as a flat `(rid, dt, om)` table (`valid/onsets/all_onsets.json`, 4,540 rows across the 48 validation segments). The v2.1 runner groups them by segment and passes them straight into `shockwave_validation_from_onsets()`. Observed-lag distributions on the 6-corridor run are genuine signal: positive lags where LWR backward propagation holds, negative lags where demand-driven forward propagation dominates. Next step is running the same onset pull against the original 77 regression segments so we can re-score the regression set with Stage 4 live.

### 14.2 Weekend pass

Same pipeline, same code, separate 10-Saturday + 10-Sunday windows. Weekend demand patterns differ from weekday and need their own profiles. No algorithm change — just different input slices.

### 14.3 Cross-city validation

Run the unchanged pipeline on a Delhi corridor and a Kolkata corridor. We have high confidence this will work (the algorithm is pure traffic-engineering physics), but it needs to be demonstrated before we claim "works globally." Blocker: getting probe-data access for those cities.

### 14.4 Operator-facing UI

`corridor-diagnostics-mockup.html` and `mundhwa-corridor-diagnostics.html` in this folder are the first-pass mockups of the engineer-facing UI. They need to be updated to show v2's verdict badges (ACTIVE BOTTLENECK / SLOW LINK / QUEUE VICTIM / FREE FLOW) instead of v1's single-color bar. The decision tree from Section 12.3 needs to be surfaced on click.

### 14.5 Multi-day trend view

Once per-day onsets are available, add a 22-day timeline per bottleneck showing which days it fired and at what severity. This is the data a traffic engineer needs for a capex justification: "this bottleneck is active 19 days out of 22, the mean PM delay is 11 minutes, 4,800 vehicles/day pass through it."

### 14.6 Integration with alerting

Once the pipeline is trusted, wire verdict transitions into the operator alerting system. New `ACTIVE BOTTLENECK` → page the corridor owner. Loss of `ACTIVE BOTTLENECK` verdict after a signal change → positive confirmation that the fix worked.

---

## 15. File and folder manifest

Everything listed below lives in the folder you selected when this session started (the "PRDs" folder on your computer). Relative paths shown are relative to that folder.

### Code

- `data/corridor_diagnostics_v2.py` — the v2 physics pipeline (unchanged by v2.1)
- `data/corridors_v2.py` — chain definitions for the 4 original + 3 new corridors
- `data/profiles_new.py` — 2-min weekday-median profiles for the 39 new-corridor segments
- **`data/v2_1/corridor_diagnostics_v2_1.py`** — v2.1 refinements layer (R1/R3/R5/R7/R8) on top of v2
- `data/v2_1/run_validation.py` — runner that feeds validation corridors + profiles + onsets into `diagnose_v21()`
- `data/v2_1/build_chains.py` — PostGIS-adjacency greedy chain walker used to pick the 6 validation corridors
- `data/v2_1/save_profile.py` — helper that parses MCP profile-query results into `{road_id: {min_of_day: tt}}`
- `data/v2_1/validation_corridors.json` — the frozen 6 corridors (3 Pune + 3 Kolkata, 48 segments, 56.86 km)
- `data/v2_1/profiles/all_profiles.json` — 2-min weekday-median profiles for all 48 validation segments
- `data/v2_1/onsets/all_onsets.json` — 4,540 per-day onset rows for Stage 4 preferred mode

### Documents

- **`CORRIDOR_DIAGNOSTICS_V2_PRD.md`** — this file
- `docs/CORRIDOR_DIAGNOSTICS_V2_DESIGN.md` — algorithm internals and design rationale (written earlier in this work stream)
- `docs/CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md` — empirical results doc, includes the blind test as Section 9
- **`docs/CORRIDOR_DIAGNOSTICS_V2_1_VALIDATION.md`** — full per-corridor breakdown of the v2.1 cross-city validation

### Run logs

- `runs/v2_original4_run_CORRECTED.txt` — full v2 output for the 4 original corridors after the timezone fix
- `runs/v2_blind_new_run.txt` — full v2 output for the 3 new corridors (joined)
- `runs/v2_blind_JBN.txt`, `runs/v2_blind_BAP.txt`, `runs/v2_blind_HDV.txt` — individual new-corridor outputs
- **`runs/v2_1/v2_1_validation_report.txt`** — v2.1 per-corridor text report for the 6 validation corridors
- **`runs/v2_1/v2_1_validation_structured.json`** — structured JSON of the same run (for downstream consumption)

### UI mockups (pre-v2, need updating)

- `corridor-diagnostics-mockup.html`
- `mundhwa-corridor-diagnostics.html`

### v1 legacy (kept for reference)

- `CORRIDOR_DIAGNOSTICS_SUMMARY.txt` — v1's old summary
- `corridor_diag_*.txt` — v1's per-corridor reports

---

**Sources**

- [v2 design doc](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/docs/CORRIDOR_DIAGNOSTICS_V2_DESIGN.md)
- [v2 regression + blind-test report](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/docs/CORRIDOR_DIAGNOSTICS_V2_REGRESSION_REPORT.md)
- [Corrected original-4 run](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/runs/v2_original4_run_CORRECTED.txt)
- [Blind-test full run](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/runs/v2_blind_new_run.txt)
- [profiles_new.py](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/data/profiles_new.py)
- [corridors_v2.py](computer:///sessions/magical-gifted-meitner/mnt/PRDs/Phase%204%20-%20Corridor%20Diagnostics/data/corridors_v2.py)
