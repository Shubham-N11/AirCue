"""Hardware hints, calibration, and profile selection (design.md D8)."""

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
    "CalibrationError",
    "CalibrationMeasurement",
    "CalibrationResult",
    "HardwareEvidence",
    "HardwareHint",
    "HardwareSelection",
    "HardwareTier",
    "ProfileCalibrator",
    "hint_for",
    "next_tier",
    "previous_tier",
    "probe_evidence",
    "select_hardware",
]
