"""Tier-1 #1 — Growth-rate (Duan et al. 2023). Spec §7.1."""

from __future__ import annotations

from typing import Iterable

from . import BertiniEvent, Context, Tier1Module


CONGESTED_REGIMES = ("CONGESTED", "SEVERE")


def _ols_slope(xs: list[float], ys: list[float]) -> float:
    """OLS slope of y on x. Assumes len(xs) == len(ys) >= 2."""
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _cluster_length_m(
    seg_idx: int,
    bucket: int,
    regimes_by_idx: tuple[tuple[str, ...], ...],
    lengths_m: list[float],
) -> float:
    """Walk left+right from seg_idx while regime is CONG/SEVR; sum segment lengths.

    If the anchored segment's own regime at this bucket is NOT CONG/SEVR,
    the cluster length is 0 (per spec: "thawed" event segment).
    """
    if regimes_by_idx[seg_idx][bucket] not in CONGESTED_REGIMES:
        return 0.0
    n = len(regimes_by_idx)
    total = float(lengths_m[seg_idx])
    # Walk left
    i = seg_idx - 1
    while i >= 0 and regimes_by_idx[i][bucket] in CONGESTED_REGIMES:
        total += float(lengths_m[i])
        i -= 1
    # Walk right
    i = seg_idx + 1
    while i < n and regimes_by_idx[i][bucket] in CONGESTED_REGIMES:
        total += float(lengths_m[i])
        i += 1
    return total


def _classify(slope_m_per_min: float, *, fast_thr: float, mod_thr: float) -> str:
    if slope_m_per_min >= fast_thr:
        return "FAST_GROWTH"
    if slope_m_per_min >= mod_thr:
        return "MODERATE"
    return "CONTAINED"


def _score_event(
    event: BertiniEvent,
    *,
    regimes_by_idx: tuple[tuple[str, ...], ...],
    lengths_m: list[float],
    anchor_bucket: int,
    window_buckets: int,
    min_buckets: int,
    fast_thr: float,
    mod_thr: float,
) -> dict:
    t_end_inclusive = min(event.t0_bucket + window_buckets - 1, anchor_bucket)
    bucket_range = list(range(event.t0_bucket, t_end_inclusive + 1))
    nbuckets = len(bucket_range)

    cluster_lengths = [
        _cluster_length_m(event.segment_idx, b, regimes_by_idx, lengths_m)
        for b in bucket_range
    ]
    minutes = [float(b * 2) for b in bucket_range]
    growth_window_minutes = (bucket_range[-1] - bucket_range[0]) * 2 if nbuckets > 1 else 0

    if nbuckets < min_buckets:
        return {
            "event_id": event.event_id,
            "segment_id": event.segment_id,
            "segment_idx": event.segment_idx,
            "t0_minute": event.t0_bucket * 2,
            "t0_bucket": event.t0_bucket,
            "growth_window_minutes": growth_window_minutes,
            "samples_used": nbuckets,
            "slope_m_per_min": None,
            "cluster_length_m_at_t0": cluster_lengths[0] if cluster_lengths else 0.0,
            "cluster_length_m_at_tend": cluster_lengths[-1] if cluster_lengths else 0.0,
            "label": "INSUFFICIENT_DATA",
        }

    if all(cl == 0.0 for cl in cluster_lengths):
        slope = 0.0
        label = "CONTAINED"
    else:
        slope = _ols_slope(minutes, cluster_lengths)
        label = _classify(slope, fast_thr=fast_thr, mod_thr=mod_thr)

    return {
        "event_id": event.event_id,
        "segment_id": event.segment_id,
        "segment_idx": event.segment_idx,
        "t0_minute": event.t0_bucket * 2,
        "t0_bucket": event.t0_bucket,
        "growth_window_minutes": growth_window_minutes,
        "samples_used": nbuckets,
        "slope_m_per_min": float(slope),
        "cluster_length_m_at_t0": cluster_lengths[0],
        "cluster_length_m_at_tend": cluster_lengths[-1],
        "label": label,
    }


def _summarise(events: Iterable[dict]) -> dict:
    n_fast = n_mod = n_cont = n_insuf = 0
    total = 0
    for e in events:
        total += 1
        lbl = e["label"]
        if lbl == "FAST_GROWTH":
            n_fast += 1
        elif lbl == "MODERATE":
            n_mod += 1
        elif lbl == "CONTAINED":
            n_cont += 1
        elif lbl == "INSUFFICIENT_DATA":
            n_insuf += 1
    return {
        "n_events": total,
        "n_fast": n_fast,
        "n_moderate": n_mod,
        "n_contained": n_cont,
        "n_insufficient": n_insuf,
    }


class GrowthRate(Tier1Module):
    name = "growth_rate"

    def required_inputs(self) -> set[str]:
        return {
            "regimes_today_by_idx",
            "bertini_events",
            "head_bottleneck_events",
            "segment_meta",
            "segment_order",
            "anchor_bucket",
            "config",
        }

    def run(self, ctx: Context) -> dict:
        cfg = ctx.config
        lengths_m = [float(ctx.segment_meta[s]["length_m"]) for s in ctx.segment_order]
        events: list[dict] = []
        for ev in list(ctx.bertini_events) + list(ctx.head_bottleneck_events):
            events.append(
                _score_event(
                    ev,
                    regimes_by_idx=ctx.regimes_today_by_idx,
                    lengths_m=lengths_m,
                    anchor_bucket=ctx.anchor_bucket,
                    window_buckets=cfg.tier1_growth_window_buckets,
                    min_buckets=cfg.tier1_growth_min_buckets,
                    fast_thr=cfg.tier1_growth_fast_m_per_min,
                    mod_thr=cfg.tier1_growth_moderate_m_per_min,
                )
            )
        # Sort by t0_bucket then segment_idx for deterministic ordering
        events.sort(key=lambda e: (e["t0_bucket"], e["segment_idx"], e["event_id"]))
        return {"events": events, "summary": _summarise(events)}
