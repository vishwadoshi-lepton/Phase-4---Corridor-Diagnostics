"""TraffiCure Corridor Diagnostics v3-A — corridor-deep extension of v2.1.

Single source of truth: docs/superpowers/specs/2026-05-04-corridor-diagnostics-v3a-design.md

Public surface kept intentionally small. Use:
    from data.v3_a.api import submit_run, get_run, stream_events
    from data.v3_a import EngineConfig
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json


@dataclass(frozen=True)
class EngineConfig:
    """All thresholds and tunables. Spec §5.6.

    Defaults match v2.1 behaviour where they overlap. Tests may construct
    alternate configs; production callers MUST use ``EngineConfig.default()``.
    """

    # v2.1-inherited (mirrored only; v2.1 owns the actual values)
    ff_ceiling_kmph: float = 80.0
    regime_thresholds: tuple[float, float, float] = (0.80, 0.50, 0.30)
    bertini_min_minutes: int = 10
    shockwave_kmph_range: tuple[float, float] = (12.0, 22.0)
    shockwave_tolerance_min: int = 3
    systemic_simul_pct: float = 0.80
    systemic_contig_pct: float = 0.60

    # v3-A new
    tier1_growth_window_buckets: int = 7  # 14 minutes; see spec §7.1
    tier1_growth_min_buckets: int = 4
    tier1_growth_fast_m_per_min: float = 50.0
    tier1_growth_moderate_m_per_min: float = 10.0
    tier1_percolation_unit: str = "length_m"
    tier1_jamtree_adjacency_only: bool = True
    tier1_mfd_density_unit: str = "length_fraction"
    dow_anomaly_n_weeks_lookback: int = 6
    dow_anomaly_min_samples: int = 3
    baseline_n_weekdays: int = 22
    baseline_min_weekdays: int = 5
    baseline_thin_threshold: int = 14
    cache_today_ttl_sec: int = 300
    cache_anchor_truncation_sec: int = 120
    run_timeout_sec: int = 60
    per_corridor_concurrency: int = 1

    @classmethod
    def default(cls) -> "EngineConfig":
        return cls()

    def signature(self) -> str:
        """SHA-256 prefix of the canonical JSON of this config. Used for cache keys
        and meta.config_signature."""
        canonical = json.dumps(asdict(self), sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


ENGINE_VERSION = "v3.a.0"
SCHEMA_VERSION = "v3"

__all__ = ["EngineConfig", "ENGINE_VERSION", "SCHEMA_VERSION"]
