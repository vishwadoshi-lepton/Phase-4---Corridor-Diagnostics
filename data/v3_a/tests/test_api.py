"""Tests for api.py. Spec §15.1."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from data.v3_a import EngineConfig
from data.v3_a.api import (
    _reset_for_tests,
    get_run,
    list_runs,
    submit_run,
    wait_for_run,
)
from data.v3_a.baseline import BaselineResult, DowSamples
from data.v3_a.data_pull import Row, TodayPull
from data.v3_a.progress import IST, RunStatus


REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES = REPO_ROOT / "data" / "v2_1" / "profiles" / "all_profiles_weekday.json"
ONSETS = REPO_ROOT / "data" / "v2_1" / "onsets" / "all_onsets_weekday.json"
CORRIDORS = REPO_ROOT / "data" / "v2_1" / "validation_corridors.json"


@pytest.fixture(autouse=True)
def reset_state():
    _reset_for_tests()
    yield
    _reset_for_tests()


@pytest.fixture
def kol_b_inputs():
    if not PROFILES.exists():
        pytest.skip("missing cached profiles")
    with open(CORRIDORS) as f:
        c = json.load(f)["KOL_B"]
    seg_ord = [s["road_id"] for s in c["chain"]]
    with open(PROFILES) as f:
        p = json.load(f)
    profile_by_seg = {rid: {int(k): int(v) for k, v in p[rid].items()} for rid in seg_ord}
    with open(ONSETS) as f:
        onsets = json.load(f)
    raw_onsets = [(r["rid"], r["dt"], int(r["om"])) for r in onsets if r["rid"] in set(seg_ord)]
    baseline = BaselineResult(profile_by_seg=profile_by_seg, n_actual_days=22,
                              distinct_days=[date(2026, 4, 1)] * 22, thin=False)
    return seg_ord, baseline, raw_onsets, profile_by_seg


def test_retrospective_run_completes(kol_b_inputs):
    seg_ord, baseline, raw_onsets, _ = kol_b_inputs
    run_id = submit_run(
        "KOL_B", "2026-04-01T23:58:00+05:30", mode="retrospective",
        baseline_override=baseline, raw_onsets_override=raw_onsets,
    )
    rec = wait_for_run(run_id, timeout_sec=30)
    assert rec.status == RunStatus.COMPLETED, f"failed: {rec.error}"
    assert rec.result is not None
    assert rec.result["mode"] == "retrospective"
    assert rec.completed_at is not None


def test_two_submits_same_inputs_share_run_id(kol_b_inputs):
    _, baseline, raw_onsets, _ = kol_b_inputs
    a = submit_run("KOL_B", "2026-04-01T23:58:00+05:30", mode="retrospective",
                   baseline_override=baseline, raw_onsets_override=raw_onsets)
    b = submit_run("KOL_B", "2026-04-01T23:58:00+05:30", mode="retrospective",
                   baseline_override=baseline, raw_onsets_override=raw_onsets)
    assert a == b


def test_unknown_corridor_fails(kol_b_inputs):
    _, baseline, raw_onsets, _ = kol_b_inputs
    run_id = submit_run("NONEXISTENT", "2026-04-01T23:58:00+05:30", mode="retrospective",
                        baseline_override=baseline, raw_onsets_override=raw_onsets)
    rec = wait_for_run(run_id, timeout_sec=10)
    assert rec.status == RunStatus.FAILED
    assert rec.error["code"] == "HARD_ERR_UNKNOWN_CORRIDOR"


def test_future_anchor_fails(kol_b_inputs):
    _, baseline, raw_onsets, _ = kol_b_inputs
    future = datetime(2099, 1, 1, 12, 0, tzinfo=IST)
    run_id = submit_run("KOL_B", future, mode="retrospective",
                        baseline_override=baseline, raw_onsets_override=raw_onsets)
    rec = wait_for_run(run_id, timeout_sec=10)
    assert rec.status == RunStatus.FAILED
    assert rec.error["code"] == "HARD_ERR_FUTURE_ANCHOR"


def test_list_runs_filters(kol_b_inputs):
    _, baseline, raw_onsets, _ = kol_b_inputs
    rid = submit_run("KOL_B", "2026-04-01T23:58:00+05:30", mode="retrospective",
                     baseline_override=baseline, raw_onsets_override=raw_onsets)
    wait_for_run(rid, timeout_sec=30)
    completed = list_runs(corridor_id="KOL_B", status=RunStatus.COMPLETED)
    assert len(completed) == 1
    assert list_runs(corridor_id="OTHER") == []


def test_cache_hit_synthesises_completed_record(kol_b_inputs):
    _, baseline, raw_onsets, _ = kol_b_inputs
    rid_first = submit_run("KOL_B", "2026-04-01T23:58:00+05:30", mode="retrospective",
                           baseline_override=baseline, raw_onsets_override=raw_onsets)
    wait_for_run(rid_first, timeout_sec=30)
    # Second submit — same key, should hit cache and complete instantly
    rid_second = submit_run("KOL_B", "2026-04-01T23:58:00+05:30", mode="retrospective",
                            baseline_override=baseline, raw_onsets_override=raw_onsets)
    rec = get_run(rid_second)
    assert rec.status == RunStatus.COMPLETED
    assert any(e.stage == "cache_hit" for e in rec.events)
