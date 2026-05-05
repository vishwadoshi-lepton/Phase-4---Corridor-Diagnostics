"""Tests for tier1/percolation.py. Spec §15.1."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from data.v3_a import EngineConfig
from data.v3_a.progress import IST
from data.v3_a.tier1 import Context
from data.v3_a.tier1.percolation import (
    Percolation,
    _component_lengths_at_bucket,
    _find_onset,
    _time_to_merge,
    _trace,
)


def _ctx(*, regimes_by_idx, segment_order, segment_meta, anchor_bucket=719):
    cfg = EngineConfig.default()
    return Context(
        corridor_id="TEST",
        corridor_name="Test",
        anchor_ts=datetime(2026, 5, 4, 23, 58, tzinfo=IST),
        anchor_bucket=anchor_bucket,
        today_date=date(2026, 5, 4),
        segment_order=tuple(segment_order),
        segment_meta=segment_meta,
        total_length_m=sum(segment_meta[s]["length_m"] for s in segment_order),
        n_buckets=anchor_bucket + 1,
        regimes_today_by_idx=tuple(tuple(regimes_by_idx[i]) for i in range(len(segment_order))),
        regimes_typical_by_idx=tuple(tuple(regimes_by_idx[i]) for i in range(len(segment_order))),
        bertini_events=(),
        head_bottleneck_events=(),
        primary_windows_today=(),
        historical_onsets_by_seg={},
        today_onsets_by_seg={},
        speed_today_by_idx=tuple(tuple([60.0] * 720) for _ in range(len(segment_order))),
        ff_speed_kmph_by_seg={s: 60.0 for s in segment_order},
        v21_verdicts={s: "FREE_FLOW" for s in segment_order},
        config=cfg,
    )


def _make_regimes(per_seg_per_bucket: list[list[str]]) -> tuple[tuple[str, ...], ...]:
    """Helper: pad each seg list to length 720 with 'FREE'."""
    n_buckets = max(len(seg) for seg in per_seg_per_bucket)
    full: list[tuple[str, ...]] = []
    for seg in per_seg_per_bucket:
        padded = list(seg) + ["FREE"] * (720 - len(seg))
        full.append(tuple(padded))
    return tuple(full)


class TestComponentLengthsAtBucket:
    def test_all_free_returns_empty(self):
        regimes = _make_regimes([["FREE", "FREE"], ["FREE", "FREE"], ["FREE", "FREE"]])
        assert _component_lengths_at_bucket(0, regimes, [100, 100, 100]) == []

    def test_single_component(self):
        regimes = _make_regimes([["FREE"], ["CONGESTED"], ["CONGESTED"], ["FREE"]])
        out = _component_lengths_at_bucket(0, regimes, [50, 100, 200, 50])
        assert out == [300.0]

    def test_two_components_sorted_desc(self):
        regimes = _make_regimes([["CONGESTED"], ["FREE"], ["SEVERE"], ["SEVERE"], ["FREE"]])
        # comp1: 100 (idx 0); comp2: 50+250 = 300 (idx 2,3) — sorted desc
        out = _component_lengths_at_bucket(0, regimes, [100, 999, 50, 250, 999])
        assert out == [300.0, 100.0]

    def test_severe_counts_as_occupied(self):
        regimes = _make_regimes([["SEVERE"], ["CONGESTED"]])
        out = _component_lengths_at_bucket(0, regimes, [100, 200])
        assert out == [300.0]


class TestTrace:
    def test_anchor_bucket_truncates(self):
        regimes = _make_regimes([["CONGESTED", "CONGESTED", "CONGESTED"]])
        lcc, slcc, n2 = _trace(regimes, [100.0], anchor_bucket=1)
        assert len(lcc) == 2  # buckets [0, 1]
        assert len(slcc) == 2

    def test_no_components(self):
        regimes = _make_regimes([["FREE"] * 5, ["FREE"] * 5])
        lcc, slcc, n2 = _trace(regimes, [100, 100], anchor_bucket=4)
        assert lcc == [0.0] * 5
        assert slcc == [0.0] * 5
        assert n2 == 0

    def test_two_components_at_bucket(self):
        # 5 segs, 100m each. Bucket 0: idx 0 CONG, idx 2 CONG → two components
        regimes = _make_regimes([
            ["CONGESTED"], ["FREE"], ["CONGESTED"], ["FREE"], ["FREE"],
        ])
        lcc, slcc, n2 = _trace(regimes, [100.0] * 5, anchor_bucket=0)
        assert lcc == [100.0]
        assert slcc == [100.0]
        assert n2 == 1


class TestFindOnset:
    def test_no_slcc_returns_none(self):
        assert _find_onset([0.0] * 100) is None

    def test_picks_argmax(self):
        slcc = [0.0, 0.0, 100.0, 200.0, 150.0, 0.0]
        assert _find_onset(slcc) == 3  # 200 is max


class TestTimeToMerge:
    def test_merge_detected(self):
        lcc =  [0, 100, 200, 300, 600, 600, 600]
        slcc = [0, 100, 200, 100,   0,   0,   0]
        # onset at b=2: lcc=200, slcc=200 → target = 200 + 100 = 300
        # First b > 2 with slcc=0 and lcc>=300 → b=4 (lcc=600 >= 300)
        # time_to_merge = (4-2)*2 = 4 minutes
        assert _time_to_merge(lcc, slcc, 2) == 4

    def test_no_merge_returns_none(self):
        lcc =  [0, 100, 200, 100, 50, 0]
        slcc = [0, 100, 200, 100,  0, 0]
        # onset at b=2: target=300. After b=2, lcc never reaches 300.
        assert _time_to_merge(lcc, slcc, 2) is None


class TestPercolationModule:
    def test_module_quiet_corridor_no_onset(self):
        regimes = _make_regimes([["FREE"] * 720, ["FREE"] * 720])
        ctx = _ctx(
            regimes_by_idx=regimes,
            segment_order=["s1", "s2"],
            segment_meta={"s1": {"length_m": 100}, "s2": {"length_m": 100}},
        )
        out = Percolation().run(ctx)
        assert out["onset_bucket"] is None
        assert out["onset_minute"] is None
        assert out["summary"]["max_slcc_m"] == 0.0

    def test_module_with_two_clusters(self):
        # Build 5 segs. Bucket 100: two clusters (idx 0 alone, idx 2-3).
        # Bucket 105: clusters merge.
        per = [["FREE"] * 720 for _ in range(5)]
        for b in range(100, 110):
            per[0][b] = "CONGESTED"
            per[2][b] = "CONGESTED"
            per[3][b] = "CONGESTED"
        for b in range(105, 110):
            per[1][b] = "CONGESTED"  # bridges cluster 1 and 2
        regimes = _make_regimes(per)
        ctx = _ctx(
            regimes_by_idx=regimes,
            segment_order=["s0", "s1", "s2", "s3", "s4"],
            segment_meta={s: {"length_m": 100} for s in ["s0", "s1", "s2", "s3", "s4"]},
        )
        out = Percolation().run(ctx)
        # SLCC peaks during 100-104 when there are two distinct clusters.
        assert out["onset_bucket"] is not None
        assert 100 <= out["onset_bucket"] <= 104
        assert out["onset_lcc_m"] == 200.0  # idx 2-3
        assert out["onset_slcc_m"] == 100.0  # idx 0

    def test_module_anchor_bucket_truncates_trace(self):
        per = [["CONGESTED"] * 720]
        regimes = _make_regimes(per)
        ctx = _ctx(
            regimes_by_idx=regimes,
            segment_order=["s0"],
            segment_meta={"s0": {"length_m": 100}},
            anchor_bucket=99,
        )
        out = Percolation().run(ctx)
        assert len(out["lcc_trace_m"]) == 100
        assert len(out["slcc_trace_m"]) == 100
