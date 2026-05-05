# `data/v3_a/` — Corridor Diagnostics v3-A

Corridor-deep extension of v2.1. Adds **Mode B** (point-in-time diagnostics anchored at any past or current timestamp) and **four research-grounded Tier-1 modules** layered on top of v2.1's six stages:

1. **Growth-rate** (Duan et al. 2023) — first-15-min cluster growth slope per Bertini event.
2. **Percolation-on-corridor** (Li 2015 / Zeng 2019 / Ambühl 2023) — LCC/SLCC trace, systemic onset bucket.
3. **Jam-tree + temporal precedence** (Serok 2022 / Duan 2023) — causal origin vs propagated victim.
4. **MFD with hysteresis** (Geroliminis & Daganzo 2008 / Saberi 2013) — speed-density loop, capacity-loss area.

Plus a self-gating **DOW anomaly track** (today-vs-same-DOW typical, surfaced when N≥3 samples).

## Spec

Single source of truth: [`docs/superpowers/specs/2026-05-04-corridor-diagnostics-v3a-design.md`](../../docs/superpowers/specs/2026-05-04-corridor-diagnostics-v3a-design.md). Every threshold, error code, file path, and validation criterion lives there.

## Quick start

```python
from data.v3_a.api import submit_run, wait_for_run

run_id = submit_run("KOL_B", "2026-05-04T19:00:00+05:30", mode="today_as_of_T")
record = wait_for_run(run_id, timeout_sec=60)
envelope = record.result    # the unified output envelope (spec §9)
```

CLI:

```bash
python -m data.v3_a.cli --corridor KOL_B --anchor "2026-05-04T19:00:00+05:30" --out diag.json
```

## Modes

- `today_as_of_T` (default) — runs v2.1 baseline + Tier-1 on today's data up to anchor T.
- `retrospective` — reproduces v2.1's classic 22-weekday diagnostic byte-for-byte. Used for the b1 pass-through equivalence gate; not exposed via the CLI by default.
- `live_snapshot` — reserved (Mode A). Raises `ModeNotImplemented`.

## Validation gates

- **b1 pass-through equivalence** — `tests/test_pass_through_equivalence.py`. Mode `retrospective` output must match v2.1's `to_plain_dict` byte-for-byte (after key normalisation) on KOL_B / KOL_C / DEL_AUROBINDO.
- **b2 Tier-1 sanity** — `tests/test_tier1_sanity.py`. KOL_B and KOL_C must produce non-trivial Tier-1 output.

```bash
python3 -m pytest data/v3_a/tests/ -v
```

## Layout

```
data/v3_a/
├── __init__.py            # EngineConfig + ENGINE_VERSION
├── errors.py              # Hard error classes + soft-warning code constants
├── progress.py            # RunStatus, StageEvent, RunRecord, ProgressEmitter
├── data_pull.py           # SQL queries + connection helper + gap detection
├── baseline.py            # 22-weekday baseline assembly + DOW samples
├── stages_v21.py          # Wrappers around v2.1 stages with anchor semantics
├── regime_today.py        # Today's bucketized regimes from today's TTs + ff_tt
├── dow_anomaly.py         # Same-DOW deviation track
├── envelope.py            # Unified output envelope assembly
├── cache.py               # In-memory CacheKey/Cache with TTL semantics
├── api.py                 # submit_run / get_run / list_runs / stream_events
├── run.py                 # The synchronous orchestrator
├── cli.py                 # python -m data.v3_a.cli
├── tier1/
│   ├── __init__.py        # Tier1Module ABC + module registry + run_all
│   ├── growth_rate.py
│   ├── percolation.py
│   ├── jam_tree.py
│   └── mfd.py
└── tests/                 # pytest suite (14 modules, ~125 tests)
```

## What v3-A is NOT

- No network-level analysis. No 3000-segment Delhi graph. (→ v3-B)
- No live-snapshot mode. (→ Mode A in [`FUTURE_WORK.md`](../../docs/CORRIDOR_DIAGNOSTICS_V3A_FUTURE_WORK.md))
- No prediction layer.
- No new database tables, no scheduled workers, no daily extraction crons.
- No frontend code (only the API contract).

## Key design rules

- v2.1 (`data/v2_1/`) is **byte-identical** before and after v3-A — all modifications happen in `data/v3_a/`.
- Tier-1 modules are independent: each one is a self-contained file, registered with `tier1/__init__.py`. Adding a fifth module is a 1-file PR.
- Soft errors → run completes with `meta.partial = true`. Hard errors → run fails.
- Cache: 5-min TTL on today anchors; infinite for replay.
