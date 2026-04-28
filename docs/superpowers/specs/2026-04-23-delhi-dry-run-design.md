# Delhi (Sri Aurobindo Marg) dry-run — design

## Goal

Produce the same educational dry-run artifacts for the Delhi corridor
(`DEL_AUROBINDO`, 41 segments on Sri Aurobindo Marg) that exist for Pune and
Kolkata corridors today, covering both the weekday and weekend slices.

Expected outputs (match existing filename convention in `docs/dry_runs/`):
- `DEL_AUROBINDO_dry_run.html` — weekday pass
- `DEL_AUROBINDO_weekend_dry_run.html` — weekend pass
- `DEL_AUROBINDO_compare.html` — side-by-side

## Data situation (verified against dev DB `.97`)

7 consecutive days of `traffic_observation` on all 41 segments:

| date | DOW | hours covered (IST) | status |
|---|---|---|---|
| 2026-04-15 | Wed | 00:00–23:59 | full |
| 2026-04-16 | Thu | 00:00–18:29 | partial (PM missing) |
| 2026-04-17 | Fri | 09:02–23:59 | partial (AM missing) |
| 2026-04-18 | Sat | 00:00–23:59 | full |
| 2026-04-19 | Sun | 00:00–23:59 | full |
| 2026-04-20 | Mon | 00:00–23:59 | full (post-backfill) |
| 2026-04-21 | Tue | 00:00–12:59 | partial (PM missing) |

Per-bucket weekday sample density (sample segment): 720/720 buckets populated,
avg 3.84 / 5 weekdays contribute per 2-min bucket (min 2, max 5). Weekend
pool: 720/720 populated, avg 1.98 / 2. Workable for both slices; R7 confidence
will reflect the sample thinness naturally — no pipeline changes required.

## Approach

**Zero new scripts.** The existing v2.1 scaffolding already handles new
corridors automatically because every runner iterates over
`validation_corridors.json`. The entire Delhi job is:

1. **Add `DEL_AUROBINDO` as a 7th entry in `data/v2_1/validation_corridors.json`.**
   Shape identical to existing entries (`city`, `name`, `chain[]`,
   `total_length_m`, `n_segments`). Each chain entry carries `road_id`,
   `road_name`, `length_m`, `road_class`.

   - `road_id`, `road_name`, `length_m` — pulled from `public.road_segment`
     via one approved read-only query (already completed during design).
   - `road_class` — `public.road_segment` has no `road_class` column on this
     DB. Pipeline doesn't use the field for logic (per `corridor_diagnostics_v2_1.py`
     comment on R2: "we don't have reliable road_class labels yet");
     `run_validation.py` defaults missing values to `"unknown"`.
     For Delhi we label all 41 segments `"Arterial"` as a display value —
     Sri Aurobindo Marg is an arterial in Delhi's network, and this keeps the
     dry-run HTML's class column populated.
   - Chain order preserved from `data/delhi_corridor/delhi_corridor_chain.py`
     (upstream → downstream along the Google polyline).

2. **Run the existing pipeline end-to-end, both slices:**
   ```
   python3 pull_profiles.py  --slice weekday
   python3 pull_profiles.py  --slice weekend
   python3 pull_onsets.py    --slice weekday
   python3 pull_onsets.py    --slice weekend
   python3 run_validation.py --slice weekday
   python3 run_validation.py --slice weekend
   python3 generate_dry_runs.py --slice weekday
   python3 generate_dry_runs.py --slice weekend
   python3 generate_comparison.py
   ```

   Every script reads `validation_corridors.json` at start, so Delhi is
   picked up automatically. No flag or filter needed.

3. **Verify the three Delhi HTML files exist in `docs/dry_runs/` and open
   them.** No additional review pass beyond visual checks.

## Out of scope

- No new profile-builder, runner, or HTML-generator code.
- No refactor of `profiles.py` / `profiles_new.py` / `run_blind_new.py`
  (those are v2 legacy; v2.1 scripts supersede).
- No cross-city validation write-up — that's a separate artifact once all
  three dry runs look reasonable.
- No changes to `corridor_diagnostics_v2_1.py` (the pipeline itself).
- Stage 4 preferred mode vs fallback — whatever `run_validation.py` does
  today for Pune is what we'll get for Delhi. No special handling.

## Risks / caveats

- **Thin data.** 5 weekdays and 2 weekend days vs Pune's 22. Medians over
  ~3–4 samples per 2-min bucket. R7 confidence will be LOW on most Delhi
  verdicts — this is correct behaviour, not a bug, and a useful teaching
  point for the junior engineer reading the artifact.
- **Fragmented segmentation.** 41 segs totalling ~2,900m (avg ~70m per
  segment) vs Pune's 6 segs at 7,122m. The heatstrip will be taller and
  thinner, but `generate_dry_runs.py` handles variable-length chains.
- **`pull_profiles.py` window.** Defaults to `--days 30`. With today at
  2026-04-23 this captures Delhi's full Apr 13 onwards data. The partial
  Apr 13 Monday (starts 10:05 IST) and today (partial, ongoing) will be
  included. These don't materially affect the median; accepting as-is.
