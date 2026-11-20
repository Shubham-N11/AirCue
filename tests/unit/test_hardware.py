from __future__ import annotations

from dataclasses import replace

import pytest

from aircue.capture.types import Frame
from aircue.config.schema import Config, HardwareConfig
from aircue.hardware import (
    CalibrationError,
    CalibrationMeasurement,
    CalibrationResult,
    HardwareEvidence,
    HardwareTier,
    ProfileCalibrator,
    hint_for,
    select_hardware,
)


class FakeClock:
    def __init__(self, step_ms: float = 0.0) -> None:
        self.now_ns = 0
        self.step_ns = int(step_ms * 1_000_000)

    def __call__(self) -> int:
        return self.now_ns

    def advance(self) -> None:
        self.now_ns += self.step_ns


class FakeTracker:
    def __init__(
        self,
        clock: FakeClock,
        latency_by_width: dict[int, float] | None = None,
        *,
        default_latency_ms: float = 1.0,
    ) -> None:
        self.clock = clock
        self.latency_by_width = latency_by_width or {}
        self.default_latency_ms = default_latency_ms
        self.widths: list[int] = []
        self.closed = False

    def detect(self, frame: Frame) -> tuple:
        width = int(frame.image.shape[1])
        self.widths.append(width)
        latency = self.latency_by_width.get(width, self.default_latency_ms)
        self.clock.now_ns += int(latency * 1_000_000)
        return ()

    def close(self) -> None:
        self.closed = True


def _calibrator(
    clock: FakeClock,
    *,
    window_ms: int = 100,
    min_samples: int = 3,
    max_samples: int = 50,
    warmup_frames: int = 0,
) -> ProfileCalibrator:
    return ProfileCalibrator(
        HardwareConfig(),
        window_ms=window_ms,
        min_samples=min_samples,
        max_samples=max_samples,
        warmup_frames=warmup_frames,
        clock_ns=clock,
    )


def _calibration(profile: HardwareTier = HardwareTier.TIER3) -> CalibrationResult:
    return CalibrationResult(
        hint=HardwareTier.TIER3,
        profile=profile,
        measurement=CalibrationMeasurement(
            samples=10, duration_ns=1_000_000_000, median_ms=10.0, p95_ms=20.0
        ),
        target_p95_ms=35.0,
        downgraded=profile is not HardwareTier.TIER3,
        upgraded=profile is HardwareTier.TIER3,
        reason="test",
    )


def test_low_power_cpu_identity_is_a_tier1_hint() -> None:
    hint = hint_for(
        HardwareEvidence(
            cpu_name="Intel Celeron N5105",
            physical_cores=8,
            logical_cores=8,
            ram_gb=16.0,
            gpu_adapters=("Intel UHD Graphics",),
        )
    )

    assert hint.tier is HardwareTier.TIER1
    assert "low-power" in hint.reason


def test_two_physical_cores_are_a_tier1_hint() -> None:
    hint = hint_for(HardwareEvidence(physical_cores=2, ram_gb=8.0))

    assert hint.tier is HardwareTier.TIER1


def test_less_than_eight_gigabytes_is_a_tier1_hint() -> None:
    hint = hint_for(HardwareEvidence(physical_cores=4, ram_gb=4.0))

    assert hint.tier is HardwareTier.TIER1


def test_modest_evidence_is_a_tier2_hint() -> None:
    hint = hint_for(
        HardwareEvidence(
            physical_cores=4,
            ram_gb=16.0,
            gpu_adapters=("Intel Iris Xe Graphics",),
        )
    )

    assert hint.tier is HardwareTier.TIER2


def test_high_end_evidence_is_a_tier3_hint() -> None:
    hint = hint_for(
        HardwareEvidence(
            physical_cores=8,
            ram_gb=32.0,
            gpu_adapters=("NVIDIA GeForce RTX 4060",),
        )
    )

    assert hint.tier is HardwareTier.TIER3
    assert "8 physical cores" in hint.reason


