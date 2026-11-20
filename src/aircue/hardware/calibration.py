"""Startup calibration and sustained upward adjustment (design.md D8)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from aircue.capture.types import Frame
from aircue.config.schema import HardwareConfig, TierConfig
from aircue.hardware.hints import HardwareTier, next_tier, previous_tier
from aircue.vision.tracker import HandTracker

CALIBRATION_WINDOW_MS = 1000
CALIBRATION_MIN_SAMPLES = 20
CALIBRATION_MAX_SAMPLES = 1200
CALIBRATION_WARMUP_FRAMES = 3


class CalibrationError(RuntimeError):
    """Calibration inference failed; startup continues uncalibrated."""


@dataclass(frozen=True)
class CalibrationMeasurement:
    samples: int
    duration_ns: int
    median_ms: float
    p95_ms: float

    @property
    def throughput_fps(self) -> float:
        if self.duration_ns <= 0:
            return 0.0
        return self.samples * 1_000_000_000 / self.duration_ns


@dataclass(frozen=True)
class CalibrationResult:
    hint: HardwareTier
    profile: HardwareTier
    measurement: CalibrationMeasurement
    target_p95_ms: float
    downgraded: bool
    upgraded: bool
    reason: str


class ProfileCalibrator:
    """Measure inference on synthetic frames and pick a starting profile.

    A hint is only lowered when its target is missed. It is raised by at most one
    tier, and only when the measurement itself covered the sustained window.
    """

    def __init__(
        self,
        hardware: HardwareConfig,
        *,
        window_ms: int = CALIBRATION_WINDOW_MS,
        min_samples: int = CALIBRATION_MIN_SAMPLES,
        max_samples: int = CALIBRATION_MAX_SAMPLES,
        warmup_frames: int = CALIBRATION_WARMUP_FRAMES,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        self._hardware = hardware
        self._window_ns = max(0, window_ms) * 1_000_000
        self._min_samples = max(1, min_samples)
        self._max_samples = max(self._min_samples, max_samples)
        self._warmup_frames = max(0, warmup_frames)
        self._clock_ns = clock_ns

    def startup(self, tracker: HandTracker, hint: HardwareTier) -> CalibrationResult:
        """Keep, lower, or raise the hint from one sustained measurement set."""
        candidate = hint
        measurement = self._measure(tracker, candidate)
        reasons: list[str] = []

        while measurement.p95_ms > self._target_ms(candidate):
            reasons.append(
                f"{candidate.value} p95 {measurement.p95_ms:.1f} ms missed "
                f"{self._target_ms(candidate):.1f} ms target"
            )
            lower = previous_tier(candidate)
            if lower is None:
                break
            candidate = lower
            measurement = self._measure(tracker, candidate)

        downgraded = candidate is not hint
        upgraded = False
        if (
            not downgraded
            and measurement.p95_ms <= self._target_ms(candidate)
            and measurement.duration_ns >= self._window_ns
        ):
            reasons.append(
                f"{candidate.value} p95 {measurement.p95_ms:.1f} ms within "
                f"{self._target_ms(candidate):.1f} ms target over "
                f"{measurement.duration_ns / 1_000_000:.0f} ms"
            )
            higher = next_tier(candidate)
            if higher is not None:
                higher_measurement = self._measure(tracker, higher)
                if (
                    higher_measurement.duration_ns >= self._window_ns
                    and higher_measurement.p95_ms <= self._target_ms(higher)
                ):
                    reasons.append(
                        f"upgraded to {higher.value} at p95 "
                        f"{higher_measurement.p95_ms:.1f} ms within "
                        f"{self._target_ms(higher):.1f} ms"
                    )
                    candidate = higher
                    measurement = higher_measurement
                    upgraded = True
                else:
                    reasons.append(
                        f"{higher.value} p95 {higher_measurement.p95_ms:.1f} ms "
                        f"missed {self._target_ms(higher):.1f} ms target; "
                        f"stayed at {candidate.value}"
                    )
        elif measurement.duration_ns < self._window_ns:
            reasons.append(
                f"only {measurement.duration_ns / 1_000_000:.0f} ms of evidence; "
                "no upward adjustment"
            )

        return CalibrationResult(
            hint=hint,
            profile=candidate,
            measurement=measurement,
            target_p95_ms=self._target_ms(candidate),
            downgraded=downgraded,
            upgraded=upgraded,
            reason="; ".join(reasons) or "hint target met",
        )

    def _measure(
        self, tracker: HandTracker, tier: HardwareTier
    ) -> CalibrationMeasurement:
        config = self._tier(tier)
        image = np.full((config.height, config.width, 3), 127, dtype=np.uint8)
        frame = Frame(image=image, capture_ts_ns=0, sequence=0)
        for _ in range(self._warmup_frames):
            self._detect(tracker, frame, tier)

        start_ns = self._clock_ns()
        latencies_ns: list[int] = []
        while True:
            before_ns = self._clock_ns()
            self._detect(tracker, frame, tier)
            after_ns = self._clock_ns()
            latencies_ns.append(max(1, after_ns - before_ns))
            elapsed_ns = after_ns - start_ns
            if len(latencies_ns) >= self._min_samples and (
                elapsed_ns >= self._window_ns
                or len(latencies_ns) >= self._max_samples
            ):
                break

        duration_ns = max(1, self._clock_ns() - start_ns)
        return CalibrationMeasurement(
            samples=len(latencies_ns),
            duration_ns=duration_ns,
            median_ms=_percentile_ms(latencies_ns, 50),
            p95_ms=_percentile_ms(latencies_ns, 95),
        )

    def _detect(self, tracker: HandTracker, frame: Frame, tier: HardwareTier) -> None:
        try:
            tracker.detect(frame)
        except Exception as exc:
            raise CalibrationError(f"{tier.value} calibration inference failed: {exc}") from exc

    def _tier(self, tier: HardwareTier) -> TierConfig:
        return getattr(self._hardware, tier.value)

    def _target_ms(self, tier: HardwareTier) -> float:
        return self._tier(tier).recognition_compute_p95_ms


def _percentile_ms(values: Sequence[int], percent: float) -> float:
    """Nearest-rank percentile so known samples have exact expected results."""
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1] / 1_000_000
