"""Tests for regime_today.py. Spec §15.1."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from data.v3_a.data_pull import Row, TodayPull
from data.v3_a.progress import IST
from data.v3_a.regime_today import (
    BUCKETS_PER_DAY,
    BUCKET_MIN,
    anchor_bucket_of,
    build_today_regimes_and_speeds,
    build_today_tts,
    bucket_of,
)


def _today(t_min: int) -> datetime:
    """Convenience: 2026-05-04 00:00 IST + t_min minutes."""
    return datetime(2026, 5, 4, 0, 0, tzinfo=IST) + timedelta(minutes=t_min)


def _today_pull(rows_per_seg: dict[str, list[tuple[int, float]]]) -> TodayPull:
    """rows_per_seg: seg -> [(minute_of_day, tt_sec), ...]"""
    rows = []
    by_seg = {}
    for seg, samples in rows_per_seg.items():
        by_seg[seg] = []
        for m, tt in samples:
            r = Row(seg, _today(m), tt)
            rows.append(r)
            by_seg[seg].append(r)
    return TodayPull(rows=rows, by_seg=by_seg, gap_warnings=[])


class TestBucketOf:
    def test_zero_bucket(self):
        day_start = _today(0)
        assert bucket_of(_today(0), day_start) == 0
        assert bucket_of(_today(1), day_start) == 0
        assert bucket_of(_today(2), day_start) == 1

    def test_last_bucket(self):
        day_start = _today(0)
        assert bucket_of(_today(1438), day_start) == 719
        assert bucket_of(_today(1439), day_start) == 719

    def test_anchor_bucket_of_truncates(self):
        # 19:01 IST → minute 1141 → bucket 570
        anchor = _today(19 * 60 + 1)
        assert anchor_bucket_of(anchor) == 570


class TestBuildTodayTts:
    def test_pads_after_anchor_with_ff_tt(self):
        # Anchor at 6:00 (bucket 180) → buckets [181, 720) = ff_tt
        anchor = _today(6 * 60)
        today = _today_pull({"s1": [(0, 50.0), (4, 60.0)]})
        tts, anchor_bucket = build_today_tts(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            ff_tt_by_seg={"s1": 100.0},
            baseline_profile_by_seg={"s1": {0: 200.0}},
        )
        assert anchor_bucket == 180
        assert tts["s1"][180] == pytest.approx(60.0) or tts["s1"][180] == pytest.approx(50.0)
        # Bucket 181 onwards = ff_tt
        for b in range(181, 720):
            assert tts["s1"][b] == 100.0

    def test_forward_fill_within_today(self):
        # observation at bucket 0 only; buckets 1..10 should forward-fill
        anchor = _today(20)  # bucket 10
        today = _today_pull({"s1": [(0, 50.0)]})
        tts, anchor_bucket = build_today_tts(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            ff_tt_by_seg={"s1": 100.0},
            baseline_profile_by_seg={"s1": {2: 200.0, 4: 200.0}},
        )
        for b in range(0, 11):
            assert tts["s1"][b] == 50.0

    def test_baseline_fallback_when_no_today_data(self):
        anchor = _today(10)  # bucket 5
        today = _today_pull({"s1": []})
        tts, _ = build_today_tts(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            ff_tt_by_seg={"s1": 100.0},
            baseline_profile_by_seg={"s1": {0: 200.0, 2: 210.0, 4: 220.0, 6: 230.0, 8: 240.0, 10: 250.0}},
        )
        # Buckets 0..5 should pull from baseline by minute_of_day
        assert tts["s1"][0] == 200.0
        assert tts["s1"][1] == 210.0
        assert tts["s1"][5] == 250.0

    def test_late_first_observation_backfills_leading(self):
        # bucket 0..4 have no today data; bucket 5 has 75; buckets 0..4 should
        # backfill from bucket 5 (since today eventually arrived).
        anchor = _today(20)  # bucket 10
        today = _today_pull({"s1": [(10, 75.0)]})
        tts, _ = build_today_tts(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            ff_tt_by_seg={"s1": 100.0},
            baseline_profile_by_seg={"s1": {0: 200.0, 2: 200.0, 4: 200.0, 6: 200.0, 8: 200.0, 10: 200.0}},
        )
        # Bucket 5 (minute_of_day 10) had today data
        assert tts["s1"][5] == 75.0
        # Buckets 6..10 forward-filled to 75
        for b in range(5, 11):
            assert tts["s1"][b] == 75.0
        # Buckets 0..4 — backfill behaviour: replaces baseline-filled buckets with
        # the first today observation
        for b in range(5):
            assert tts["s1"][b] == 75.0

    def test_median_when_multiple_obs_in_bucket(self):
        # Two obs in bucket 0 (minutes 0 and 1) → median
        anchor = _today(2)  # bucket 1
        today = _today_pull({"s1": [(0, 50.0), (1, 70.0)]})
        tts, _ = build_today_tts(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            ff_tt_by_seg={"s1": 100.0},
            baseline_profile_by_seg={"s1": {0: 200.0, 2: 200.0}},
        )
        assert tts["s1"][0] == 60.0  # median(50, 70)


class TestBuildRegimesAndSpeeds:
    def test_regimes_use_v2_classifier(self):
        # ff_tt = 60; observation tt = 60 → ratio 1.0 → FREE
        anchor = _today(10)
        today = _today_pull({"s1": [(0, 60.0)]})
        regimes, speeds, anchor_bucket = build_today_regimes_and_speeds(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            segment_meta={"s1": {"length_m": 1000}},
            ff_tt_by_seg={"s1": 60.0},
            baseline_profile_by_seg={"s1": {0: 60.0, 2: 60.0, 4: 60.0, 6: 60.0, 8: 60.0, 10: 60.0}},
        )
        # All early buckets free-flow
        assert regimes["s1"][0] == "FREE"
        # Speed at FF: 1000m / 60s = 16.67 m/s = 60 kmph
        assert speeds["s1"][0] == pytest.approx(60.0, abs=0.01)

    def test_severe_regime_when_tt_much_higher(self):
        # tt=300, ff_tt=60 → ratio 0.20 → SEVERE
        anchor = _today(2)
        today = _today_pull({"s1": [(0, 300.0)]})
        regimes, _, _ = build_today_regimes_and_speeds(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            segment_meta={"s1": {"length_m": 1000}},
            ff_tt_by_seg={"s1": 60.0},
            baseline_profile_by_seg={"s1": {0: 60.0, 2: 60.0}},
        )
        assert regimes["s1"][0] == "SEVERE"

    def test_post_anchor_regime_is_free(self):
        # Anchor bucket 5; bucket 6+ should be FREE since TT == ff_tt
        anchor = _today(10)
        today = _today_pull({"s1": [(0, 60.0)]})
        regimes, _, anchor_bucket = build_today_regimes_and_speeds(
            today,
            anchor_ts=anchor,
            segment_order=["s1"],
            segment_meta={"s1": {"length_m": 1000}},
            ff_tt_by_seg={"s1": 60.0},
            baseline_profile_by_seg={"s1": {0: 60.0, 2: 60.0, 4: 60.0, 6: 60.0, 8: 60.0, 10: 60.0}},
        )
        for b in range(anchor_bucket + 1, BUCKETS_PER_DAY):
            assert regimes["s1"][b] == "FREE"
