#!/usr/bin/env python3
"""Run v2.1 corridor diagnostic on the 6 validation corridors and emit full report."""
import json, sys, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from corridor_diagnostics_v2_1 import diagnose_v21, render_v21, to_plain_dict

HERE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
OUT_DIR      = os.path.join(PROJECT_ROOT, "runs", "v2_1")
os.makedirs(OUT_DIR, exist_ok=True)
corridors = json.load(open(f"{HERE}/validation_corridors.json"))
profiles  = json.load(open(f"{HERE}/profiles/all_profiles.json"))
onsets    = json.load(open(f"{HERE}/onsets/all_onsets.json"))

# group onsets by segment
onsets_by_seg = defaultdict(list)
for row in onsets:
    onsets_by_seg[row["rid"]].append((row["dt"], row["om"]))

# Convert profile minute-of-day -> int (JSON loads keys as strings)
profiles = {seg: {int(m): tt for m, tt in prof.items()} for seg, prof in profiles.items()}

reports = []
structured = {}

for cid, cdata in corridors.items():
    seg_order = [s["road_id"] for s in cdata["chain"]]
    seg_meta = {
        s["road_id"]: {
            "name": s.get("road_name", s["road_id"][:8]),
            "length_m": s["length_m"],
            "road_class": s.get("road_class", "unknown"),
        }
        for s in cdata["chain"]
    }

    # Build raw_onsets list: (seg, date, onset_min_of_day)
    raw_onsets = []
    for s in seg_order:
        for d, om in onsets_by_seg.get(s, []):
            raw_onsets.append((s, d, om))

    # Stage 6 input: onsets_by_day_by_seg is dict[date -> dict[seg -> first_onset]]
    # (not used by v2.1 directly — we pass raw_onsets for Stage 4)
    diag = diagnose_v21(
        corridor_id=cid,
        corridor_name=cdata.get("name", cid),
        segment_order=seg_order,
        segment_meta=seg_meta,
        profile_by_seg={s: profiles[s] for s in seg_order},
        raw_onsets=raw_onsets,
    )

    reports.append(render_v21(diag))
    structured[cid] = to_plain_dict(diag)

# write outputs
report_path     = os.path.join(OUT_DIR, "v2_1_validation_report.txt")
structured_path = os.path.join(OUT_DIR, "v2_1_validation_structured.json")
with open(report_path, "w") as f:
    f.write("\n\n".join(reports))
with open(structured_path, "w") as f:
    json.dump(structured, f, indent=2, default=str)

print("\n\n".join(reports))
print("\n\n" + "=" * 90)
print("Wrote:")
print(f"  {report_path}")
print(f"  {structured_path}")
