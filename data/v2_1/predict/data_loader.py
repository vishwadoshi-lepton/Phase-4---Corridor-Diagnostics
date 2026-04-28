"""Load corridors, profiles, onsets, and v2.1 diagnosis."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List

from . import config as C


def load_corridors() -> Dict:
    return json.loads(C.CORRIDORS_PATH.read_text())


def load_profiles() -> Dict[str, Dict[int, float]]:
    """Return {road_id: {min_of_day_int: tt_sec_float}}."""
    raw = json.loads(C.PROFILES_PATH.read_text())
    out: Dict[str, Dict[int, float]] = {}
    for rid, prof in raw.items():
        out[rid] = {int(k): float(v) for k, v in prof.items()}
    return out


def load_onsets() -> List[Dict]:
    """Return list of {'rid', 'dt', 'om'} rows."""
    return json.loads(C.ONSETS_PATH.read_text())


def load_diagnosis() -> Dict:
    return json.loads(C.DIAGNOSIS_PATH.read_text())


def onsets_by_rid_date(onsets: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Index onsets: {rid: {date_str: onset_minute}}."""
    out: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in onsets:
        out[row["rid"]][row["dt"]] = int(row["om"])
    return out


def onset_dates_for_rid(onsets_by_rid: Dict, rid: str) -> List[str]:
    return sorted(onsets_by_rid.get(rid, {}).keys())
