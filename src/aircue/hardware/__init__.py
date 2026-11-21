"""Hardware hints, calibration, and profile selection (design.md D8)."""

from aircue.hardware.backend_gate import (
    BackendCandidate,
    BackendDecision,
    BackendMeasurement,
    BackendProbe,
    benchmark_candidates,
    measure_backend,
    select_backend,
)
from aircue.hardware.calibration import (
    CalibrationError,
    CalibrationMeasurement,
    CalibrationResult,
    ProfileCalibrator,
)
from aircue.hardware.hints import (
    HardwareEvidence,
    HardwareHint,
    HardwareTier,
    hint_for,
    next_tier,
    previous_tier,
    probe_evidence,
)
from aircue.hardware.selection import HardwareSelection, select_hardware

__all__ = [
    "BackendCandidate",
    "BackendDecision",
    "BackendMeasurement",
    "BackendProbe",
    "CalibrationError",
    "CalibrationMeasurement",
    "CalibrationResult",
    "HardwareEvidence",
    "HardwareHint",
    "HardwareSelection",
    "HardwareTier",
    "ProfileCalibrator",
    "benchmark_candidates",
    "hint_for",
    "measure_backend",
    "next_tier",
    "previous_tier",
    "probe_evidence",
    "select_backend",
    "select_hardware",
]
