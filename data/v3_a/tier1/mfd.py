"""Tier-1 #4 — MFD with hysteresis (Geroliminis & Daganzo 2008 / Saberi 2013). Spec §7.4."""

from __future__ import annotations

import math

from . import Context, Tier1Module


CONGESTED_REGIMES = ("CONGESTED", "SEVERE")


def _density_and_speed_per_bucket(
    regimes_by_idx: tuple[tuple[str, ...], ...],
    speed_by_idx: tuple[tuple[float, ...], ...],
    lengths_m: list[float],
    anchor_bucket: int,
    total_length_m: float,
) -> tuple[list[float], list[float]]:
    """Return (density_trace, speed_trace) over [0, anchor_bucket].

    density(b): sum(length over segs in CONG/SEVR at b) / total_length, in [0, 1].
    speed(b):   length-weighted mean speed, with NaN-segments excluded and weights rescaled.
                NaN if all segments have NaN speed.
    """
    density: list[float] = []
    speed: list[float] = []
    n = len(regimes_by_idx)
    for b in range(anchor_bucket + 1):
        cong_len = 0.0
        sum_w = 0.0
        sum_ws = 0.0
        for i in range(n):
            if regimes_by_idx[i][b] in CONGESTED_REGIMES:
                cong_len += lengths_m[i]
            sp = speed_by_idx[i][b]
            if sp is not None and not (isinstance(sp, float) and math.isnan(sp)) and sp > 0:
                sum_w += lengths_m[i]
                sum_ws += lengths_m[i] * sp
        density.append(cong_len / total_length_m if total_length_m > 0 else 0.0)
        speed.append(sum_ws / sum_w if sum_w > 0 else float("nan"))
    return density, speed


def _shoelace_area(points: list[tuple[float, float]]) -> float:
    """Signed area of polygon via the shoelace formula. Last point implicitly
    closes back to first if not already."""
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += (x1 * y2 - x2 * y1)
    return area / 2.0


def _peak_density_bucket(density: list[float]) -> tuple[int | None, float]:
    if not density:
        return None, 0.0
    bi = max(range(len(density)), key=lambda b: density[b])
    return bi, density[bi]


def _recovery_lag_min(
    density: list[float],
    speed: list[float],
    peak_b: int,
    peak_density: float,
    ff_corridor_kmph: float,
) -> int | None:
    """Lag in minutes between density halving (b_d) and speed recovery (b_s).

    b_d = first bucket > peak_b where density <= peak_density / 2.
    b_s = first bucket > peak_b where speed >= ff_corridor_kmph - 5.
    None if either never reached within [peak_b, anchor_bucket].
    """
    target_d = peak_density / 2.0
    target_s = ff_corridor_kmph - 5.0
    b_d = None
    b_s = None
    n = len(density)
    for b in range(peak_b + 1, n):
        if b_d is None and density[b] <= target_d:
            b_d = b
        if b_s is None:
            sp = speed[b]
            if sp is not None and not (isinstance(sp, float) and math.isnan(sp)) and sp >= target_s:
                b_s = b
        if b_d is not None and b_s is not None:
            break
    if b_d is None or b_s is None:
        return None
    return (b_s - b_d) * 2


class MFD(Tier1Module):
    name = "mfd"

    def required_inputs(self) -> set[str]:
        return {
            "regimes_today_by_idx",
            "speed_today_by_idx",
            "segment_order",
            "segment_meta",
            "ff_speed_kmph_by_seg",
            "anchor_bucket",
        }

    def run(self, ctx: Context) -> dict:
        lengths_m = [float(ctx.segment_meta[s]["length_m"]) for s in ctx.segment_order]
        density, speed = _density_and_speed_per_bucket(
            ctx.regimes_today_by_idx, ctx.speed_today_by_idx,
            lengths_m, ctx.anchor_bucket, ctx.total_length_m,
        )
        # Filter NaN speed points for the loop-area computation
        valid = [
            (density[b], speed[b])
            for b in range(len(density))
            if not (isinstance(speed[b], float) and math.isnan(speed[b]))
        ]
        warnings: list[dict] = []
        if len(valid) < 4:
            return {
                "speed_trace_kmph": speed,
                "density_trace_frac": density,
                "loop_area": 0.0,
                "loop_closes": False,
                "peak_density_bucket": None,
                "peak_density_frac": 0.0,
                "recovery_lag_min": None,
                "ff_corridor_kmph": _ff_corridor(ctx, lengths_m),
                "warnings": [{"code": "SOFT_WARN_MFD_THIN",
                              "message": f"MFD has only {len(valid)} valid (density, speed) points",
                              "context": {"valid_points": len(valid)}}],
            }

        loop_closes = density[0] <= 0.05 and density[-1] <= 0.05
        loop_area = _shoelace_area(valid)
        peak_b, peak_d = _peak_density_bucket(density)
        ff_corridor = _ff_corridor(ctx, lengths_m)
        recovery = _recovery_lag_min(density, speed, peak_b or 0, peak_d, ff_corridor) if peak_b is not None else None
        if peak_b is not None and recovery is None:
            warnings.append({"code": "SOFT_WARN_MFD_NO_RECOVERY",
                             "message": "MFD anchor cuts off before recovery",
                             "context": {"peak_density_bucket": peak_b}})

        return {
            "speed_trace_kmph": speed,
            "density_trace_frac": density,
            "loop_area": loop_area,
            "loop_closes": loop_closes,
            "peak_density_bucket": peak_b,
            "peak_density_frac": peak_d,
            "recovery_lag_min": recovery,
            "ff_corridor_kmph": ff_corridor,
            "warnings": warnings,
        }


def _ff_corridor(ctx: Context, lengths_m: list[float]) -> float:
    """Length-weighted mean of per-segment ff_speed_kmph."""
    sum_w = sum(lengths_m)
    if sum_w == 0:
        return 0.0
    return sum(ctx.ff_speed_kmph_by_seg.get(s, 0.0) * lengths_m[i] for i, s in enumerate(ctx.segment_order)) / sum_w