def test_high_core_count_without_a_usable_gpu_is_capped_at_tier2() -> None:
    hint = hint_for(
        HardwareEvidence(physical_cores=12, ram_gb=64.0, gpu_adapters=())
    )

    assert hint.tier is HardwareTier.TIER2
    assert "capped at Tier 2" in hint.reason


@pytest.mark.parametrize(
    "adapter", ["Microsoft Basic Display Adapter", "Microsoft Remote Display Adapter"]
)
def test_basic_display_adapters_do_not_count(adapter: str) -> None:
    hint = hint_for(
        HardwareEvidence(physical_cores=8, ram_gb=32.0, gpu_adapters=(adapter,))
    )

    assert hint.tier is HardwareTier.TIER2


def test_unknown_evidence_falls_back_to_the_tier2_baseline() -> None:
    hint = hint_for(HardwareEvidence())

    assert hint.tier is HardwareTier.TIER2
    assert "baseline hint" in hint.reason


def test_evidence_description_names_every_field() -> None:
    description = HardwareEvidence(
        cpu_name="Example CPU",
        physical_cores=8,
        logical_cores=16,
        ram_gb=32.0,
        gpu_adapters=("Example GPU",),
    ).describe()

    assert "cpu=Example CPU" in description
    assert "physical_cores=8" in description
    assert "logical_cores=16" in description
    assert "ram_gb=32.0" in description
    assert "Example GPU" in description


def test_a_strong_hint_is_downgraded_when_latency_misses_the_target() -> None:
    clock = FakeClock()
    tracker = FakeTracker(clock, {1280: 40.0, 640: 30.0})
    calibrator = _calibrator(clock)

    result = calibrator.startup(tracker, HardwareTier.TIER3)

    assert result.profile is HardwareTier.TIER1
    assert result.downgraded is True
    assert result.upgraded is False
    assert result.measurement.p95_ms == 30.0
    assert "tier3" in result.reason
    assert "missed" in result.reason


def test_a_modest_hint_is_upgraded_after_a_sustained_measurement() -> None:
    clock = FakeClock()
    tracker = FakeTracker(clock, default_latency_ms=20.0)
    calibrator = _calibrator(clock)

    result = calibrator.startup(tracker, HardwareTier.TIER1)

    assert result.profile is HardwareTier.TIER2
    assert result.upgraded is True
    assert result.downgraded is False
    assert result.measurement.duration_ns >= 100_000_000
    assert result.measurement.throughput_fps == 50.0
    assert len(tracker.widths) == 10


def test_no_upgrade_without_the_sustained_window() -> None:
    clock = FakeClock(step_ms=1.0)
    tracker = FakeTracker(clock, default_latency_ms=1.0)
    calibrator = _calibrator(
        clock, window_ms=1_000, min_samples=5, max_samples=5
    )

    result = calibrator.startup(tracker, HardwareTier.TIER1)

    assert result.profile is HardwareTier.TIER1
    assert result.upgraded is False
    assert "no upward adjustment" in result.reason


def test_the_sustained_window_boundary_permits_the_upgrade() -> None:
    clock = FakeClock(step_ms=1.0)
    tracker = FakeTracker(clock, default_latency_ms=1.0)
    calibrator = _calibrator(
        clock, window_ms=5, min_samples=5, max_samples=10
    )

    result = calibrator.startup(tracker, HardwareTier.TIER1)

    assert result.profile is HardwareTier.TIER2
    assert result.upgraded is True


def test_calibration_inference_failure_is_reported() -> None:
    clock = FakeClock()
    calibrator = _calibrator(clock)

    class FailingTracker(FakeTracker):
        def detect(self, frame: Frame) -> tuple:
            raise RuntimeError("boom")

    with pytest.raises(CalibrationError, match="calibration inference failed"):
        calibrator.startup(FailingTracker(clock), HardwareTier.TIER2)


