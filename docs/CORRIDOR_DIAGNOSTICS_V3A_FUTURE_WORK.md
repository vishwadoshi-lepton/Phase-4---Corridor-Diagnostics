# Corridor Diagnostics v3-A — FUTURE WORK

Items deliberately deferred from v3-A's MVP. Order is rough sequencing, not strict dependency.

## 1. Mode A — live snapshot

A fourth mode (`mode = "live_snapshot"`) returning ONLY:
- current-bucket regimes per segment,
- current-bucket percolation state (LCC / SLCC at the latest bucket),
- active growth-rate events with `t0 >= now() - 30min`.

No historical baselines used. Useful for low-latency dashboard polling.

**Implementation:** a thin orchestrator path in `run.py` that runs `regime_today` (last bucket only) + `tier1.percolation` (last bucket only) + a filtered `tier1.growth_rate`. Same envelope, different `mode` discriminator.

**Why deferred:** Mode B already covers the operator-facing "what's happening now" answer. Mode A is a perf optimisation for high-poll surfaces and is only needed if Trafficure starts hitting `today_as_of_T` more than once per minute per corridor.

## 2. Tier-1 #5 — Scaling exponent

**Paper:** Chen et al. 2024, Zeng et al. 2025.

**Concept:** Power-law fit on per-segment delay distributions across multiple weeks. Exponent steepness over time is a leading indicator that demand is approaching corridor capacity.

**Required data:** ≥4 weeks of trailing daily delay distributions per corridor.

**Why deferred:** Delhi's `traffic_observation` history is currently ~10 days for DEL_AUROBINDO; the trend signal is statistical noise on that horizon. Activate first on Pune/Kolkata (≥90 days available). For Delhi, wait until ≥4 weeks of history accumulate.

**How to enable:** drop `tier1/scaling_exponent.py` into the registry (after MFD). One-file PR.

## 3. v3-B — Network-level analysis (the city-wide step)

The "Axis B" promise from brainstorm Q1. Move from per-corridor to the full Delhi 3000-segment graph.

### 3.1 Build the registry

- `data/v3_b/network/build_registry.py` — query `road_segment` for `tag = 'Delhi'` AND `has_recent_traffic_observation`, persist `delhi_segments.json` (3000 entries with geometry, length, road_class).
- Endpoint-snapping (≤30 m tolerance, like `data/delhi_corridor/find_corridor.py`) to derive `delhi_edges.json` adjacency list.

### 3.2 Network orchestrator

- `data/v3_b/run_network.py` — parallel to v3-A's `run.py` but takes the full registry instead of one corridor.
- Reuses `data_pull.py`, `cache.py`, `progress.py`, `envelope.py` (with `mode = "network"`).

### 3.3 Network-tier modules

- **Percolation across the city** — GCC/SLCC on the 3000-segment graph instead of a 1-D chain. Tipping-point alarm for systemic gridlock.
- **Dual betweenness centrality** — free-flow BC vs congested-period BC. Identifies "stress absorbers" and "abandoned routes."
- **Community detection** — Louvain on segment-pair speed correlation → reveals functional corridor structure independent of hand-built corridors.
- **Epidemic SIS model** — fits β/γ from regime transitions, identifies super-spreader segments.
- **Network resilience simulation** — for each segment, hypothetically free-flow it, recompute network shortest paths, rank by total delay reduction.

The Tier-1 ABC from `data/v3_a/tier1/__init__.py` carries forward, but the modules themselves do NOT — 1-D-chain assumptions in growth-rate / jam-tree / percolation-on-corridor / MFD don't transfer to a graph. New `tierN/` (network-tier) folder.

## 4. Persistent cache

Replace in-memory `Cache` with a Redis or Postgres-backed implementation when run frequency justifies it. Same `CacheKey` interface; just a swap-in.

## 5. HTTP wrapper for the API

A small FastAPI/Starlette app exposing `submit_run` / `get_run` / `stream_events` (SSE) under `/v3a/*`. Frontend integration target. Not part of v3-A core.

## 6. Per-corridor calibration of growth-rate thresholds

Duan 2023's 50/10 m/min thresholds were calibrated on freeway data. Signalised arterials behave differently — congestion grows in shorter, more episodic bursts.

**Action:** once we have ≥4 weeks of validated KOL_B / KOL_C / DEL_AUROBINDO Mode-B runs, fit corridor-specific thresholds on the empirical slope distribution, persist as JSON next to each corridor's entry in `validation_corridors.json`.

## 7. Real per-day Trafficure UI integration

The v3-A spec defines the API contract (`POST /v3a/run`, `GET /v3a/run/:id`, SSE events). The frontend implementation — single page, three modes (Retrospective / Today / Replay), two-column layout (timeline-first centerpiece + sidebar) — is owned by the Trafficure UI team and is out of scope for the v3-A backend milestone.

## 8. Ground-truth validation on real systemic days

The Tier-1 sanity gate currently runs on synthetic-typical-day data (the cached weekday median). Once Trafficure ops captures a known systemic-day timestamp on KOL_B / KOL_C / DEL_AUROBINDO, switch the gate to run against that real day's data and tighten the MFD `loop_area` and growth-rate thresholds. This is the first ground-truth calibration step.
