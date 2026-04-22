#!/usr/bin/env python3
"""Run v2.1 corridor diagnostic on the 6 validation corridors and emit full report.

--slice weekday|weekend selects which input/output set to use.

Input resolution per slice:
  profiles/all_profiles_{slice}.json  (falls back to all_profiles.json for weekday
                                       to preserve pre-slice artifacts)
  onsets/all_onsets_{slice}.json      (same fallback)

Outputs are always slice-suffixed:
  runs/v2_1/v2_1_validation_{slice}_report.txt
  runs/v2_1/v2_1_validation_{slice}_structured.json

With --legacy-names, weekday outputs use the original (non-suffixed) filenames
for backwards compatibility with older tooling.
"""
import argparse, json, sys, os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from corridor_diagnostics_v2_1 import diagnose_v21, render_v21, to_plain_dict

HERE         = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
OUT_DIR      = os.path.join(PROJECT_ROOT, "runs", "v2_1")


def resolve_input(kind: str, slice_: str) -> str:
    """Return path to profiles/onsets file for this slice, with legacy fallback."""
    suffixed = os.path.join(HERE, kind, f"all_{kind}_{slice_}.json")
    if os.path.isfile(suffixed):
        return suffixed
    # Legacy path for the weekday default — pre-slice pipeline wrote here
    legacy = os.path.join(HERE, kind, f"all_{kind}.json")
    if slice_ == "weekday" and os.path.isfile(legacy):
        return legacy
    raise FileNotFoundError(
        f"no {kind} file for slice={slice_}: looked for {suffixed}"
        + (f" and {legacy}" if slice_ == "weekday" else "")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", default="weekday", choices=["weekday", "weekend"])
    ap.add_argument("--legacy-names", action="store_true",
                    help="for slice=weekday, write un-suffixed output filenames")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    profiles_path = resolve_input("profiles", args.slice)
    onsets_path   = resolve_input("onsets", args.slice)
    corridors = json.load(open(f"{HERE}/validation_corridors.json"))
    profiles_raw = json.load(open(profiles_path))
    onsets    = json.load(open(onsets_path))

    print(f"slice={args.slice}")
    print(f"  profiles: {profiles_path}")
    print(f"  onsets:   {onsets_path}")

    onsets_by_seg = defaultdict(list)
    for row in onsets:
        onsets_by_seg[row["rid"]].append((row["dt"], row["om"]))

    profiles = {seg: {int(m): tt for m, tt in prof.items()} for seg, prof in profiles_raw.items()}

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
        raw_onsets = []
        for s in seg_order:
            for d, om in onsets_by_seg.get(s, []):
                raw_onsets.append((s, d, om))
        # Skip corridors where the slice has no profile data for the chain
        missing_profiles = [s for s in seg_order if s not in profiles or not profiles[s]]
        if missing_profiles:
            print(f"  SKIP {cid}: {len(missing_profiles)} segments missing profile data "
                  f"in slice={args.slice}")
            continue
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

    # Output naming
    if args.legacy_names and args.slice == "weekday":
        report_name     = "v2_1_validation_report.txt"
        structured_name = "v2_1_validation_structured.json"
    else:
        report_name     = f"v2_1_validation_{args.slice}_report.txt"
        structured_name = f"v2_1_validation_{args.slice}_structured.json"

    report_path     = os.path.join(OUT_DIR, report_name)
    structured_path = os.path.join(OUT_DIR, structured_name)
    with open(report_path, "w") as f:
        f.write("\n\n".join(reports))
    with open(structured_path, "w") as f:
        json.dump(structured, f, indent=2, default=str)

    print("\n\n" + "=" * 90)
    print(f"Wrote {len(structured)} corridor(s):")
    print(f"  {report_path}")
    print(f"  {structured_path}")


if __name__ == "__main__":
    main()
