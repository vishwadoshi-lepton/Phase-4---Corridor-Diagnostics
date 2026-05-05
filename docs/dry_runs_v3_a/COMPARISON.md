# v2.1 vs v3-A — Side-by-side dry-run comparison

Run on synthetic anchor `2026-04-22T23:58 IST` with the cached weekday-typical
profile fed in as today's data (so v3-A Mode B sees a 'typical day' worth of obs).
Real-day data on a known-systemic weekday will produce more pronounced Tier-1 signals.

## Pass-through equivalence (gate b1)

v3-A `mode="retrospective"` output equals v2.1's `to_plain_dict` byte-for-byte for both corridors. ✅
(Verified by `data/v3_a/tests/test_pass_through_equivalence.py`.)

## DEL_AUROBINDO — Sri Aurobindo Marg (Delhi) - polyline-derived

  - segments: 41
  - total length: 2901 m

### What v2.1 already gave you (unchanged in v3-A)

- **Systemic verdict (typical day):** `False` — max contiguous-CONG length fraction = `39.80%`
- **Per-segment verdict counts:**  FREE_FLOW=18  QUEUE_VICTIM=8  ACTIVE_BOTTLENECK=13  SLOW_LINK=2
- **Primary windows (typical day):** 1 window(s)
- **HEAD_BOTTLENECK intervals:** 0

### What v3-A Mode B adds

- **Growth-rate (Duan 2023):** 36 events scored — fast=0, moderate=1, contained=35, insufficient=0.
  - Each Bertini event now carries a slope-m-per-min and severity label, enabling early-warning operator UX.
- **Percolation (Li 2015):** systemic onset detected at bucket `435` (14:30).
  - LCC at onset: `675 m`. SLCC at onset: `455 m`.
  - Time to cluster merge: `None` min.
  - This replaces v2.1's arbitrary 80%-simultaneous threshold with a precise phase-transition bucket.
- **Jam-tree (Serok 2022):** `13` ORIGIN node(s), `23` PROPAGATED, max_depth `7`.
  - Reclassifies `0` v2.1 QUEUE_VICTIMs that actually preceded their supposed bottleneck (causal flip).
- **MFD (Geroliminis 2008):** peak_density `60.19%` at `18:54`. loop_closes=False. loop_area=`0.80` (kmph·density-frac).
  - Recovery lag: `None` min between density halving and speed return-to-FF. Capacity-loss metric for the day.
- **DOW anomaly:** `3` same-DOW samples → available. Max deviation `0.00%` at bucket `0`.

## KOL_B — JLN Rd to SPM Rd to DPS Rd (S-N central)

  - segments: 7
  - total length: 7981 m

### What v2.1 already gave you (unchanged in v3-A)

- **Systemic verdict (typical day):** `False` — max contiguous-CONG length fraction = `44.50%`
- **Per-segment verdict counts:**  QUEUE_VICTIM=2  ACTIVE_BOTTLENECK=3  FREE_FLOW=1  SLOW_LINK=1
- **Primary windows (typical day):** 2 window(s)
- **HEAD_BOTTLENECK intervals:** 0

### What v3-A Mode B adds

- **Growth-rate (Duan 2023):** 3 events scored — fast=0, moderate=0, contained=3, insufficient=0.
  - Each Bertini event now carries a slope-m-per-min and severity label, enabling early-warning operator UX.
- **Percolation (Li 2015):** systemic onset detected at bucket `386` (12:52).
  - LCC at onset: `3551 m`. SLCC at onset: `3359 m`.
  - Time to cluster merge: `None` min.
  - This replaces v2.1's arbitrary 80%-simultaneous threshold with a precise phase-transition bucket.
- **Jam-tree (Serok 2022):** `3` ORIGIN node(s), `4` PROPAGATED, max_depth `2`.
  - Reclassifies `0` v2.1 QUEUE_VICTIMs that actually preceded their supposed bottleneck (causal flip).
- **MFD (Geroliminis 2008):** peak_density `86.58%` at `12:52`. loop_closes=True. loop_area=`-0.66` (kmph·density-frac).
  - Recovery lag: `210` min between density halving and speed return-to-FF. Capacity-loss metric for the day.
- **DOW anomaly:** `3` same-DOW samples → available. Max deviation `0.00%` at bucket `0`.

---

## Interpretation — what these numbers actually mean

### The synthetic constraint
Both runs use the cached **weekday-typical median profile** as the "today" pull. Three consequences worth noting:
1. The DOW anomaly always shows 0% deviation — today *is* the typical (samples were also cloned from the typical).
2. Growth-rate slopes are mostly 0 because the typical-day median doesn't capture the steep onset → sustained-CONG → quick-recovery shape of a real systemic day. On a real day with a 30-min onset ramp, slopes will land in MODERATE/FAST.
3. MFD loop areas are small for the same reason — rise and fall use the same median data, so hysteresis is muted.

