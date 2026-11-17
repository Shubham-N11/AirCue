"""Normalized pointer coordinates to the identified slideshow monitor."""

from __future__ import annotations

from aircue.presentation.target import ScreenRect


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
