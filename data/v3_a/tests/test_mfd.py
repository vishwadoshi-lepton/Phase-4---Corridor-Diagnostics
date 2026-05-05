"""Tests for tier1/mfd.py. Spec §15.1."""

from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from data.v3_a import EngineConfig
from data.v3_a.progress import IST
from data.v3_a.tier1 import Context
from data.v3_a.tier1.mfd import (
    MFD,
    _density_and_speed_per_bucket,
    _peak_density_bucket,
    _recovery_lag_min,
    _shoelace_area,
)


def _ctx(*, regimes_by_idx, speed_by_idx, segment_order, segment_meta, ff_speed_kmph_by_seg, anchor_bucket=719):
    cfg = EngineConfig.default()
    n = len(segment_order)
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
        regimes_today_by_idx=tuple(tuple(regimes_by_idx[i]) for i in range(n)),
        regimes_typical_by_idx=tuple(tuple(regimes_by_idx[i]) for i in range(n)),
        bertini_events=(),
        head_bottleneck_events=(),
        primary_windows_today=(),
        historical_onsets_by_seg={},
        today_onsets_by_seg={},
        speed_today_by_idx=tuple(tuple(speed_by_idx[i]) for i in range(n)),
        ff_speed_kmph_by_seg=ff_speed_kmph_by_seg,
        v21_verdicts={s: "FREE_FLOW" for s in segment_order},
        config=cfg,
    )


class TestDensityAndSpeed:
    def test_all_free_zero_density(self):
        regimes = ((["FREE"] * 5, ["FREE"] * 5))
        regimes_by_idx = tuple(tuple(r) for r in regimes)
        speeds_by_idx = tuple(tuple([60.0] * 5) for _ in range(2))
        d, s = _density_and_speed_per_bucket(regimes_by_idx, speeds_by_idx, [100.0, 100.0], 4, 200.0)
        assert d == [0.0] * 5
        assert s == [60.0] * 5

    def test_partial_congestion_density(self):
        # idx 0 CONG (200m); idx 1 FREE (300m). Total 500m. density = 200/500 = 0.4
        regimes_by_idx = (tuple(["CONGESTED"] * 5), tuple(["FREE"] * 5))
        speeds_by_idx = (tuple([20.0] * 5), tuple([60.0] * 5))
        d, s = _density_and_speed_per_bucket(regimes_by_idx, speeds_by_idx, [200.0, 300.0], 4, 500.0)
        assert d[0] == 0.4
        # speed = (200*20 + 300*60) / 500 = (4000 + 18000) / 500 = 44
        assert s[0] == pytest.approx(44.0)

    def test_nan_segments_excluded(self):
        regimes_by_idx = (tuple(["FREE"] * 5), tuple(["FREE"] * 5))
        speeds_by_idx = (tuple([float("nan")] * 5), tuple([60.0] * 5))
        d, s = _density_and_speed_per_bucket(regimes_by_idx, speeds_by_idx, [100.0, 100.0], 4, 200.0)
        # speed should = 60 (only seg 1 contributes)
        assert s[0] == pytest.approx(60.0)


class TestPeakDensity:
    def test_picks_argmax(self):
        b, v = _peak_density_bucket([0.1, 0.5, 0.3])
        assert (b, v) == (1, 0.5)

    def test_empty(self):
        assert _peak_density_bucket([]) == (None, 0.0)


class TestRecoveryLag:
    def test_basic_lag(self):
        # peak at b=2 with density 0.6. ff=60, target_s=55
        # density: 0.0, 0.2, 0.6, 0.5, 0.2, 0.1 → b_d (first <= 0.3) = b=4
        # speed: 60, 50, 30, 40, 50, 60 → b_s (first >= 55) = b=5
        # lag = (5-4)*2 = 2 min
        density = [0.0, 0.2, 0.6, 0.5, 0.2, 0.1]
        speed = [60.0, 50.0, 30.0, 40.0, 50.0, 60.0]
        assert _recovery_lag_min(density, speed, peak_b=2, peak_density=0.6, ff_corridor_kmph=60.0) == 2

    def test_no_recovery_returns_none(self):
        density = [0.0, 0.4, 0.6, 0.6]  # never halves
        speed = [60.0, 30.0, 25.0, 20.0]
        assert _recovery_lag_min(density, speed, peak_b=2, peak_density=0.6, ff_corridor_kmph=60.0) is None


class TestShoelace:
    def test_unit_square(self):
        # square: (0,0) → (1,0) → (1,1) → (0,1)
        area = _shoelace_area([(0, 0), (1, 0), (1, 1), (0, 1)])
        assert abs(area) == pytest.approx(1.0)

    def test_degenerate_returns_zero(self):
        assert _shoelace_area([(0, 0), (1, 1)]) == 0.0


class TestMFDModule:
    def test_thin_data_emits_warning(self):
        regimes = [["FREE"] * 3, ["FREE"] * 3]
        speeds = [[60.0, 60.0, 60.0], [60.0, 60.0, 60.0]]
        ctx = _ctx(
            regimes_by_idx=regimes, speed_by_idx=speeds,
            segment_order=["a", "b"],
            segment_meta={"a": {"length_m": 100}, "b": {"length_m": 100}},
            ff_speed_kmph_by_seg={"a": 60.0, "b": 60.0},
            anchor_bucket=2,
        )
        out = MFD().run(ctx)
        assert out["loop_closes"] is False
        # 3 valid points < 4 → THIN warning
        assert any(w["code"] == "SOFT_WARN_MFD_THIN" for w in out["warnings"])

    def test_full_day_with_hysteresis(self):
        # Synthesize a hysteresis loop: density rises 540→570 with speed dropping;
        # density falls 570→600 with speed lower than the symmetric rise (recovery slower).
        n_buckets = 720
        regimes = [["FREE"] * n_buckets for _ in range(2)]
        speeds = [[60.0] * n_buckets for _ in range(2)]

        # Rising phase: bucket 540-569 (30 buckets), density goes 0 → 0.5
        for k, b in enumerate(range(540, 570)):
            regimes[0][b] = "CONGESTED"
            speeds[0][b] = 60.0 - k * 1.2  # 60 → 25
        # Recovery phase: bucket 570-600 (30 buckets), density falls 0.5 → 0; speed
        # recovers but stays a few kmph below the rising-phase counterpart at the same density.
        for k, b in enumerate(range(570, 600)):
            regimes[0][b] = "CONGESTED" if k < 25 else "FREE"
            speeds[0][b] = 25.0 + k * 0.8  # 25 → 49

        ctx = _ctx(
            regimes_by_idx=regimes, speed_by_idx=speeds,
            segment_order=["a", "b"],
            segment_meta={"a": {"length_m": 1000}, "b": {"length_m": 1000}},
            ff_speed_kmph_by_seg={"a": 60.0, "b": 60.0},
            anchor_bucket=719,
        )
        out = MFD().run(ctx)
        assert out["peak_density_bucket"] in range(540, 600)
        assert out["peak_density_frac"] == pytest.approx(0.5)
        assert out["loop_closes"] is True
        # Hysteresis present → nonzero signed area
        assert abs(out["loop_area"]) > 0.0
        assert out["ff_corridor_kmph"] == pytest.approx(60.0)
