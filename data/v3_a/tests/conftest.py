"""Shared pytest fixtures for v3-A tests."""

from __future__ import annotations

import pytest

from data.v3_a import EngineConfig


@pytest.fixture
def config_default() -> EngineConfig:
    return EngineConfig.default()
