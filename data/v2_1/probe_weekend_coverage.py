#!/usr/bin/env python3
"""
Probe weekend-coverage of the 48 v2.1 validation segments in traffic_observation.

READ-ONLY: the only SQL emitted is a single SELECT with a COUNT/GROUP BY.
No DDL, no DML, no transactions. psycopg2 opens a connection, runs one
query, prints a table, and closes. Nothing is written back to the DB.

Output decides whether the weekend pass is viable:
  - segments with weekend_days >= 15  → v2.1 can run on the weekend slice
  - segments with weekend_days <  15  → p15 free-flow estimate will be noisy;
                                          widen the analysis window or drop
                                          those segments from the weekend run
  - segments with weekend_rows == 0   → no weekend feed on this segment at all

Usage:
  export POSTGRES_HOST=... POSTGRES_PORT=... POSTGRES_DB=...
  export POSTGRES_USER=... POSTGRES_PASSWORD=...
  python3 probe_weekend_coverage.py                 # default 60-day window
  python3 probe_weekend_coverage.py --days 90       # widen window

The 48 road_ids come from validation_corridors.json (same file run_validation.py
consumes), so the probe scope matches the v2.1 regression set exactly.
"""
from __future__ import annotations
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _env import load_dotenv  # noqa: E402
load_dotenv()  # reads <project-root>/.env if present, doesn't overwrite shell vars

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

CORRIDORS_PATH = os.path.join(HERE, "validation_corridors.json")


def load_validation_road_ids() -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Flatten all chains in validation_corridors.json into (road_id, corridor, name) rows."""
    corridors = json.load(open(CORRIDORS_PATH))
    rids: list[str] = []
    meta: dict[str, tuple[str, str]] = {}
    for cid, c in corridors.items():
        for seg in c["chain"]:
            rid = seg["road_id"]
            if rid not in meta:
                rids.append(rid)
                meta[rid] = (cid, seg.get("road_name", rid[:8]))
    return rids, meta


def probe(days: int) -> int:
    rids, meta = load_validation_road_ids()
    missing_env = [v for v in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
                               "POSTGRES_USER", "POSTGRES_PASSWORD")
                   if not os.environ.get(v)]
    if missing_env:
        print(f"ERROR: missing env vars: {', '.join(missing_env)}", file=sys.stderr)
        return 2

    print(f"Probing traffic_observation on {os.environ['POSTGRES_HOST']}:"
          f"{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']} "
          f"(window: last {days} calendar days, weekends only)")
    print(f"Scope: {len(rids)} validation segments across "
          f"{len(set(cid for cid, _ in meta.values()))} corridors")
    print()

    sql = """
        SELECT road_id,
               COUNT(*)                                                                 AS weekend_rows,
               COUNT(DISTINCT (event_time AT TIME ZONE 'Asia/Kolkata')::date)           AS weekend_days,
               MIN((event_time AT TIME ZONE 'Asia/Kolkata')::date)                      AS earliest_ist,
               MAX((event_time AT TIME ZONE 'Asia/Kolkata')::date)                      AS latest_ist
          FROM traffic_observation
         WHERE road_id = ANY(%s)
           AND event_time >= now() - (%s || ' days')::interval
           AND EXTRACT(ISODOW FROM event_time AT TIME ZONE 'Asia/Kolkata') IN (6, 7)
         GROUP BY road_id
    """

    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    # Belt-and-braces read-only: start a transaction, set it read-only, run SELECT, rollback.
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql, (rids, str(days)))
                rows = cur.fetchall()
    finally:
        conn.close()

    by_rid: dict[str, dict] = {r["road_id"]: r for r in rows}

    # Tally for the go/no-go decision
    healthy = sparse = missing = 0
    for rid in rids:
        days_ct = (by_rid.get(rid) or {}).get("weekend_days", 0) or 0
        if days_ct >= 15:
            healthy += 1
        elif days_ct > 0:
            sparse += 1
        else:
            missing += 1

    # Per-segment table (grouped by corridor for readability)
    by_corridor: dict[str, list[str]] = {}
    for rid in rids:
        by_corridor.setdefault(meta[rid][0], []).append(rid)

    print(f"{'corridor':<8} {'seg':<4} {'rid':<10} "
          f"{'wknd_days':>9} {'wknd_rows':>10} "
          f"{'earliest':<11} {'latest':<11}  name")
    print("-" * 100)
    for cid, rid_list in by_corridor.items():
        for i, rid in enumerate(rid_list):
            row = by_rid.get(rid) or {}
            days_ct = row.get("weekend_days", 0) or 0
            rows_ct = row.get("weekend_rows", 0) or 0
            earliest = str(row.get("earliest_ist") or "—")
            latest   = str(row.get("latest_ist") or "—")
            status = "✓" if days_ct >= 15 else ("~" if days_ct > 0 else "✗")
            print(f"{cid:<8} S{i+1:02d}  {rid[:8]:<10} "
                  f"{days_ct:>9} {rows_ct:>10} "
                  f"{earliest:<11} {latest:<11}  {status} {meta[rid][1][:55]}")
        print()

    print("-" * 100)
    print(f"Summary: {healthy} healthy (≥15 weekend days), "
          f"{sparse} sparse (1–14 weekend days), "
          f"{missing} missing (0 weekend rows)   "
          f"/ {len(rids)} segments total")
    return 0 if healthy >= len(rids) // 2 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60,
                    help="calendar-day lookback window (default 60)")
    args = ap.parse_args()
    sys.exit(probe(args.days))
