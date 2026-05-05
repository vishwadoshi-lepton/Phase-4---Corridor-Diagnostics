# Network-Level Deep Dive: What 3000 Connected Segments Actually Unlock

**For:** TraffiCure — moving beyond corridor diagnostics to city-scale intelligence  
**Data shape:** ~3000 connected segments, bidirectional, 2-min median speed/travel-time, speed-only (no flow, no occupancy, no signal timing), 10 days Delhi / 3+ months Pune-Kolkata  
**Date:** 2026-05-01

---

## Part 0 — Self-Critique Before I Start

The corridor pipeline (v2.1) treats each corridor as an isolated chain of segments. That was the right starting point — you validated the physics on 19 corridors across 3 cities with zero tuning. But a corridor is a 1D slice of a 2D network. Here's what corridor-level analysis structurally cannot see:

**It can't see detour effects.** When PUNE_A's S02 bottlenecks, traffic diverts to parallel roads. Those parallel roads slow down. Your corridor pipeline sees PUNE_A getting worse but has no idea whether that's because traffic is *arriving faster* (diversion loading) or because the bottleneck itself is intensifying. These are different problems with different interventions.

**It can't see origin bottlenecks outside the corridor.** If congestion enters your corridor from a perpendicular feeder road, your pipeline sees the first segment go CONG and calls it a HEAD_BOTTLENECK. But the real bottleneck is on the feeder road — outside your corridor chain. Only a network-level view can trace that.

**It can't see cascading failures.** The moment when Delhi goes from "several busy corridors" to "citywide gridlock" is a network-level phase transition. No single corridor's verdict captures it.

**It can't rank interventions.** If you have budget to fix one intersection, which one? You need network-level centrality to answer this. The busiest corridor isn't necessarily the one whose fix yields the most citywide relief — that depends on the network topology.

Now, I also need to be honest about the constraints:

**10 days of Delhi data is thin for ML.** Any model that needs to learn temporal patterns (weekday vs weekend, holiday effects, seasonal variation) will be data-starved. I'll flag which analyses work with 10 days and which need months.

**No flow data is a real limitation.** You cannot build a true Macroscopic Fundamental Diagram without vehicle counts. I'll be explicit about which analyses genuinely work with speed-only and which require hacks or proxies.

**3000 segments is mid-scale.** It's large enough that O(N³) algorithms become slow, but small enough that most graph algorithms run in seconds. I'll note computational constraints where they matter.

---

## Part 1 — The Six Network-Level Analyses That Actually Work With Your Data

Ordered by (impact × implementability × data-readiness). Each one uses only data you already have.

---

### Analysis 1: Percolation on the Full City Network — The "When Does Delhi Break?" Detector

**Why this is #1:** You already validated percolation at corridor level (RESEARCH_DEEP_DIVE, Finding 2). Scaling it to the full 3000-segment network is the single highest-value extension because it answers a question no corridor-level analysis can: *when does the city transition from "several busy corridors" to "systemically gridlocked"?*

**How it works on your network:**

At each 2-min tick *t*:

1. Mark each segment as CONGESTED if `speed_ratio < 0.50` (your existing Stage 2 threshold).
2. Build the subgraph *G_cong(t)* of congested segments, connected by physical adjacency.
3. Compute the **Giant Connected Component (GCC)** — the largest contiguous cluster of congested segments.
4. Track `gcc_fraction(t) = |GCC| / |total_segments|` through the day.

The **percolation transition** is the moment when GCC jumps from a small fraction to a large one. In Li et al. (2015, PNAS) and Zeng et al. (2019, PNAS), this transition is sharp — it behaves like a physical phase transition with a well-defined critical point.

**What you get operationally:**

- **Morning build-up curve:** GCC grows from 0% at 5am to its peak around 9–10am. The *shape* of this curve is diagnostic: a slow linear rise means distributed congestion, a sudden jump means cascading collapse.
- **Critical fraction:** The fraction of congested segments at which GCC suddenly jumps. This is your network's "tipping point." Below it, jams are isolated. Above it, they merge into gridlock. This replaces intuition with physics.
- **Evening comparison:** The evening transition typically has a different shape (Zeng 2019 found cities switch between "continuous" and "discontinuous" percolation modes between morning and evening). This is free additional diagnostic information.
- **Day-over-day stability:** If the critical fraction is stable across your 10 Delhi days, that's a robust finding. If it varies, that tells you which days the network was fragile.

