"""
run_blind_new.py — blind-test the v2 diagnostic pipeline on the three new
corridors JBN / BAP / HDV (39 segments total).

No onset rows are supplied, so Stage 4 uses the fallback (median-profile
centroid) shockwave test. This is the same stance the original-4 regression
was run under after the DB downtime, so the two runs are directly comparable.
"""
import sys, pathlib
sys.path.insert(0, "/sessions/magical-gifted-meitner")

from corridor_diagnostics_v2 import diagnose, render
from corridors_v2 import NEW_CORRIDORS
from profiles_new import PROFILES, SEG_LENGTHS_M


def run_one(cdef):
    seg_order = [rid for rid, _name in cdef["chain"]]
    seg_meta = {rid: {"name": name, "length_m": SEG_LENGTHS_M[rid]}
                for rid, name in cdef["chain"]}

    # Sanity: every segment has a profile
    missing = [rid for rid in seg_order if rid not in PROFILES]
    if missing:
        raise SystemExit(f"!! {cdef['id']}: missing profiles for {missing}")

    prof = {rid: PROFILES[rid] for rid in seg_order}
    diag = diagnose(cdef["id"], cdef["name"], seg_order, seg_meta, prof)
    return render(diag), diag


def main():
    out_dir = pathlib.Path("/sessions/magical-gifted-meitner")
    joined = []
    for cdef in NEW_CORRIDORS:
        text, diag = run_one(cdef)
        path = out_dir / f"v2_blind_{cdef['id']}.txt"
        path.write_text(text + "\n")
        print(f"-> {path}  ({len(text)} chars)")
        joined.append(text)

    all_path = out_dir / "v2_blind_new_run.txt"
    all_path.write_text("\n\n\n".join(joined) + "\n")
    print(f"-> {all_path}")


if __name__ == "__main__":
    main()
