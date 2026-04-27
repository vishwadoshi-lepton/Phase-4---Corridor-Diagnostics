#!/usr/bin/env python3
"""
Pull per-day congestion onsets for the 48 v2.1 validation segments.

READ-ONLY. Mirrors the SQL in CORRIDOR_DIAGNOSTICS_V2_1_ENGINEER_HANDOFF.md §7.2:
for each (road_id, IST date), find the first 2-min minute-of-day where the
observed travel time stays above 1.5 × free-flow proxy for ≥ 10 minutes
(5 consecutive buckets).

Output: onsets/all_onsets_{slice}.json
Shape:  [ {"rid": ..., "dt": "YYYY-MM-DD", "om": minute_of_day_int}, ... ]

No free_flow_proxy table exists in this project — Stage 1 in v2.1 discovers
free-flow per segment from its own quietest 30 min. So we compute the
threshold on the fly from the same observations we're thresholding:
  ff_tt_proxy = 15th percentile of the segment's 01:30–05:30 IST travel times
                (matches v2.discover_freeflow's nightly-quiet window)

Usage:
  python3 pull_onsets.py --slice weekend
  python3 pull_onsets.py --slice weekday --days 30
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
ONSETS_DIR     = os.path.join(HERE, "onsets")

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
    dest = os.path.join(ONSETS_DIR, f"all_onsets_{slice_}.json")
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
    print(f"Pulling {slice_} onsets for {len(rids)} segments ({scope_label}), "
          f"last {days} calendar days, from {os.environ['POSTGRES_HOST']}...")

    # ff_tt_proxy: per-segment p15 of observations in 01:30-05:30 IST over the whole window.
    # Then for each (rid, day), find the first minute-of-day where tt > 1.5 × ff_tt_proxy
    # sustained for ≥ 5 consecutive 2-min buckets.
    sql = f"""
        WITH base AS (
            SELECT
                road_id,
                event_time AT TIME ZONE 'Asia/Kolkata' AS ist,
                current_travel_time_sec AS tt
              FROM traffic_observation
             WHERE road_id = ANY(%s)
               AND event_time >= now() - (%s || ' days')::interval
               AND EXTRACT(ISODOW FROM event_time AT TIME ZONE 'Asia/Kolkata') {SLICE_FILTER[slice_]}
        ),
        ff AS (
            SELECT
                road_id,
                percentile_cont(0.15) WITHIN GROUP (ORDER BY tt) AS ff_tt
              FROM base
             WHERE EXTRACT(HOUR FROM ist) BETWEEN 1 AND 5
               AND NOT (EXTRACT(HOUR FROM ist) = 5 AND EXTRACT(MINUTE FROM ist) > 30)
               AND NOT (EXTRACT(HOUR FROM ist) = 1 AND EXTRACT(MINUTE FROM ist) < 30)
             GROUP BY road_id
        ),
        bucketed AS (
            SELECT
                b.road_id,
                ist::date AS dt,
                (EXTRACT(HOUR FROM ist)::int * 60 + EXTRACT(MINUTE FROM ist)::int) AS mod_min,
                b.tt,
                ff.ff_tt * 1.5 AS thresh
              FROM base b
              JOIN ff USING (road_id)
        ),
        flagged AS (
            SELECT *, CASE WHEN tt > thresh THEN 1 ELSE 0 END AS over
              FROM bucketed
        ),
        runs AS (
            SELECT road_id, dt, mod_min,
                   SUM(over) OVER (PARTITION BY road_id, dt
                                   ORDER BY mod_min
                                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS sustained
              FROM flagged
        )
        SELECT road_id AS rid, dt::text AS dt, MIN(mod_min)::int AS om
          FROM runs
         WHERE sustained >= 5
         GROUP BY road_id, dt
         ORDER BY road_id, dt
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

    # Normalize to a list of plain dicts
    out = [{"rid": r["rid"], "dt": str(r["dt"]), "om": int(r["om"])} for r in rows]

    # Coverage summary
    per_seg: dict[str, int] = {}
    for o in out:
        per_seg[o["rid"]] = per_seg.get(o["rid"], 0) + 1
    covered = sum(1 for rid in rids if per_seg.get(rid, 0) >= 5)
    empty   = sum(1 for rid in rids if per_seg.get(rid, 0) == 0)
    print(f"  onset rows total: {len(out)}")
    print(f"  segments with ≥5 onset days: {covered}")
    print(f"  segments with 0 onset days:  {empty}")

    os.makedirs(ONSETS_DIR, exist_ok=True)
    if corridor_id is not None and os.path.isfile(dest):
        existing = json.load(open(dest))
        scoped_rids = set(rids)
        # Drop existing rows for the scoped rids, then append the freshly-pulled rows.
        existing = [row for row in existing if row["rid"] not in scoped_rids]
        out = existing + out
    with open(dest, "w") as f:
        json.dump(out, f)
    print(f"Wrote {dest}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", default="weekday", choices=list(SLICE_FILTER))
    ap.add_argument("--days",  type=int, default=30,
                    help="calendar-day lookback window (default 30)")
    ap.add_argument("--corridor",
                    help="restrict to one corridor_id from validation_corridors.json")
    ap.add_argument("--max-age",
                    help="skip pull if onsets file's mtime is younger than this "
                         "duration (e.g. '1h', '30m'); applies per slice")
    args = ap.parse_args()
    sys.exit(pull(args.slice, args.days, args.corridor, args.max_age))
