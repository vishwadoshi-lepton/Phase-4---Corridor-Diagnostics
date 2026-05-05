"""SQL-backed data acquisition for v3-A. Spec §5.4 / §5.3.

Today's observations come back as raw rows. Historical baselines come back
SQL-aggregated to (seg, day, 2-min-bucket) so we don't drag tens of millions
of rows back into Python.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

from data.v2_1._env import load_dotenv

from .errors import DBUnreachable, SoftWarn, Warning_
from .progress import IST


# Module-level: load .env once on import (idempotent — safe to call many times).
load_dotenv()


# --------------------------------------------------------------------------- #
# Connection                                                                  #
# --------------------------------------------------------------------------- #


def pick_connection(corridor_id: str | None = None):
    """Open a psycopg2 connection.

    v2.1 uses single-host ``POSTGRES_HOST``; v3-A matches that. The
    ``corridor_id`` argument is reserved for future per-corridor routing
    (e.g. polyline-derived Delhi segments on a different instance), but
    is currently unused — single host for everything.
    """
    import psycopg2

    required = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [k for k in required if k not in os.environ]
    if missing:
        raise DBUnreachable(f"Missing env vars: {missing}", hint="Run `data/v2_1/_env.py` style .env load")

    try:
        return psycopg2.connect(
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            connect_timeout=10,
        )
    except psycopg2.OperationalError as oe:
        raise DBUnreachable(str(oe)) from oe


# --------------------------------------------------------------------------- #
# Data containers                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class Row:
    road_id: str
    event_time: datetime  # tz-aware IST
    travel_time_sec: float


@dataclass
class TodayPull:
    rows: list[Row]
    by_seg: dict[str, list[Row]]
    gap_warnings: list[Warning_]


@dataclass
class HistoricalAggPull:
    """SQL-aggregated baseline: per (seg, day, 2-min-bucket) median TT.

    Shape: ``by_seg_by_day[seg_id][date] -> dict[minute_of_day -> tt_sec]``.
    """

    by_seg_by_day: dict[str, dict[date, dict[int, float]]]
    distinct_days: list[date]


# --------------------------------------------------------------------------- #
# Today's observations (raw)                                                  #
# --------------------------------------------------------------------------- #


def pull_today_observations(conn, road_ids: list[str], anchor_ts: datetime) -> TodayPull:
    """Pull rows in the half-open interval [start_of_day(anchor), anchor + 2min). Spec §5.4.1."""
    if anchor_ts.tzinfo is None:
        anchor_ts = anchor_ts.replace(tzinfo=IST)
    start_of_day = anchor_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    upper_bound = anchor_ts + timedelta(minutes=2)

    sql = """
        SELECT road_id, event_time, current_travel_time_sec
        FROM traffic_observation
        WHERE road_id = ANY(%(road_ids)s::text[])
          AND event_time >= %(start_of_day)s::timestamptz
          AND event_time <  %(upper_bound)s::timestamptz
        ORDER BY road_id, event_time
    """
    rows = _fetch_rows(conn, sql, {"road_ids": list(road_ids), "start_of_day": start_of_day, "upper_bound": upper_bound})
    by_seg = _group_by_seg(rows, road_ids)
    gap_warnings = _detect_gaps(by_seg)
    return TodayPull(rows=rows, by_seg=by_seg, gap_warnings=gap_warnings)


# --------------------------------------------------------------------------- #
# Historical aggregates (baseline + same-DOW)                                 #
# --------------------------------------------------------------------------- #


def pull_baseline_aggregated(
    conn,
    road_ids: list[str],
    anchor_ts: datetime,
    *,
    calendar_days_lookback: int = 30,
) -> HistoricalAggPull:
    """22-weekday baseline: 30 calendar-day window before anchor.date(), weekdays only.

    Spec §5.4.2. Caller (``baseline.py``) further filters to the most-recent 22 distinct
    weekdays and computes the typical-day median across days.
    """
    if anchor_ts.tzinfo is None:
        anchor_ts = anchor_ts.replace(tzinfo=IST)
    window_end = anchor_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(days=calendar_days_lookback)
    return _pull_historical_aggregated(conn, road_ids, window_start, window_end, dow=None)


def pull_same_dow_aggregated(
    conn,
    road_ids: list[str],
    anchor_ts: datetime,
    *,
    n_weeks_lookback: int = 6,
) -> HistoricalAggPull:
    """Same-DOW track: lookback in weeks, only matching anchor's ISO-DOW. Spec §5.4.3."""
    if anchor_ts.tzinfo is None:
        anchor_ts = anchor_ts.replace(tzinfo=IST)
    window_end = anchor_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(weeks=n_weeks_lookback)
    target_dow = anchor_ts.isoweekday()  # 1..7
    return _pull_historical_aggregated(conn, road_ids, window_start, window_end, dow=target_dow)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _pull_historical_aggregated(conn, road_ids, window_start, window_end, *, dow: int | None) -> HistoricalAggPull:
    if dow is None:
        dow_clause = "AND extract(isodow from event_time at time zone 'Asia/Kolkata') BETWEEN 1 AND 5"
        params: dict = {"road_ids": list(road_ids), "window_start": window_start, "window_end": window_end}
    else:
        dow_clause = "AND extract(isodow from event_time at time zone 'Asia/Kolkata') = %(dow)s"
        params = {"road_ids": list(road_ids), "window_start": window_start, "window_end": window_end, "dow": dow}

    sql = f"""
        WITH bucketed AS (
            SELECT road_id,
                   (event_time AT TIME ZONE 'Asia/Kolkata')::date AS dt,
                   (FLOOR((extract(hour FROM event_time AT TIME ZONE 'Asia/Kolkata') * 60
                          + extract(minute FROM event_time AT TIME ZONE 'Asia/Kolkata')) / 2.0)::int * 2) AS minute_of_day,
                   current_travel_time_sec AS tt
              FROM traffic_observation
             WHERE road_id = ANY(%(road_ids)s::text[])
               AND event_time >= %(window_start)s::timestamptz
               AND event_time <  %(window_end)s::timestamptz
               {dow_clause}
        )
        SELECT road_id, dt, minute_of_day,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tt) AS tt_med
          FROM bucketed
         GROUP BY road_id, dt, minute_of_day
         ORDER BY road_id, dt, minute_of_day
    """

    cur = conn.cursor()
    cur.execute(sql, params)
    by_seg_by_day: dict[str, dict[date, dict[int, float]]] = {}
    distinct: set[date] = set()
    for rid, dt, mod, tt in cur.fetchall():
        seg = by_seg_by_day.setdefault(rid, {})
        day = seg.setdefault(dt, {})
        day[int(mod)] = float(tt)
        distinct.add(dt)
    cur.close()
    return HistoricalAggPull(by_seg_by_day=by_seg_by_day, distinct_days=sorted(distinct))