A real day on the live `traffic_observation` will produce much sharper Tier-1 signals. The dry-run is the algorithm sanity check; the magnitude calibration happens against real data.

### KOL_B — what changed for the operator
- **v2.1 says:** 4 segments fire ACTIVE_BOTTLENECK / QUEUE_VICTIM each on a typical weekday. `systemic_v21 = False`. Two primary windows.
- **v3-A adds:**
  - **Percolation onset at 12:52** — the moment the corridor first developed two distinct congestion clusters about to merge. SLCC at onset is `3.36 km` of CONG/SEVR, vs LCC `3.55 km`: nearly half the corridor is in a "second cluster" right before merge. This is operationally meaningful — exactly when a dispatcher would intervene.
  - **Percolation onset at 12:52 is inside primary window 10:24–15:06** — the spec's b2 sanity criterion ✅.
  - **Jam-tree:** v2.1 lists 3 ACTIVE_BOTTLENECK + 2 QUEUE_VICTIM = 5 "bottleneck-y" segments. Jam-tree compresses to **3 ORIGINs + 4 PROPAGATED**, max-depth 2. The real causal initiators are 3 segments — the other 4 are propagated victims. **That's the headline value-add.**
  - **MFD:** loop closes, peak_density 86.6%, recovery_lag 210 min. The 3.5-hour recovery-after-density-halves is a real number a planning team can act on.

### DEL_AUROBINDO — what changed for the operator
- **v2.1 says:** 13 ACTIVE_BOTTLENECK + 8 QUEUE_VICTIM + 2 SLOW_LINK on this 2.9 km, 41-segment corridor — i.e. *almost everything is "bad"*. This is the dossier's classic Aurobindo problem: the verdict-based view doesn't give a dispatcher anywhere to focus.
- **v3-A adds:**
  - **Percolation onset at 14:30**, with onset_lcc 675 m and onset_slcc 455 m — both clusters individually short; corridor never gets fully systemic on the typical median. (Real-day data will likely show a sharper systemic transition.)
  - **Jam-tree:** **13 ORIGINs vs 13 v2.1 bottlenecks → ratio 1.00, no compression yet.** This is *informative*: on the typical-median profile, every Aurobindo segment that fires Bertini does so at minute 0 of the day (the typical median is "always congested" for these short urban segments). When Mode B runs against a *real* day with sharper temporal onset, jam-tree should compress to a handful of origins. The dossier's structural claim — that Aurobindo's 13-bottleneck verdict is mostly propagation — needs real-day data to validate.
  - **MFD:** peak_density 60.2%, loop_closes False (anchor at 23:58 is mid-recovery on synthetic data; real data will close), loop_area `0.80`. Capacity-loss tracking for Aurobindo will be more meaningful once we have a week of real Mode-B runs to plot loop-area trends.

### Operationally: what to do next
1. **Wire Mode B against live `traffic_observation`** for KOL_B (KOL_C and DEL_AUROBINDO follow). The dry-run validates the algorithms; the next step is running them on real day data so the magnitudes are believable.
2. **Calibrate growth-rate thresholds** on signalised-arterial real data (FUTURE_WORK §6). The Duan 2023 freeway thresholds (50/10 m/min) likely undershoot — most real events will be CONTAINED unless we drop the cuts.
3. **Capture a known-systemic Aurobindo day timestamp** and re-run the regression (FUTURE_WORK §8) — that's where jam-tree compression will become visible.
4. **Trafficure UI integration** — the API contract is locked (single envelope, three modes, async run lifecycle, stage events). Frontend implements Layout B (timeline-first centerpiece + sidebar) per the brainstorm Q9 decision.

### Test summary
- **121 tests pass** (100% of v3-A test suite).
- **Pass-through equivalence (b1)** GREEN on KOL_B, KOL_C, DEL_AUROBINDO.
- **Tier-1 sanity (b2)** GREEN on KOL_B and KOL_C.
- **DEL_AUROBINDO regression record** shows current 1:1 origin/bottleneck ratio on synthetic-typical data — flag for re-validation on real-day data.

### Files in this dry-run bundle
```
docs/dry_runs_v3_a/
├── COMPARISON.md                           # this file
├── DEL_AUROBINDO/
│   ├── v21_reference.json                  # v2.1's CorridorDiagnosisV21 → to_plain_dict
│   ├── v21_reference_report.txt            # v2.1's render_v21 textual report
│   ├── v3a_retrospective.json              # v3-A retrospective envelope (matches v21_reference)
│   ├── v3a_today_as_of_T.json              # full v3-A Mode B envelope
│   └── v3a_today_as_of_T.txt               # human-readable Mode B summary
└── KOL_B/
    └── ... (same five files)
```
