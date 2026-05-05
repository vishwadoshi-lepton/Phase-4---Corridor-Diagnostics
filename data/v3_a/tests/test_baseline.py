"""Tests for baseline.py. Spec §15.1."""

from __future__ import annotations

from datetime import date

import pytest

from data.v3_a.baseline import (
    BaselineResult,
    DowSamples,
    build_baseline_profile,
    build_dow_samples,
)
from data.v3_a.data_pull import HistoricalAggPull
from data.v3_a.errors import InsufficientBaseline


def _agg(by_seg_by_day):
    days = sorted({d for s in by_seg_by_day.values() for d in s})
    return HistoricalAggPull(by_seg_by_day=by_seg_by_day, distinct_days=days)


class TestBaselineProfile:
    def test_median_across_days_per_minute(self):
        hist = _agg({
            "s1": {
                date(2026, 4, 1): {0: 100.0, 2: 110.0},
                date(2026, 4, 2): {0: 200.0, 2: 220.0},
                date(2026, 4, 3): {0: 300.0, 2: 330.0},
                date(2026, 4, 4): {0: 400.0, 2: 440.0},
                date(2026, 4, 5): {0: 500.0, 2: 550.0},
            },
        })
        out = build_baseline_profile(hist, n_target_days=22, min_days=5, thin_threshold=14)
        assert out.profile_by_seg["s1"][0] == 300.0  # median of [100,200,300,400,500]
        assert out.profile_by_seg["s1"][2] == 330.0
        assert out.n_actual_days == 5
        assert out.thin is True  # 5 < 14

    def test_picks_most_recent_n(self):
        # 8 days but n_target=3 → only the 3 most recent count
        days_data = {date(2026, 4, d): {0: float(d) * 10} for d in range(1, 9)}
        hist = _agg({"s1": days_data})
        out = build_baseline_profile(hist, n_target_days=3, min_days=2, thin_threshold=14)
        # most recent 3 are days 6, 7, 8 → tts 60, 70, 80 → median 70
        assert out.profile_by_seg["s1"][0] == 70.0
        assert out.n_actual_days == 3

    def test_insufficient_baseline_raises(self):
        hist = _agg({
            "s1": {date(2026, 4, 1): {0: 100.0}, date(2026, 4, 2): {0: 200.0}},
        })
        with pytest.raises(InsufficientBaseline) as ei:
            build_baseline_profile(hist, n_target_days=22, min_days=5)
        assert "2" in ei.value.message  # "Only 2 distinct weekdays..."
        assert ei.value.context["n_actual_days"] == 2

    def test_thin_threshold_at_boundary(self):
        # 14 days = NOT thin (boundary is strict <)
        days_data = {date(2026, 4, d): {0: 100.0} for d in range(1, 15)}
        hist = _agg({"s1": days_data})
        out = build_baseline_profile(hist, n_target_days=22, min_days=5, thin_threshold=14)
        assert out.n_actual_days == 14
        assert out.thin is False

    def test_thin_threshold_below_boundary(self):
        days_data = {date(2026, 4, d): {0: 100.0} for d in range(1, 14)}
        hist = _agg({"s1": days_data})
        out = build_baseline_profile(hist, n_target_days=22, min_days=5, thin_threshold=14)
        assert out.n_actual_days == 13
        assert out.thin is True

    def test_segment_with_partial_minute_coverage(self):
        # s1 has data for both minutes; s2 only for minute 0
        hist = _agg({
            "s1": {date(2026, 4, d): {0: 100.0, 2: 110.0} for d in range(1, 6)},
            "s2": {date(2026, 4, d): {0: 50.0} for d in range(1, 6)},
        })
        out = build_baseline_profile(hist, n_target_days=22, min_days=5, thin_threshold=14)
        assert set(out.profile_by_seg["s1"].keys()) == {0, 2}
        assert set(out.profile_by_seg["s2"].keys()) == {0}


class TestDowSamples:
    def test_available_when_enough(self):
        hist = _agg({"s1": {date(2026, 4, d): {} for d in (1, 8, 15, 22, 29)}})
        out = build_dow_samples(hist, target_dow=3, min_samples=3)
        assert out.available is True
        assert out.n_samples == 5
        assert out.dow == 3

    def test_unavailable_when_thin(self):
        hist = _agg({"s1": {date(2026, 4, 1): {}, date(2026, 4, 8): {}}})
        out = build_dow_samples(hist, target_dow=3, min_samples=3)
        assert out.available is False
        assert out.n_samples == 2

    def test_boundary(self):
        hist = _agg({"s1": {date(2026, 4, d): {} for d in (1, 8, 15)}})
        out = build_dow_samples(hist, target_dow=3, min_samples=3)
        assert out.available is True  # 3 >= 3
        assert out.n_samples == 3
