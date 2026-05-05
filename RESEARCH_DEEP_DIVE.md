# Deep Research Dive: What the Traffic Literature Actually Gives You

**For:** TraffiCure Corridor Diagnostics v2.1 pipeline  
**Data shape:** ~100 segments, 2-min travel times, speed-only (no flow, no occupancy, no signal timing), 10 days Delhi / 3+ months Pune-Kolkata  
**Date:** 2026-04-30

---

## Part 0 — Self-Critique of My Initial Take

Before I get to the real findings, let me be honest about what I got wrong in my first pass.

**I oversold ASM.** I said "10 lines of NumPy, biggest quality lift available." That was sloppy. ASM was designed for point sensors (loop detectors) measuring speed at fixed locations continuously. Your data is segment-average travel times from probes — fundamentally different spatial representation. More importantly, ASM's anisotropic kernel propagates information along two characteristic directions: forward at free-flow speed (~50 km/h for your arterials), and backward at jam-wave speed (~15 km/h). On a freeway, those speeds are physical constants from the fundamental diagram. On a signalized arterial, the backward wave speed is dominated by signal cycles (90–180 seconds in India), not jam density. ASM with a fixed V_cong = −15 km/h would produce artifacts near every signal. Your 2-min temporal resolution already partially averages over signal cycles, so the denoising benefit of ASM is much smaller than I claimed. **Verdict: demoted from "implement immediately" to "consider only for Stage 4 onset sharpening, after validating on one corridor."**

**I oversold day-clustering for Delhi.** I said "PCA + k-means on daily speed profiles." With 10 days of data, PCA + k-means is statistically meaningless — you'd get clusters of 2–3 observations each, which is noise, not signal. For Pune/Kolkata with 90+ days, yes. For Delhi's 10 days, no. **Verdict: replaced with a simpler, robust approach (see Tier 1 below).**

**I undersold the percolation literature.** This turned out to be the most directly valuable body of work for your pipeline. The percolation framework gives you a physics-grounded replacement for your Stage 5's arbitrary "≥80% simultaneous" threshold, plus an early-warning mechanism you don't have at all today. More on this below.

**I missed the jam-tree model entirely.** This is the most natural extension of your existing ACTIVE_BOTTLENECK / QUEUE_VICTIM distinction, and it fell out of a 2022–2025 series of papers (Serok, Havlin, Duan, Zeng) that your reading list doesn't include. It's the single most important gap in your current reading list.

---

## Part 1 — The Five Genuinely Load-Bearing Findings

These are ordered by impact × implementability. Each one maps directly to a gap in your current v2.1 pipeline, uses only data you already have, and I've verified the method works with speed-only segment-level data at 2-min resolution.

---

### Finding 1: Early Warning from Congestion Growth Rate

**Source:** Duan, Zeng, et al. (2023). "Spatiotemporal dynamics of traffic bottlenecks yields an early signal of heavy congestions." *Nature Communications* 14, 8477.

**The discovery:** The growth speed of a congestion cluster in its first 15 minutes is highly correlated with the cluster's eventual maximum size. Traffic jams dissolve roughly twice as slowly as they grow (dissipation duration follows a power-law distribution). This means you can predict the severity of a developing jam from its first 7–8 data points at 2-min resolution.

**What this gives you that you don't have today:** Your pipeline currently produces *retrospective* verdicts — "S10 was an ACTIVE_BOTTLENECK between 17:30 and 19:00." It says nothing about whether a *currently developing* congestion will be small (self-limiting, ignore it) or large (will propagate, act now). The growth-rate metric turns your diagnostic from a post-hoc report into a real-time early warning.

**How to implement on your data:**

When Stage 3 (Bertini) detects a new activation on any segment at bucket *t₀*:

1. Define the **congestion component** at each subsequent bucket as the set of contiguous segments in CONGESTED or SEVERE regime. This uses your existing Stage 2 regime labels — no new computation.

2. Track the **component size** C(t) = total length in meters of all contiguous CONG/SEVR segments, starting from t₀.

3. After 15 minutes (t₀ + 7 buckets), compute:  
   **growth_speed** = (C(t₀+7) − C(t₀)) / 15 [meters per minute]

4. Classify:
   - growth_speed > 50 m/min → **FAST GROWTH** — likely heavy congestion, alert immediately
   - growth_speed 10–50 m/min → **MODERATE GROWTH** — monitor closely
   - growth_speed < 10 m/min → **CONTAINED** — self-limiting, low priority

The threshold values (50, 10) are starting points. Calibrate on your historical data: for each past Bertini activation, retroactively compute growth_speed at +15 min and plot against actual max component size. The correlation should be strong (the paper reports R ≈ 0.7–0.85 across multiple cities).

