"""Tests for cli.py. Spec §15.1."""

from __future__ import annotations

import sys

import pytest

from data.v3_a.cli import _parse_args


class TestArgParsing:
    def test_required_args(self):
        with pytest.raises(SystemExit):
            _parse_args([])

    def test_default_mode(self):
        ns = _parse_args(["--corridor", "KOL_B", "--anchor", "2026-04-01T19:00"])
        assert ns.mode == "today_as_of_T"
        assert ns.progress == "text"
        assert ns.out == "-"
        assert ns.no_cache is False

    def test_invalid_mode(self):
        with pytest.raises(SystemExit):
            _parse_args(["--corridor", "K", "--anchor", "2026-04-01T19:00", "--mode", "garbage"])

    def test_no_cache_flag(self):
        ns = _parse_args(["--corridor", "K", "--anchor", "2026-04-01T19:00", "--no-cache"])
        assert ns.no_cache is True
