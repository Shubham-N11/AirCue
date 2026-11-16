"""Camera frame and capture types."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CaptureMode:
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    capture_ts_ns: int
    sequence: int


@dataclass(frozen=True)
class CaptureAttempt:
    mode: CaptureMode
    opened: bool
    reason: str = ""


@dataclass(frozen=True)
class CaptureOpenResult:
    mode: CaptureMode
    requested: CaptureMode
    attempts: tuple[CaptureAttempt, ...]

    @property
    def fallback_used(self) -> bool:
        return self.mode != self.requested


class CaptureError(RuntimeError):
    """Base class for camera capture failures."""


class CaptureConfigurationError(CaptureError):
    """The requested mode was unavailable; a fallback may still succeed."""


class CaptureUnavailableError(CaptureConfigurationError):
    """No requested or fallback mode could be opened."""


class CaptureFailureError(CaptureError):
    """A capture device failed after opening."""
