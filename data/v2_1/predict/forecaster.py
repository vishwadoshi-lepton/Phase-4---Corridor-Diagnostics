"""Forecaster interface + TimesFM 2.5 backend + statistical baseline fallback.

Contract:
    forecaster.forecast(horizon_steps, contexts) -> (point, quantiles)
        point:     np.ndarray of shape (N, H), float32, travel-time-in-seconds
        quantiles: np.ndarray of shape (N, H, 10), float32
            quantile indices: 0 = mean, 1 = q10, 2 = q20, ..., 5 = q50, ..., 9 = q90
"""
from __future__ import annotations

import warnings
from typing import List, Tuple

import numpy as np

from . import config as C


class Forecaster:
    """Abstract forecaster interface."""
    name: str = "abstract"

    def forecast(
        self, horizon_steps: int, contexts: List[np.ndarray]
    ) -> Tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError


class TimesFMForecaster(Forecaster):
    """TimesFM 2.5 200M PyTorch backend."""
    name = "timesfm-2.5-200m"

    def __init__(self, max_context: int = 6000, max_horizon: int = 128):
        import torch
        import timesfm

        torch.set_float32_matmul_precision("high")

        # Check that the torch backend is importable
        if not hasattr(timesfm, "TimesFM_2p5_200M_torch"):
            raise RuntimeError(
                "TimesFM_2p5_200M_torch not importable — torch backend missing"
            )

        self.model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch"
        )
        self.model.compile(
            timesfm.ForecastConfig(
                max_context=max_context,
                max_horizon=max_horizon,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
        self.max_context = max_context

    def forecast(
        self, horizon_steps: int, contexts: List[np.ndarray]
    ) -> Tuple[np.ndarray, np.ndarray]:
        # Trim to max_context (the model truncates anyway; doing it explicitly is cleaner)
        trimmed = [
            (c[-self.max_context:] if len(c) > self.max_context else c).astype(np.float32)
            for c in contexts
        ]
        point, quantiles = self.model.forecast(horizon=horizon_steps, inputs=trimmed)
        return np.asarray(point, dtype=np.float32), np.asarray(quantiles, dtype=np.float32)


class StatisticalBaselineForecaster(Forecaster):
    """Honest statistical baseline for when TimesFM is unavailable.

    Strategy per series:
      - Point forecast = profile_at_future_time (the weekday median at t+k),
        shifted by the average deviation of today-so-far from that profile over
        the last 60 min. This is "persist today's slant forward."
      - Quantile bands come from bootstrap over the last 2 h of residuals.

    This is intentionally a strong classical baseline (not a naive lookup), so
    the downstream pipeline behaves reasonably when TimesFM is missing. All
    outputs match the TimesFM interface shape exactly.
    """
    name = "statistical-baseline"

    def forecast(
        self, horizon_steps: int, contexts: List[np.ndarray]
    ) -> Tuple[np.ndarray, np.ndarray]:
        n = len(contexts)
        point = np.zeros((n, horizon_steps), dtype=np.float32)
        quantiles = np.zeros((n, horizon_steps, 10), dtype=np.float32)

        for i, ctx in enumerate(contexts):
            ctx = np.asarray(ctx, dtype=np.float32)
            if len(ctx) < 720:
                # Too short — just flat-extrapolate the last value
                last = ctx[-1] if len(ctx) else 0.0
                point[i] = last
                spread = max(1.0, last * 0.10)
                for q in range(10):
                    z = -1.28 + (q / 9.0) * 2.56   # q10 ≈ -1.28σ, q90 ≈ +1.28σ
                    quantiles[i, :, q] = last + z * spread
                quantiles[i, :, 0] = last  # index 0 = mean
                continue

            # "History" = everything except the last (today-so-far) portion
            #   we approximate by assuming the last <720 values are today's morning
            #   and the rest is the repeated weekday median
            # Median profile = first 720 of ctx (any of the tiled history blocks)
            profile = ctx[:720]
            # Today-so-far = tail after full history multiple
            # Find last chunk-boundary at a multiple of 720 (that's where today's data starts)
            anchor_bkt = len(ctx) % 720
            if anchor_bkt == 0:
                anchor_bkt = 720  # exactly on boundary — take last day as "today"
            today_so_far = ctx[-anchor_bkt:]

            # deviation over last 30 buckets (60 min)
            look_back = min(30, len(today_so_far))
            profile_recent = profile[anchor_bkt - look_back : anchor_bkt]
            today_recent = today_so_far[-look_back:]
            avg_dev = float(np.mean(today_recent - profile_recent))

            # residual spread (for quantile bands)
            residuals = today_recent - profile_recent
            sigma = float(np.std(residuals)) if len(residuals) > 2 else 0.05 * float(np.mean(profile))

            # forecast: future profile + current deviation
            future_profile = np.array([
                profile[(anchor_bkt + k) % 720] for k in range(horizon_steps)
            ], dtype=np.float32)
            forecast_mean = future_profile + avg_dev

            point[i] = forecast_mean
            for q in range(10):
                if q == 0:
                    quantiles[i, :, q] = forecast_mean
                else:
                    # q=1 → q10 (-1.28σ) ... q=9 → q90 (+1.28σ)
                    z = -1.28 + ((q - 1) / 8.0) * 2.56
                    quantiles[i, :, q] = forecast_mean + z * sigma

        return point, quantiles


def load_forecaster(prefer_timesfm: bool = True) -> Forecaster:
    """Return TimesFM if usable, else the statistical baseline (with a warning)."""
    if prefer_timesfm:
        try:
            # keep context ≤ 1200 samples for CPU-feasible latency (~5s per batched call of 48)
            ctx_budget = C.HISTORY_DAYS_CONCAT * C.BUCKETS_PER_DAY + C.BUCKETS_PER_DAY
            return TimesFMForecaster(
                max_context=min(1200, max(1024, ctx_budget)),
                max_horizon=max(64, C.HORIZON_STEPS + 16),
            )
        except Exception as e:
            warnings.warn(
                f"TimesFM unavailable ({e}); falling back to statistical baseline.",
                RuntimeWarning,
            )
    return StatisticalBaselineForecaster()