**Visualization:** A percolation diagram — x-axis = fraction of congested segments, y-axis = GCC fraction. You'll see an S-curve with a sharp inflection. The inflection point is your critical threshold.

**Data requirements:** Topology (segment adjacency) + speed at each tick. You have both. 10 days is plenty — you're computing a graph property at each tick, not training a model.

**Code cost:** NetworkX or igraph. ~50 lines. Build `G_cong(t)` at each tick, call `connected_components()`, track the largest. Plot over time.

**Self-critique:** The 0.50 speed_ratio threshold matters. You should sweep it from 0.30 to 0.70 and look at how the critical point shifts. If the transition is sharp at every threshold, the finding is robust. If it smears out, you need to pick the threshold that gives the sharpest transition (this is standard in percolation analysis).

---

### Analysis 2: Congestion Propagation as Epidemic Spreading — "Who Infects Whom?"

**Why this matters:** Your corridor pipeline identifies ACTIVE_BOTTLENECK and QUEUE_VICTIM but only on a 1D chain. On the full network, congestion spreads in 2D — a bottleneck at a junction sends queues down multiple arms simultaneously. Epidemic models on graphs capture exactly this.

**The SIS (Susceptible-Infected-Susceptible) model for traffic:**

Each segment at each tick is in one of two states:
- **Susceptible (S):** speed_ratio ≥ 0.50 (not congested)
- **Infected (I):** speed_ratio < 0.50 (congested)

A susceptible segment becomes infected with probability proportional to the number of its neighbors that are already infected. An infected segment recovers (traffic clears) with some rate. Both rates are *estimated empirically from your data* — not assumed.

**What to estimate from your 10 days:**

1. **Transmission rate β:** For each segment *i* at each tick *t*, if *i* is S at *t* and I at *t+1*, count how many of *i*'s neighbors were I at *t*. Aggregate across all segments and ticks. The fraction of S→I transitions where ≥1 neighbor was I gives you an empirical transmission probability.

2. **Recovery rate γ:** For each segment, measure the average duration of a congestion episode (consecutive ticks in I state). γ = 1 / mean_duration.

3. **Effective reproduction number R₀ = β/γ:** If R₀ > 1, congestion spreads. If R₀ < 1, it self-limits. Track R₀ through the day — it should rise during onset and fall during clearance.

**What you get operationally:**

- **Congestion isochrone maps:** For each day, compute the "time of first infection" for each segment. Plot as a heatmap on the city map. This shows *where congestion starts* and *which direction it spreads*. Morning: expect centripetal spread (periphery → center). Evening: centrifugal (center → periphery).
- **Super-spreader segments:** Segments with the highest empirical transmission rate — segments whose congestion reliably causes neighbors to congest within 2–4 minutes. These are your true network-level bottlenecks, regardless of whether they sit on a named corridor.
- **R₀ as early warning:** When R₀ crosses 1.0 and rising, the network is entering the cascading regime. This is a 2-min-resolution real-time signal.

**Self-critique:** SIS is a simplification — traffic congestion is not truly stochastic like a disease. Congestion propagation is deterministic given demand, signal timing, and geometry. But as a *descriptive* model for "what happened," it's surprisingly effective because it captures the statistical regularity of commuter patterns without requiring demand data. The limitation: it can't distinguish between "B got congested because A infected it" and "B got congested because B's own demand surged at the same time as A's." You need temporal precedence (did A go CONG before B?) to disambiguate, which you can enforce.

**Code cost:** ~80 lines. NetworkX graph + state vector updated per tick. NDlib (network diffusion library) can do the simulation, or roll your own — it's just a loop over ticks.

---

### Analysis 3: Graph Centrality — "Which Segment Matters Most?"

**Three centrality metrics, each tells you something different:**

**A. Betweenness Centrality (BC)**

Counts how many shortest paths (weighted by travel time) pass through each segment. High BC = choke point that many routes depend on. Compute it twice:

- **BC_freeflow:** Weights = free-flow travel times. This is the *structural* importance — purely from geometry and road hierarchy.
- **BC_congested:** Weights = congested-period travel times (e.g., 8–9am average). This is the *stressed* importance — how routes redistribute under congestion.

