"""Adaptive processed-frame rate within profile bounds (design.md D8).

Frequency changes use recognition compute latency, queue depth, and CPU
pressure. The intentional click window is never an input, so arbitration
delays cannot be mistaken for overload.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class FrequencyDecision:
    fps: float
    changed: bool = False
    reason: str = ""


class AdaptiveFrequencyController:
    """Reduce quickly on sustained pressure, recover one step at a time."""

    def __init__(
        self,
        *,
        min_fps: float,
        max_fps: float,
        target_ms: float,
        start_fps: float | None = None,
        forced: bool = False,
        step_fps: float = 5.0,
        window_ms: int = 3_000,
        recovery_ms: int = 10_000,
        cooldown_ms: int = 5_000,
        min_samples: int = 10,
        queue_threshold: int = 2,
        cpu_ceiling: float | None = None,
        cpu_recovery: float = 0.70,
        recovery_latency_ratio: float = 0.80,
    ) -> None:
        self._min_fps = min_fps
        self._max_fps = max(min_fps, max_fps)
        self._target_ms = target_ms
        self._forced = forced
        self._step_fps = max(0.1, step_fps)
        self._window_ns = max(0, window_ms) * 1_000_000
        self._recovery_ns = max(0, recovery_ms) * 1_000_000
        self._cooldown_ns = max(0, cooldown_ms) * 1_000_000
        self._min_samples = max(1, min_samples)
        self._queue_threshold = max(1, queue_threshold)
        self._cpu_ceiling = cpu_ceiling
        self._cpu_recovery = min(
            cpu_recovery,
            cpu_ceiling * 0.9 if cpu_ceiling is not None else cpu_recovery,
        )
        self._recovery_latency_ratio = recovery_latency_ratio
        self._fps = self._clamp(
            self._max_fps if start_fps is None else start_fps
        )
        self._samples: deque[tuple[int, float]] = deque()
        self._last_change_ns: int | None = None
        self._recovery_since_ns: int | None = None

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def min_fps(self) -> float:
        return self._min_fps

    @property
    def max_fps(self) -> float:
        return self._max_fps

    def observe(
        self,
        *,
        compute_ms: float,
        queue_depth: int,
        cpu_fraction: float | None,
        now_ns: int | None = None,
    ) -> FrequencyDecision:
        """Feed one processed frame and return the current decision."""
        if self._forced:
            return FrequencyDecision(self._fps, reason="frequency is forced")

        now = time.monotonic_ns() if now_ns is None else now_ns
        self._samples.append((now, compute_ms))
        cutoff = now - self._window_ns
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        if len(self._samples) < self._min_samples:
            return FrequencyDecision(self._fps)

        median_ms = _median([value for _, value in self._samples])
        overload: list[str] = []
        if median_ms > self._target_ms:
            overload.append(
                f"latency {median_ms:.1f} ms > {self._target_ms:.1f} ms"
            )
        if queue_depth >= self._queue_threshold:
            overload.append(f"queue depth {queue_depth}")
        if (
            cpu_fraction is not None
            and self._cpu_ceiling is not None
            and cpu_fraction >= self._cpu_ceiling
        ):
            overload.append(f"cpu {cpu_fraction * 100:.0f}%")

        if overload:
            self._recovery_since_ns = None
            if self._fps <= self._min_fps or self._cooling_down(now):
                return FrequencyDecision(self._fps, reason=", ".join(overload))
            self._fps = self._clamp(self._fps - self._step_fps)
            self._changed(now)
            return FrequencyDecision(
                self._fps, changed=True, reason=", ".join(overload)
            )

        recovered = (
            median_ms <= self._target_ms * self._recovery_latency_ratio
            and queue_depth == 0
            and (
                cpu_fraction is None
                or self._cpu_ceiling is None
                or cpu_fraction < self._cpu_recovery
            )
        )
        if self._fps >= self._max_fps or not recovered:
            self._recovery_since_ns = None
            return FrequencyDecision(self._fps)

        if self._recovery_since_ns is None:
            self._recovery_since_ns = now
            return FrequencyDecision(self._fps, reason="recovery started")
        if (
            now - self._recovery_since_ns < self._recovery_ns
            or self._cooling_down(now)
        ):
            return FrequencyDecision(self._fps, reason="recovery in progress")

        self._fps = self._clamp(self._fps + self._step_fps)
        self._changed(now)
        return FrequencyDecision(
            self._fps, changed=True, reason="latency recovered"
        )

    def _clamp(self, fps: float) -> float:
        return max(self._min_fps, min(self._max_fps, fps))

    def _cooling_down(self, now_ns: int) -> bool:
        return (
            self._last_change_ns is not None
            and now_ns - self._last_change_ns < self._cooldown_ns
        )

    def _changed(self, now_ns: int) -> None:
        self._last_change_ns = now_ns
        self._recovery_since_ns = None
        self._samples.clear()


def _median(values: list[float]) -> float:
    """Nearest-rank p50, matching the metrics ring's percentile rule."""
    ordered = sorted(values)
    rank = max(1, math.ceil(50 / 100 * len(ordered)))
    return ordered[rank - 1]
