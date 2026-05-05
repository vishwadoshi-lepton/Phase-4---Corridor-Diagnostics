"""Run lifecycle API — submit_run / get_run / list_runs / stream_events. Spec §10.

In-process, threaded. Persistence and HTTP wrapping live downstream of v3-A.
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
from datetime import datetime
from typing import Iterator

from . import EngineConfig
from .cache import Cache, CacheKey, global_cache
from .envelope import make_run_id
from .errors import HardError
from .progress import IST, ProgressEmitter, RunRecord, RunStatus, StageEvent, now_ist_iso
from .run import run_diagnostic


log = logging.getLogger("data.v3_a.api")


# --------------------------------------------------------------------------- #
# Module-level run registry                                                    #
# --------------------------------------------------------------------------- #


class _Registry:
    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.corridor_locks: dict[str, threading.Lock] = {}
        self.event_queues: dict[str, queue.Queue] = {}
        self.lock = threading.RLock()


_REG = _Registry()


def _reset_for_tests() -> None:
    """Test-only — wipe the in-memory state."""
    global _REG
    _REG = _Registry()
    global_cache().clear()


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def submit_run(
    corridor_id: str,
    anchor_ts: str | datetime,
    *,
    mode: str = "today_as_of_T",
    config: EngineConfig | None = None,
    no_cache: bool = False,
    cache: Cache | None = None,
    **diagnose_overrides,
) -> str:
    """Submit a run. Returns the ``run_id``.

    Caching:
      - Cache hit (within TTL or replay) → synthesize a completed RunRecord
        and return its run_id immediately. No worker thread spawned.
      - Cache miss → spawn a daemon worker thread.

    Concurrency:
      - If a run with the same ``run_id`` is already RUNNING/PENDING, reattach
        and return that run_id (no duplicate).
    """
    cfg = config or EngineConfig.default()
    sig = cfg.signature()
    anchor_dt = _parse_anchor(anchor_ts)
    truncated = _truncate_anchor(anchor_dt)
    run_id = make_run_id(corridor_id=corridor_id, anchor_ts=truncated, mode=mode, config_signature=sig)
    cache_obj = cache or global_cache()
    key = CacheKey(corridor_id=corridor_id, anchor_ts_truncated=truncated.isoformat(),
                   mode=mode, config_signature=sig)

    if not no_cache:
        cached = cache_obj.get(key)
        if cached is not None:
            return _record_cache_hit(run_id, cached, corridor_id, truncated, mode, sig)

    with _REG.lock:
        existing = _REG.runs.get(run_id)
        if existing is not None and existing.status in (RunStatus.PENDING, RunStatus.RUNNING):
            return run_id
        record = RunRecord(
            run_id=run_id, corridor_id=corridor_id,
            anchor_ts=truncated.isoformat(), mode=mode, config_signature=sig,
        )
        _REG.runs[run_id] = record
        _REG.event_queues[run_id] = queue.Queue()

    threading.Thread(
        target=_worker,
        args=(run_id, corridor_id, truncated, mode, cfg, cache_obj, key, diagnose_overrides),
        daemon=True,
    ).start()
    return run_id


def get_run(run_id: str) -> RunRecord:
    with _REG.lock:
        record = _REG.runs.get(run_id)
        if record is None:
            raise KeyError(run_id)
        return record


def list_runs(*, corridor_id: str | None = None, status: RunStatus | None = None) -> list[RunRecord]:
    with _REG.lock:
        out = list(_REG.runs.values())
    if corridor_id is not None:
        out = [r for r in out if r.corridor_id == corridor_id]
    if status is not None:
        out = [r for r in out if r.status == status]
    return out


def stream_events(run_id: str, *, timeout_sec: float | None = None) -> Iterator[StageEvent]:
    """Yield events as they arrive. Closes when the run reaches a terminal status."""
    with _REG.lock:
        if run_id not in _REG.runs:
            raise KeyError(run_id)
        q = _REG.event_queues[run_id]
        # First, replay events that already happened
        for ev in list(_REG.runs[run_id].events):
            yield ev
    while True:
        try:
            ev = q.get(timeout=timeout_sec)
        except queue.Empty:
            return
        if ev is None:  # sentinel
            return
        yield ev


def wait_for_run(run_id: str, *, timeout_sec: float | None = 60.0) -> RunRecord:
    """Block until the given run reaches a terminal status."""
    deadline = None if timeout_sec is None else (now_monotonic() + timeout_sec)
    while True:
        rec = get_run(run_id)
        if rec.status in (RunStatus.COMPLETED, RunStatus.FAILED):
            return rec
        if deadline is not None and now_monotonic() > deadline:
            return rec
        # Block on the queue briefly; events arrive while running.
        with _REG.lock:
            q = _REG.event_queues.get(run_id)
        if q is None:
            return rec
        try:
            ev = q.get(timeout=0.1)
            if ev is None:
                return get_run(run_id)
        except queue.Empty:
            continue


# --------------------------------------------------------------------------- #
# Internal                                                                    #
# --------------------------------------------------------------------------- #


def now_monotonic() -> float:
    import time
    return time.monotonic()


def _parse_anchor(anchor_ts: str | datetime) -> datetime:
    if isinstance(anchor_ts, datetime):
        dt = anchor_ts
    else:
        dt = datetime.fromisoformat(anchor_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt


def _truncate_anchor(dt: datetime) -> datetime:
    minute = dt.minute - (dt.minute % 2)
    return dt.replace(minute=minute, second=0, microsecond=0)


def _record_cache_hit(run_id: str, envelope: dict, corridor_id: str,
                      anchor: datetime, mode: str, sig: str) -> str:
    with _REG.lock:
        record = RunRecord(
            run_id=run_id, corridor_id=corridor_id,
            anchor_ts=anchor.isoformat(), mode=mode, config_signature=sig,
            status=RunStatus.COMPLETED,
            started_at=now_ist_iso(), completed_at=now_ist_iso(),
            result=envelope,
        )
        record.events.append(StageEvent(run_id=run_id, stage="cache_hit", status="completed", ts=now_ist_iso()))
        _REG.runs[run_id] = record
        # Empty queue with a sentinel so any concurrent stream_events terminates cleanly
        q = _REG.event_queues.setdefault(run_id, queue.Queue())
        q.put(None)
    return run_id


class _ApiEmitter(ProgressEmitter):
    def __init__(self, run_id: str, record: RunRecord, q: queue.Queue) -> None:
        self.run_id = run_id
        self.record = record
        self.q = q

    def emit(self, event: StageEvent) -> None:
        if not event.run_id:
            event = StageEvent(
                run_id=self.run_id, stage=event.stage, status=event.status,
                ts=event.ts, duration_ms=event.duration_ms, detail=event.detail,
            )
        with _REG.lock:
            self.record.events.append(event)
        self.q.put(event)


def _worker(run_id, corridor_id, anchor, mode, cfg, cache_obj, key, overrides):
    record = get_run(run_id)
    record.status = RunStatus.RUNNING
    record.started_at = now_ist_iso()
    q = _REG.event_queues[run_id]

    lock = _REG.corridor_locks.setdefault(corridor_id, threading.Lock())
    acquired = lock.acquire(timeout=cfg.run_timeout_sec)
    try:
        if not acquired:
            record.status = RunStatus.FAILED
            record.error = {"code": "HARD_ERR_TIMEOUT",
                            "message": f"could not acquire corridor lock within {cfg.run_timeout_sec}s",
                            "hint": "wait for the in-flight run", "context": {}}
            record.completed_at = now_ist_iso()
            return

        emitter = _ApiEmitter(run_id, record, q)
        try:
            envelope = run_diagnostic(
                corridor_id=corridor_id, anchor_ts=anchor, mode=mode,
                progress=emitter, config=cfg, **overrides,
            )
            record.result = envelope
            record.status = RunStatus.COMPLETED
            record.completed_at = now_ist_iso()
            ttl = cfg.cache_today_ttl_sec if anchor.date() == datetime.now(IST).date() else None
            cache_obj.put(key, envelope, ttl)
        except HardError as he:
            record.error = he.to_dict()
            record.status = RunStatus.FAILED
            record.completed_at = now_ist_iso()
        except Exception as e:
            record.error = {
                "code": "HARD_ERR_INTERNAL",
                "message": str(e),
                "hint": None,
                "context": {"traceback": traceback.format_exc()},
            }
            record.status = RunStatus.FAILED
            record.completed_at = now_ist_iso()
    finally:
        if acquired:
            lock.release()
        q.put(None)


__all__ = [
    "submit_run", "get_run", "list_runs", "stream_events", "wait_for_run",
    "_reset_for_tests",
]