Segments where BC_congested >> BC_freeflow are *stress absorbers* — roads that become critical only when main routes congest (drivers divert to them). These are your capacity expansion candidates: widening them wouldn't matter normally, but during peak hours they're load-bearing.

Segments where BC_freeflow >> BC_congested are *avoided under stress* — main roads that drivers abandon when congested. These are your signal-timing optimization candidates: they have capacity but drivers don't trust them during peak.

**B. PageRank on the Dual Graph**

Transform your segment network into a dual graph: segments become nodes, two nodes are connected if the corresponding segments share an endpoint (i.e., traffic can flow from one to the other). Run PageRank with the damping factor interpreted as "probability a driver continues forward vs. making a random choice." High-PageRank segments are important not because many paths cross them, but because they're connected to other important segments — the *backbone* of the network.

**C. Eigenvector Centrality**

Similar to PageRank but undirected. Identifies segments that are part of the most-connected cluster of segments. Useful for finding the core spine of the city's road network.

**What you get operationally:** A ranked list of the top 50 most critical segments in Delhi, from three independent perspectives (structural throughput, stressed routing, backbone connectivity). Cross-referencing this with your corridor verdicts tells you which bottlenecks are *locally* bad (corridor-level) vs *systemically* critical (network-level). A segment that's ACTIVE_BOTTLENECK on its corridor AND top-20 in betweenness centrality is a priority fix.

**Data requirements:** Topology + travel times. You have both. BC on 3000 edges runs in <5 seconds with igraph.

**Self-critique:** Betweenness assumes shortest-path routing, which is a reasonable approximation for navigation-app-guided traffic (most Delhi drivers use Google Maps) but not perfect — habit and local knowledge cause deviations. Also, BC doesn't account for road capacity: a narrow lane and a 6-lane highway with the same travel time get equal weight. You could proxy capacity with free-flow speed × segment length, but it's imperfect.

---

### Analysis 4: Community Detection — "Which Parts of Delhi Congest Together?"

**The idea:** Use the time-series correlation of congestion patterns to discover which segments form natural "congestion communities" — groups that tend to congest and clear at the same times, regardless of physical proximity.

**Method:**

1. For each segment, extract the daily speed_ratio profile (720 values per day, 2-min ticks).
2. Compute pairwise Pearson correlation between every pair of segments' average daily profiles. This gives a 3000×3000 correlation matrix.
3. Threshold the correlation matrix (keep edges where |r| > 0.5) to build a **correlation graph**.
4. Run Louvain or Leiden community detection on this correlation graph.

**What falls out:**

- **Synchronous zones:** Groups of 50–200 segments that congest and clear on the same schedule. These are your natural "traffic districts." They may or may not align with administrative boundaries.
- **Corridor discovery:** Your 7 pre-built corridors were hand-picked. Community detection will find the corridors *the network itself* defines — groups of segments that behave as functional units. Some will match your pre-built corridors. Others will reveal corridors you didn't think to look at.
- **Cross-city comparison:** Run the same community detection on Pune and Kolkata. Do cities with similar geometry produce similar community structures? This tests your "zero tuning" principle at network scale.
- **Inter-community edges:** Segments that bridge two communities are *gate segments* — where congestion transfers between zones. These are high-value intervention points.

**Self-critique:** Pearson correlation is linear and doesn't capture lagged relationships (A congests, then B congests 10 minutes later). For lagged discovery, use cross-correlation with a lag window of ±10 ticks (20 minutes) and take the max correlation across lags. This is more expensive (3000² × 20 lag values) but still feasible. Also, with only 10 Delhi days, your correlation estimates will be noisy — consider computing per-day correlation matrices and averaging them.

**Code cost:** ~40 lines for the correlation matrix, ~10 lines for Louvain (python-louvain or networkx.community). The visualization (coloring segments by community on a map) is the most effort but the most impactful deliverable.

---

### Analysis 5: Network Resilience — "What Happens If I Fix One Segment?"

**This is the intervention-planning analysis.** It answers: if you could eliminate congestion on a single segment (by widening, signal optimization, grade separation, etc.), how much would the rest of the network benefit?

**Method (attack/removal simulation):**

1. Compute the average travel time across all segments during peak (say 8:30–9:30am).
2. For each segment *s*, hypothetically set *s*'s travel time to its free-flow value (simulating a "fix").
3. Recompute shortest paths for all O-D pairs and measure the change in total network travel time.
4. Rank segments by the magnitude of improvement they produce.

