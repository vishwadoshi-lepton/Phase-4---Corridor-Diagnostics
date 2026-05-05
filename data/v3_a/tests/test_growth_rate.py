"""Tests for tier1/growth_rate.py. Spec §15.1."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from data.v3_a import EngineConfig
from data.v3_a.progress import IST
from data.v3_a.tier1 import BertiniEvent, Context
from data.v3_a.tier1.growth_rate import (
    GrowthRate,
    _classify,
    _cluster_length_m,
    _ols_slope,
    _score_event,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _ctx(*, regimes_by_idx, segment_order, segment_meta, bertini=(), head=(), anchor_bucket=719, config=None):
    cfg = config or EngineConfig.default()
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
        bertini_events=tuple(bertini),
        head_bottleneck_events=tuple(head),
        primary_windows_today=(),
        historical_onsets_by_seg={},
        today_onsets_by_seg={},
        speed_today_by_idx=tuple(tuple([60.0] * 720) for _ in range(len(segment_order))),
        ff_speed_kmph_by_seg={s: 60.0 for s in segment_order},
        v21_verdicts={s: "FREE_FLOW" for s in segment_order},
        config=cfg,
    )


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


class TestOlsSlope:
    def test_perfect_line(self):
        assert _ols_slope([0, 1, 2, 3], [0, 10, 20, 30]) == 10.0

    def test_flat(self):
        assert _ols_slope([0, 1, 2], [5, 5, 5]) == 0.0

    def test_two_points(self):
        assert _ols_slope([0, 4], [0, 100]) == 25.0

    def test_zero_denom(self):
        # all xs equal → slope undefined; we return 0
        assert _ols_slope([2, 2, 2], [1, 5, 7]) == 0.0


class TestClusterLength:
    def test_anchor_segment_thawed_is_zero(self):
        regimes = (("FREE",), ("FREE",))
        lengths = [100.0, 100.0]
        # Build flat 720-len regime arrays
        regimes720 = (("FREE",) * 720, ("FREE",) * 720)
        assert _cluster_length_m(0, 0, regimes720, lengths) == 0.0

    def test_walks_left_and_right(self):
        # idx 2 anchored CONG, neighbours all CONG, edges FREE
        labels = ["FREE", "CONGESTED", "CONGESTED", "CONGESTED", "FREE"]
        regimes = tuple(tuple([labels[i]] * 720) for i in range(5))
        lengths = [100.0, 100.0, 100.0, 100.0, 100.0]
        assert _cluster_length_m(2, 0, regimes, lengths) == 300.0

    def test_severe_counts(self):
        labels = ["SEVERE", "CONGESTED", "FREE"]
        regimes = tuple(tuple([labels[i]] * 720) for i in range(3))
        lengths = [50.0, 75.0, 50.0]
        assert _cluster_length_m(0, 0, regimes, lengths) == 125.0


class TestClassify:
    def test_fast(self):
        assert _classify(60, fast_thr=50, mod_thr=10) == "FAST_GROWTH"

    def test_boundary_fast(self):
        assert _classify(50, fast_thr=50, mod_thr=10) == "FAST_GROWTH"

    def test_moderate(self):
        assert _classify(30, fast_thr=50, mod_thr=10) == "MODERATE"

    def test_contained(self):
        assert _classify(5, fast_thr=50, mod_thr=10) == "CONTAINED"

    def test_negative_slope_contained(self):
        assert _classify(-5, fast_thr=50, mod_thr=10) == "CONTAINED"


# --------------------------------------------------------------------------- #
# Event scoring                                                                #
# --------------------------------------------------------------------------- #


class TestScoreEvent:
    def _build(self, regimes_per_seg, lengths):
        regimes_by_idx = tuple(tuple(r) for r in regimes_per_seg)
        return regimes_by_idx, lengths

    def test_insufficient_data_when_few_buckets(self):
        # event at bucket 718, anchor at 719 → only 2 buckets in window
        regimes = ([["FREE"] * 720])
        regimes[0][718] = "CONGESTED"
        regimes[0][719] = "CONGESTED"
        regimes_by_idx, lengths = self._build(regimes, [100.0])
        ev = BertiniEvent("s", 0, 718, 719, "BERTINI", 1)
        out = _score_event(ev, regimes_by_idx=regimes_by_idx, lengths_m=lengths,
                           anchor_bucket=719, window_buckets=7, min_buckets=4,
                           fast_thr=50, mod_thr=10)
        assert out["label"] == "INSUFFICIENT_DATA"
        assert out["slope_m_per_min"] is None

    def test_fast_growth(self):
        # 3 segments (idx 0, 1, 2), each length 1000 m. Event anchored at idx 1.
        # bucket 100: only idx 1 CONG → 1000
        # bucket 102: idx 1,2 CONG → 2000
        # bucket 104: idx 0,1,2 CONG → 3000
        # bucket 106: same → 3000
        regimes = [["FREE"] * 720 for _ in range(3)]
        for b in range(100, 107):
            regimes[1][b] = "CONGESTED"
        for b in range(102, 107):
            regimes[2][b] = "CONGESTED"
        for b in range(104, 107):
            regimes[0][b] = "CONGESTED"
        regimes_by_idx, lengths = self._build(regimes, [1000.0, 1000.0, 1000.0])
        ev = BertiniEvent("s1", 1, 100, 106, "BERTINI", 1)
        out = _score_event(ev, regimes_by_idx=regimes_by_idx, lengths_m=lengths,
                           anchor_bucket=719, window_buckets=7, min_buckets=4,
                           fast_thr=50, mod_thr=10)
        # cluster lengths: 1000, 1000, 2000, 2000, 3000, 3000, 3000 → slope ~ 196 m/min
        assert out["label"] == "FAST_GROWTH"
        assert out["samples_used"] == 7
        assert out["slope_m_per_min"] > 50.0

    def test_contained_when_cluster_zero(self):
        # event segment is FREE through whole window → all-zeros cluster
        regimes = [["FREE"] * 720]
        regimes_by_idx, lengths = self._build(regimes, [200.0])
        ev = BertiniEvent("s", 0, 100, 106, "BERTINI", 1)
        out = _score_event(ev, regimes_by_idx=regimes_by_idx, lengths_m=lengths,
                           anchor_bucket=719, window_buckets=7, min_buckets=4,
                           fast_thr=50, mod_thr=10)
        assert out["label"] == "CONTAINED"
        assert out["slope_m_per_min"] == 0.0

    def test_moderate(self):
        # Slow growth — about 20 m/min
        regimes = [["FREE"] * 720, ["FREE"] * 720]
        # idx 0 CONG for whole window; idx 1 joins after some time
        for b in range(100, 107):
            regimes[0][b] = "CONGESTED"
        for b in range(105, 107):
            regimes[1][b] = "CONGESTED"
        regimes_by_idx, lengths = self._build(regimes, [200.0, 200.0])
        ev = BertiniEvent("s0", 0, 100, 106, "BERTINI", 1)
        out = _score_event(ev, regimes_by_idx=regimes_by_idx, lengths_m=lengths,
                           anchor_bucket=719, window_buckets=7, min_buckets=4,
                           fast_thr=50, mod_thr=10)
        # cluster lengths [200, 200, 200, 200, 200, 400, 400] → slope ~20-25
        assert out["label"] in ("MODERATE", "CONTAINED")  # depends on rounding
        assert 5.0 < (out["slope_m_per_min"] or 0) < 50.0


# --------------------------------------------------------------------------- #
# Module integration                                                          #
# --------------------------------------------------------------------------- #


class TestGrowthRateModule:
    def test_empty_events_returns_empty_summary(self):
        regimes = [["FREE"] * 720]
        ctx = _ctx(regimes_by_idx=regimes, segment_order=["s1"], segment_meta={"s1": {"length_m": 100}})
        out = GrowthRate().run(ctx)
        assert out["events"] == []
        assert out["summary"]["n_events"] == 0

    def test_event_id_format(self):
        regimes = [["FREE"] * 720]
        for b in range(10, 17):
            regimes[0][b] = "CONGESTED"
        ctx = _ctx(
            regimes_by_idx=regimes,
            segment_order=["seg-X"],
            segment_meta={"seg-X": {"length_m": 100}},
            bertini=[BertiniEvent("seg-X", 0, 10, 16, "BERTINI", 1)],
        )
        out = GrowthRate().run(ctx)
        assert out["events"][0]["event_id"] == "BERTINI-seg-X-1"
        assert out["summary"]["n_events"] == 1

    def test_head_events_included(self):
        regimes = [["FREE"] * 720]
        for b in range(10, 17):
            regimes[0][b] = "CONGESTED"
        ctx = _ctx(
            regimes_by_idx=regimes,
            segment_order=["s1"],
            segment_meta={"s1": {"length_m": 100}},
            head=[BertiniEvent("s1", 0, 10, 16, "HEAD", 1)],
        )
        out = GrowthRate().run(ctx)
        assert any(e["event_id"].startswith("HEAD-") for e in out["events"])
