"""Normalized pointer smoothing and mapping to the identified slideshow monitor."""

from __future__ import annotations

import math

from aircue.presentation.target import ScreenRect

# Normalized units per second that count as a deliberate fast hand movement.
_FAST_SPEED = 1.5


def map_pointer(
    x: float,
    y: float,
    monitor: ScreenRect | None,
    *,
    dead_zone: float = 0.01,
    neutral_x: float = 0.5,
    neutral_y: float = 0.5,
    active_range: float = 0.4,
    sensitivity: float = 1.0,
) -> tuple[int, int] | None:
    """Map a normalized pointer position onto one monitor, or None if unidentified.

    The active range is centered on the neutral position and spans each axis onto
    the monitor's full extent, so the same normalized position keeps its
    proportional place at any resolution. Movement inside the neutral region
    holds the monitor center, and out-of-range input clamps to the monitor edge.
    There is no primary-monitor fallback.
    """
    if monitor is None:
        return None
    width = monitor.right - monitor.left
    height = monitor.bottom - monitor.top
    if width <= 0 or height <= 0:
        return None

    dx = x - neutral_x
    dy = y - neutral_y
    if abs(dx) <= dead_zone and abs(dy) <= dead_zone:
        return _point(monitor, 0.0, 0.0)

    half_range = active_range / 2
    if half_range <= 0:
        return _point(monitor, 0.0, 0.0)
    nx = _clamp(dx * sensitivity / half_range)
    ny = _clamp(dy * sensitivity / half_range)
    return _point(monitor, nx, ny)


class PointerSmoother:
    """Adaptive EMA that freezes on loss and re-anchors without a jump.

    Slow movement is smoothed at ``min_alpha``; a fast sweep approaches
    ``max_alpha`` so the cursor stays responsive. Movement below ``dead_zone``
    is ignored, which suppresses stationary jitter. After invalidation the last
    output is held, and the first valid sample becomes a new relative anchor so
    the cursor resumes from the held position instead of teleporting.
    """

    def __init__(
        self,
        *,
        dead_zone: float = 0.01,
        min_alpha: float = 0.20,
        max_alpha: float = 0.45,
        max_added_latency_ms: int = 40,
    ) -> None:
        if min_alpha > max_alpha:
            raise ValueError("pointer smoothing min_alpha must be <= max_alpha")
        self._dead_zone = dead_zone
        self._min_alpha = min_alpha
        self._max_alpha = max_alpha
        self._max_added_latency_ns = max_added_latency_ms * 1_000_000
        self._position: tuple[float, float] | None = None
        self._last_raw: tuple[float, float] | None = None
        self._last_ns: int | None = None
        self._offset = (0.0, 0.0)
        self._frozen = False

    @property
    def position(self) -> tuple[float, float] | None:
        return self._position

    def invalidate(self) -> None:
        """Hold the last position and prepare a relative re-anchor."""
        self._frozen = True
        self._last_raw = None
        self._last_ns = None

    def update(
        self, point: tuple[float, float] | None, timestamp_ns: int
    ) -> tuple[float, float] | None:
        """Return the smoothed normalized position, or None while invalid."""
        if point is None:
            self.invalidate()
            return None
        if self._position is None:
            self._position = point
            self._last_raw = point
            self._last_ns = timestamp_ns
            self._frozen = False
            return point
        if self._frozen:
            self._offset = (
                self._position[0] - point[0],
                self._position[1] - point[1],
            )
            self._last_raw = point
            self._last_ns = timestamp_ns
            self._frozen = False
            return self._position

        assert self._last_raw is not None and self._last_ns is not None
        moved = math.dist(point, self._last_raw)
        adjusted = (point[0] + self._offset[0], point[1] + self._offset[1])
        if moved < self._dead_zone and math.dist(adjusted, self._position) < self._dead_zone:
            self._last_ns = timestamp_ns
            return self._position
        elapsed_ns = max(timestamp_ns - self._last_ns, 1)
        speed = moved / (elapsed_ns / 1_000_000_000)
        alpha = self._min_alpha + (self._max_alpha - self._min_alpha) * min(
            1.0, speed / _FAST_SPEED
        )
        # Slow frame rates already add latency; do not smooth further there.
        if elapsed_ns > self._max_added_latency_ns:
            alpha = self._max_alpha
        self._position = (
            alpha * adjusted[0] + (1 - alpha) * self._position[0],
            alpha * adjusted[1] + (1 - alpha) * self._position[1],
        )
        self._last_raw = point
        self._last_ns = timestamp_ns
        return self._position


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _point(monitor: ScreenRect, nx: float, ny: float) -> tuple[int, int]:
    width = monitor.right - monitor.left
    height = monitor.bottom - monitor.top
    x = round(monitor.left + (nx + 1) * width / 2)
    y = round(monitor.top + (ny + 1) * height / 2)
    return (
        min(max(x, monitor.left), monitor.right - 1),
        min(max(y, monitor.top), monitor.bottom - 1),
    )