**Simpler version (if full shortest-path recomputation is too slow):**

1. During peak, compute the GCC of congested segments.
2. For each segment *s* in the GCC, hypothetically remove *s* (set it to free-flow) and recompute GCC.
3. Segments whose removal causes the GCC to *fragment* into disconnected components are **critical links** — they're the bridges holding the congestion cluster together. Breaking these bridges breaks the cascade.

**What you get:** A ranked "intervention priority" list that accounts for network effects. This is dramatically more useful than ranking by corridor-level verdict severity, because a moderate bottleneck at a critical network junction might yield more benefit than a severe bottleneck on a dead-end road.

**Self-critique:** This simulation doesn't account for *induced demand* — if you fix a road, more traffic will route through it, partially negating the benefit. The simulation assumes static demand, which is a first-order approximation. Also, without flow data, you can't estimate how much travel time other segments gain from the fix. You're really measuring *topological criticality*, not *flow-weighted* impact. Still, it's the best you can do without an OD matrix.

---

### Analysis 6: Junction Identification + Signal Analysis from OSM

**This is infrastructure, not analysis — but it unlocks several of the above.**

**Step 1: Extract junctions from OSM**

Use the Overpass API:
```
[out:json];
node["highway"="traffic_signals"](28.4,76.8,28.9,77.4);
out body;
```

This returns all signalized intersections in Delhi. You'll also want:
- `highway=crossing` (pedestrian crossings, often unsignalized)
- `highway=turning_circle` (roundabouts, common in Delhi)
- Junction nodes: any OSM node that is shared by 3+ OSM ways

**Step 2: Match OSM junctions to your segment endpoints**

Your 3000 segments have start/end coordinates. Snap OSM junction nodes to your segment endpoints using nearest-neighbor matching (50m tolerance). This tags each segment with:
- Whether it starts/ends at a signalized intersection
- The junction type (traffic signal, roundabout, uncontrolled)
- The junction degree (3-way T, 4-way cross, 5+ way)

**Step 3: What this unlocks**

- **Signal-proximity analysis:** Do segments adjacent to signalized intersections have systematically different congestion patterns than mid-block segments? (Almost certainly yes — signal delay is the dominant source of urban congestion.)
- **Junction-degree vs bottleneck correlation:** Are 5-way intersections more likely to produce ACTIVE_BOTTLENECK verdicts than 4-way ones? This tests whether your diagnostic verdicts correlate with geometric complexity.
- **Junction-level aggregation of segment verdicts:** Instead of "segment S42 is an ACTIVE_BOTTLENECK," you can say "the Prithviraj Road / Aurobindo Marg junction is a bottleneck" — which is what a traffic engineer actually wants to hear.
- **Phase timing estimation:** Even without OSM signal timing data (which is basically nonexistent), you can *infer* approximate cycle lengths from your speed data. At a signalized intersection, speed oscillates with the signal cycle. With 2-min data you can't resolve individual cycles (typically 90–180s), but you can detect the *variance* — segments near signals will have higher speed variance than mid-link segments.

**Signal timing data availability:** Virtually zero in OSM globally. Less than 1% of signals have `cycle_time` or `green_time` tags. For Delhi, expect zero. Municipal SCADA data would be the source, but access is typically restricted.

**Self-critique:** The 50m snapping tolerance will produce some mismatches, especially where your segment definitions don't align cleanly with OSM way boundaries. Manual spot-checking of 20–30 junctions is essential. Also, OSM data quality in Delhi is variable — coverage of `highway=traffic_signals` is probably 60–80% complete, not 100%.

---

## Part 2 — ML/DL Approaches: Honest Assessment

This section covers what the ML world offers and why most of it is premature for your current data situation.

---

### Approach A: Graph WaveNet / DCRNN / STGCN (Graph Neural Networks)

**What they do:** Learn spatial-temporal patterns on a graph. The adjacency matrix encodes road connectivity. Temporal layers (LSTM, GRU, temporal convolution) capture time patterns. These are the state-of-the-art for traffic forecasting on sensor networks.

**Honest assessment for your data:**

