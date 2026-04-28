# v2.1 Prediction Layer — Quickstart

Short-horizon (90 min) traffic now-cast on top of the v2.1 diagnostic pipeline. Uses Google Research **TimesFM 2.5** fused with v2.1's verdict and onset distribution.

**Full design doc:** `docs/CORRIDOR_PREDICTION_V1_DESIGN.md` — read that before extending.

## Run it

```bash
# one-time: install deps
pip3 install --user numpy pandas torch
pip3 install --user "git+https://github.com/google-research/timesfm.git"

# 1. held-out-day traces (synthetic; deterministic)
python3 -m data.v2_1.predict.synthetic_day

# 2. precompute forecasts  (~28 min CPU with TimesFM, ~2 s baseline)
python3 -m data.v2_1.predict.precompute            # TimesFM if available
python3 -m data.v2_1.predict.precompute --baseline # force statistical baseline

# 3. render HTML replays
python3 -m data.v2_1.predict.render_replay

# 4. view
open ../../../docs/replay/index.html
```

## Files

| File | Role |
|---|---|
| `config.py` | Tunables, paths, anchor tick generator |
| `data_loader.py` | Load corridors / profiles / onsets / v2.1 diagnosis |
| `synthetic_day.py` | Deterministic held-out-day traces (swap for Postgres pull in prod) |
| `live_context.py` | C2 context assembly: history days + today-so-far |
| `forecaster.py` | `TimesFMForecaster` + `StatisticalBaselineForecaster` |
| `regime_mapper.py` | tt_sec → FREE / APPROACHING / CONGESTED / SEVERE |
| `fusion.py` | Reconcile TimesFM forecast with v2.1 prior |
| `precompute.py` | Orchestrator — batched inference per (date, anchor) |
| `render_replay.py` | Self-contained HTML per (corridor, date) |

## Outputs

- `held_out_days.json` — synthetic 2-min traces
- `forecasts/*.json` — per (corridor, date), all anchors
- `docs/replay/*.html` — the operator-facing replay pages

See the design doc for data shapes, UI semantics, fusion rules, limitations, and the roadmap.