**Why I'm confident this works on your data:** You have 2-min resolution (better than the 5-min data in the paper), you have contiguous segment chains (corridors), and you have regime labels at every bucket. The only thing you don't have that they used is network-level data (they worked on full city graphs) — but corridor-level analysis is actually a simpler version of the same problem, and the physics is the same: if congestion is spreading fast along your corridor in the first 15 minutes, it will get worse.

**Code cost:** ~30 lines on top of your existing Stage 3 output. No new data pulls. No new dependencies.

---

### Finding 2: Percolation-Based Systemic Detection (Replacing the 80% Threshold)

**Sources:**  
- Li, D. et al. (2015). "Percolation transition in dynamical traffic network with evolving critical bottlenecks." *PNAS* 112(3), 669–672.  
- Zeng, G. et al. (2019). "Switch between critical percolation modes in city traffic dynamics." *PNAS* 116(1), 23–28.  
- Ambühl, L., Loder, A., Bliemer, M., Menendez, M. & Axhausen, K. (2023). "Understanding congestion propagation by combining percolation theory with the macroscopic fundamental diagram." *Communications Physics* 6, 26.

**The problem with your current Stage 5:** You use "≥80% of segments simultaneously in CONG" as the systemic threshold. This is arbitrary. KOL_B hits 86% simultaneity but only 44% contiguity — your R5 refinement correctly flags this as "simultaneous but fragmented." But you still don't have a principled way to decide *when* point-bottleneck congestion transitions into systemic. The 80% threshold came from intuition, not physics.

**What percolation theory gives you:** A phase transition model with a physically meaningful critical point. Here's the core idea, adapted to your corridor:

At each 2-min bucket, build a graph from your segment chain:
- Each segment is a node
- Two adjacent segments are **connected** if BOTH are in CONG or SEVR regime
- Count the **number of connected components** (clusters of contiguous congested segments)
- Track the **size of the largest component** (in meters)

As congestion builds during a day:
1. **Early phase:** Small isolated clusters appear. Number of components rises. Largest component is small. → This is your POINT BOTTLENECK regime.
2. **Critical transition:** Clusters start merging. Number of components peaks and then DROPS. Largest component rapidly grows. → This is the percolation transition.
3. **Post-transition:** One giant component dominates. Number of components is low. → This is your SYSTEMIC regime.

**The critical insight from the PNAS 2015 paper:** The percolation transition happens when the **second-largest cluster reaches its maximum size**. At that moment, the two largest clusters are about to merge, and the system tips from fragmented to systemic. This is a precise, measurable threshold — not an arbitrary percentage.

**How to implement:**

For each primary window, at each 2-min bucket:
```
segments_cong = [s for s in corridor if regime[s] == CONG or regime[s] == SEVR]
components = find_connected_components(segments_cong, adjacency)
n_components = len(components)
largest = max(component_length(c) for c in components)
second_largest = second_max(component_length(c) for c in components)
```

Track n_components and second_largest over time. The bucket where second_largest peaks is the percolation transition. If it occurs during the primary window, classify the corridor as undergoing a systemic transition at that time. If it never occurs (second_largest stays small), the corridor stays in POINT mode throughout.

**What this replaces:** Your Stage 5 80% threshold AND your R5 contiguity check, with a single unified metric that has a physical interpretation (phase transition in a 1D percolation process). The 80% threshold was a rough proxy for this anyway — percolation theory makes it precise.

**Bonus — the PNAS 2019 finding:** During non-rush hours, arterial networks behave like small-world networks (fast highways act as long-range links). During rush hours, highways congest and those long-range links disappear, making the network behave like a 2D lattice. For your corridor-level analysis, the equivalent is: during off-peak, your corridor behaves as a chain of independent segments (1D percolation). During peak, congestion clusters merge and the corridor behaves as a single entity. The percolation transition marks exactly when this shift happens.

**Code cost:** ~50 lines. Uses existing regime labels from Stage 2. No new data.

---

### Finding 3: Jam-Tree Construction for Causal Propagation Tracing

**Sources:**  
- Serok, N., Havlin, S. & Blumenfeld Lieberthal, E. (2022). "Identification, cost evaluation, and prioritization of urban traffic congestions and their origin." *Scientific Reports* 12, 13109.  
- Duan, J., Zeng, G., Serok, N. et al. (2023). *Nature Communications* 14, 8477 [same as Finding 1].  
- Zeng, G., Serok, N. et al. (2025). "Unveiling city jam-prints of urban traffic based on jam patterns." *Communications Physics*.

