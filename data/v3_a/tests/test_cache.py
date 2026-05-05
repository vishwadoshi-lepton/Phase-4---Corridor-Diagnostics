"""Tests for cache.py. Spec §15.1."""

from __future__ import annotations

import time

import pytest

from data.v3_a.cache import Cache, CacheKey


def _key(corridor="KOL_B", anchor="2026-05-04T19:00:00+05:30", mode="today_as_of_T", sig="sha256:abc"):
    return CacheKey(corridor_id=corridor, anchor_ts_truncated=anchor, mode=mode, config_signature=sig)


class TestCacheBasic:
    def test_miss_returns_none(self):
        c = Cache()
        assert c.get(_key()) is None

    def test_put_then_get(self):
        c = Cache()
        env = {"k": "v"}
        c.put(_key(), env, ttl_sec=300)
        assert c.get(_key()) == env

    def test_invalidate(self):
        c = Cache()
        c.put(_key(), {"k": "v"}, ttl_sec=300)
        c.invalidate(_key())
        assert c.get(_key()) is None

    def test_clear(self):
        c = Cache()
        c.put(_key(corridor="A"), {}, ttl_sec=300)
        c.put(_key(corridor="B"), {}, ttl_sec=300)
        assert len(c) == 2
        c.clear()
        assert len(c) == 0


class TestCacheTtl:
    def test_infinite_ttl_never_expires(self):
        c = Cache()
        c.put(_key(), {"k": "v"}, ttl_sec=None)
        assert c.get(_key()) == {"k": "v"}

    def test_expired_entry_returns_none(self, monkeypatch):
        c = Cache()
        c.put(_key(), {"k": "v"}, ttl_sec=1)
        # Force the monotonic clock forward
        original = time.monotonic
        future = original() + 100
        monkeypatch.setattr(time, "monotonic", lambda: future)
        assert c.get(_key()) is None

    def test_lazy_eviction_on_get(self, monkeypatch):
        c = Cache()
        c.put(_key(), {"k": "v"}, ttl_sec=1)
        future = time.monotonic() + 100
        monkeypatch.setattr(time, "monotonic", lambda: future)
        # Get triggers eviction
        c.get(_key())
        assert len(c) == 0


class TestCacheKey:
    def test_keys_with_different_modes_differ(self):
        c = Cache()
        c.put(_key(mode="today_as_of_T"), {"a": 1}, ttl_sec=None)
        c.put(_key(mode="retrospective"), {"a": 2}, ttl_sec=None)
        assert c.get(_key(mode="today_as_of_T")) == {"a": 1}
        assert c.get(_key(mode="retrospective")) == {"a": 2}

    def test_config_signature_changes_key(self):
        c = Cache()
        c.put(_key(sig="x"), {"v": 1}, ttl_sec=None)
        c.put(_key(sig="y"), {"v": 2}, ttl_sec=None)
        assert c.get(_key(sig="x")) == {"v": 1}
        assert c.get(_key(sig="y")) == {"v": 2}
