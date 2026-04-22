#!/usr/bin/env python3
"""
Local-only comparison of weekday vs weekend v2.1 structured outputs.

Reads two files on disk and prints a side-by-side table. No network, no DB,
no prod access — purely reads:
  runs/v2_1/v2_1_validation_structured.json                 (weekday)
  runs/v2_1/v2_1_validation_weekend_structured.json         (weekend)

Usage:
  python3 compare_slices.py
"""
from __future__ import annotations
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))
import corridor_diagnostics_v2 as v2  # noqa: E402

WD_PATH = os.path.join(PROJECT_ROOT, "runs", "v2_1", "v2_1_validation_structured.json")
WE_PATH = os.path.join(PROJECT_ROOT, "runs", "v2_1", "v2_1_validation_weekend_structured.json")

def systemic_verdict(d: dict) -> str:
    sv2  = (d.get("systemic_v2") or {}).get("max_fraction", 0) or 0
    sv21 = (d.get("systemic_v21") or {}).get("systemic_by_contig", False)
    return "SYSTEMIC" if sv2 >= v2.SYSTEMIC_ALL_FRACTION or sv21 else "POINT   "

def bottlenecks(d: dict) -> dict[str, str]:
    return {s: v for s, v in (d.get("verdicts") or {}).items()
            if v in ("ACTIVE_BOTTLENECK", "HEAD_BOTTLENECK")}

def summarize(d: dict) -> str:
    v = systemic_verdict(d)
    bcount = len(bottlenecks(d))
    pw = len(d.get("primary_windows_v21") or [])
    sim = (d.get("systemic_v2") or {}).get("max_fraction", 0) or 0
    sw  = (d.get("shockwave") or {}).get("pass_rate")
    sw_s = f"{sw*100:.0f}%" if sw is not None else "—"
    return f"{v}  bots={bcount:<2} pw={pw:<2} sim={sim*100:>3.0f}%  sw={sw_s}"

def main():
    WD = json.load(open(WD_PATH))
    WE = json.load(open(WE_PATH))

    print(f"{'corridor':<8}  {'weekday':<42}  {'weekend':<42}")
    print("-" * 98)
    for cid in WD:
        we = WE.get(cid, {})
        print(f"{cid:<8}  {summarize(WD[cid]):<42}  {summarize(we):<42}")

    print()
    print("=== per-corridor bottleneck segment deltas ===")
    for cid in WD:
        wd_b = bottlenecks(WD[cid])
        we_b = bottlenecks(WE.get(cid, {}))
        common = set(wd_b) & set(we_b)
        only_wd = set(wd_b) - set(we_b)
        only_we = set(we_b) - set(wd_b)
        print(f"\n{cid}:")
        print(f"  common ({len(common)}):       " +
              (", ".join(f"{s[:8]}={wd_b[s][:4]}" for s in sorted(common)) or "—"))
        print(f"  weekday-only ({len(only_wd)}): " +
              (", ".join(f"{s[:8]}={wd_b[s][:4]}" for s in sorted(only_wd)) or "—"))
        print(f"  weekend-only ({len(only_we)}): " +
              (", ".join(f"{s[:8]}={we_b[s][:4]}" for s in sorted(only_we)) or "—"))

    print()
    print("=== Stage 6 recurrence: ACTIVE/HEAD segments, band per slice ===")
    for cid in WD:
        wd = WD[cid]; we = WE.get(cid, {})
        segs = set(bottlenecks(wd)) | set(bottlenecks(we))
        if not segs:
            continue
        print(f"\n{cid}:")
        for s in sorted(segs):
            wd_v = (wd.get("verdicts") or {}).get(s, "—")
            we_v = (we.get("verdicts") or {}).get(s, "—")
            wd_r = (wd.get("recurrence") or {}).get(s) or {}
            we_r = (we.get("recurrence") or {}).get(s) or {}
            wd_lab = f"{wd_r.get('label','—')} ({wd_r.get('n_days',0)}/{wd_r.get('total_days',0)})"
            we_lab = f"{we_r.get('label','—')} ({we_r.get('n_days',0)}/{we_r.get('total_days',0)})"
            print(f"  {s[:8]}  weekday: {wd_v:<18} {wd_lab:<22}  weekend: {we_v:<18} {we_lab}")

if __name__ == "__main__":
    main()
