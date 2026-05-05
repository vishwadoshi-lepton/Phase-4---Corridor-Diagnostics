"""Tests for tier1/jam_tree.py. Spec §15.1."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from data.v3_a import EngineConfig
from data.v3_a.progress import IST
from data.v3_a.tier1 import BertiniEvent, Context
from data.v3_a.tier1.jam_tree import (
    JamTree,
    _build_tree,
    _reclassify_queue_victims,
)


def _ctx(*, segment_order, today_onsets_by_seg, bertini_events=(), head_events=(), v21_verdicts=None):
    cfg = EngineConfig.default()
    n = len(segment_order)
    seg_meta = {s: {"length_m": 100} for s in segment_order}
    if v21_verdicts is None:
        v21_verdicts = {s: "FREE_FLOW" for s in segment_order}
    return Context(
        corridor_id="TEST",
        corridor_name="Test",
        anchor_ts=datetime(2026, 5, 4, 23, 58, tzinfo=IST),
        anchor_bucket=719,
        today_date=date(2026, 5, 4),
        segment_order=tuple(segment_order),
        segment_meta=seg_meta,
        total_length_m=100.0 * n,
        n_buckets=720,
        regimes_today_by_idx=tuple(tuple(["FREE"] * 720) for _ in range(n)),
        regimes_typical_by_idx=tuple(tuple(["FREE"] * 720) for _ in range(n)),
        bertini_events=tuple(bertini_events),
        head_bottleneck_events=tuple(head_events),
        primary_windows_today=(),
        historical_onsets_by_seg={},
        today_onsets_by_seg=dict(today_onsets_by_seg),
        speed_today_by_idx=tuple(tuple([60.0] * 720) for _ in range(n)),
        ff_speed_kmph_by_seg={s: 60.0 for s in segment_order},
        v21_verdicts=v21_verdicts,
        config=cfg,
    )


class TestBuildTree:
    def test_single_origin_no_neighbours(self):
        onsets = [("s1", 0, 100)]
        nodes, edges = _build_tree(onsets, n_segments=1)
        assert len(nodes) == 1
        assert nodes[0]["role"] == "ORIGIN"
        assert nodes[0]["depth"] == 0
        assert edges == []

    def test_chain_propagation(self):
        # 3 segs, onsets at buckets 100, 110, 130 → chain 0→1→2
        onsets = [("a", 0, 100), ("b", 1, 110), ("c", 2, 130)]
        nodes, edges = _build_tree(onsets, n_segments=3)
        by_id = {n["segment_id"]: n for n in nodes}
        assert by_id["a"]["role"] == "ORIGIN"
        assert by_id["a"]["depth"] == 0
        assert by_id["b"]["role"] == "PROPAGATED"
        assert by_id["b"]["parent_segment_id"] == "a"
        assert by_id["b"]["depth"] == 1
        assert by_id["c"]["parent_segment_id"] == "b"
        assert by_id["c"]["depth"] == 2
        assert any(e["lag_minutes"] == 20 for e in edges)  # 110 - 100 = 10 buckets * 2 min = 20 min
        assert any(e["lag_minutes"] == 40 for e in edges)  # 130 - 110

    def test_two_origins_disconnected(self):
        # 4 segs; onsets at idx 0 and idx 2 (not adjacent through onset graph)
        onsets = [("a", 0, 100), ("c", 2, 110)]
        nodes, edges = _build_tree(onsets, n_segments=4)
        # idx 0 has no onset-having neighbour (idx 1 has no onset) → ORIGIN
        # idx 2 has no onset-having earlier neighbour (idx 1 absent, idx 3 absent) → ORIGIN
        for n in nodes:
            assert n["role"] == "ORIGIN"
        assert edges == []

    def test_picks_latest_earlier_onset_as_parent(self):
        # idx 1 has TWO onset neighbours both earlier: idx 0 at 100, idx 2 at 105
        # idx 1 onset at 110. Closer-in-time = idx 2 (105 vs 100).
        onsets = [("left", 0, 100), ("right", 2, 105), ("mid", 1, 110)]
        nodes, edges = _build_tree(onsets, n_segments=3)
        mid = next(n for n in nodes if n["segment_id"] == "mid")
        assert mid["parent_segment_id"] == "right"


class TestReclassify:
    def test_victim_preceded_bottleneck(self):
        # idx 0 = bottleneck (onset 110), idx 1 = victim (onset 100, earlier)
        recs = _reclassify_queue_victims(
            nodes=[
                {"segment_id": "victim", "role": "ORIGIN"},
                {"segment_id": "bot", "role": "ORIGIN"},
            ],
            today_onsets_by_seg={"victim": 100, "bot": 110},
            bertini_segs_today={"bot"},
            head_segs_today=set(),
            v21_verdicts={"victim": "QUEUE_VICTIM", "bot": "ACTIVE_BOTTLENECK"},
            segment_order=("victim", "bot"),
        )
        assert len(recs) == 1
        assert recs[0]["segment_id"] == "victim"
        assert recs[0]["earlier_by_minutes"] == 20

    def test_victim_after_bottleneck_not_reclassified(self):
        recs = _reclassify_queue_victims(
            nodes=[],
            today_onsets_by_seg={"victim": 120, "bot": 110},
            bertini_segs_today={"bot"},
            head_segs_today=set(),
            v21_verdicts={"victim": "QUEUE_VICTIM", "bot": "ACTIVE_BOTTLENECK"},
            segment_order=("victim", "bot"),
        )
        assert recs == []

    def test_no_adjacent_bottleneck_no_reclassify(self):
        recs = _reclassify_queue_victims(
            nodes=[],
            today_onsets_by_seg={"victim": 100},
            bertini_segs_today=set(),
            head_segs_today=set(),
            v21_verdicts={"victim": "QUEUE_VICTIM"},
            segment_order=("victim",),
        )
        assert recs == []


class TestJamTreeModule:
    def test_quiet_corridor_returns_empty(self):
        ctx = _ctx(segment_order=["a", "b"], today_onsets_by_seg={})
        out = JamTree().run(ctx)
        assert out["nodes"] == []
        assert out["summary"]["n_origins"] == 0

    def test_compresses_chain_to_one_origin(self):
        ctx = _ctx(
            segment_order=["a", "b", "c", "d"],
            today_onsets_by_seg={"a": 100, "b": 105, "c": 110, "d": 115},
        )
        out = JamTree().run(ctx)
        assert out["summary"]["n_origins"] == 1
        assert out["summary"]["n_propagated"] == 3
        assert out["summary"]["max_depth"] == 3

    def test_reclassification_surfaces(self):
        # idx 0 = bot (onset 110), idx 1 = victim (onset 100)
        bertini = [BertiniEvent("bot", 0, 110, 130, "BERTINI", 1)]
        ctx = _ctx(
            segment_order=["bot", "victim"],
            today_onsets_by_seg={"bot": 110, "victim": 100},
            bertini_events=bertini,
            v21_verdicts={"bot": "ACTIVE_BOTTLENECK", "victim": "QUEUE_VICTIM"},
        )
        out = JamTree().run(ctx)
        assert out["summary"]["n_reclassifications"] == 1
        assert out["queue_victim_reclassifications"][0]["segment_id"] == "victim"
