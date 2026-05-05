"""Tests for dow_anomaly.py. Spec §15.1."""

from __future__ import annotations

from datetime import date

import pytest

from data.v3_a.baseline import DowSamples
from data.v3_a.dow_anomaly import compute_dow_anomaly


def _samples(by_seg_by_day, dow=1):
    days = sorted({d for s in by_seg_by_day.values() for d in s})
    return DowSamples(
        by_seg_by_day=by_seg_by_day,
        distinct_days=days,
        n_samples=len(days),
        dow=dow,
        available=len(days) >= 3,
    )


class TestUnavailable:
    def test_too_few_samples(self):
        s = _samples({"a": {date(2026, 4, 1): {0: 50}}})
        out = compute_dow_anomaly(
            today_tts_by_seg={"a": [50] * 5},
            dow_samples=s,
            segment_order=["a"],
            anchor_bucket=4,
        )
        assert out == {"available": False, "n_samples": 1, "reason": "insufficient_samples"}


class TestAvailable:
    def test_basic_deviation(self):
        # 5 same-DOW days, all with TT 100 at minute 0; today's TT = 150 → +50% deviation
        by_day = {date(2026, 4, d): {0: 100, 2: 100} for d in (1, 8, 15, 22, 29)}
        s = _samples({"a": by_day})
        today = {"a": [150.0, 150.0]}
        out = compute_dow_anomaly(
            today_tts_by_seg=today, dow_samples=s,
            segment_order=["a"], anchor_bucket=1,
        )
        assert out["available"] is True
        assert out["n_samples"] == 5
        assert out["deviation_pct_trace"][0] == pytest.approx(50.0)
        assert out["max_deviation_pct"] == pytest.approx(50.0)
        assert out["max_deviation_bucket"] == 0

    def test_zero_deviation_when_matches_typical(self):
        by_day = {date(2026, 4, d): {0: 100} for d in (1, 8, 15)}
        s = _samples({"a": by_day})
        today = {"a": [100.0]}
        out = compute_dow_anomaly(
            today_tts_by_seg=today, dow_samples=s,
            segment_order=["a"], anchor_bucket=0,
        )
        assert out["deviation_pct_trace"][0] == pytest.approx(0.0)

    def test_picks_max_abs_deviation(self):
        # deviations [-30, +50, -10] → max abs is +50 (bucket 1)
        by_day = {date(2026, 4, d): {0: 100, 2: 100, 4: 100} for d in (1, 8, 15)}
        s = _samples({"a": by_day})
        today = {"a": [70.0, 150.0, 90.0]}
        out = compute_dow_anomaly(
            today_tts_by_seg=today, dow_samples=s,
            segment_order=["a"], anchor_bucket=2,
        )
        assert out["max_deviation_bucket"] == 1
        assert out["max_deviation_pct"] == pytest.approx(50.0)

    def test_missing_segment_data_yields_null(self):
        by_day = {date(2026, 4, d): {0: 100} for d in (1, 8, 15)}
        s = _samples({"a": by_day})
        today = {"a": [None]}  # bucket 0 missing today
        out = compute_dow_anomaly(
            today_tts_by_seg={"a": []},  # no buckets at all
            dow_samples=s, segment_order=["a"], anchor_bucket=0,
        )
        assert out["today_corridor_tt_trace_sec"][0] is None
        assert out["deviation_pct_trace"][0] is None
