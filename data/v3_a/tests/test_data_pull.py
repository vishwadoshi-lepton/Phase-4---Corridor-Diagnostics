"""Tests for data_pull.py. Spec §15.1.

The SQL paths are smoke-tested separately against the live DB in step 5/15
(via the pass-through equivalence + Tier-1 sanity gates). Here we test:

  * gap detection helper
  * by-segment grouping helper
  * connection error path on missing env vars
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from data.v3_a.data_pull import (
    Row,
    _detect_gaps,
    _group_by_seg,
    pick_connection,
)
from data.v3_a.errors import DBUnreachable, SoftWarn
from data.v3_a.progress import IST


def _row(rid: str, t_min_offset: int, tt: float = 50.0) -> Row:
    base = datetime(2026, 5, 4, 0, 0, tzinfo=IST)
    return Row(rid, base + timedelta(minutes=t_min_offset), tt)


class TestDetectGaps:
    def test_no_gap(self):
        by_seg = {"a": [_row("a", 0), _row("a", 2), _row("a", 4)]}
        assert _detect_gaps(by_seg) == []

    def test_single_row_segment_skipped(self):
        by_seg = {"a": [_row("a", 0)]}
        assert _detect_gaps(by_seg) == []

    def test_empty_segment_skipped(self):
        assert _detect_gaps({"a": []}) == []

    def test_gap_above_threshold_emits_warning(self):
        by_seg = {"a": [_row("a", 0), _row("a", 2), _row("a", 30)]}  # 28-min gap
        ws = _detect_gaps(by_seg)
        assert len(ws) == 1
        assert ws[0].code == SoftWarn.DATA_GAP
        assert ws[0].context["segment_id"] == "a"
        assert ws[0].context["gap_minutes"] == pytest.approx(28.0)

    def test_gap_below_threshold_silent(self):
        by_seg = {"a": [_row("a", 0), _row("a", 2), _row("a", 11)]}  # 9-min gap
        assert _detect_gaps(by_seg) == []

    def test_threshold_boundary_strict(self):
        # threshold 10.0 → exactly 10 is NOT a warning (strict >)
        by_seg = {"a": [_row("a", 0), _row("a", 10)]}
        assert _detect_gaps(by_seg) == []

    def test_multiple_segments(self):
        by_seg = {
            "good": [_row("good", 0), _row("good", 2)],
            "bad":  [_row("bad", 0),  _row("bad", 50)],
        }
        ws = _detect_gaps(by_seg)
        assert len(ws) == 1
        assert ws[0].context["segment_id"] == "bad"


class TestGroupBySeg:
    def test_groups_in_order(self):
        rows = [_row("a", 0), _row("b", 1), _row("a", 2)]
        out = _group_by_seg(rows, ["a", "b"])
        assert list(out["a"]) == [rows[0], rows[2]]
        assert list(out["b"]) == [rows[1]]

    def test_empty_segments_present(self):
        out = _group_by_seg([], ["a", "b"])
        assert out == {"a": [], "b": []}

    def test_unexpected_seg_still_kept(self):
        rows = [_row("c", 0)]
        out = _group_by_seg(rows, ["a"])
        assert "c" in out and out["c"] == rows
        assert out["a"] == []


class TestPickConnection:
    def test_missing_env_raises(self, monkeypatch):
        for k in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(DBUnreachable) as ei:
            pick_connection()
        assert "Missing env vars" in ei.value.message
