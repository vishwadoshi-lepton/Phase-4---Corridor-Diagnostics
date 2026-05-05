"""Tests for envelope.py. Spec §15.1."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from data.v2_1 import corridor_diagnostics_v2_1 as v2_1
from data.v3_a import EngineConfig
from data.v3_a.baseline import BaselineResult, DowSamples
from data.v3_a.envelope import build_envelope, make_run_id
from data.v3_a.progress import IST
from data.v3_a.stages_v21 import V21StagesResult, run_v21_stages


REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES = REPO_ROOT / "data" / "v2_1" / "profiles" / "all_profiles_weekday.json"
ONSETS = REPO_ROOT / "data" / "v2_1" / "onsets" / "all_onsets_weekday.json"
CORRIDORS = REPO_ROOT / "data" / "v2_1" / "validation_corridors.json"


@pytest.fixture
def kol_b_setup():
    if not PROFILES.exists():
        pytest.skip("missing cached profiles")
    with open(CORRIDORS) as f:
        c = json.load(f)["KOL_B"]
    chain = c["chain"]
    segment_order = [s["road_id"] for s in chain]
    segment_meta = {
        s["road_id"]: {"name": s["road_name"], "length_m": s["length_m"], "road_class": s.get("road_class", "unknown")}
        for s in chain
    }
    with open(PROFILES) as f:
        all_p = json.load(f)
    profile_by_seg = {rid: {int(k): int(v) for k, v in all_p[rid].items()} for rid in segment_order if rid in all_p}
    if len(profile_by_seg) < len(segment_order):
        pytest.skip("partial profile data")
    with open(ONSETS) as f:
        all_o = json.load(f)
    rid_set = set(segment_order)
    onsets = [(r["rid"], r["dt"], int(r["om"])) for r in all_o if r["rid"] in rid_set]
    baseline = BaselineResult(profile_by_seg=profile_by_seg, n_actual_days=22, distinct_days=[date(2026, 4, 1)] * 22, thin=False)
    return c, segment_order, segment_meta, baseline, onsets


class TestRunIdDeterminism:
    def test_same_inputs_same_id(self):
        anchor = datetime(2026, 5, 4, 19, 0, tzinfo=IST)
        a = make_run_id(corridor_id="KOL_B", anchor_ts=anchor, mode="today_as_of_T", config_signature="sha256:abc")
        b = make_run_id(corridor_id="KOL_B", anchor_ts=anchor, mode="today_as_of_T", config_signature="sha256:abc")
        assert a == b

    def test_format(self):
        anchor = datetime(2026, 5, 4, 19, 0, tzinfo=IST)
        rid = make_run_id(corridor_id="KOL_B", anchor_ts=anchor, mode="today_as_of_T", config_signature="sha256:abc")
        assert rid.startswith("v3a-20260504T190000-KOL_B-")
        assert len(rid.split("-")[-1]) == 4

    def test_different_inputs_different_ids(self):
        anchor = datetime(2026, 5, 4, 19, 0, tzinfo=IST)
        a = make_run_id(corridor_id="KOL_B", anchor_ts=anchor, mode="today_as_of_T", config_signature="sha256:abc")
        b = make_run_id(corridor_id="KOL_C", anchor_ts=anchor, mode="today_as_of_T", config_signature="sha256:abc")
        assert a != b


class TestEnvelopeStructure:
    def test_retrospective_envelope_keys(self, kol_b_setup):
        c, segment_order, segment_meta, baseline, onsets = kol_b_setup
        cfg = EngineConfig.default()
        anchor = datetime(2026, 5, 4, 23, 58, tzinfo=IST)
        stages = run_v21_stages(
            corridor_id="KOL_B", corridor_name=c["name"],
            segment_order=segment_order, segment_meta=segment_meta,
            baseline=baseline, raw_onsets=onsets, today_pull=None,
            anchor_ts=anchor, mode="retrospective",
        )
        dow_samples = DowSamples(by_seg_by_day={}, distinct_days=[], n_samples=0, dow=1, available=False)
        env = build_envelope(
            corridor_id="KOL_B", corridor_name=c["name"], anchor_ts=anchor,
            mode="retrospective", config=cfg, stages=stages,
            tier1_payloads={}, dow_anomaly_payload={"available": False, "n_samples": 0, "reason": "insufficient_samples"},
            baseline_result=baseline, dow_samples=dow_samples, warnings=[],
            anchor_ts_received=anchor.isoformat(),
        )
        # Top-level keys (in order)
        expected_top = [
            "schema_version", "engine_version", "mode", "corridor_id", "corridor_name",
            "anchor_ts", "run_id", "computed_at", "meta", "payload",
        ]
        assert list(env.keys()) == expected_top
        assert env["schema_version"] == "v3"
        assert env["engine_version"] == "v3.a.0"
        assert env["mode"] == "retrospective"
        assert env["meta"]["partial"] is False
        assert env["meta"]["tier1_modules_run"] == []
        assert "stages_v21" in env["payload"]

    def test_partial_when_module_skipped(self, kol_b_setup):
        c, segment_order, segment_meta, baseline, onsets = kol_b_setup
        cfg = EngineConfig.default()
        anchor = datetime(2026, 5, 4, 23, 58, tzinfo=IST)
        stages = run_v21_stages(
            corridor_id="KOL_B", corridor_name=c["name"],
            segment_order=segment_order, segment_meta=segment_meta,
            baseline=baseline, raw_onsets=onsets, today_pull=None,
            anchor_ts=anchor, mode="retrospective",
        )
        dow_samples = DowSamples(by_seg_by_day={}, distinct_days=[], n_samples=0, dow=1, available=False)
        env = build_envelope(
            corridor_id="KOL_B", corridor_name=c["name"], anchor_ts=anchor,
            mode="retrospective", config=cfg, stages=stages,
            tier1_payloads={"growth_rate": None},     # one skipped
            dow_anomaly_payload={"available": False},
            baseline_result=baseline, dow_samples=dow_samples,
            warnings=[{"code": "SOFT_WARN_TIER1_GROWTH_RATE_FAILED", "message": "x", "context": {}}],
            anchor_ts_received=anchor.isoformat(),
        )
        assert env["meta"]["partial"] is True
        assert env["meta"]["tier1_modules_skipped"] == ["growth_rate"]
        assert any(w["code"] == "SOFT_WARN_TIER1_GROWTH_RATE_FAILED" for w in env["meta"]["warnings"])

    def test_module_payload_warnings_hoisted_to_meta(self, kol_b_setup):
        c, segment_order, segment_meta, baseline, onsets = kol_b_setup
        cfg = EngineConfig.default()
        anchor = datetime(2026, 5, 4, 23, 58, tzinfo=IST)
        stages = run_v21_stages(
            corridor_id="KOL_B", corridor_name=c["name"],
            segment_order=segment_order, segment_meta=segment_meta,
            baseline=baseline, raw_onsets=onsets, today_pull=None,
            anchor_ts=anchor, mode="retrospective",
        )
        dow_samples = DowSamples(by_seg_by_day={}, distinct_days=[], n_samples=0, dow=1, available=False)
        # MFD payload includes warnings → must be hoisted
        env = build_envelope(
            corridor_id="KOL_B", corridor_name=c["name"], anchor_ts=anchor,
            mode="retrospective", config=cfg, stages=stages,
            tier1_payloads={"mfd": {"loop_area": 0.0, "warnings": [{"code": "SOFT_WARN_MFD_THIN", "message": "thin", "context": {}}]}},
            dow_anomaly_payload={"available": False},
            baseline_result=baseline, dow_samples=dow_samples, warnings=[],
            anchor_ts_received=anchor.isoformat(),
        )
        warns = env["meta"]["warnings"]
        assert any(w["code"] == "SOFT_WARN_MFD_THIN" for w in warns)
        # And the warnings key has been popped from the module payload
        assert "warnings" not in env["payload"]["tier1"]["mfd"]
        assert env["meta"]["partial"] is True