def _fetch_rows(conn, sql: str, params: dict) -> list[Row]:
    cur = conn.cursor()
    cur.execute(sql, params)
    out: list[Row] = []
    for rid, et, tt in cur.fetchall():
        if et.tzinfo is None:
            et = et.replace(tzinfo=IST)
        else:
            et = et.astimezone(IST)
        out.append(Row(rid, et, float(tt)))
    cur.close()
    return out


def _group_by_seg(rows: Iterable[Row], road_ids: Iterable[str]) -> dict[str, list[Row]]:
    by_seg: dict[str, list[Row]] = {rid: [] for rid in road_ids}
    for r in rows:
        if r.road_id in by_seg:
            by_seg[r.road_id].append(r)
        else:
            by_seg.setdefault(r.road_id, []).append(r)
    return by_seg


def _detect_gaps(by_seg: dict[str, list[Row]], threshold_min: float = 10.0) -> list[Warning_]:
    warnings: list[Warning_] = []
    for rid, seg_rows in by_seg.items():
        if len(seg_rows) < 2:
            continue
        worst_gap = max(
            (b.event_time - a.event_time).total_seconds() / 60.0
            for a, b in zip(seg_rows, seg_rows[1:])
        )
        if worst_gap > threshold_min:
            warnings.append(
                Warning_(
                    code=SoftWarn.DATA_GAP,
                    message=f"Segment {rid} has a {worst_gap:.0f}-minute gap in today's data",
                    context={"segment_id": rid, "gap_minutes": round(worst_gap, 1)},
                )
            )
    return warnings


__all__ = [
    "pick_connection",
    "Row",
    "TodayPull",
    "HistoricalAggPull",
    "pull_today_observations",
    "pull_baseline_aggregated",
    "pull_same_dow_aggregated",
]