- **Input format is compatible.** GNNs take N×T×F tensors (nodes × timesteps × features). Your speed_ratio, delay_intensity, congestion_score at 2-min ticks map directly.
- **Pune/Kolkata (3+ months, 3000 segments) is viable.** Enough data to train, enough nodes to justify the graph structure. METR-LA benchmark is 4 months / 207 sensors — you have more segments and comparable time span.
- **Delhi (10 days) is NOT viable for training.** You need 4–6 weeks minimum to capture weekly periodicity. With 10 days you'd overfit catastrophically.
- **Transfer from Pune→Delhi doesn't work naively.** The graph structure (adjacency matrix) is different between cities. Adaptive adjacency (Graph WaveNet's approach) learns city-specific spatial correlations, which don't transfer. You'd need to train a temporal encoder on Pune, freeze it, and fine-tune with Delhi's graph — this is active research, not production-ready.
- **The right adjacency matrix matters hugely.** Physical connectivity alone underperforms because urban networks have many connected-but-uncorrelated segments (a highway on-ramp connects to a residential street but their traffic patterns are independent). **Adaptive/learned adjacency** (let the model discover which segment pairs actually correlate) outperforms fixed adjacency by 10–15%. This is Graph WaveNet's key innovation.
- **Compute:** Single A100 or equivalent, 4–12 hours training, <16GB VRAM for 3000 nodes with 24-tick (48-min) input/output windows.

**Verdict:** Train Graph WaveNet on Pune/Kolkata for 15/30/60-min speed forecasting. Use adaptive adjacency. Do NOT attempt on Delhi with only 10 days. This is a Tier 2 project (this month, not this week).

---

### Approach B: Google TimesFM

**What it does:** Foundation model for time-series forecasting. Zero-shot or few-shot. 200M parameters pretrained on 100B+ time points.

**Honest assessment:**

- **Purely temporal, univariate.** Each segment is forecast independently. TimesFM has NO spatial awareness — it doesn't know that segment S42 is adjacent to S43. Neighboring-segment congestion is invisible to it.
- **No published traffic benchmarks.** Google's papers show results on ETT, Weather, ECL datasets. METR-LA/PEMS-BAY results are conspicuously absent. Domain-specific spatial-temporal models (DCRNN, STGCN) consistently outperform purely temporal models on traffic by 10–20% MAE, precisely because spatial propagation matters.
- **But it works with 10 days.** Since it's a foundation model, it doesn't need months of training data. You can forecast today's 8pm traffic from today's 6pm traffic, using just the input context window. This is its killer advantage for Delhi.
- **Inference at scale is feasible.** 3000 independent forecasts × 720 ticks = fast, no graph construction needed.