@pytest.mark.parametrize(
    ("evidence", "expected_tier", "width", "height", "fps"),
    [
        (
            HardwareEvidence(physical_cores=2, ram_gb=4.0),
            HardwareTier.TIER1,
            640,
            360,
            15.0,
        ),
        (
            HardwareEvidence(physical_cores=4, ram_gb=16.0),
            HardwareTier.TIER2,
            1280,
            720,
            30.0,
        ),
        (
            HardwareEvidence(
                physical_cores=8,
                ram_gb=32.0,
                gpu_adapters=("Example GPU",),
            ),
            HardwareTier.TIER3,
            1280,
            720,
            60.0,
        ),
    ],
)
def test_profile_defaults_come_from_the_selected_tier(
    evidence: HardwareEvidence,
    expected_tier: HardwareTier,
    width: int,
    height: int,
    fps: float,
) -> None:
    selection = select_hardware(HardwareConfig(), evidence=evidence)

    assert selection.profile is expected_tier
    assert selection.profile_source == "hint"
    assert selection.backend == "cpu"
    assert selection.capture_mode().width == width
    assert selection.capture_mode().height == height
    assert selection.capture_mode().fps == fps


def test_a_forced_profile_wins_over_the_hint_and_calibration() -> None:
    hardware = replace(HardwareConfig(), profile="tier1")

    selection = select_hardware(
        hardware,
        evidence=HardwareEvidence(
            physical_cores=8, ram_gb=32.0, gpu_adapters=("Example GPU",)
        ),
        calibration=_calibration(HardwareTier.TIER3),
    )

    assert selection.profile is HardwareTier.TIER1
    assert selection.profile_source == "forced"
    assert selection.capture_mode().width == 640
    assert "profile=tier1" in selection.overrides


def test_forced_cpu_is_recorded() -> None:
    hardware = replace(HardwareConfig(), backend="cpu")

    selection = select_hardware(hardware)

    assert selection.backend == "cpu"
    assert "backend=cpu" in selection.overrides


def test_forced_gpu_without_a_backend_records_the_fallback() -> None:
    hardware = replace(HardwareConfig(), backend="gpu")

    selection = select_hardware(hardware)

    assert selection.backend == "cpu"
    assert any("no supported GPU backend" in item for item in selection.overrides)


def test_forced_frequency_is_used_for_the_capture_request() -> None:
    hardware = replace(HardwareConfig(), processing_fps=24.0)

    selection = select_hardware(hardware)

    assert selection.processing_fps == 24.0
    assert selection.capture_mode().fps == 24.0
    assert "processing_fps=24" in selection.overrides


def test_diagnostics_report_hint_profile_backend_frequency_and_benchmark() -> None:
    selection = select_hardware(
        HardwareConfig(),
        evidence=HardwareEvidence(
            physical_cores=8, ram_gb=32.0, gpu_adapters=("Example GPU",)
        ),
        calibration=_calibration(HardwareTier.TIER2),
        benchmark_result="cpu_selected",
        benchmark_margin_percent=12.5,
    )

    lines = "\n".join(selection.diagnostic_lines())

    assert "hint=tier3" in lines
    assert "profile=tier2" in lines
    assert "source=calibrated" in lines
    assert "backend=cpu" in lines
    assert "fps=30" in lines
    assert "benchmark: result=cpu_selected margin=12.5%" in lines
    assert "evidence:" in lines
    assert "calibration:" in lines


def test_calibration_error_is_reported_in_diagnostics() -> None:
    selection = select_hardware(
        HardwareConfig(), calibration_error="tracker unavailable"
    )

    lines = "\n".join(selection.diagnostic_lines())

    assert "calibration: failed: tracker unavailable" in lines


def test_no_override_lines_are_emitted_for_defaults() -> None:
    selection = select_hardware(Config().hardware)

    assert selection.overrides == ()
