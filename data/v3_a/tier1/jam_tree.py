"""Tier-1 #3 — Jam-tree + temporal precedence (Serok 2022 / Duan 2023). Spec §7.3."""

from __future__ import annotations

from collections import deque

from . import BertiniEvent, Context, Tier1Module


def _build_tree(
    onsets: list[tuple[str, int, int]],          # [(seg_id, seg_idx, onset_bucket)]
    n_segments: int,
) -> tuple[list[dict], list[dict]]:
    """Build the causal tree.

    For each onset (s_i, b_i): find adjacent indices (i-1, i+1) that have an
    onset earlier than b_i; pick the latest-firing of those as the parent
    (closest in time).
    """
    # idx -> (seg_id, onset_bucket); only segments with onsets
    idx_to_data: dict[int, tuple[str, int]] = {idx: (sid, b) for sid, idx, b in onsets}

    nodes: list[dict] = []
    edges: list[dict] = []

    # Process in onset order to keep things deterministic
    onsets_sorted = sorted(onsets, key=lambda x: (x[2], x[1]))
    for sid, idx, bucket in onsets_sorted:
        candidates: list[tuple[int, int, str]] = []  # (parent_bucket, parent_idx, parent_id)
        for adj_idx in (idx - 1, idx + 1):
            if 0 <= adj_idx < n_segments and adj_idx in idx_to_data:
                pid, pbucket = idx_to_data[adj_idx]
                if pbucket < bucket:
                    candidates.append((pbucket, adj_idx, pid))
        if candidates:
            # Latest-firing earlier-onset → max by parent_bucket
            candidates.sort(reverse=True)
            parent_bucket, parent_idx, parent_id = candidates[0]
            nodes.append({
                "segment_id": sid,
                "segment_idx": idx,
                "onset_bucket": bucket,
                "onset_minute": bucket * 2,
                "parent_segment_id": parent_id,
                "depth": -1,  # filled in later via BFS
                "role": "PROPAGATED",
            })
            edges.append({
                "parent_segment_id": parent_id,
                "child_segment_id": sid,
                "lag_minutes": (bucket - parent_bucket) * 2,
            })
        else:
            nodes.append({
                "segment_id": sid,
                "segment_idx": idx,
                "onset_bucket": bucket,
                "onset_minute": bucket * 2,
                "parent_segment_id": None,
                "depth": 0,
                "role": "ORIGIN",
            })

    # BFS to assign depth
    by_id = {n["segment_id"]: n for n in nodes}
    children_of: dict[str | None, list[dict]] = {}
    for n in nodes:
        children_of.setdefault(n["parent_segment_id"], []).append(n)
    queue: deque[str] = deque()
    for n in nodes:
        if n["role"] == "ORIGIN":
            queue.append(n["segment_id"])
    while queue:
        cur = queue.popleft()
        cur_depth = by_id[cur]["depth"]
        for child in children_of.get(cur, []):
            child["depth"] = cur_depth + 1
            queue.append(child["segment_id"])

    return nodes, edges


def _reclassify_queue_victims(
    nodes: list[dict],
    today_onsets_by_seg: dict[str, int],
    bertini_segs_today: set[str],
    head_segs_today: set[str],
    v21_verdicts: dict[str, str],
    segment_order: tuple[str, ...],
) -> list[dict]:
    """Spec §7.3 step 4. Identify v2.1 QUEUE_VICTIM segments that fired *before*
    every adjacent ACTIVE_BOTTLENECK / HEAD_BOTTLENECK today."""
    seg_idx_of = {s: i for i, s in enumerate(segment_order)}
    bottleneck_segs = bertini_segs_today | head_segs_today
    out: list[dict] = []
    for seg, verdict in v21_verdicts.items():
        if verdict != "QUEUE_VICTIM":
            continue
        if seg not in today_onsets_by_seg:
            continue
        my_onset = today_onsets_by_seg[seg]
        idx = seg_idx_of.get(seg)
        if idx is None:
            continue
        adj_bottlenecks: list[tuple[str, int]] = []
        for adj_idx in (idx - 1, idx + 1):
            if 0 <= adj_idx < len(segment_order):
                adj_seg = segment_order[adj_idx]
                if adj_seg in bottleneck_segs and adj_seg in today_onsets_by_seg:
                    adj_bottlenecks.append((adj_seg, today_onsets_by_seg[adj_seg]))
        if not adj_bottlenecks:
            continue
        if all(my_onset < b_onset for _, b_onset in adj_bottlenecks):
            earliest_adj = min(b_onset for _, b_onset in adj_bottlenecks)
            tree_role = next((n["role"] for n in nodes if n["segment_id"] == seg), "ORIGIN")
            out.append({
                "segment_id": seg,
                "v21_verdict": "QUEUE_VICTIM",
                "tree_role": tree_role,
                "reason": "preceded supposed bottleneck",
                "earlier_by_minutes": (earliest_adj - my_onset) * 2,
            })
    return out


class JamTree(Tier1Module):
    name = "jam_tree"

    def required_inputs(self) -> set[str]:
        return {
            "regimes_today_by_idx",
            "today_onsets_by_seg",
            "segment_order",
            "segment_meta",
            "anchor_bucket",
            "bertini_events",
            "head_bottleneck_events",
            "v21_verdicts",
        }

    def run(self, ctx: Context) -> dict:
        seg_idx_of = {s: i for i, s in enumerate(ctx.segment_order)}
        onsets: list[tuple[str, int, int]] = []
        for sid, b in ctx.today_onsets_by_seg.items():
            if sid in seg_idx_of:
                onsets.append((sid, seg_idx_of[sid], int(b)))

        if not onsets:
            return {
                "nodes": [],
                "edges": [],
                "summary": {"n_origins": 0, "n_propagated": 0, "max_depth": 0, "n_reclassifications": 0},
                "queue_victim_reclassifications": [],
            }

        nodes, edges = _build_tree(onsets, n_segments=len(ctx.segment_order))

        bertini_segs_today = {ev.segment_id for ev in ctx.bertini_events}
        head_segs_today = {ev.segment_id for ev in ctx.head_bottleneck_events}
        reclass = _reclassify_queue_victims(
            nodes,
            today_onsets_by_seg=dict(ctx.today_onsets_by_seg),
            bertini_segs_today=bertini_segs_today,
            head_segs_today=head_segs_today,
            v21_verdicts=dict(ctx.v21_verdicts),
            segment_order=ctx.segment_order,
        )

        n_origins = sum(1 for n in nodes if n["role"] == "ORIGIN")
        n_propagated = sum(1 for n in nodes if n["role"] == "PROPAGATED")
        max_depth = max((n["depth"] for n in nodes), default=0)

        return {
            "nodes": nodes,
            "edges": edges,
            "summary": {
                "n_origins": n_origins,
                "n_propagated": n_propagated,
                "max_depth": max_depth,
                "n_reclassifications": len(reclass),
            },
            "queue_victim_reclassifications": reclass,
        }
