"""Hard error classes and soft warning codes for v3-A. Spec §11."""

from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# Hard errors — abort the run with status=FAILED                              #
# --------------------------------------------------------------------------- #


class HardError(Exception):
    """Base class for hard failures."""

    code: str = "HARD_ERR_INTERNAL"

    def __init__(self, message: str, hint: str | None = None, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.context = context

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "context": self.context,
        }


class UnknownCorridor(HardError):
    code = "HARD_ERR_UNKNOWN_CORRIDOR"


class FutureAnchor(HardError):
    code = "HARD_ERR_FUTURE_ANCHOR"


class AnchorPreHistory(HardError):
    code = "HARD_ERR_ANCHOR_PRE_HISTORY"


class NoTodayData(HardError):
    code = "HARD_ERR_NO_TODAY_DATA"


class InsufficientBaseline(HardError):
    code = "HARD_ERR_INSUFFICIENT_BASELINE"


class DBUnreachable(HardError):
    code = "HARD_ERR_DB_UNREACHABLE"


class Timeout(HardError):
    code = "HARD_ERR_TIMEOUT"


class BadConfig(HardError):
    code = "HARD_ERR_BAD_CONFIG"


class ModeNotImplemented(HardError):
    code = "HARD_ERR_MODE_NOT_IMPLEMENTED"


# --------------------------------------------------------------------------- #
# Soft warnings — run still completes with partial=true                       #
# --------------------------------------------------------------------------- #


class SoftWarn:
    """Soft-warning code constants."""

    THIN_BASELINE = "SOFT_WARN_THIN_BASELINE"
    DATA_GAP = "SOFT_WARN_DATA_GAP"
    QUIET_DAY = "SOFT_WARN_QUIET_DAY"
    TZ_ASSUMED = "SOFT_WARN_TZ_ASSUMED"
    MFD_THIN = "SOFT_WARN_MFD_THIN"
    MFD_NO_RECOVERY = "SOFT_WARN_MFD_NO_RECOVERY"
    DOW_FAILED = "SOFT_WARN_DOW_FAILED"

    @staticmethod
    def tier1_failed(name: str) -> str:
        return f"SOFT_WARN_TIER1_{name.upper()}_FAILED"


@dataclass
class Warning_:
    """A single soft warning. Stored in meta.warnings as a dict via to_dict()."""

    code: str
    message: str
    context: dict | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context or {},
        }


__all__ = [
    "HardError",
    "UnknownCorridor",
    "FutureAnchor",
    "AnchorPreHistory",
    "NoTodayData",
    "InsufficientBaseline",
    "DBUnreachable",
    "Timeout",
    "BadConfig",
    "ModeNotImplemented",
    "SoftWarn",
    "Warning_",
]
