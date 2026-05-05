"""DEL_AUROBINDO regression record (informational). Spec §14.3.

Asserts that jam-tree compresses v2.1's ACTIVE_BOTTLENECK + HEAD_BOTTLENECK count
into a smaller (or at least equal) jam-tree ORIGIN count on the same day. Records
the ratio for tracking compression quality.

This test does NOT gate the v3-A milestone — it's a regression record so we can
notice if compression degrades over time.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from data.v3_a.api import _reset_for_tests, submit_run, wait_for_run
from data.v3_a.baseline import BaselineResult, DowSamples
from data.v3_a.data_pull import Row, TodayPull
from data.v3_a.progress import IST, RunStatus


REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES = REPO_ROOT / "data" / "v2_1" / "profiles" / "all_profiles_weekday.json"
ONSETS = REPO_ROOT / "data" / "v2_1" / "onsets" / "all_onsets_weekday.json"
CORRIDORS = REPO_ROOT / "data" / "v2_1" / "validation_corridors.json"


@pytest.fixture(autouse=True)
def reset():
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_aurobindo_jam_tree_compression():
    if not PROFILES.exists():
        pytest.skip("missing profiles cache")
    with open(CORRIDORS) as f:
        c = json.load(f)
    if "DEL_AUROBINDO" not in c:
        pytest.skip("DEL_AUROBINDO not in validation_corridors")
    cor = c["DEL_AUROBINDO"]
    seg_ord = [s["road_id"] for s in cor["chain"]]
    with open(PROFILES) as f:
        all_p = json.load(f)
    profile_by_seg = {rid: {int(k): int(v) for k, v in all_p[rid].items()}
                       for rid in seg_ord if rid in all_p and all_p[rid]}
    if len(profile_by_seg) < len(seg_ord):
        pytest.skip("partial profile data for DEL_AUROBINDO")
    with open(ONSETS) as f:
        all_o = json.load(f)
    rid_set = set(seg_ord)
    raw_onsets = [(r["rid"], r["dt"], int(r["om"])) for r in all_o if r["rid"] in rid_set]

    baseline = BaselineResult(
        profile_by_seg=profile_by_seg, n_actual_days=22,
        distinct_days=[date(2026, 4, 1)] * 22, thin=False,
    )
    anchor = datetime(2026, 4, 22, 23, 58, tzinfo=IST)
    day_start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [
        Row(seg, day_start + timedelta(minutes=mod), float(tt))
        for seg, by_min in profile_by_seg.items() for mod, tt in by_min.items()
    ]
    today_pull = TodayPull(rows=rows, by_seg={s: [r for r in rows if r.road_id == s] for s in seg_ord}, gap_warnings=[])
    dow_samples = DowSamples({s: {date(2026, 4, 1): profile_by_seg[s], date(2026, 4, 8): profile_by_seg[s], date(2026, 4, 15): profile_by_seg[s]} for s in seg_ord},
                             [date(2026, 4, 1), date(2026, 4, 8), date(2026, 4, 15)], 3, 2, True)

    run_id = submit_run(
        "DEL_AUROBINDO", anchor, mode="today_as_of_T",
        baseline_override=baseline, today_pull_override=today_pull,
        dow_samples_override=dow_samples, raw_onsets_override=raw_onsets,
    )
    rec = wait_for_run(run_id, timeout_sec=60)
    assert rec.status == RunStatus.COMPLETED, f"failed: {rec.error}"

    payload = rec.result["payload"]
    verdicts = payload["stages_v21"]["verdicts"]
    n_v21_bottlenecks = sum(1 for v in verdicts.values() if v in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK"))
    n_origins = payload["tier1"]["jam_tree"]["summary"]["n_origins"]
    n_propagated = payload["tier1"]["jam_tree"]["summary"]["n_propagated"]

    print(f"\n=== DEL_AUROBINDO compression ===")
    print(f"  v2.1 ACTIVE_BOTTLENECK + HEAD_BOTTLENECK: {n_v21_bottlenecks}")
    print(f"  v3-A jam_tree ORIGIN nodes:               {n_origins}")
    print(f"  v3-A jam_tree PROPAGATED nodes:           {n_propagated}")
    if n_v21_bottlenecks > 0:
        print(f"  compression ratio (origins / bottlenecks): {n_origins / n_v21_bottlenecks:.2f}")

    # Soft expectation: ORIGINs should be no more than the v2.1 bottleneck count
    # (jam-tree never invents more bottlenecks than v2.1 saw). Compression > 1
    # would indicate a bug, not a feature.
    assert n_origins <= max(n_v21_bottlenecks, 1), \
        "jam-tree produced more origins than v2.1 bottlenecks — investigate"