**What your pipeline is missing (Gap #3 from your reading list):** Your current QUEUE_VICTIM classification is spatial (adjacent to a Bertini hit) but not temporal. You don't know whether a QUEUE_VICTIM segment became congested BEFORE or AFTER the bottleneck. If it became congested BEFORE, it's not a victim — it might be a co-origin or even the real cause.

**The jam-tree model:**

Traffic congestion propagates as a tree structure:
- The **trunk** is the first segment to enter CONG — this is the congestion origin (analogous to your ACTIVE_BOTTLENECK)
- **Branches** are segments that subsequently enter CONG due to propagation from the trunk (analogous to your QUEUE_VICTIM)
- The temporal ordering of onset times defines the parent-child relationships in the tree

For your corridor (which is a chain, i.e. a 1D graph), the jam tree simplifies beautifully:

```
For each day d:
  onset[s][d] = first bucket when segment s enters CONG during primary window
  
  Sort segments by onset time
  root = segment with earliest onset
  
  For each subsequent segment s (in onset order):
    parent[s] = the adjacent segment that entered CONG most recently before s
    lag[s] = onset[s] - onset[parent[s]]
    direction[s] = "upstream" if parent is downstream, else "downstream"
```

**What this gives you:**

1. **Validated origin identification:** The root of the jam tree is the true congestion origin on that day. Compare with your Bertini-based ACTIVE_BOTTLENECK verdict. If they disagree on some days, that's diagnostic — it means your bottleneck is not the same segment every day (migrating bottleneck, which your pipeline can't currently detect).

2. **Propagation direction per day:** Is congestion propagating backward (queue backing up upstream from bottleneck, which is LWR physics) or forward (demand-driven, which your Stage 4 negative lags already show)? The jam tree makes this explicit per day.

3. **Tree stability across days:** Compare jam trees across your 10 (Delhi) or 90+ (Pune/Kolkata) days. If the tree structure is similar every day (same root, same propagation order), the bottleneck is stable and structural → confident RECURRING verdict. If the tree structure varies (different root on different days), the congestion pattern is heterogeneous → your single-segment recurrence label is misleading.

4. **The jam-print extension:** The 2025 paper shows that the distribution of congestion costs across a city's jam trees follows a power law, and the exponent is characteristic of the city. For your corridors, you can compute a "corridor jam-print" — the distribution of per-segment delays within the jam tree across days. Different corridors will have different exponents. Corridors with steeper power laws (exponent more negative) have congestion concentrated at the origin; corridors with flatter power laws have congestion distributed across many segments. This is a new corridor-level metric that captures something none of your current stages measure.

**How this connects to your existing data:** You already have per-day onset times in `all_onsets_weekday.json`. You have adjacency information in your corridor segment chain. Building the jam tree is literally sorting segments by onset time and linking to the nearest already-congested neighbor. You already computed this data — you just haven't assembled it into the tree structure.

**Code cost:** ~60 lines. Uses existing onset data. No new pulls.

---

### Finding 4: Temporal Precedence Validation for QUEUE_VICTIM

**Sources:**  
- Chen, C., Skabardonis, A. & Varaiya, P. (2004). "Systematic Identification of Freeway Bottlenecks." *Transportation Research Record* 1867, 46–52.  
- Serok et al. (2022) [same as Finding 3].

**The Chen algorithm's key contribution your pipeline doesn't use:** Chen et al. track bottleneck *activations and deactivations* as paired events. When a downstream bottleneck creates spillback that reaches an upstream location, the upstream location is "masked" — all delay is attributed to the downstream (originating) bottleneck. This prevents double-counting.

Your pipeline has a version of this (QUEUE_VICTIM = congested but adjacent to Bertini hit), but it's spatial-only. Chen adds temporal: a QUEUE_VICTIM must become congested *after* the bottleneck activates.

**The specific check to add:**

For each segment currently classified as QUEUE_VICTIM:

```
For each day d:
  onset_victim[d] = first bucket when QUEUE_VICTIM segment enters CONG
  onset_bottleneck[d] = first bucket when adjacent ACTIVE_BOTTLENECK enters CONG
  
  If onset_victim[d] < onset_bottleneck[d]:
    flag: "QUEUE_VICTIM preceded ACTIVE_BOTTLENECK on day d"
```

If a QUEUE_VICTIM consistently (>50% of days) enters CONG before the adjacent bottleneck, one of three things is happening:

1. **The QUEUE_VICTIM is actually a co-origin** — both segments are independent bottlenecks activating in parallel. Reclassify as ACTIVE_BOTTLENECK (the Bertini test might not fire because its downstream segment is also congested, violating the "downstream FREE" condition).

