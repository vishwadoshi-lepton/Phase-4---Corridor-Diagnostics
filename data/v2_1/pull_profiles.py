#!/usr/bin/env python3
"""
Pull 2-min median travel-time profiles for the 48 v2.1 validation segments.

READ-ONLY: single SELECT with percentile_cont(0.5) and GROUP BY. No DDL, no DML.

Output: profiles/all_profiles_{slice}.json
Shape:  { road_id: { minute_of_day: tt_sec, ... } }  — compatible with run_validation.py

The SELECT computes, per (road_id, 2-min bucket), the median travel time across
all observations in the window that fall in the requested day-of-week slice:

  slice=weekday  → ISODOW BETWEEN 1 AND 5
  slice=weekend  → ISODOW IN (6, 7)

Why median (p50) and not mean: the 2-min window already aggregates every
minute-level observation in that bucket across N days; a single noisy probe
sample or freak traffic-light backup can skew the mean. Median is robust and
matches the "weekday-median 2-min profile" language in the PRD.

Usage:
  python3 pull_profiles.py --slice weekend
  python3 pull_profiles.py --slice weekday --days 30
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _env import load_dotenv  # noqa: E402
load_dotenv()

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

CORRIDORS_PATH = os.path.join(HERE, "validation_corridors.json")
PROFILES_DIR   = os.path.join(HERE, "profiles")

SLICE_FILTER = {
    "weekday": "BETWEEN 1 AND 5",
    "weekend": "IN (6, 7)",
}

import re, time  # noqa: E402

def _parse_duration_seconds(s: str) -> int:
    """Parse '1h', '30m', '2h30m', '90s' → seconds. Raises on bad input."""
    m = re.fullmatch(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\s*", s or "")
    if not m or not any(m.groups()):
        raise ValueError(f"unparseable duration: {s!r}")
    h, mn, sc = (int(g or 0) for g in m.groups())
    return h * 3600 + mn * 60 + sc

def _is_cache_fresh(path: str, max_age: str | None) -> bool:
    if not max_age or not os.path.isfile(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < _parse_duration_seconds(max_age)


def load_validation_road_ids(corridor_id: str | None = None) -> list[str]:
    corridors = json.load(open(CORRIDORS_PATH))
    rids: list[str] = []
    for cid, c in corridors.items():
        if corridor_id is not None and cid != corridor_id:
            continue
        for seg in c["chain"]:
            if seg["road_id"] not in rids:
                rids.append(seg["road_id"])
    if corridor_id is not None and not rids:
        raise SystemExit(f"ERROR: corridor_id '{corridor_id}' not found in "
                         f"{CORRIDORS_PATH}")
    return rids


def pull(slice_: str, days: int, corridor_id: str | None = None,
         max_age: str | None = None) -> int:
    if slice_ not in SLICE_FILTER:
        print(f"ERROR: slice must be one of {list(SLICE_FILTER)}", file=sys.stderr)
        return 2
    dest = os.path.join(PROFILES_DIR, f"all_profiles_{slice_}.json")
    if _is_cache_fresh(dest, max_age):
        print(f"Cache fresh ({max_age}): skipping pull, reusing {dest}")
        return 0
    missing = [v for v in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                           "POSTGRES_USER", "POSTGRES_PASSWORD")
               if not os.environ.get(v)]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    rids = load_validation_road_ids(corridor_id)
    scope_label = f"corridor={corridor_id}" if corridor_id else "all corridors"
    print(f"Pulling {slice_} profiles for {len(rids)} segments ({scope_label}), "
          f"last {days} calendar days, from {os.environ['POSTGRES_HOST']}...")

    sql = f"""
        SELECT
            road_id,
            (EXTRACT(HOUR   FROM event_time AT TIME ZONE 'Asia/Kolkata')::int * 30
           + EXTRACT(MINUTE FROM event_time AT TIME ZONE 'Asia/Kolkata')::int / 2) AS bkt,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY current_travel_time_sec) AS tt
          FROM traffic_observation
         WHERE road_id = ANY(%s)
           AND event_time >= now() - (%s || ' days')::interval
           AND EXTRACT(ISODOW FROM event_time AT TIME ZONE 'Asia/Kolkata') {SLICE_FILTER[slice_]}
         GROUP BY road_id, bkt
         ORDER BY road_id, bkt
    """

    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql, (rids, str(days)))
                rows = cur.fetchall()
    finally:
        conn.close()

    # Roll up: { road_id: { minute_of_day: tt_sec } }
    out: dict[str, dict[int, int]] = {rid: {} for rid in rids}
    for r in rows:
        rid = r["road_id"]
        bkt = int(r["bkt"])
        if 0 <= bkt < 720:
            out[rid][bkt * 2] = int(round(float(r["tt"])))

    # Coverage report
    covered = [rid for rid, prof in out.items() if len(prof) >= 600]  # ≥ 20 hrs of buckets
    thin    = [rid for rid, prof in out.items() if 0 < len(prof) < 600]
    empty   = [rid for rid, prof in out.items() if len(prof) == 0]
    print(f"  full coverage: {len(covered)} segs (≥600 of 720 buckets)")
    print(f"  thin coverage: {len(thin)} segs ({', '.join(r[:8] for r in thin) or '—'})")
    print(f"  empty:         {len(empty)} segs ({', '.join(r[:8] for r in empty) or '—'})")

    os.makedirs(PROFILES_DIR, exist_ok=True)
    if corridor_id is not None and os.path.isfile(dest):
        existing = json.load(open(dest))
        # Don't overwrite other corridors' road_ids; only update ones we just pulled.
        for rid, prof in out.items():
            existing[rid] = prof
        out = existing
    with open(dest, "w") as f:
        json.dump(out, f)
    print(f"Wrote {dest}  ({sum(len(p) for p in out.values())} bucket rows)")
    return 0 if not empty else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", default="weekday", choices=list(SLICE_FILTER))
    ap.add_argument("--days",  type=int, default=30,
                    help="calendar-day lookback window (default 30)")
    ap.add_argument("--corridor",
                    help="restrict to one corridor_id from validation_corridors.json")
    ap.add_argument("--max-age",
                    help="skip pull if profiles file's mtime is younger than this "
                         "duration (e.g. '1h', '30m'); applies per slice")
    args = ap.parse_args()
    sys.exit(pull(args.slice, args.days, args.corridor, args.max_age))
