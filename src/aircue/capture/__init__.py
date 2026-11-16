"""Camera capture."""

from aircue.capture.mailbox import CaptureThread, FrameMailbox
from aircue.capture.opencv_source import OpenCvCameraSource, candidate_modes
from aircue.capture.source import FrameSource
from aircue.capture.types import (
    CaptureAttempt,
    CaptureConfigurationError,
    CaptureError,
    CaptureFailureError,
    CaptureMode,
    CaptureOpenResult,
    CaptureUnavailableError,
    Frame,
)

__all__ = [
    "CaptureAttempt",
    "CaptureConfigurationError",
    "CaptureError",
    "CaptureFailureError",
    "CaptureMode",
    "CaptureOpenResult",
    "CaptureThread",
    "CaptureUnavailableError",
    "Frame",
    "FrameMailbox",
    "FrameSource",
    "OpenCvCameraSource",
    "candidate_modes",
]