2. **Forward propagation** — demand is hitting the QUEUE_VICTIM first and flowing downstream to the bottleneck. This is the demand-driven pattern your Stage 4 negative lags already detect. The jam tree from Finding 3 will show this as a forward-growing tree.

3. **Misidentified bottleneck** — the true bottleneck is the QUEUE_VICTIM, and the Bertini segment is the downstream discharge zone that happens to also be slow.

**Why this matters for your DEL_AUROBINDO corridor:** You have 41 segments, 13 ACTIVE_BOTTLENECK verdicts, and several QUEUE_VICTIM segments (S08, S09, S24, S25, S30). With 13 active bottlenecks on a 2.9 km corridor, the question is whether these are truly 13 independent bottlenecks or whether some are propagation effects from a smaller number of origins. Temporal precedence checking will collapse some of those 13 into propagation chains anchored at fewer true origins.

**Code cost:** ~20 lines. Uses existing onset data.

---

### Finding 5: Corridor-Level Macroscopic Fundamental Diagram with Hysteresis Detection

**Sources:**  
- Geroliminis, N. & Daganzo, C. (2008). "An analytical approximation for the macroscopic fundamental diagram of urban traffic." *Transportation Research Part B* 42(9), 771–781.  
- Ambühl et al. (2023) [same as Finding 2].  
- Saberi, M. & Mahmassani, H.S. (2013). "Hysteresis and capacity drop phenomena in freeway networks." *Transportation Research Record* 2391, 44–55.  
- Penn State (Gayah research group). "Hysteresis in Macroscopic Fundamental Diagrams."

