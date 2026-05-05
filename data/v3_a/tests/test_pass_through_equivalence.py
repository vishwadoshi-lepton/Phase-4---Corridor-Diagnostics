"""Pass-through equivalence test (gate b1). Spec §14.1.

In ``mode="retrospective"`` v3-A's ``run_v21_stages`` must call ``diagnose_v21``
with the same inputs and surface the same ``to_plain_dict`` output.

Uses cached profiles + onsets (`data/v2_1/profiles/all_profiles_weekday.json`,
`data/v2_1/onsets/all_onsets_weekday.json`) so the test runs without a live DB.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from data.v2_1 import corridor_diagnostics_v2_1 as v2_1
from data.v3_a.baseline import BaselineResult
from data.v3_a.stages_v21 import run_v21_stages


REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES = REPO_ROOT / "data" / "v2_1" / "profiles" / "all_profiles_weekday.json"
ONSETS = REPO_ROOT / "data" / "v2_1" / "onsets" / "all_onsets_weekday.json"
CORRIDORS = REPO_ROOT / "data" / "v2_1" / "validation_corridors.json"


def _load_corridor(cid: str) -> dict:
    with open(CORRIDORS) as f:
        cors = json.load(f)
    if cid not in cors:
        pytest.skip(f"corridor {cid} not in validation_corridors.json")
    return cors[cid]


def _load_profile_subset(road_ids: list[str]) -> dict[str, dict[int, int]]:
    if not PROFILES.exists():
        pytest.skip(f"missing {PROFILES}")
    with open(PROFILES) as f:
        all_p = json.load(f)
    out: dict[str, dict[int, int]] = {}
    for rid in road_ids:
        if rid in all_p and all_p[rid]:
            out[rid] = {int(k): int(v) for k, v in all_p[rid].items()}
    if len(out) < len(road_ids):
        missing = [r for r in road_ids if r not in out]
        pytest.skip(f"profile data missing for {len(missing)} segments")
    return out


def _load_onsets_subset(road_ids: list[str]) -> list[tuple[str, str, int]] | None:
    if not ONSETS.exists():
        return None
    with open(ONSETS) as f:
        all_o = json.load(f)
    rid_set = set(road_ids)
    return [(r["rid"], r["dt"], int(r["om"])) for r in all_o if r["rid"] in rid_set]


def _canonical(d):
    """Recursively normalise: sort dict keys, round floats to 6 decimals, tuple->list."""
    if isinstance(d, dict):
        return {k: _canonical(d[k]) for k in sorted(d.keys(), key=str)}
    if isinstance(d, (list, tuple)):
        return [_canonical(x) for x in d]
    if isinstance(d, float):
        return round(d, 6)
    return d


@pytest.mark.parametrize("corridor_id", ["KOL_B", "KOL_C", "DEL_AUROBINDO"])
def test_retrospective_matches_v21(corridor_id):
    c = _load_corridor(corridor_id)
    chain = c["chain"]
    segment_order = [s["road_id"] for s in chain]
    segment_meta = {
        s["road_id"]: {
            "name": s["road_name"],
            "length_m": s["length_m"],
            "road_class": s.get("road_class", "unknown"),
        }
        for s in chain
    }

    profile_by_seg = _load_profile_subset(segment_order)
    raw_onsets = _load_onsets_subset(segment_order)

    # v2.1 reference
    v21_ref = v2_1.diagnose_v21(
        corridor_id, c["name"], segment_order, segment_meta,
        profile_by_seg, raw_onsets=raw_onsets,
    )
    ref_dict = v2_1.to_plain_dict(v21_ref)

    # v3-A retrospective
    baseline = BaselineResult(
        profile_by_seg=profile_by_seg,
        n_actual_days=22,
        distinct_days=[date(2026, 4, 1)] * 22,
        thin=False,
    )
    result = run_v21_stages(
        corridor_id=corridor_id,
        corridor_name=c["name"],
        segment_order=segment_order,
        segment_meta=segment_meta,
        baseline=baseline,
        raw_onsets=raw_onsets,
        today_pull=None,
        anchor_ts=datetime(2026, 4, 1),
        mode="retrospective",
    )
    v3a_dict = v2_1.to_plain_dict(result.typical_v21)

    assert _canonical(v3a_dict) == _canonical(ref_dict), \
        f"v3-A retrospective output diverges from v2.1 for {corridor_id}"
