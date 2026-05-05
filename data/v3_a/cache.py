"""In-memory cache with TTL semantics. Spec §10.5."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CacheKey:
    corridor_id: str
    anchor_ts_truncated: str
    mode: str
    config_signature: str


@dataclass
class _Entry:
    envelope: dict
    expires_at: float | None  # None = never expires


class Cache:
    """In-memory ``CacheKey -> envelope`` map with optional TTL.

    Thread-safe via a single RLock around all reads/writes (cache traffic is
    light — no need for fine-grained locking).
    """

    def __init__(self) -> None:
        self._store: dict[CacheKey, _Entry] = {}
        self._lock = threading.RLock()

    def get(self, key: CacheKey) -> dict | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at is not None and time.monotonic() > entry.expires_at:
                # Lazy eviction
                self._store.pop(key, None)
                return None
            return entry.envelope

    def put(self, key: CacheKey, envelope: dict, ttl_sec: int | None) -> None:
        with self._lock:
            expires_at = time.monotonic() + ttl_sec if ttl_sec is not None else None
            self._store[key] = _Entry(envelope=envelope, expires_at=expires_at)

    def invalidate(self, key: CacheKey) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Process-wide singleton
_GLOBAL_CACHE = Cache()


def global_cache() -> Cache:
    return _GLOBAL_CACHE


__all__ = ["CacheKey", "Cache", "global_cache"]