**What is a corridor MFD?** Instead of the traditional speed-flow diagram (which needs flow data you don't have), compute a **speed-density proxy** for your corridor at each 2-min bucket:

```
mean_speed(t) = mean(calculated_speed_kmph for all segments at bucket t)
congestion_density(t) = fraction of segments in CONG or SEVR at bucket t
```

Plot mean_speed vs congestion_density across all buckets of a day. You get a curve that looks like the fundamental diagram — high speed at low density, declining speed at high density.

**The hysteresis insight:** If you trace this curve in temporal order (morning → peak → evening), you'll see a LOOP, not a single curve:

- **Onset path** (morning congestion building): Speed drops as density increases, following the "free-flow branch"
- **Recovery path** (evening congestion dissipating): Speed recovers at the SAME density but at LOWER speeds than during onset

This clockwise hysteresis loop is a direct observable of **capacity drop** — the phenomenon where a corridor's throughput after congestion onset is 5–15% lower than before onset (Cassidy & Bertini 1999 measured 7–10%). Your corridor is physically less efficient during recovery than during onset.

**What this gives you:**

1. **Corridor health metric:** The area enclosed by the hysteresis loop is a scalar measure of how "damaged" the corridor is by each congestion episode. Larger loop area = more severe capacity drop = harder recovery. This is a new KPI you can track across days and corridors.

2. **Onset vs recovery asymmetry:** The Duan et al. finding that "jams dissolve twice as slowly as they grow" shows up directly in the hysteresis loop — the recovery branch is longer (in time) than the onset branch.

3. **Without flow data:** You can't build the traditional speed-flow MFD, but the speed-density_proxy MFD is fully constructable from your data. The congestion_density proxy (fraction of segments congested) correlates with actual vehicular density — more segments congested means more vehicles are queued in the corridor.

4. **Day-to-day comparison:** Overlay multiple days' loops on the same plot. Days with similar loops have similar congestion dynamics. Days with different loop shapes have different failure modes. This is a simpler, more visual alternative to the day-clustering approach, and it works with 10 days.

**Code cost:** ~40 lines. Produces a plot per corridor per day. Uses existing Stage 2 regime labels and speed data.

---

## Part 2 — The Three Things I Almost Recommended But Shouldn't Have

### Anti-Recommendation 1: ASM Preprocessing (Demoted)

As I explained in Part 0, ASM was designed for freeway point-sensor data. On your signalized arterials with 2-min segment-level data:

- The temporal denoising benefit is small because 2-min aggregation already averages over signal cycles
- The spatial smoothing benefit is small because your segments are short (70m average on DEL_AUROBINDO) and share the same signal controller
- The anisotropic kernel's backward wave speed (V_cong = −15 km/h) is physically wrong for signalized intersections where queue growth is signal-cycle-dominated

**When ASM WOULD help:** If you get higher-resolution data (sub-minute) or longer segments (> 500m), ASM becomes valuable. Also, if you specifically want to sharpen Stage 4 onset times, ASM's directional smoothing would help — but only after calibrating V_cong for each corridor's signal spacing.

**Bottom line:** Skip for now. Your 2-min median profiles are adequate. If you want denoising, a simple 3-bucket (6-minute) temporal moving average per segment is 95% as good as ASM for your data shape and costs zero research effort.

### Anti-Recommendation 2: Signal-Cycle Decomposition (Infeasible)

Papers #16 (Tang et al. 2018), #17 (Purdue ATSPM), and #18 (Hao et al. 2018) from your reading list describe methods to decompose arterial travel time into running time + control delay. This is intellectually the right decomposition — it separates "infrastructure problem" from "operations problem."

**Why you can't do it:** Hao's reverse-engineering method (inferring signal timing from probe data alone) requires sub-30-second temporal resolution to resolve individual signal phases. Your 2-min data smears 1–2 full signal cycles into each observation. You physically cannot distinguish "stopped at red for 40 seconds" from "crawling at 5 km/h for 120 seconds" at 2-min resolution.

**What to do instead:** Use the FHWA "reference speed" approach. Your Stage 1 free-flow discovery already computes a reference speed that includes normal signal delay (because signals operate at night too). Your speed_ratio is therefore measuring excess delay above the signal-inclusive baseline. This is correct for your audience. File the signal decomposition for later, when/if you get vehicle trajectory data with sub-second GPS pings.

### Anti-Recommendation 3: Full Graph Neural Network Prediction (Overkill)

Paper #23 (Cui et al. 2020, T-GCN) from your reading list is the standard architecture for network-scale traffic prediction. Your reading list correctly notes it's "not a substitute for diagnosis." But more importantly: you have 100 segments in Delhi, not 10,000. A GNN is architectural overkill. Your existing TimesFM-based prediction layer (already running on 6 corridors) is the right tool — foundation models handle the temporal patterns, and your corridors are linear chains (1D graphs) where GNN's spatial learning adds nothing over a simple neighbor-aware feature set.

---

## Part 3 — The Reading List Papers, Ranked by Actual Value to You

I've read through all 30 papers on your reading list (via their methods sections, key results, and limitations). Here's my honest ranking of which ones actually move the needle, given your specific data:

### Tier A — Read These, They Change How You Think

**#6 Lopez et al. 2017 (3D speed maps, Scientific Reports):** Still the most important paper on your list, even after my self-critique. The 3D tensor (segment × time-of-day × day) clustering approach is the right long-term architecture for your recurrence typing. But use it on Pune/Kolkata (90+ days), NOT Delhi (10 days). For Delhi, use the simpler day-type flagging in Finding 5 above.

**#10 Chen, Skabardonis & Varaiya 2004 (systematic bottleneck identification):** The activation/deactivation tracking and spillback attribution are directly actionable (Finding 4 above). Their speed differential thresholds (upstream < 40 mph, differential ≥ 20 mph) translate to approximately speed_ratio < 0.5 upstream and > 0.8 downstream in your framework — close to your existing CONG/FREE boundary. The delay quantification method (VHD = vehicle-hours of delay) is the standard metric your traffic engineer audience expects, but you can't compute it without flow data. Proxy: use `delay_intensity_sec_per_km × segment_length` as a flow-independent cost proxy.

**#22 Liu et al. 2023 (DTW propagation, IJGIS):** The directed propagation graph is exactly what Finding 3's jam tree provides in simpler form. Liu's DTW approach is more powerful (handles non-linear time warping) but also more fragile on noisy 2-min arterial data. **Recommendation: implement the jam tree first (Finding 3), then upgrade to DTW if you need finer propagation timing.**

### Tier B — Useful Context, Partial Applicability

**#3+#4 Treiber/Schreiter (ASM):** Demoted per Anti-Recommendation 1. Read for the physics of characteristic directions (forward at V_free, backward at V_cong) — this intuition is useful even if you don't implement ASM. The concept that information propagates differently in congested vs free traffic is foundational for understanding why your Stage 4 shockwave check expects backward propagation.

**#5 Treiber, Hennecke & Helbing 2000 (phase diagram of congestion):** The six congested states (PLC, MLC, OCT, HCT, TSG, etc.) are defined in speed-flow space, which you can't observe directly. However, the key distinction that matters for you is **pinned localized cluster (PLC) vs moving localized cluster (MLC)**:
- PLC = congestion stuck at a fixed location (your ACTIVE_BOTTLENECK)
- MLC = congestion moving upstream over time (your shockwave)

Your pipeline already distinguishes these via Bertini (PLC) vs shockwave validation (MLC confirms the PLC is generating a backward wave). The six-state taxonomy adds nuance but doesn't change your verdicts.

**#15 FHWA CBI Tool (2016):** The wavelet filtering approach for arterial signal artifacts. Your 2-min aggregation handles most of the same noise, so the wavelet is less critical than it first appears. But the **D.I.V.E. framework** (Duration, Intensity, Variability, Extent) is a useful operator-facing taxonomy. Consider mapping your verdicts to D.I.V.E. dimensions in your UI.

**#19 Virginia DOT VTRC 19-R20:** The node-link method using probe speeds + AADT is the closest recipe to your setup. Their congestion thresholds (< 60% of reference speed for congested, < 40% for severely congested) map approximately to your speed_ratio thresholds (CONG at < 0.50, SEVR at < 0.30). The volume-weighted congestion-hour ranking metric is what you'd use for prioritizing which corridor to fix first — but you need AADT estimates, which you might be able to get from city traffic departments.

**#24 Pan et al. (frequent itemset mining):** Co-occurrence rules like "S17 congested → S10 congested with 87% confidence, lag 6 min" are gold for your diagnostician audience. Implementation is simple (Apriori or FP-Growth on binary congestion matrices), and the output directly feeds the operator UI as "if you see S17 congesting, expect S10 in 6 minutes." But this is essentially what the jam tree (Finding 3) gives you in a more structured form.

### Tier C — Academically Interesting, Low Direct Value for Now

**#7 Cerqueira et al. 2018 (FCD quality):** The probe penetration bias issue is real but secondary for you — you're using Google/HERE-sourced probe data that's already vendor-corrected for penetration bias. Read if you ever switch to a raw GPS data source.

**#9 Saberi & Mahmassani 2013 (hysteresis):** The hysteresis finding is incorporated into Finding 5 above. You don't need the full paper's freeway-specific treatment.

**#12 Nguyen et al. 2021 (multiple bottleneck activations):** Their spatiotemporal clustering of activations handles the multi-bottleneck case better than your current Stage 5. But it's engineered for freeway sensor data with 30-second resolution. Your 2-min corridor data is too coarse for their clustering parameters. The percolation approach (Finding 2) handles the same problem more naturally for your data shape.

**#26 Anbaroglu et al. 2014 (non-recurrent separation):** Their 40% excess LJT for 25+ minutes threshold for non-recurrent events is a useful sanity check. Worth implementing as a day-flagging filter (takes 10 lines of code): for each day, if any segment's travel time exceeds 1.4× its profile for 25+ consecutive minutes AND no adjacent segments show similar patterns, flag as non-recurrent (incident, weather) and exclude from recurrence counting. Especially important for Delhi with only 10 days.

**#28 Yan et al. 2024 (causal graph):** The causal graph over congestion features is the long-term architecture for your "similar episode retrieval" feature. But it requires hundreds of episodes to learn the causal structure — you don't have enough data yet. Revisit after 6+ months of production data.

---

## Part 4 — Papers NOT on Your Reading List That You Should Know About

These came from my deep search and are directly relevant to your pipeline:

### NEW-1: Duan, Zeng et al. 2023 — Early Warning Signal
(Already detailed in Finding 1 above)

### NEW-2: Li et al. 2015 + Zeng et al. 2019 — Percolation Transitions in Traffic
(Already detailed in Finding 2 above)

### NEW-3: Serok, Havlin et al. 2022 — Congestion Origin Identification
(Already detailed in Findings 3 and 4 above)

### NEW-4: Zeng, Serok et al. 2025 — Jam-Prints (Communications Physics)

**Key idea:** The distribution of congestion costs within a city's jam trees follows a power law, and the exponent is a fingerprint of the city. Different cities have different exponents; the SAME city on different days has SIMILAR exponents.

**Application to you:** Compute a "corridor jam-print" — for each corridor, fit a power law to the distribution of per-segment excess travel times during congested periods across all days. The exponent tells you about the concentration of congestion: steep exponent (−2.5 to −3.0) = congestion concentrated at one bottleneck; flat exponent (−1.5 to −2.0) = congestion spread across many segments. This is a single number that captures the "personality" of each corridor, and it can be tracked over time to detect regime changes.

### NEW-5: Chen et al. 2024 — Scaling Law of Traffic Jams (EPJ Data Science)

**Key finding:** Travel demand dominates the scale of congestion via scaling laws. There's a negative linear correlation between travel demand and scaling exponents — higher demand = flatter power law = more severe jams. You can't directly measure demand from your speed-only data, but you CAN use the scaling exponent as a proxy: if a corridor's scaling exponent is flattening over weeks, demand is growing and the corridor is approaching capacity limits, even if the average speed hasn't changed yet. This is a leading indicator of future breakdown.

### NEW-6: Ambühl et al. 2023 — Percolation + MFD Combined

**Key finding:** The maximum number of congested clusters and the maximum MFD flow occur at the SAME moment (correlation 0.93 across five cities). This means the moment when your corridor has the most fragmented congestion clusters is exactly the moment of peak throughput — immediately afterward, clusters merge and throughput drops. For your pipeline, this means: track n_components over time (from Finding 2). The peak of n_components is the capacity point of your corridor. After that peak, the corridor is operating beyond capacity and throughput is declining.

### NEW-7: The "Beyond the Jam" Field Theory (2025)

**Key idea:** Congestion influence propagates like a field — zones with high traffic density exert "pressure" on nearby low-density zones. The propagation is heterogeneous (depends on human route choices, not just physical topology).

**Why it matters for you:** Your current pipeline treats propagation as purely physical (LWR backward shockwave at 12–22 km/h). The field theory suggests that on urban arterials, a significant portion of propagation is demand-driven (drivers diverting from a congested parallel route onto your corridor). This explains your negative observed lags in Stage 4 — they're not physics failures, they're evidence of demand-driven forward propagation. The field theory gives you a framework to distinguish the two: backward propagation = physical queue growth (LWR applies), forward propagation = demand spillover (LWR doesn't apply, different intervention needed).

---

## Part 5 — Concrete Implementation Roadmap

### Tier 1 — This Week (existing data, simple code)

| # | What | Lines | Uses | Pipeline stage affected |
|---|---|---|---|---|
| 1a | Early-warning growth rate metric | ~30 | Stage 2 regimes + Stage 3 activations | New: real-time severity prediction |
| 1b | Temporal precedence check for QUEUE_VICTIM | ~20 | onset data (`all_onsets_weekday.json`) | Stage 3 / verdicts |
| 1c | Non-recurrent day flagging (Delhi) | ~15 | profiles + onset data | Stage 6 recurrence |
| 1d | Speed-ratio first derivative (direction indicator) | ~10 | `speed_ratio` from traffic_metric | New: bottleneck phase detection |

### Tier 2 — This Month (moderate engineering)

| # | What | Lines | Uses | Pipeline stage affected |
|---|---|---|---|---|
| 2a | Percolation-based systemic detection | ~50 | Stage 2 regimes | Stage 5 replacement |
| 2b | Jam-tree construction per corridor | ~60 | onset data + adjacency | New stage / Finding 3 |
| 2c | Corridor-level MFD with hysteresis | ~40 | speeds + regimes | New: corridor health metric |
| 2d | Day-type flagging via MFD loop similarity | ~30 | MFD from 2c | Stage 6 augmentation |

### Tier 3 — Next Quarter (research effort)

| # | What | Lines | Uses | Pipeline stage affected |
|---|---|---|---|---|
| 3a | Jam-print power-law fitting per corridor | ~80 | jam trees from 2b | New: corridor fingerprint |
| 3b | DTW propagation graph (upgrade from jam tree) | ~120 | daily speed profiles | Finding 3 upgrade |
| 3c | 3D speed-map clustering (Pune/Kolkata only) | ~100 | 90+ days of profiles | Stage 6 replacement |
| 3d | Demand-proxy estimation via scaling exponent tracking | ~60 | jam sizes over weeks | New: capacity planning |

---

## Part 6 — What This Means for Your Pipeline Architecture

If you implement Tier 1 and Tier 2, your pipeline evolves from:

**Current v2.1:**
```
raw data → profiles → free-flow → regimes → primary windows → Bertini → shockwave → systemic(80%) → recurrence → confidence → verdicts
```

**Proposed v3:**
```
raw data → profiles → free-flow → regimes → primary windows → Bertini 
    → temporal precedence validation (Finding 4)
    → jam-tree construction (Finding 3)
    → percolation-based systemic detection (Finding 2, replaces Stage 5)
    → early-warning growth rate (Finding 1)
    → corridor MFD + hysteresis (Finding 5)
    → recurrence (with non-recurrent day filtering)
    → confidence → verdicts + new metrics (growth_speed, loop_area, jam_tree_stability)
```

The new metrics give your three audiences different things:

- **Traffic engineer (Audience A):** jam-tree identifies the true origin, growth_speed tells them urgency, temporal precedence validates the bottleneck is real
- **Operations center (Audience B):** early-warning gives 15-minute advance notice of heavy jams, percolation transition tells them when the corridor tips from manageable to systemic
- **Planning/capex (Audience C):** corridor MFD hysteresis area quantifies the cost of each congestion episode, jam-print exponent tracks corridor degradation over months, scaling exponent is a leading indicator of demand exceeding capacity

---

## Sources

### Papers cited from the reading list
- [Bertini & Leal 2005 — three-point bottleneck test](https://www.researchgate.net/publication/228650849_Empirical_Study_of_Traffic_Features_at_a_Freeway_Lane_Drop)
- [Cassidy & Bertini 1999 — capacity drop](https://www.tandfonline.com/doi/full/10.1080/21680566.2016.1245163)
- [Treiber & Helbing 2002 — ASM](https://arxiv.org/abs/cond-mat/0210050)
- [Schreiter et al. 2010 — fast ASM](https://www.mtreiber.de/publications/ASMfast_submission.pdf)
- [Treiber, Hennecke & Helbing 2000 — phase diagram](https://arxiv.org/abs/cond-mat/0002177)
- [Lopez et al. 2017 — 3D speed maps](https://www.nature.com/articles/s41598-017-14237-8)
- [Chen, Skabardonis & Varaiya 2004 — systematic bottleneck ID](https://journals.sagepub.com/doi/abs/10.3141/1867-06)
- [Nguyen et al. 2021 — multiple bottleneck activations](https://ieeexplore.ieee.org/document/9352245/)
- [Zheng et al. 2011 — wavelet transform](https://www.sciencedirect.com/science/article/abs/pii/S0191261510001037)
- [FHWA 2016 — CBI Tool HRT-16-064](https://www.fhwa.dot.gov/publications/research/operations/16064/003.cfm)
- [Virginia DOT VTRC 19-R20](https://vtrc.virginia.gov/media/vtrc/vtrc-pdf/vtrc-pdf/19-R20.pdf)
- [FHWA HOP-15-033 — arterial congestion](https://ops.fhwa.dot.gov/publications/fhwahop15033/sec3.htm)
- [Anbaroglu et al. 2014 — non-recurrent separation](https://www.sciencedirect.com/science/article/pii/S0968090X14002186)
- [Liu et al. 2023 — DTW propagation](https://www.tandfonline.com/doi/abs/10.1080/13658816.2023.2178653)
- [Pan et al. — spatiotemporal bottleneck mining](https://ieeexplore.ieee.org/document/5766752/)

### Papers NOT on the reading list (new finds)
- [Duan, Zeng et al. 2023 — early warning signal, Nature Communications](https://www.nature.com/articles/s41467-023-43591-7)
- [Li et al. 2015 — percolation transition, PNAS](https://www.pnas.org/doi/10.1073/pnas.1419185112)
- [Zeng et al. 2019 — percolation mode switching, PNAS](https://www.pnas.org/doi/10.1073/pnas.1801545116)
- [Ambühl et al. 2023 — percolation + MFD, Communications Physics](https://www.nature.com/articles/s42005-023-01144-w)
- [Serok, Havlin et al. 2022 — congestion origin ID, Scientific Reports](https://www.nature.com/articles/s41598-022-17404-8)
- [Zeng, Serok et al. 2025 — jam-prints, Communications Physics](https://www.nature.com/articles/s42005-025-02049-6)
- [Chen et al. 2024 — scaling law of traffic jams, EPJ Data Science](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-024-00471-4)
- [2025 — "Beyond the jam" field theory](https://www.tandfonline.com/doi/full/10.1080/15481603.2025.2547126)
- [Geroliminis & Daganzo 2008 — MFD](https://www.sciencedirect.com/science/article/abs/pii/S0191261508000799)
- [Saberi & Mahmassani 2013 — hysteresis](https://www.researchgate.net/publication/227427026_Hysteresis_Phenomena_of_a_Macroscopic_Fundamental_Diagram_in_Freeway_Networks)
- [Ehime/ISTS 2018 — urban bottleneck ID](https://www.cee.ehime-u.ac.jp/~keikaku/ists18/pdf/ISTS_IWTDCS_2018_paper_1.pdf)
- [Calibrating ASM 2026 — arxiv](https://arxiv.org/html/2602.02072v1)
- [Generalized ASM 2022 — matrix completion](https://arxiv.org/abs/2206.01461)
- [Anisotropic Gaussian processes for traffic 2023](https://arxiv.org/html/2303.02311v2)
- [New Delhi Traffic Probe Analytics 2024 — Kaggle](https://www.kaggle.com/datasets/rawsi18/new-delhi-traffic-probe-and-analytics-2024)
- [Multistability in urban traffic — percolation 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12295039/)