**Verdict:** Use TimesFM as your Delhi forecasting baseline (you're already doing this in v2.1 prediction layer). But acknowledge it's leaving ~15% accuracy on the table by ignoring spatial structure. For Pune/Kolkata where you have enough data, Graph WaveNet should beat it.

**The best hybrid:** TimesFM per-segment temporal forecast + lightweight XGBoost spatial correction layer (train XGBoost on residuals using neighbor-segment features). This captures spatial spillover without needing a full GNN. Feasible even on 10 Delhi days because XGBoost is sample-efficient.

---

### Approach C: XGBoost / LightGBM with Spatial Features

**The dark horse that often beats deep learning at low data volumes.**

**Feature engineering:**
- Target: speed_ratio of segment *s* at tick *t+k* (k = forecast horizon)
- Features: speed_ratio of *s* at t, t-1, ..., t-5 (last 10 min)
- Neighbor features: speed_ratio of each 1-hop neighbor at t
- 2-hop neighbors: average speed_ratio of 2-hop neighbors at t
- Time features: hour_of_day, day_of_week, is_weekend
- Segment features: free_flow_speed, segment_length, junction_type (from OSM)

**Why it works with 10 days:** Each segment × tick is one training row. 3000 segments × 720 ticks × 10 days = 21.6M rows. That's plenty for tree-based models. XGBoost handles tabular data with mixed features better than neural networks at this scale.

**Benchmarks:** In the academic literature, XGBoost with spatial features typically achieves 85–90% of STGCN's accuracy on traffic forecasting, trains in minutes instead of hours, and requires 10x less data. For the 10-day Delhi case, it will likely *beat* any deep learning model simply because the deep models can't converge with so little data.

**Verdict:** This should be your *first* ML model. Not because it's the best, but because it's the fastest to validate, the most interpretable (feature importance tells you which spatial lags matter), and the strongest baseline. If XGBoost with 2-hop neighbors achieves, say, 12% MAPE on Delhi 30-min forecasting, you know that any fancier model must beat 12% to justify its complexity.

---

### Approach D: LSTM/RNN

**Honest assessment:** Vanilla LSTM/RNN without graph structure is strictly dominated by TimesFM (same idea, better pretrained, zero-shot). LSTM with spatial attention is reinventing DCRNN/STGCN but worse. There is no scenario where a custom LSTM is your best choice. Skip it.

---

## Part 3 — Anti-Recommendations (What NOT To Do)

**1. Don't build a full OD (origin-destination) matrix from probe data.** You don't have individual vehicle traces, you have segment-level aggregates. You cannot track individual trips. Attempting to infer OD patterns from segment speed alone is a research problem, not an engineering task.

**2. Don't train a GNN on Delhi's 10 days.** I've said this twice and I'll say it a third time because the temptation will be strong. The model will memorize the 10 days and produce garbage on day 11.

**3. Don't try real-time signal optimization.** You have no signal timing data, no control interface to the signals, and no per-vehicle trajectory data. Signal optimization requires all three. Your data can *identify* which intersections are problematic, but cannot *optimize* their timing.

**4. Don't chase tensor completion for "filling in missing segments."** Tensor completion (Tucker decomposition, NTF) is theoretically appealing for sparse probe networks — "infer speed on unmonitored segments from monitored neighbors." But with 3000 segments already covered, your network is reasonably dense. The marginal value of inferring the remaining gaps is low compared to the analysis potential of the 3000 you have.

**5. Don't build a digital twin (yet).** A true traffic digital twin requires calibrated demand models, signal timing, turning movements, and validated microsimulation. You don't have any of these. What you CAN build is a *data-driven diagnostic twin* — the six analyses above — which is 80% of the value at 10% of the effort.

---

## Part 4 — Implementation Roadmap

### Tier 1 — This Week (requires only existing data + standard libraries)

| # | Analysis | Input | Output | Lines of code | Library |
|---|----------|-------|--------|---------------|---------|
| 1 | Percolation on full network | Adjacency + speed per tick | GCC curve, critical fraction, percolation diagram | ~50 | NetworkX/igraph |
| 2 | Betweenness centrality (free-flow + congested) | Adjacency + travel times | Ranked segment list, stress-absorber segments | ~30 | igraph |
| 3 | OSM junction extraction | Overpass API query | Junction-tagged segment list | ~40 | requests + geopy |
| 4 | Congestion isochrone map | Adjacency + speed per tick | "Time of first infection" heatmap per day | ~40 | NetworkX + matplotlib |

### Tier 2 — This Month (requires more setup, validation)

| # | Analysis | Prerequisite | Notes |
|---|----------|--------------|-------|
| 5 | Community detection (correlation + Louvain) | Need to compute 3000×3000 correlation matrix | ~2 hours compute time on a laptop |
| 6 | SIS epidemic model fitting | Tier 1 isochrone data | Estimate β, γ, R₀ empirically |
| 7 | XGBoost baseline forecasting | Feature engineering with spatial lags | Delhi 10-day: leave-2-days-out cross-validation |
| 8 | TimesFM + spatial correction ensemble | TimesFM forecasts + XGBoost residual model | Combines temporal + spatial |
| 9 | Network resilience simulation | Tier 1 betweenness + GCC | Sequential removal of top-BC segments |

### Tier 3 — Next Quarter (requires more data or infrastructure)

| # | Analysis | Blocker | Notes |
|---|----------|---------|-------|
| 10 | Graph WaveNet on Pune/Kolkata | Need to structure 3-month data as N×T×F tensor | Training pipeline + GPU |
| 11 | Cross-city community structure comparison | Need Pune/Kolkata full network (not just corridors) | Tests "zero tuning" at network scale |
| 12 | MFD proxy with speed×length production | Need to validate that speed×length correlates with actual flow | Requires comparison with ground-truth flow data from any source |

---

## Part 5 — What The Pipeline Evolution Looks Like

Today: **Corridor Diagnostics v2.1** — 1D chains, physics-based verdicts, city-portable.

Next: **Network Diagnostics v1** — the six analyses above layered on top of corridor verdicts.

The architecture:

```
Layer 0: Data Foundation
  └─ 3000 segments, 2-min speed, OSM junction tags

Layer 1: Corridor Diagnostics (existing v2.1)
  └─ Per-corridor verdicts (ACTIVE_BOTTLENECK, QUEUE_VICTIM, etc.)

Layer 2: Network Graph Analysis (NEW)
  ├─ Percolation: "Is Delhi in gridlock or isolated jams?"
  ├─ Centrality: "Which segments are structurally critical?"
  ├─ Communities: "Which zones congest together?"
  └─ Epidemic model: "Where does congestion originate and how does it spread?"

Layer 3: Network Forecasting (NEW)
  ├─ TimesFM + spatial correction (Delhi, low-data)
  ├─ XGBoost spatial baseline (all cities)
  └─ Graph WaveNet (Pune/Kolkata, data-rich)

Layer 4: Intervention Ranking (NEW)
  └─ Combine centrality + corridor verdicts + resilience simulation
     → "Fix this junction first"
```

The key insight: layers 1 and 2 are complementary, not competing. Corridor verdicts tell you *what's happening on each road*. Network analysis tells you *why it matters to the city*. A segment that's ACTIVE_BOTTLENECK (Layer 1) AND high-betweenness AND a bridge in the percolation GCC (Layer 2) is categorically more important than a segment that's ACTIVE_BOTTLENECK on a dead-end road.

---

## Part 6 — Papers and References

**Percolation on traffic networks:**
- Li, D. et al. (2015). "Percolation transition in dynamical traffic network." *PNAS* 112(3), 669–672.
- Zeng, G. et al. (2019). "Switch between critical percolation modes in city traffic dynamics." *PNAS* 116(1), 23–28.
- Ambühl, L. et al. (2023). "Understanding congestion propagation by combining percolation theory with the macroscopic fundamental diagram." *Communications Physics* 6, 26.

**Graph neural networks for traffic:**
- Li, Y. et al. (2018). "Diffusion convolutional recurrent neural network: Data-driven traffic forecasting." *ICLR 2018*. (DCRNN)
- Wu, Z. et al. (2019). "Graph WaveNet for deep spatial-temporal graph modeling." *IJCAI 2019*.
- Yu, B. et al. (2018). "Spatio-temporal graph convolutional networks." *IJCAI 2018*. (STGCN)

**Network partitioning and MFD:**
- Ji, Y. & Geroliminis, N. (2012). "On the spatial partitioning of urban transportation networks." *Transportation Research Part B* 46(10), 1639–1656.
- Yildirimoglu, M. & Kim, J. (2018). "Identification of communities in urban mobility networks using multi-layer graphs of network traffic." *Transportation Research Part C* 89, 254–267.

**Epidemic models for traffic:**
- Saberi, M. et al. (2020). "A simple contagion process describes spreading of traffic jams in urban networks." *Nature Communications* 11, 1616.

**TimesFM:**
- Das, A. et al. (2024). "A decoder-only foundation model for time-series forecasting." *ICML 2024*.

**Traffic forecasting baselines:**
- Cui, Z. et al. (2020). "Traffic graph convolutional recurrent neural network." *Transportation Research Part C* 117, 102620. (Includes XGBoost baseline comparison)

---

## Part 7 — Final Self-Critique

**What I'm most confident about:** Percolation analysis (Analysis 1) and betweenness centrality (Analysis 3). These are well-established, require only topology + speed, work with 10 days of data, and produce immediately actionable outputs. Implement these first.

**What I'm moderately confident about:** Community detection (Analysis 4) and the epidemic model (Analysis 2). These are methodologically sound but the results need interpretation — communities might not be operationally meaningful, and the SIS model's β/γ estimates from 10 days will have wide confidence intervals.

**What I'm least confident about:** GNN forecasting (Approach A) on your data. The academic benchmarks are overwhelmingly on freeway networks (METR-LA, PEMS-BAY) with clean loop-detector data. Urban arterial networks with probe data, signalized intersections, and turning movements are fundamentally harder. The 10–15% improvement over baselines reported in papers may not materialize on your network. Start with XGBoost. Only invest in GNNs if XGBoost clearly plateaus.

**The meta-question I haven't answered:** What does the *operator* do with network-level intelligence? Your corridor diagnostics has a clear user story: "Show me what's wrong with this road." Network diagnostics needs a different UI — probably a city-level dashboard with a map showing percolation state, community boundaries, and centrality-ranked intervention priorities. That's a design problem, not an algorithm problem, and it's worth thinking about before implementing all six analyses.
