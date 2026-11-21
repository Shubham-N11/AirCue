"""Profile, backend, and frequency selection from config and evidence."""

from __future__ import annotations

from dataclasses import dataclass

from aircue.capture.types import CaptureMode
from aircue.config.schema import HardwareConfig, TierConfig
from aircue.hardware.calibration import CalibrationResult
from aircue.hardware.hints import (
    HardwareEvidence,
    HardwareHint,
    HardwareTier,
    hint_for,
)

# AirCue ships CPU-only; a GPU backend is added only after the benchmark gate.
SUPPORTED_BACKENDS = ("cpu",)


@dataclass(frozen=True)
class HardwareSelection:
    """The values a session will actually use, plus why they were chosen."""

    hint: HardwareHint
    profile: HardwareTier
    tier: TierConfig
    backend: str
    processing_fps: float
    processing_fps_forced: bool = False
    profile_source: str = "hint"
    overrides: tuple[str, ...] = ()
    calibration: CalibrationResult | None = None
    calibration_error: str | None = None
    benchmark_result: str = "not_run"
    benchmark_margin_percent: float | None = None

    def capture_mode(self) -> CaptureMode:
        return CaptureMode(self.tier.width, self.tier.height, self.processing_fps)

    def diagnostic_lines(self) -> tuple[str, ...]:
        calibration = "not_run"
        if self.calibration is not None:
            result = self.calibration
            calibration = (
                f"{result.hint.value}->{result.profile.value} "
                f"p95={result.measurement.p95_ms:.1f}ms "
                f"target={result.target_p95_ms:.1f}ms "
                f"throughput={result.measurement.throughput_fps:.1f}fps "
                f"samples={result.measurement.samples} "
                f"sustained={result.measurement.duration_ns / 1_000_000:.0f}ms"
            )
            if result.downgraded:
                calibration += " downgraded"
            if result.upgraded:
                calibration += " upgraded"
            calibration += f" ({result.reason})"
        elif self.calibration_error:
            calibration = f"failed: {self.calibration_error}"

        margin = (
            "n/a"
            if self.benchmark_margin_percent is None
            else f"{self.benchmark_margin_percent:.1f}%"
        )
        lines = [
            (
                f"hint={self.hint.tier.value} profile={self.profile.value} "
                f"source={self.profile_source} backend={self.backend} "
                f"fps={self.processing_fps:g} "
                f"capture={self.tier.width}x{self.tier.height}"
            ),
            f"evidence: {self.hint.evidence.describe()} hint_reason={self.hint.reason}",
            f"calibration: {calibration}",
            f"benchmark: result={self.benchmark_result} margin={margin}",
        ]
        lines.extend(f"override: {item}" for item in self.overrides)
        return tuple(lines)


def select_hardware(
    hardware: HardwareConfig,
    *,
    evidence: HardwareEvidence | None = None,
    calibration: CalibrationResult | None = None,
    calibration_error: str | None = None,
    benchmark_result: str = "not_run",
    benchmark_margin_percent: float | None = None,
) -> HardwareSelection:
    """Resolve a hint, calibration, and manual overrides into session values."""
    hint = hint_for(evidence or HardwareEvidence())
    overrides: list[str] = []

    if hardware.profile == "auto":
        if calibration is not None:
            profile = calibration.profile
            profile_source = "calibrated"
        else:
            profile = hint.tier
            profile_source = "hint"
    else:
        profile = HardwareTier(hardware.profile)
        profile_source = "forced"
        overrides.append(f"profile={profile.value}")

    if hardware.backend == "auto":
        backend = SUPPORTED_BACKENDS[0]
    elif hardware.backend == "cpu":
        backend = "cpu"
        overrides.append("backend=cpu")
    else:
        backend = SUPPORTED_BACKENDS[0]
        overrides.append("backend=gpu requested; cpu used (no supported GPU backend)")

    tier: TierConfig = getattr(hardware, profile.value)
    forced_fps = hardware.processing_fps > 0
    if forced_fps:
        processing_fps = hardware.processing_fps
        overrides.append(f"processing_fps={processing_fps:g}")
    else:
        processing_fps = tier.max_fps

    return HardwareSelection(
        hint=hint,
        profile=profile,
        tier=tier,
        backend=backend,
        processing_fps=processing_fps,
        processing_fps_forced=forced_fps,
        profile_source=profile_source,
        overrides=tuple(overrides),
        calibration=calibration,
        calibration_error=calibration_error,
        benchmark_result=benchmark_result,
        benchmark_margin_percent=benchmark_margin_percent,
    )
