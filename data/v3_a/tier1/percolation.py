"""Tier-1 #2 — Percolation on corridor (Li 2015 / Zeng 2019 / Ambühl 2023). Spec §7.2.

LCC = largest connected component of CONG/SEVR segments at a bucket.
SLCC = second-largest. The onset of systemic failure is the bucket where SLCC peaks
— the moment two clusters are about to merge.
"""

from __future__ import annotations

from . import Context, Tier1Module


CONGESTED_REGIMES = ("CONGESTED", "SEVERE")


def _component_lengths_at_bucket(
    bucket: int,
    regimes_by_idx: tuple[tuple[str, ...], ...],
    lengths_m: list[float],
) -> list[float]:
    """Return component lengths in metres, sorted descending. Empty list if all FREE/APPR."""
    lengths_out: list[float] = []
    n = len(regimes_by_idx)
    i = 0
    while i < n:
        if regimes_by_idx[i][bucket] in CONGESTED_REGIMES:
            comp = float(lengths_m[i])
            j = i + 1
            while j < n and regimes_by_idx[j][bucket] in CONGESTED_REGIMES:
                comp += float(lengths_m[j])
                j += 1
            lengths_out.append(comp)
            i = j
        else:
            i += 1
    lengths_out.sort(reverse=True)
    return lengths_out


def _trace(
    regimes_by_idx: tuple[tuple[str, ...], ...],
    lengths_m: list[float],
    anchor_bucket: int,
) -> tuple[list[float], list[float], int]:
    """Compute LCC and SLCC trace over [0, anchor_bucket]. Returns (lcc, slcc, n_with_2plus)."""
    lcc: list[float] = []
    slcc: list[float] = []
    n_2plus = 0
    for b in range(anchor_bucket + 1):
        comps = _component_lengths_at_bucket(b, regimes_by_idx, lengths_m)
        lcc.append(comps[0] if comps else 0.0)
        slcc.append(comps[1] if len(comps) >= 2 else 0.0)
        if len(comps) >= 2:
            n_2plus += 1
    return lcc, slcc, n_2plus


def _find_onset(slcc_trace: list[float]) -> int | None:
    """Bucket index of the SLCC peak. None if SLCC is all zero."""
    best_b: int | None = None
    best_v = 0.0
    for b, v in enumerate(slcc_trace):
        if v > best_v:
            best_v = v
            best_b = b
    return best_b if best_v > 0 else None


def _time_to_merge(
    lcc: list[float],
    slcc: list[float],
    onset_bucket: int,
) -> int | None:
    """Minutes from onset to merge: first b* > onset where SLCC(b*) == 0 AND
    LCC(b*) >= LCC(onset) + 0.5 * SLCC(onset). None if condition never met."""
    target = lcc[onset_bucket] + 0.5 * slcc[onset_bucket]
    for b in range(onset_bucket + 1, len(slcc)):
        if slcc[b] == 0.0 and lcc[b] >= target:
            return (b - onset_bucket) * 2
    return None


class Percolation(Tier1Module):
    name = "percolation"

    def required_inputs(self) -> set[str]:
        return {"regimes_today_by_idx", "segment_meta", "segment_order", "anchor_bucket"}

    def run(self, ctx: Context) -> dict:
        lengths_m = [float(ctx.segment_meta[s]["length_m"]) for s in ctx.segment_order]
        lcc, slcc, n_2plus = _trace(ctx.regimes_today_by_idx, lengths_m, ctx.anchor_bucket)
        onset_b = _find_onset(slcc)
        if onset_b is None:
            return {
                "lcc_trace_m": lcc,
                "slcc_trace_m": slcc,
                "onset_bucket": None,
                "onset_minute": None,
                "onset_lcc_m": None,
                "onset_slcc_m": None,
                "time_to_merge_minutes": None,
                "summary": {
                    "max_lcc_m": max(lcc) if lcc else 0.0,
                    "max_slcc_m": 0.0,
                    "buckets_with_2plus_components": n_2plus,
                },
            }

        return {
            "lcc_trace_m": lcc,
            "slcc_trace_m": slcc,
            "onset_bucket": onset_b,
            "onset_minute": onset_b * 2,
            "onset_lcc_m": lcc[onset_b],
            "onset_slcc_m": slcc[onset_b],
            "time_to_merge_minutes": _time_to_merge(lcc, slcc, onset_b),
            "summary": {
                "max_lcc_m": max(lcc) if lcc else 0.0,
                "max_slcc_m": max(slcc),
                "buckets_with_2plus_components": n_2plus,
            },
        }
